from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""
    retry_recommended: bool = False


_DEFAULT_MIN_LINES: dict[str, int] = {
    "classification": 5,
    "core_docs_check": 5,
    "adaptive_docs_selection": 5,
    "product_completeness_review": 10,
    "scope_structuring": 5,
    "work_sizing": 5,
    "plan_packing": 5,
    "plan_review": 10,
    "exec_plan_skeleton": 10,
    "exec_plan_feature_outline": 15,
    "exec_plan_detail": 15,
    "brownfield_code_observation_extraction": 10,
    "brownfield_observation_synthesis": 10,
    "brownfield_gap_synthesis": 10,
}


def evaluate_stage_gate(
    *,
    stage: str,
    run_dir: Path,
    expected_outputs: tuple[str, ...] = (),
    min_lines: int | None = None,
) -> GateResult:
    """Evaluate quality gate for a completed stage."""
    effective_min = min_lines if min_lines is not None else _DEFAULT_MIN_LINES.get(stage, 5)

    for output_rel in expected_outputs:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if not output_path.exists():
            return GateResult(passed=False, reason=f"Missing expected output: {output_rel}", retry_recommended=True)

        line_count = len(output_path.read_text(encoding="utf-8").splitlines())
        if line_count < effective_min:
            return GateResult(
                passed=False,
                reason=f"Output too short: {output_rel} has {line_count} lines (min {effective_min})",
                retry_recommended=True,
            )

    # Special check for skeleton: must produce parseable features
    if stage == "exec_plan_skeleton" and expected_outputs:
        from cowork_pilot.planning.outline import parse_skeleton_features

        for output_rel in expected_outputs:
            output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
            if output_path.exists():
                features = parse_skeleton_features(output_path.read_text(encoding="utf-8"))
                if len(features) == 0:
                    return GateResult(
                        passed=False,
                        reason=f"Skeleton has 0 features parsed from {output_rel}",
                        retry_recommended=True,
                    )

    return GateResult(passed=True)


@dataclass(frozen=True)
class RollbackResult:
    rolled_back: bool
    retry_dispatch_index: int = -1
    escalated: bool = False


_RETRY_COUNTS_FILENAME = "retry-counts.json"


def _read_retry_counts(run_dir: Path) -> dict[str, int]:
    path = run_dir / _RETRY_COUNTS_FILENAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_retry_count(run_dir: Path, dispatch_index: int, count: int) -> None:
    counts = _read_retry_counts(run_dir)
    counts[str(dispatch_index)] = count
    (run_dir / _RETRY_COUNTS_FILENAME).write_text(
        json.dumps(counts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def rollback_stage(
    *,
    run_dir: Path,
    dispatch_index: int,
    outputs_to_remove: tuple[str, ...] = (),
    max_retries: int = 3,
) -> RollbackResult:
    """Rollback a failed stage: remove outputs, return index to retry.

    Retry count is persisted in retry-counts.json so it survives crashes/resume.
    """
    counts = _read_retry_counts(run_dir)
    current = counts.get(str(dispatch_index), 0)

    if current >= max_retries:
        return RollbackResult(rolled_back=False, escalated=True)

    for output_rel in outputs_to_remove:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if output_path.exists():
            from cowork_pilot.planning.runtime_storage import append_runtime_event

            append_runtime_event(run_dir, {
                "type": "rollback_file_deleted",
                "dispatch_index": dispatch_index,
                "path": str(output_path),
            })
            output_path.unlink()

    _write_retry_count(run_dir, dispatch_index, current + 1)
    return RollbackResult(rolled_back=True, retry_dispatch_index=dispatch_index)
