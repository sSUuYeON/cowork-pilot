"""Open a new Cowork session and optionally type an initial prompt.

Uses AppleScript to:
1. Activate Claude Desktop
2. Send Shift+Cmd+O to open a new session
3. Wait for the session to load
4. Paste an initial prompt via clipboard + Cmd+V
5. Press Enter to submit
"""
from __future__ import annotations

from cowork_pilot.responder import execute_applescript, set_clipboard

APP_NAME = "Claude"


def build_open_session_script(
    activate_delay: float = 0.5,
    session_load_delay: float = 3.0,
) -> str:
    """Build AppleScript to open a new Cowork session via Shift+Cmd+O."""
    return "\n".join([
        f'tell application "{APP_NAME}" to activate',
        f"delay {activate_delay}",
        'tell application "System Events"',
        f'  tell process "{APP_NAME}"',
        "    key code 31 using {shift down, command down}",  # key code 31 = O
        "  end tell",
        "end tell",
        f"delay {session_load_delay}",
    ])


def build_type_prompt_script(
    activate_delay: float = 0.3,
) -> str:
    """Build AppleScript to paste from clipboard and press Enter.

    Clipboard must be pre-loaded via set_clipboard() before calling this.
    """
    return "\n".join([
        f'tell application "{APP_NAME}" to activate',
        f"delay {activate_delay}",
        'tell application "System Events"',
        f'  tell process "{APP_NAME}"',
        "    key code 9 using command down",   # Cmd+V paste
        "    delay 0.3",
        "    keystroke return",
        "  end tell",
        "end tell",
    ])


def open_new_session(
    initial_prompt: str | None = None,
    activate_delay: float = 0.5,
    session_load_delay: float = 3.0,
) -> bool:
    """Open a new Cowork session and optionally send an initial prompt.

    Steps:
    1. Activate Claude Desktop + Shift+Cmd+O
    2. Wait for new session to load
    3. If initial_prompt given: paste it and press Enter

    Returns True if all AppleScript steps succeeded.
    """
    # Step 1: Open new session
    open_script = build_open_session_script(
        activate_delay=activate_delay,
        session_load_delay=session_load_delay,
    )
    if not execute_applescript(open_script):
        return False

    # Step 2: Type initial prompt (if given)
    if initial_prompt is not None:
        if not set_clipboard(initial_prompt):
            return False

        type_script = build_type_prompt_script(activate_delay=activate_delay)
        if not execute_applescript(type_script):
            return False

    return True
