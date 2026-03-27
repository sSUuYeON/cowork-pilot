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
import time
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.completion_detector import (
    build_feedback_text,
    is_idle_trigger,
    send_feedback,
)
from cowork_pilot.config import HarnessConfig, ReviewConfig
from cowork_pilot.plan_parser import Chunk, ExecPlan, parse_exec_plan, update_checkboxes
from cowork_pilot.session_finder import IGNORED_FILENAMES


# ── Session prompt builder ──────────────────────────────────────────

REVIEW_INSTRUCTIONS = """\

다음 순서를 반드시 지켜라:

1. 위 Tasks를 구현해라
2. 구현 완료 후 /engineering:code-review 스킬로 이번 chunk의 코드를 리뷰해라
   - 추가 리뷰 항목: docs/DESIGN_GUIDE.md의 레이아웃/스페이싱 수치 준수 여부
3. 리뷰에서 발견된 문제를 직접 수정해라
4. docs/implementation-map/ 아래에 이번 기능의 구현 기록을 작성해라
   - 기능 폴더와 index.md 생성 (형식은 docs/implementation-map/index.md 참조)
   - docs/implementation-map/index.md 루트 테이블에도 행 추가
5. 마지막으로 /chunk-complete:chunk-complete 스킬로 완료 처리해라

※ /vm-install:vm-install은 순서 무관 — npm install 등 설치가 필요한 시점에 호출
※ /chunk-complete:chunk-complete는 반드시 마지막에 호출 (리뷰+수정+기록 완료 후)
스타일/레이아웃 구현 시 반드시 docs/DESIGN_GUIDE.md를 직접 열어 읽고 수치를 따라라.
코드를 예측하지 말고 항상 직접 확인해라."""


def build_session_prompt(
    chunk: Chunk,
    review_config: ReviewConfig | None = None,
) -> str:
    """Wrap a chunk's session prompt with review instructions if enabled.

    When review is enabled (and this chunk is not in skip_chunks),
    appends the review/implementation-map/chunk-complete ordering
    instructions to the original session prompt.

    When review is disabled, returns the original prompt unchanged.
    """
    prompt = chunk.session_prompt

    if review_config is None or not review_config.enabled:
        return prompt

    if chunk.number in review_config.skip_chunks:
        return prompt

    return prompt + REVIEW_INSTRUCTIONS


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
    review_config: ReviewConfig | None = None,
) -> Path | None:
    """Open a new Cowork session for a Chunk and return the new JSONL path.

    Steps:
    1. Build session prompt (with review instructions if enabled)
    2. Snapshot current JSONL files
    3. Call session_opener.open_new_session() with the prompt
    4. Detect the new JSONL file

    Returns the new JSONL Path, or None on failure.
    """
    from cowork_pilot.session_opener import open_new_session

    prompt = build_session_prompt(chunk, review_config)

    for attempt in range(max_retries):
        snapshot = _get_jsonl_snapshot(session_base_path)

        success = open_new_session(
            initial_prompt=prompt,
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


def promote_next_plan(exec_plans_dir: Path) -> Path | None:
    """Move the next plan from planning/ to active/.

    Selects by filename sort order (e.g. 01-xxx before 02-yyy).
    Returns the new path in active/, or None if nothing to promote
    or active/ already has a plan.
    """
    planning_dir = exec_plans_dir / "planning"
    active_dir = exec_plans_dir / "active"

    if not planning_dir.exists():
        return None

    # Don't promote if active/ already has a plan
    if list(active_dir.glob("*.md")):
        return None

    candidates = sorted(planning_dir.glob("*.md"))
    if not candidates:
        return None

    next_plan = candidates[0]
    dest = active_dir / next_plan.name
    shutil.move(str(next_plan), str(dest))
    return dest


# ── Retry counters ───────────────────────────────────────────────────

@dataclass
class ChunkRetryState:
    """Per-chunk retry counters (reset when moving to a new chunk)."""
    cli_failure_count: int = 0
    incomplete_feedback_count: int = 0


# ── ESCALATE ─────────────────────────────────────────────────────────

def notify_escalate(message: str) -> None:
    """Send macOS notification for ESCALATE."""
    from cowork_pilot.responder import notify
    notify("⚠️ Harness ESCALATE", message)


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
