from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from cowork_pilot.config import Config, HarnessConfig, load_config, load_harness_config
from cowork_pilot.dispatcher import build_prompt, call_cli, load_docs
from cowork_pilot.logger import StructuredLogger
from cowork_pilot.models import Event, EventType, Response, WatcherState
from cowork_pilot.responder import build_applescript, execute_applescript, has_tool_result_arrived, post_verify_response, set_clipboard
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

    # TTS readout via macOS `say`
    tts_text = f"에스컬레이트. {body}"
    try:
        _sp.Popen(["say", tts_text])  # non-blocking
    except (OSError, ValueError):
        pass



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

    # 2.6 Permission allow — auto-press Enter via AppleScript
    #     Cowork permission dialogs are in-app UI (not native macOS dialogs),
    #     so keystroke Enter works reliably.

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

    # ── Just-in-time guard ──────────────────────────────────────────
    # Between the debounce timeout and now (dispatcher + validation took
    # time), Cowork may have auto-approved the tool and the tool may have
    # already finished.  Re-read JSONL to check for a matching tool_result.
    # If found, skip AppleScript entirely — there is no dialog to click.
    if has_tool_result_arrived(jsonl_path, event.tool_use_id):
        logger.info(
            "responder",
            "tool_result already in JSONL — skipping AppleScript (auto-approved tool)",
            tool_use_id=event.tool_use_id,
            tool_name=event.tool_name,
        )
        return True  # Treat as success — tool ran fine without our intervention

    # Capture file size BEFORE AppleScript runs so post-verify doesn't
    # miss a tool_result that arrives between osascript and the poll start.
    pre_exec_size = jsonl_path.stat().st_size if jsonl_path.exists() else 0

    success = execute_applescript(script)
    if not success:
        logger.error("responder", "AppleScript execution failed")
        return False

    # 4. Post-verify (skip for permissions — tool_result appears only after
    #    the tool finishes executing, which can take minutes for builds etc.)
    if event.event_type == EventType.PERMISSION:
        logger.info(
            "responder",
            "Permission Enter sent, skipping post-verify (tool execution may take a while)",
            tool_use_id=event.tool_use_id,
            action=validated.action,
        )
        return True

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


