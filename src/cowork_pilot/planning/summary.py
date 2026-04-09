from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.runtime_storage import read_completed_stages, read_run_state


@dataclass(frozen=True)
class PipelineSummary:
    total_stages_completed: int
    exec_plan_count: int
    errors: int
    exec_plan_files: tuple[str, ...]


def build_pipeline_summary(*, run_dir: Path, project_dir: Path) -> PipelineSummary:
    """Build final pipeline summary from run artifacts."""
    completed = read_completed_stages(run_dir)

    plans_dir = project_dir / "docs" / "exec-plans" / "planning"
    plan_files = sorted(plans_dir.glob("*.md")) if plans_dir.is_dir() else []
    plan_files = [f for f in plan_files if f.name != "exec-plan.md"]  # exclude legacy single file

    run_state = read_run_state(run_dir)
    error_count = int(run_state.get("error_count", 0))

    return PipelineSummary(
        total_stages_completed=len(completed),
        exec_plan_count=len(plan_files),
        errors=error_count,
        exec_plan_files=tuple(f.name for f in plan_files),
    )


def print_pipeline_summary(summary: PipelineSummary) -> None:
    """Print human-readable summary to stderr."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("Planning Pipeline — Final Summary", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Stages completed: {summary.total_stages_completed}", file=sys.stderr)
    print(f"  Exec-plan files: {summary.exec_plan_count}", file=sys.stderr)
    print(f"  Errors: {summary.errors}", file=sys.stderr)
    if summary.exec_plan_files:
        for name in summary.exec_plan_files:
            print(f"    - {name}", file=sys.stderr)
    else:
        print("  WARNING: No exec-plan files generated", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
