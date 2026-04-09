from __future__ import annotations

import re
from pathlib import Path

from cowork_pilot.planning.models import OutlinePlan, PlanningStage, StageDispatch

_TABLE_PATTERN = re.compile(
    r"^\|\s*\d+\s*\|\s*(\d{2}-[a-zA-Z0-9_-]+)\.md\s*\|",
    re.MULTILINE,
)
_HEADER_PATTERN = re.compile(
    r"^##\s+(\d{2}-[a-zA-Z0-9_-]+)\.md",
    re.MULTILINE,
)

_SKELETON_TABLE_PATTERN = re.compile(
    r"^\|\s*\d+\s*\|\s*([a-zA-Z0-9_-]+)\s*\|",
    re.MULTILINE,
)


def parse_outline_plans(content: str) -> tuple[OutlinePlan, ...]:
    """Parse exec-plan outline to extract numbered plan entries."""
    seen: set[str] = set()
    plans: list[OutlinePlan] = []

    for pattern in (_TABLE_PATTERN, _HEADER_PATTERN):
        for match in pattern.finditer(content):
            name_with_number = match.group(1)
            if name_with_number in seen:
                continue
            seen.add(name_with_number)
            parts = name_with_number.split("-", 1)
            number = parts[0]
            bare_name = parts[1] if len(parts) > 1 else name_with_number
            plans.append(OutlinePlan(
                number=number,
                name=bare_name,
                filename=f"{name_with_number}.md",
            ))

    plans.sort(key=lambda p: p.number)
    return tuple(plans)


def parse_skeleton_features(content: str) -> tuple[str, ...]:
    """Parse skeleton output to extract ordered feature names."""
    features: list[str] = []
    seen: set[str] = set()
    for match in _SKELETON_TABLE_PATTERN.finditer(content):
        name = match.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            features.append(name)
    return tuple(features)


def build_detail_dispatches(
    plans: tuple[OutlinePlan, ...],
    *,
    start_order: int,
) -> tuple[StageDispatch, ...]:
    """Create one EXEC_PLAN_DETAIL dispatch per outline plan."""
    return tuple(
        StageDispatch(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            execution_kind="ai",
            order=start_order + index,
            substage=f"{plan.number}-{plan.name}",
        )
        for index, plan in enumerate(plans)
    )


def build_feature_outline_dispatches(
    features: tuple[str, ...],
    *,
    start_order: int,
) -> tuple[StageDispatch, ...]:
    """Create one EXEC_PLAN_FEATURE_OUTLINE dispatch per feature from skeleton."""
    return tuple(
        StageDispatch(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            execution_kind="ai",
            order=start_order + index,
            substage=feature,
        )
        for index, feature in enumerate(features)
    )


def merge_feature_outlines(*, run_dir: Path) -> Path:
    """Merge skeleton ordering + per-feature outline files into exec-plan-outline.md.

    Reads:
      - run_dir/exec-plan-skeleton.md (for feature ordering)
      - run_dir/feature-outlines/{feature}.md (per-feature chunk details)

    Writes:
      - run_dir/exec-plan-outline.md (unified, numbered outline)
    """
    skeleton_path = run_dir / "exec-plan-skeleton.md"
    skeleton_content = skeleton_path.read_text(encoding="utf-8") if skeleton_path.exists() else ""
    features = parse_skeleton_features(skeleton_content)

    outlines_dir = run_dir / "feature-outlines"
    sections: list[str] = []

    # Header table
    table_lines = [
        "## exec-plan 개요\n",
        "| # | 파일명 | 범위 |",
        "|---|--------|------|",
    ]
    for idx, feature in enumerate(features, 1):
        number = f"{idx:02d}"
        table_lines.append(f"| {idx} | {number}-{feature}.md | {feature} |")
    sections.append("\n".join(table_lines))

    # Per-feature sections
    for idx, feature in enumerate(features, 1):
        number = f"{idx:02d}"
        feature_file = outlines_dir / f"{feature}.md"
        if feature_file.exists():
            feature_content = feature_file.read_text(encoding="utf-8")
            sections.append(f"\n## {number}-{feature}.md 상세\n\n{feature_content}")
        else:
            sections.append(f"\n## {number}-{feature}.md 상세\n\n> WARNING: Feature outline missing for {feature}\n")

    outline_path = run_dir / "exec-plan-outline.md"
    outline_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return outline_path
