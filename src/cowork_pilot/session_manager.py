"""Chunk lifecycle manager — the top-level harness orchestrator.

Coordinates plan_parser, completion_detector, session_opener, and
session_finder to execute an exec-plan Chunk by Chunk.

Flow:
1. Parse exec-plan → find next incomplete Chunk
2. Open Cowork session with Chunk's session prompt
3. Detect new JSONL (race-condition safe)
4. Monitor for idle → CLI verify → COMPLETED or INCOMPLETE feedback
5. On COMPLETED: update checkboxes → next Chunk
6. On all Chunks done: move exec-plan to completed/
"""
from __future__ import annotations

import glob as _glob
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from cowork_pilot.completion_detector import (
    build_feedback_text,
    is_idle_trigger,
    send_feedback,
)
from cowork_pilot.plan_parser import Chunk, ExecPlan, parse_exec_plan, update_checkboxes
from cowork_pilot.session_finder import IGNORED_FILENAMES


# ── Configuration ────────────────────────────────────────────────────

@dataclass
class HarnessConfig:
    """Harness-specific configuration (loaded from config.toml [harness])."""
    idle_timeout_seconds: float = 120.0
    completion_check_max_retries: int = 3
    incomplete_retry_max: int = 3
    exec_plans_dir: str = "docs/exec-plans"

    # Session timing
    session_open_delay: float = 3.0
    session_prompt_delay: float = 1.0
    session_detect_timeout: float = 10.0
    session_detect_poll_interval: float = 1.0

    # Engine for CLI verification
    engine: str = "claude"
    engine_command: str = "claude"
    engine_args: list[str] = field(default_factory=lambda: ["-p"])


# ── Session lifecycle helpers ────────────────────────────────────────

def _get_jsonl_snapshot(base_path: Path) -> set[str]:
    """Take a snapshot of all .jsonl files under base_path (excluding ignored)."""
    return {
        str(p) for p in base_path.rglob("*.jsonl")
        if p.name not in IGNORED_FILENAMES
    }


def detect_new_jsonl(
    base_path: Path,
    before_snapshot: set[str],
    timeout: float = 10.0,
    poll_interval: float = 1.0,
) -> Path | None:
    """Poll for a new JSONL file that wasn't in the snapshot.

    Returns the new file Path, or None if not detected within timeout.
    """
    start = time.monotonic()
    while (time.monotonic() - start) < timeout:
        current = {
            str(p) for p in base_path.rglob("*.jsonl")
            if p.name not in IGNORED_FILENAMES
        }
        new_files = current - before_snapshot
        if new_files:
            # Return the newest one
            new_paths = [Path(p) for p in new_files]
            new_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return new_paths[0]
        time.sleep(poll_interval)
    return None


def open_chunk_session(
    chunk: Chunk,
    harness_config: HarnessConfig,
    session_base_path: Path,
    max_retries: int = 3,
) -> Path | None:
    """Open a new Cowork session for a Chunk and return the new JSONL path.

    Steps:
    1. Snapshot current JSONL files
    2. Call session_opener.open_new_session() with chunk's prompt
    3. Detect the new JSONL file

    Returns the new JSONL Path, or None on failure.
    """
    from cowork_pilot.session_opener import open_new_session

    for attempt in range(max_retries):
        snapshot = _get_jsonl_snapshot(session_base_path)

        success = open_new_session(
            initial_prompt=chunk.session_prompt,
            session_load_delay=harness_config.session_open_delay,
        )

        if not success:
            continue

        new_jsonl = detect_new_jsonl(
            session_base_path,
            snapshot,
            timeout=harness_config.session_detect_timeout,
            poll_interval=harness_config.session_detect_poll_interval,
        )

        if new_jsonl is not None:
            return new_jsonl

    return None  # All retries exhausted → ESCALATE


# ── Chunk transition ─────────────────────────────────────────────────

def find_next_incomplete_chunk(plan: ExecPlan) -> Chunk | None:
    """Find the first chunk that is not completed."""
    for chunk in plan.chunks:
        if chunk.status != "completed":
            return chunk
    return None


