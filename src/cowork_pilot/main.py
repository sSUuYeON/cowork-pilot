from __future__ import annotations

import sys
import time
from pathlib import Path

from cowork_pilot.config import Config, load_config
from cowork_pilot.dispatcher import build_prompt, call_cli, load_docs
from cowork_pilot.logger import StructuredLogger
from cowork_pilot.models import Event, EventType, Response, WatcherState
from cowork_pilot.responder import build_applescript, execute_applescript, post_verify_response, set_clipboard
from cowork_pilot.session_finder import find_active_jsonl
from cowork_pilot.validator import validate_response
from cowork_pilot.watcher import JSONLTail, WatcherStateMachine, parse_jsonl_line


def _notify_escalate(event: Event) -> None:
    """Send macOS notification + sound when ESCALATE is triggered.

    Uses osascript to show a native macOS notification center alert
    and plays the system alert sound so the user notices.
    """
    import subprocess as _sp

    # Build descriptive message
    if event.event_type == EventType.QUESTION and event.questions:
        question_text = event.questions[0].get("question", "Unknown question")
        body = f"Q: {question_text[:80]}"
    elif event.event_type == EventType.PERMISSION:
        tool_desc = event.tool_name
        cmd = event.tool_input.get("command", event.tool_input.get("description", ""))
        if cmd:
            tool_desc = f"{event.tool_name}: {cmd[:60]}"
        body = f"Tool: {tool_desc}"
    else:
        body = f"{event.event_type.value} — {event.tool_name}"

    title = "⚠️ Cowork Pilot — ESCALATE"

    # macOS notification via osascript
    script = (
        f'display notification "{_escape_for_applescript(body)}" '
        f'with title "{_escape_for_applescript(title)}" '
        f'sound name "Sosumi"'
    )
    try:
        _sp.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, _sp.TimeoutExpired):
        pass

    # Terminal bell as fallback
    print(f"\a⚠️  ESCALATE: {body}", file=sys.stderr)


def _notify_allow(event: Event) -> None:
    """Send macOS notification + sound when permission allow is needed.

    Auto-Enter is unreliable for native macOS dialogs, so we notify
    the human to click the allow button manually.
    """
    import subprocess as _sp

    tool_desc = event.tool_name
    cmd = event.tool_input.get("command", event.tool_input.get("description", ""))
    if cmd:
        tool_desc = f"{event.tool_name}: {cmd[:60]}"
    body = f"Tool: {tool_desc}"

    title = "✅ Cowork Pilot — ALLOW"

    script = (
        f'display notification "{_escape_for_applescript(body)}" '
        f'with title "{_escape_for_applescript(title)}" '
        f'sound name "Glass"'
    )
    try:
        _sp.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, _sp.TimeoutExpired):
        pass

    print(f"\a✅  ALLOW (please approve): {body}", file=sys.stderr)


