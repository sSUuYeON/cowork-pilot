from __future__ import annotations

from enum import Enum
from pathlib import Path

from cowork_pilot.planning.quality_gate import _DEFAULT_MIN_LINES


class RecoveryDecision(str, Enum):
    MARK_COMPLETED = "mark_completed"
    DELETE_AND_RETRY = "delete_and_retry"
    RETRY = "retry"


def recover_interrupted_stage(
    *,
    run_dir: Path,
    stage: str,
    expected_outputs: tuple[str, ...] = (),
    min_lines: int | None = None,
) -> RecoveryDecision:
    """3-step recovery policy for interrupted stages.

    1. Outputs exist + sufficient lines → MARK_COMPLETED
    2. Outputs exist but too short → DELETE_AND_RETRY
    3. No outputs → RETRY
    """
    effective_min = min_lines if min_lines is not None else _DEFAULT_MIN_LINES.get(stage, 5)

    any_exists = False
    for output_rel in expected_outputs:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if output_path.exists():
            any_exists = True
            line_count = len(output_path.read_text(encoding="utf-8").splitlines())
            if line_count < effective_min:
                # Step 2: exists but bad → log, delete, retry
                from cowork_pilot.planning.runtime_storage import append_runtime_event
                append_runtime_event(run_dir, {
                    "type": "recovery_file_deleted",
                    "stage": stage,
                    "path": str(output_path),
                    "line_count": line_count,
                    "min_required": effective_min,
                })
                output_path.unlink()
                return RecoveryDecision.DELETE_AND_RETRY

    if not any_exists and expected_outputs:
        # Step 3: nothing produced → retry
        return RecoveryDecision.RETRY

    # Step 1: all exist with sufficient content → completed
    return RecoveryDecision.MARK_COMPLETED
