from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from cowork_pilot.config import Config, HarnessConfig, load_config, load_harness_config
from cowork_pilot.dispatcher import build_prompt, call_cli, load_docs
from cowork_pilot.logger import StructuredLogger
from cowork_pilot.models import Event, EventType, Response, WatcherState
from cowork_pilot.responder import build_applescript, execute_applescript, has_tool_result_arrived, notify, post_verify_response, set_clipboard
from cowork_pilot.session_finder import find_active_jsonl
from cowork_pilot.validator import validate_response
from cowork_pilot.watcher import JSONLTail, WatcherStateMachine, parse_jsonl_line


def _notify_escalate(event: Event) -> None:
    """Send macOS notification + TTS when ESCALATE is triggered."""
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

    notify("⚠️ Cowork Pilot — ESCALATE", body, tts=True)


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
            # All chunks in current plan completed
            completed_path = move_to_completed(plan_path)
            logger.info("harness", "Plan completed", dest=str(completed_path))
            print(f"Harness: Plan completed! Moved to {completed_path}")

            # Try to promote next plan from planning/
            promoted = promote_next_plan(active_dir.parent)
            if promoted is None:
                # No more plans — truly done
                logger.info("harness", "All plans completed")
                notify("✅ Cowork Pilot — 전체 완료", "모든 구현 계획이 완료되었습니다.", tts=True)
                print("Harness: All plans completed!")
                break

            # Load the promoted plan and continue
            plan_path = promoted
            logger.info("harness", "Promoted next plan", plan=str(plan_path))
            print(f"\nHarness: Promoted {plan_path.name} to active/")
            try:
                plan = parse_exec_plan(plan_path)
            except (ValueError, OSError) as e:
                notify_escalate(f"exec-plan parse error: {e}")
                break
            continue

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


def run_planning_mode(
    config_path: Path,
    *,
    project_mode: str = "",
    request: str = "",
    request_file: str = "",
    change_request: str = "",
    change_request_file: str = "",
    interactive: bool = False,
) -> None:
    from cowork_pilot.config import load_planning_config
    from cowork_pilot.planning.input_contract import resolve_planning_input_bundle
    from cowork_pilot.planning.models import PlanningContext
    from cowork_pilot.planning.runner import run_planning_pipeline
    from cowork_pilot.planning.storage import bootstrap_run_dir, create_run_id

    base_config = load_config(config_path)
    planning_config = load_planning_config(config_path)
    project_dir = Path(base_config.project_dir)
    run_root = project_dir / planning_config.run_root
    input_bundle = resolve_planning_input_bundle(
        project_dir=project_dir,
        project_mode_arg=project_mode,
        request_arg=request,
        request_file_arg=request_file,
        change_request_arg=change_request,
        change_request_file_arg=change_request_file,
    )
    run_id = create_run_id(input_bundle.project_mode.value, "cli-planning")
    run_dir = bootstrap_run_dir(run_root, run_id)
    run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            target_version="cli-planning",
            mode=input_bundle.project_mode,
            explicit_mode=input_bundle.explicit_mode,
            request_text=input_bundle.request_text,
            request_source=input_bundle.request_source,
            change_request_text=input_bundle.change_request_text,
            change_request_source=input_bundle.change_request_source,
        ),
        interactive=interactive,
    )


