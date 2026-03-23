from __future__ import annotations

import json
import subprocess
import time as _time
from pathlib import Path

from cowork_pilot.models import Response, EventType


APP_NAME = "Claude"


def build_applescript(
    response: Response,
    event_type: EventType,
    num_options: int = 0,
    activate_delay: float = 0.3,
) -> str:
    """Build an AppleScript string to input the response into Claude Desktop.

    All interaction is keyboard-only:
    - AskUserQuestion: arrow keys to navigate options, Enter to select
    - Permission: Enter to allow, Esc to deny
    - Free text: type text, then Enter
    """
    lines = [
        f'tell application "{APP_NAME}" to activate',
        f"delay {activate_delay}",
        'tell application "System Events"',
        f'  tell process "{APP_NAME}"',
    ]

    if event_type == EventType.QUESTION:
        # Warmup: the first arrow interaction with the Cowork question
        # dialog jumps 2 positions instead of 1.  Pressing down
        # ceil(total_items/2) times cycles back to option 1 and
        # stabilises subsequent navigation.
        #   2 options (3 items) → 2 presses
        #   3 options (4 items) → 2 presses
        #   4 options (5 items) → 3 presses
        warmup_presses = (num_options + 2) // 2
        for _ in range(warmup_presses):
            lines.append("    key code 125")  # arrow down
            lines.append("    delay 0.1")
        lines.append("    delay 0.1")

        if response.action == "select":
            # Navigate down to the right option (1-indexed, first is already selected)
            moves_down = response.value - 1
            for _ in range(moves_down):
                lines.append("    key code 125")  # arrow down
                lines.append("    delay 0.1")
            lines.append("    keystroke return")

        elif response.action == "other":
            # "Other"(기타) is the last item after all numbered options.
            # Do NOT press Enter after reaching 기타 — the text input
            # field is already active.  Just paste and submit.
            for _ in range(num_options):
                lines.append("    key code 125")  # arrow down
                lines.append("    delay 0.1")
            lines.append("    delay 2.0")
            # Paste custom text via clipboard (pre-loaded by pbcopy)
            lines.append(_clipboard_paste_block(response.value))
            lines.append("    delay 0.3")
            lines.append("    keystroke return")

    elif event_type == EventType.PERMISSION:
        if response.action == "allow":
            lines.append("    keystroke return")  # Enter = allow
        elif response.action == "deny":
            lines.append("    key code 53")  # Esc = deny

    elif event_type == EventType.FREE_TEXT:
        # Paste via clipboard (keystroke breaks Korean IME)
        lines.append(_clipboard_paste_block(response.value))
        lines.append("    keystroke return")

    lines.append("  end tell")
    lines.append("end tell")

    return "\n".join(lines)


def _escape_applescript(text: str) -> str:
    """Escape special characters for AppleScript keystroke."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _clipboard_paste_block(text: str) -> str:
    """Build AppleScript lines to paste with Cmd+V.

    The clipboard must be pre-loaded via ``set_clipboard()`` before the
    AppleScript is executed — AppleScript's ``set the clipboard to``
    doesn't reliably work inside ``tell process`` blocks.
    """
    return '    key code 9 using command down'  # key code 9 = V


def set_clipboard(text: str) -> bool:
    """Set the macOS clipboard via pbcopy (works outside AppleScript context)."""
    try:
        subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def execute_applescript(script: str) -> bool:
    """Execute an AppleScript via osascript. Returns True on success."""
    import sys as _sys
    print(f"  [responder] AppleScript:\n{script}", file=_sys.stderr)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  [responder] osascript FAILED rc={result.returncode}", file=_sys.stderr)
            print(f"  [responder] stderr: {result.stderr[:500]}", file=_sys.stderr)
        else:
            print(f"  [responder] osascript OK", file=_sys.stderr)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("  [responder] osascript TIMEOUT (30s)", file=_sys.stderr)
        return False
    except FileNotFoundError:
        print("  [responder] osascript not found", file=_sys.stderr)
        return False
    except OSError as e:
        print(f"  [responder] OSError: {e}", file=_sys.stderr)
        return False


def post_verify_response(
    jsonl_path: Path,
    tool_use_id: str,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.5,
    file_offset: int | None = None,
) -> bool:
    """After AppleScript input, verify that a matching tool_result appeared in JSONL.

    Polls the JSONL file for a tool_result with matching tool_use_id.
    Returns True if found within timeout, False otherwise.

    ``file_offset`` should be the JSONL file size captured **before** the
    AppleScript was executed.  If omitted, the current file size is used
    (legacy behaviour — prone to race conditions).
    """
    start = _time.monotonic()
    if file_offset is not None:
        initial_size = file_offset
    else:
        initial_size = jsonl_path.stat().st_size if jsonl_path.exists() else 0

    while (_time.monotonic() - start) < timeout_seconds:
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                f.seek(initial_size)
                new_content = f.read()
        except (FileNotFoundError, OSError):
            _time.sleep(poll_interval)
            continue

        for line in new_content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "user":
                continue
            content = record.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == tool_use_id
                    ):
                        return True

        _time.sleep(poll_interval)

    return False