def _escape_for_applescript(text: str) -> str:
    """Escape special characters for AppleScript string literals."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def process_one_event(
    event: Event,
    jsonl_path: Path,
    config: Config,
    logger: StructuredLogger,
) -> bool:
    """Process a single detected event through the full pipeline.

    Dispatcher → Validator (with retry) → Responder → Post-verify.
    Returns True if response was successfully delivered.
    """
    # 1. Load docs and build prompt
    docs_content = load_docs(config.project_dir)
    prompt = build_prompt(event, docs_content=docs_content)

    # 2. Call CLI + Validate (with retries)
    validated: Response | None = None
    num_options = 0
    if event.event_type == EventType.QUESTION and event.questions:
        num_options = len(event.questions[0].get("options", []))

    for attempt in range(config.max_retries):
        raw_response = call_cli(prompt, config)

        if raw_response is None:
            logger.warn("dispatcher", "CLI returned None", attempt=attempt + 1)
            continue

        validated = validate_response(raw_response, event.event_type, num_options=num_options)

        if validated is not None:
            logger.info(
                "validator",
                "Response validated",
                raw=raw_response,
                action=validated.action,
                value=str(validated.value),
                attempt=attempt + 1,
            )
            break
        else:
            logger.warn(
                "validator",
                "Invalid format, retrying",
                raw=raw_response,
                attempt=attempt + 1,
            )

    if validated is None:
        logger.error("validator", "All retries exhausted", event_type=event.event_type.value)
        return False

    # 2.5 Handle ESCALATE — skip this event, let human handle it
    if validated.action == "escalate":
        logger.info(
            "validator",
            "ESCALATE — deferring to human",
            event_type=event.event_type.value,
            tool_name=event.tool_name,
        )
        _notify_escalate(event)
        return False  # Don't input anything, leave for human

    # 2.6 Handle permission allow — notify human (auto-Enter unreliable for native dialogs)
    if validated.action == "allow" and event.event_type == EventType.PERMISSION:
        logger.info(
            "validator",
            "ALLOW — notifying human to approve",
            event_type=event.event_type.value,
            tool_name=event.tool_name,
        )
        _notify_allow(event)
        return False  # Let human click the allow button

    # 3. Build and execute AppleScript
    script = build_applescript(
        validated,
        event.event_type,
        num_options=num_options,
        activate_delay=config.activate_delay_seconds,
    )

    # Pre-load clipboard for actions that need paste (Other, Free Text).
    # pbcopy works reliably outside AppleScript context.
    if validated.action in ("other", "text") and validated.value:
        if not set_clipboard(str(validated.value)):
            logger.error("responder", "Failed to set clipboard via pbcopy")
            return False

    # Capture file size BEFORE AppleScript runs so post-verify doesn't
    # miss a tool_result that arrives between osascript and the poll start.
    pre_exec_size = jsonl_path.stat().st_size if jsonl_path.exists() else 0

    success = execute_applescript(script)
    if not success:
        logger.error("responder", "AppleScript execution failed")
        return False

    # 4. Post-verify
    verified = post_verify_response(
        jsonl_path,
        event.tool_use_id,
        timeout_seconds=config.post_verify_timeout_seconds,
        file_offset=pre_exec_size,
    )

    if not verified:
        logger.warn("responder", "Post-verification timeout", tool_use_id=event.tool_use_id)
        return False

    logger.info(
        "responder",
        "Response delivered and verified",
        tool_use_id=event.tool_use_id,
        action=validated.action,
    )
    return True


def run(config: Config) -> None:
    """Main loop: Watch → Detect → Process → Repeat."""
    logger = StructuredLogger(config.log_path, config.log_level)
    logger.info("main", "Cowork Pilot starting", engine=config.engine)

    # Find active JSONL
    base_path = Path(config.session_base_path).expanduser()
    jsonl_path = find_active_jsonl(base_path)

    if jsonl_path is None:
        logger.error("main", "No active JSONL session found", base_path=str(base_path))
        print("Error: No active Cowork session found.", file=sys.stderr)
        sys.exit(1)

    logger.info("main", "Watching JSONL", path=str(jsonl_path))
    print(f"Watching: {jsonl_path}")

    tail = JSONLTail(jsonl_path)
    sm = WatcherStateMachine(debounce_seconds=config.debounce_seconds)

    while True:
        # Check for session switch
        new_jsonl = find_active_jsonl(base_path)
        if new_jsonl and new_jsonl != jsonl_path:
            logger.info("main", "Session switched", old=str(jsonl_path), new=str(new_jsonl))
            jsonl_path = new_jsonl
            tail.switch_file(jsonl_path)
            sm = WatcherStateMachine(debounce_seconds=config.debounce_seconds)

        # Read new lines
        new_lines = tail.read_new_lines()
        if new_lines:
            print(f"  [watcher] {len(new_lines)} new line(s)", file=sys.stderr)
        for line in new_lines:
            parsed = parse_jsonl_line(line)
            if parsed is None:
                continue

            if parsed["type"] == "assistant":
                for tu in parsed["tool_uses"]:
                    print(f"  [watcher] tool_use: {tu['name']} (id={tu['id'][:12]}...)", file=sys.stderr)
                    sm.on_tool_use(tu)

            elif parsed["type"] == "user":
                for tr_id in parsed["tool_results"]:
                    print(f"  [watcher] tool_result for {tr_id[:12]}...", file=sys.stderr)
                    sm.on_tool_result(tr_id)

        # Tick state machine
        sm.tick()

        # Check if we have a pending event to process
        event = sm.get_pending_event()
        if event is not None:
            # Add context
            from cowork_pilot.dispatcher import extract_context
            context = extract_context(jsonl_path, max_lines=10)
            event = Event(
                event_type=event.event_type,
                tool_use_id=event.tool_use_id,
                tool_name=event.tool_name,
                questions=event.questions,
                tool_input=event.tool_input,
                context_lines=context,
            )

            print(f"\n>>> Event: {event.event_type.value} | tool={event.tool_name} | id={event.tool_use_id[:12]}...", file=sys.stderr)
            if event.questions:
                for q in event.questions:
                    print(f"    Q: {q.get('question', '?')}", file=sys.stderr)
                    for i, opt in enumerate(q.get("options", []), 1):
                        print(f"       {i}. {opt.get('label', '')}", file=sys.stderr)

            logger.info(
                "watcher",
                "Event detected",
                event_type=event.event_type.value,
                tool_name=event.tool_name,
                tool_use_id=event.tool_use_id,
            )

            print("    Calling CLI...", file=sys.stderr)
            success = process_one_event(event, jsonl_path, config, logger)

            if success:
                print("    ✓ Response delivered!", file=sys.stderr)
                sm.on_tool_result(event.tool_use_id)  # Mark as handled
            else:
                print("    ✗ Failed to process event", file=sys.stderr)
                logger.error("main", "Failed to process event", tool_use_id=event.tool_use_id)
                # Reset state machine to avoid infinite loop
                sm.state = WatcherState.IDLE
                sm.pending_tool_use = None

        time.sleep(config.poll_interval_seconds)


def cli() -> None:
    """Entry point for `cowork-pilot` command."""
    import argparse

    parser = argparse.ArgumentParser(description="Cowork Pilot — auto-response agent")
    parser.add_argument("--config", type=str, default="config.toml", help="Path to config file")
    parser.add_argument("--engine", type=str, choices=["codex", "claude"], help="Override engine")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if args.engine:
        config.engine = args.engine

    run(config)


if __name__ == "__main__":
    cli()
