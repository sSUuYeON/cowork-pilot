"""Detect whether a Cowork session has finished its current Chunk.

Two-phase detection:
1. **Idle detection** — JSONL has no new records for N seconds AND
   the last record indicates the turn is complete.
2. **CLI verification** — ask a CLI agent to check each completion
   criterion mechanically (pytest, file existence, etc.).

Also provides feedback text building and feedback sending for
INCOMPLETE results.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field

from cowork_pilot.plan_parser import Chunk


# ── Idle detection ───────────────────────────────────────────────────

def is_idle_trigger(
    last_record: dict | None,
    last_record_time: float,
    now: float,
    idle_timeout_seconds: float = 30.0,
) -> bool:
    """Return True when idle timeout + turn-end conditions are met.

    Conditions (both must be true):
    - ``now - last_record_time >= idle_timeout_seconds``
    - One of:
      A. last_record type == "summary"  (preferred — turn fully complete)
      B. last_record type == "assistant" with stop_reason == "end_turn"
         and no tool_use blocks in content  (fallback)
    """
    if last_record is None:
        return False

    if (now - last_record_time) < idle_timeout_seconds:
        return False

    record_type = last_record.get("type")

    # Condition A (priority): summary record = turn fully complete
    # Also treat "last-prompt" as session-end (bookkeeping record
    # appended after the assistant's final turn).
    if record_type in ("summary", "last-prompt"):
        return True

    # Condition B (fallback): assistant end_turn without tool_use
    if record_type == "assistant":
        msg = last_record.get("message", {})
        if msg.get("stop_reason") == "end_turn":
            content = msg.get("content", [])
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in content
            )
            if not has_tool_use:
                return True

    return False


# ── CLI verification ─────────────────────────────────────────────────

def build_verification_prompt(chunk: Chunk) -> str:
    """Build a prompt for the CLI agent to verify completion criteria.

    The prompt asks the CLI to check whether the exec-plan checkboxes
    are already marked [x] — it does NOT ask it to re-run builds or
    verify files on disk.  The Cowork session itself is responsible for
    running builds and updating the checkboxes before finishing.
    """
    criteria_text = "\n".join(
        f"  {i+1}. {'[x]' if c.checked else '[ ]'} {c.description}"
        for i, c in enumerate(chunk.completion_criteria)
    )
    return (
        f"아래는 exec-plan Chunk {chunk.number}의 완료 조건 체크박스 현재 상태야.\n"
        f"직접 파일을 확인하거나 명령어를 실행하지 마.\n"
        f"체크박스 상태만 보고 판단해:\n"
        f"\n"
        f"{criteria_text}\n"
        f"\n"
        f"모든 항목이 [x]이면 \"COMPLETED\"만 출력해.\n"
        f"[x]가 아닌 항목이 하나라도 있으면 \"INCOMPLETE: {{미충족 항목 목록}}\"을 출력해.\n"
        f"다른 설명 없이 COMPLETED 또는 INCOMPLETE: ... 한 줄만 출력해."
    )


def call_verification_cli(
    prompt: str,
    project_dir: str,
    engine: str = "claude",
    engine_command: str = "claude",
    engine_args: list[str] | None = None,
    timeout: float = 120.0,
) -> str | None:
    """Call a CLI agent to verify completion criteria.

    Returns the raw CLI output string, or None on failure.
    """
    if engine_args is None:
        engine_args = ["-p"]

    cmd = [engine_command] + engine_args
    try:
        import sys as _sys
        print(f"  [verify] cmd={cmd}... cwd={project_dir}", file=_sys.stderr)
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_dir,
        )
        if result.returncode != 0:
            print(f"  [verify] FAILED rc={result.returncode}", file=_sys.stderr)
            if result.stderr:
                print(f"  [verify] stderr: {result.stderr[:300]}", file=_sys.stderr)
            if result.stdout:
                print(f"  [verify] stdout: {result.stdout[:300]}", file=_sys.stderr)
            return None
        stdout = result.stdout.strip()
        print(f"  [verify] OK, stdout({len(stdout)} chars): {stdout[:300]}", file=_sys.stderr)
        return stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        print(f"  [verify] EXCEPTION: {exc}", file=_sys.stderr)
        return None


def parse_verification_result(cli_output: str) -> tuple[str, str]:
    """Parse CLI verification output into (status, detail).

    Returns:
    - ("COMPLETED", "") if all criteria met
    - ("INCOMPLETE", "미충족 항목 설명") if some criteria not met
    - ("ERROR", "error description") if output cannot be parsed
    """
    if cli_output is None:
        return ("ERROR", "CLI returned no output")

    text = cli_output.strip()

    # Check for COMPLETED (case-insensitive, may appear anywhere)
    if "COMPLETED" in text.upper() and "INCOMPLETE" not in text.upper():
        return ("COMPLETED", "")

    # Check for INCOMPLETE
    upper = text.upper()
    idx = upper.find("INCOMPLETE")
    if idx >= 0:
        # Extract detail after "INCOMPLETE:"
        rest = text[idx + len("INCOMPLETE"):]
        rest = rest.lstrip(":").strip()
        return ("INCOMPLETE", rest)

    return ("ERROR", f"Cannot parse CLI output: {text[:200]}")


# ── Feedback builder ─────────────────────────────────────────────────

def build_feedback_text(incomplete_detail: str) -> str:
    """Build feedback text to send back to the Cowork session."""
    return (
        f"아직 미완료 항목이 있어:\n"
        f"{incomplete_detail}\n"
        f"마저 진행해. 완료 조건을 다시 확인하고 모든 항목을 만족시켜."
    )


def send_feedback(
    feedback_text: str,
    activate_delay: float = 0.3,
) -> bool:
    """Send feedback text to the active Cowork session via clipboard + AppleScript.

    Reuses Phase 1's set_clipboard + build_type_prompt_script + execute_applescript.
    """
    from cowork_pilot.responder import execute_applescript, set_clipboard
    from cowork_pilot.session_opener import build_type_prompt_script

    if not set_clipboard(feedback_text):
        return False

    script = build_type_prompt_script(activate_delay=activate_delay)
    return execute_applescript(script)