def run_harness(
    config: Config,
    harness_config: HarnessConfig,
    ignored_sessions: set[Path] | None = None,
) -> None:
    """Harness mode: execute an exec-plan Chunk by Chunk.

    Combines Phase 1 auto-response with Phase 2 Chunk orchestration
    in a single cooperative loop.

    Args:
        ignored_sessions: Session JSONL paths for which Phase 1
            auto-response should be suppressed (passed through to
            WatcherStateMachine).
    """
    from cowork_pilot.plan_parser import parse_exec_plan
    from cowork_pilot.session_manager import (
        ChunkRetryState,
        find_next_incomplete_chunk,
        move_to_completed,
        notify_escalate,
        open_chunk_session,
        process_chunk,
    )
    from cowork_pilot.completion_detector import is_idle_trigger
    from cowork_pilot.watcher import parse_jsonl_line

    logger = StructuredLogger(config.log_path, config.log_level)
    logger.info("main", "Cowork Pilot starting in HARNESS mode", engine=config.engine)

    base_path = Path(config.session_base_path).expanduser()
    project_dir = config.project_dir

    # Find active exec-plan (promote from planning/ if active/ is empty)
    active_dir = Path(project_dir) / harness_config.exec_plans_dir / "active"
    active_dir.mkdir(parents=True, exist_ok=True)

    from cowork_pilot.session_manager import promote_next_plan
    promoted = promote_next_plan(active_dir.parent)
    if promoted:
        logger.info("harness", "Promoted plan from planning/", plan=str(promoted))
        print(f"Harness: Promoted {promoted.name} to active/")

    plan_files = list(active_dir.glob("*.md"))
    if not plan_files:
        logger.error("harness", "No active exec-plan found", dir=str(active_dir))
        print(f"Error: No exec-plan files in {active_dir}", file=sys.stderr)
        sys.exit(1)
    if len(plan_files) > 1:
        names = [f.name for f in plan_files]
        logger.error("harness", "Multiple plans in active/ — ambiguous", files=names)
        print(
            f"Error: active/에 계획이 2개 이상입니다: {names}\n"
            "active/에는 항상 1개의 exec-plan만 있어야 합니다.",
            file=sys.stderr,
        )
        notify_escalate("active/에 계획이 2개 이상 — 수동 확인 필요")
        sys.exit(1)

    plan_path = plan_files[0]
    logger.info("harness", "Loading exec-plan", path=str(plan_path))
    print(f"Harness: Loading {plan_path}")

    try:
        plan = parse_exec_plan(plan_path)
    except (ValueError, OSError) as e:
        notify_escalate(f"exec-plan parse error: {e}")
        sys.exit(1)

    # Main harness loop: process chunks one by one
    while True:
        plan = parse_exec_plan(plan_path)
        chunk = find_next_incomplete_chunk(plan)

        if chunk is None:
            # All chunks completed
            completed_path = move_to_completed(plan_path)
            logger.info("harness", "All chunks completed", dest=str(completed_path))
            notify_escalate("구현 계획 실행 완료!")
            print(f"Harness: All chunks completed! Plan moved to {completed_path}")
            break

        logger.info("harness", f"Starting Chunk {chunk.number}: {chunk.name}")
        print(f"\nHarness: Starting Chunk {chunk.number}: {chunk.name}")

        # Open a new Cowork session
        new_jsonl = open_chunk_session(chunk, harness_config, base_path)
        if new_jsonl is None:
            notify_escalate(f"Chunk {chunk.number} 세션 열기 실패")
            logger.error("harness", "Failed to open session", chunk=chunk.number)
            break

        logger.info("harness", "Session opened", jsonl=str(new_jsonl))
        print(f"  Session JSONL: {new_jsonl}")

        # Set up Phase 1 watcher for the new session
        tail = JSONLTail(new_jsonl)
        sm = WatcherStateMachine(
            debounce_seconds=config.debounce_seconds,
            ignored_sessions=ignored_sessions,
        )
        sm.set_current_session(new_jsonl)

        # Harness state
        retry_state = ChunkRetryState()
        last_record: dict | None = None
        last_record_time = time.monotonic()
        harness_feedback_pending = False

        # Cooperative loop: Phase 1 + harness idle detection
        chunk_done = False
        while not chunk_done:
            now = time.monotonic()

            # ── Phase 1: event detection + auto-response ──
            if not harness_feedback_pending:
                # Check for session switch (shouldn't happen in harness, but safe)
                new_lines = tail.read_new_lines()
                if new_lines:
                    last_record_time = time.monotonic()

                for line in new_lines:
                    # Store raw JSONL record for idle detection.
                    # is_idle_trigger needs the original record (e.g. assistant
                    # end_turn with no tool_use) — parse_jsonl_line only returns
                    # records that have tool_use/tool_result blocks.
                    #
                    # All record types are stored including "last-prompt" —
                    # is_idle_trigger handles it as a session-end signal.
                    # The final assistant record may have stop_reason: null
                    # (streaming artifact), so we rely on "last-prompt" as
                    # the definitive session-completion marker.
                    try:
                        raw_record = json.loads(line.strip())
                        if isinstance(raw_record, dict):
                            last_record = raw_record
                    except (ValueError, json.JSONDecodeError):
                        pass

                    parsed = parse_jsonl_line(line)
                    if parsed is None:
                        continue

                    if parsed["type"] == "assistant":
                        for tu in parsed["tool_uses"]:
                            sm.on_tool_use(tu)
                    elif parsed["type"] == "user":
                        for tr_id in parsed["tool_results"]:
                            sm.on_tool_result(tr_id)

                sm.tick()

                event = sm.get_pending_event()
                if event is not None:
                    from cowork_pilot.dispatcher import extract_context
                    context = extract_context(new_jsonl, max_lines=10)
                    event = Event(
                        event_type=event.event_type,
                        tool_use_id=event.tool_use_id,
                        tool_name=event.tool_name,
                        questions=event.questions,
                        tool_input=event.tool_input,
                        context_lines=context,
                    )

                    success = process_one_event(event, new_jsonl, config, logger)
                    if success:
                        sm.on_tool_result(event.tool_use_id)
                    else:
                        sm.state = WatcherState.IDLE
                        sm.pending_tool_use = None

            # ── Phase 2: idle detection + completion check ──
            if is_idle_trigger(last_record, last_record_time, now,
                              idle_timeout_seconds=harness_config.idle_timeout_seconds):
                logger.info("harness", "Idle detected, running verification",
                           chunk=chunk.number)
                print(f"  Idle detected — verifying Chunk {chunk.number}...")

                harness_feedback_pending = True

                result = process_chunk(
                    plan_path, chunk, harness_config, project_dir, retry_state,
                )

                if result == "COMPLETED":
                    logger.info("harness", f"Chunk {chunk.number} completed")
                    print(f"  ✓ Chunk {chunk.number} completed!")
                    chunk_done = True
                elif result == "ESCALATE":
                    notify_escalate(f"Chunk {chunk.number} ESCALATE — 재시도 초과")
                    logger.error("harness", "ESCALATE", chunk=chunk.number)
                    print(f"  ⚠ Chunk {chunk.number} ESCALATE — pausing")
                    chunk_done = True  # Stop this chunk, human intervention needed
                else:
                    # INCOMPLETE or ERROR — feedback sent, continue watching
                    last_record_time = time.monotonic()  # Reset idle timer
                    logger.info("harness", f"Chunk {chunk.number}: {result}, continuing")
                    print(f"  → {result}, continuing to watch...")

                harness_feedback_pending = False

            time.sleep(config.poll_interval_seconds)


def cli() -> None:
    """Entry point for `cowork-pilot` command."""
    import argparse

    parser = argparse.ArgumentParser(description="Cowork Pilot — auto-response agent")
    parser.add_argument("--config", type=str, default="config.toml", help="Path to config file")
    parser.add_argument("--engine", type=str, choices=["codex", "claude"], help="Override engine")
    parser.add_argument("--mode", type=str, choices=["watch", "harness", "meta"], default="watch",
                       help="Run mode: watch (Phase 1) / harness (Phase 2) / meta (Phase 3)")
    parser.add_argument("description", nargs="?", default="",
                       help="Initial project description (meta mode only)")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if args.engine:
        config.engine = args.engine

    if args.mode == "meta":
        from cowork_pilot.config import load_meta_config
        from cowork_pilot.meta_runner import run_meta
        meta_config = load_meta_config(Path(args.config))
        if args.description:
            meta_config.initial_description = args.description
        if not meta_config.project_dir:
            meta_config.project_dir = config.project_dir
        run_meta(config, meta_config)
    elif args.mode == "harness":
        harness_config = load_harness_config(Path(args.config), config)
        run_harness(config, harness_config)
    else:
        run(config)


if __name__ == "__main__":
    cli()