def _should_use_interactive_resume(mode: str) -> bool:
    """Determine whether to prompt in the terminal for planning questions."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    # "auto" — use interactive only when both stdin and stdout are TTYs
    return sys.stdin.isatty() and sys.stdout.isatty()


def cli() -> None:
    """Entry point for `cowork-pilot` command."""
    import argparse

    parser = argparse.ArgumentParser(description="Cowork Pilot — auto-response agent")
    parser.add_argument("--config", type=str, default="config.toml", help="Path to config file")
    parser.add_argument("--engine", type=str, choices=["codex", "claude"], help="Override engine")
    parser.add_argument("--mode", type=str, choices=["watch", "harness", "meta", "docs-orchestrator", "planning"], default="watch",
                       help="Run mode: watch (Phase 1) / harness (Phase 2) / meta (Phase 3) / docs-orchestrator (auto docs generation) / planning (runtime handoff)")
    parser.add_argument("--docs-mode", type=str, choices=["auto", "manual"], default="auto",
                       help="Docs-orchestrator mode: auto (AI decides) / manual (user decides). Only used with --mode docs-orchestrator")
    parser.add_argument("--manual-override", type=str, default="",
                       help="Comma-separated domain list for manual override in docs-orchestrator mode")
    parser.add_argument("--project-mode", type=str, choices=["greenfield", "brownfield"], default="",
                       help="Planning mode override (only used with --mode planning)")
    parser.add_argument("--request", type=str, default="",
                       help="Planning request text override (only used with --mode planning)")
    parser.add_argument("--request-file", type=str, default="",
                       help="Path to a planning request file override (only used with --mode planning)")
    parser.add_argument("--change-request", type=str, default="",
                       help="Brownfield change-request text override (only used with --mode planning)")
    parser.add_argument("--change-request-file", type=str, default="",
                       help="Path to a brownfield change-request file override (only used with --mode planning)")
    parser.add_argument("--planning-subcommand", type=str, choices=["run", "resume"], default="run",
                       help="Planning subcommand: run (default) / resume (only used with --mode planning)")
    parser.add_argument("--run-dir", type=str, default="",
                       help="Path to an existing planning run directory (only used with --mode planning --planning-subcommand resume)")
    parser.add_argument("--response", type=str, default="",
                       help="Response text for resume (only used with --mode planning --planning-subcommand resume)")
    parser.add_argument("--response-kind", type=str, choices=["answer", "approval"], default="answer",
                       help="Response kind for resume (only used with --mode planning --planning-subcommand resume)")
    parser.add_argument("--interactive-resume", type=str, choices=["auto", "always", "never"], default="auto",
                       help="Prompt in the current terminal for planning questions instead of requiring --response")
    parser.add_argument("--estimate", action="store_true", default=False,
                       help="Print session estimate and exit (only used with --mode planning)")
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
    elif args.mode == "docs-orchestrator":
        from cowork_pilot.config import load_docs_orchestrator_config
        from cowork_pilot.docs_orchestrator import run_docs_orchestrator
        orch_config = load_docs_orchestrator_config(Path(args.config), config)
        # Override docs_mode and manual_override from CLI args
        orch_config.docs_mode = args.docs_mode
        if args.manual_override:
            orch_config.manual_override = [
                d.strip() for d in args.manual_override.split(",") if d.strip()
            ]
        run_docs_orchestrator(config, orch_config)
    elif args.mode == "harness":
        harness_config = load_harness_config(Path(args.config), config)
        run_harness(config, harness_config)
    elif args.mode == "planning":
        try:
            if args.estimate:
                from cowork_pilot.planning.estimation import estimate_sessions

                mode = args.project_mode or "greenfield"
                estimate = estimate_sessions(
                    mode=mode,
                    size_class="medium",
                    feature_count=5,
                    domain_count=3,
                )
                print(f"Estimated sessions: {estimate.total_sessions}")
                print(f"  Stage sessions: {estimate.stage_sessions}")
                print(f"  Skeleton sessions: {estimate.skeleton_sessions}")
                print(f"  Feature outline sessions: {estimate.feature_outline_sessions}")
                print(f"  Detail sessions: {estimate.detail_sessions}")
                print(f"  Time range: {estimate.time_range_minutes[0]}-{estimate.time_range_minutes[1]} min")
                if args.planning_subcommand != "resume":
                    sys.exit(0)

            interactive = _should_use_interactive_resume(args.interactive_resume)

            if args.planning_subcommand == "resume":
                from cowork_pilot.planning.runner import resume_planning_pipeline

                if not args.run_dir:
                    print("Error: --run-dir is required for planning resume", file=sys.stderr)
                    sys.exit(2)
                run_dir = Path(args.run_dir)
                response_text = args.response or ""
                response_kind = args.response_kind or "answer"
                result = resume_planning_pipeline(
                    run_dir=run_dir,
                    response_text=response_text,
                    response_kind=response_kind,
                    interactive=interactive,
                )
                print(f"Resume complete: state={result.runtime_state}")
            else:
                run_planning_mode(
                    Path(args.config),
                    project_mode=args.project_mode,
                    request=args.request,
                    request_file=args.request_file,
                    change_request=args.change_request,
                    change_request_file=args.change_request_file,
                    interactive=interactive,
                )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
    else:
        run(config)


if __name__ == "__main__":
    cli()