def move_to_completed(plan_path: Path) -> Path:
    """Move an exec-plan file from active/ to completed/.

    Returns the new path.
    """
    completed_dir = plan_path.parent.parent / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    dest = completed_dir / plan_path.name
    shutil.move(str(plan_path), str(dest))
    return dest


# ── Retry counters ───────────────────────────────────────────────────

@dataclass
class ChunkRetryState:
    """Per-chunk retry counters (reset when moving to a new chunk)."""
    cli_failure_count: int = 0
    incomplete_feedback_count: int = 0


# ── ESCALATE ─────────────────────────────────────────────────────────

def notify_escalate(message: str) -> None:
    """Send macOS notification for ESCALATE and pause."""
    try:
        script = (
            f'display notification "{message[:100]}" '
            f'with title "⚠️ Harness ESCALATE" '
            f'sound name "Sosumi"'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    import sys
    print(f"\a⚠️  HARNESS ESCALATE: {message}", file=sys.stderr)


# ── Main orchestration ───────────────────────────────────────────────

def run_chunk_verification(
    chunk: Chunk,
    harness_config: HarnessConfig,
    project_dir: str,
    plan_path: Path | None = None,
) -> tuple[str, str]:
    """Verify chunk completion by re-reading the exec-plan file.

    The Cowork session is responsible for updating checkboxes to [x]
    when it finishes.  We simply re-parse the file and check whether
    all criteria for this chunk are checked.

    Returns (status, detail) where status is COMPLETED/INCOMPLETE/ERROR.
    """
    if plan_path is None:
        return ("ERROR", "plan_path not provided")

    try:
        fresh_plan = parse_exec_plan(plan_path)
    except (OSError, ValueError) as exc:
        return ("ERROR", f"Cannot read plan: {exc}")

    # Find the matching chunk by number
    fresh_chunk = None
    for c in fresh_plan.chunks:
        if c.number == chunk.number:
            fresh_chunk = c
            break

    if fresh_chunk is None:
        return ("ERROR", f"Chunk {chunk.number} not found in plan")

    # Check all criteria
    unchecked = [
        cr.description for cr in fresh_chunk.completion_criteria
        if not cr.checked
    ]

    if not unchecked:
        return ("COMPLETED", "")

    return ("INCOMPLETE", ", ".join(unchecked))


def handle_chunk_completion(
    plan_path: Path,
    chunk: Chunk,
) -> None:
    """Update checkboxes for a completed chunk."""
    update_checkboxes(plan_path, chunk.number)


def process_chunk(
    plan_path: Path,
    chunk: Chunk,
    harness_config: HarnessConfig,
    project_dir: str,
    retry_state: ChunkRetryState,
    # Callbacks for testing — allow injection of mock functions
    verify_fn=None,
    feedback_fn=None,
) -> str:
    """Process the verification/feedback cycle for one chunk.

    Returns:
    - "COMPLETED" — chunk is done, checkboxes updated
    - "ESCALATE" — retries exhausted, needs human intervention
    - "WAITING" — idle conditions not met, keep watching
    """
    if verify_fn is None:
        verify_fn = run_chunk_verification
    if feedback_fn is None:
        feedback_fn = send_feedback

    status, detail = verify_fn(chunk, harness_config, project_dir, plan_path=plan_path)

    if status == "COMPLETED":
        handle_chunk_completion(plan_path, chunk)
        return "COMPLETED"

    elif status == "INCOMPLETE":
        retry_state.incomplete_feedback_count += 1
        if retry_state.incomplete_feedback_count > harness_config.incomplete_retry_max:
            return "ESCALATE"
        feedback_text = build_feedback_text(detail)
        feedback_fn(feedback_text)
        return "INCOMPLETE"

    else:  # ERROR
        retry_state.cli_failure_count += 1
        if retry_state.cli_failure_count > harness_config.completion_check_max_retries:
            return "ESCALATE"
        return "ERROR"
