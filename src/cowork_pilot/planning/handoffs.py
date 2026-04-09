from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.storage import write_intermediate_doc


@dataclass(frozen=True)
class StageHandoff:
    order: int
    stage: PlanningStage
    stage_purpose: str
    decisions: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    assumptions: tuple[str, ...]
    outputs: tuple[str, ...]
    next_read_set: tuple[str, ...]


def write_stage_handoff(
    *,
    run_dir: Path,
    order: int,
    stage: PlanningStage,
    decisions: tuple[str, ...],
    unresolved_questions: tuple[str, ...],
    assumptions: tuple[str, ...],
    outputs: tuple[str, ...],
    next_read_set: tuple[str | Path, ...],
) -> Path:
    filename = f"stage-handoffs/{order:02d}-{stage.value}.md"
    body = _render_stage_handoff(
        order=order,
        stage=stage,
        decisions=decisions,
        unresolved_questions=unresolved_questions,
        assumptions=assumptions,
        outputs=outputs,
        next_read_set=next_read_set,
    )
    return write_intermediate_doc(run_dir, filename, body)


def load_stage_handoff(path: Path) -> StageHandoff:
    lines = path.read_text(encoding="utf-8").splitlines()
    order = int(_parse_metadata_value(lines, "order"))
    stage = PlanningStage(_parse_metadata_value(lines, "stage"))
    sections = _split_sections(lines)
    return StageHandoff(
        order=order,
        stage=stage,
        stage_purpose=_parse_single_value(_require_section(sections, "Stage Purpose")),
        decisions=_parse_list_section(_require_section(sections, "Decisions")),
        unresolved_questions=_parse_list_section(_require_section(sections, "Unresolved Questions")),
        assumptions=_parse_list_section(_require_section(sections, "Assumptions")),
        outputs=_parse_list_section(_require_section(sections, "Outputs")),
        next_read_set=_parse_list_section(_require_section(sections, "Next Read Set")),
    )


def build_stage_read_set(
    *,
    run_dir: Path,
    canonical_docs: tuple[Path, ...] = (),
    previous_handoff: Path | None = None,
    runtime_logs: tuple[Path | str, ...] = (),
) -> tuple[Path, ...]:
    ordered_paths: list[Path] = []
    normalized_request = run_dir / "inputs" / "normalized-request.md"
    ordered_paths.append(normalized_request)

    change_request = run_dir / "inputs" / "change-request.md"
    if change_request.exists():
        ordered_paths.append(change_request)

    if previous_handoff is not None:
        ordered_paths.append(previous_handoff)
    ordered_paths.extend(canonical_docs)
    for runtime_log in runtime_logs:
        candidate = _resolve_runtime_log_path(run_dir, runtime_log)
        if candidate.exists():
            ordered_paths.append(candidate)
    return _dedupe_paths(ordered_paths)


def _render_stage_handoff(
    *,
    order: int,
    stage: PlanningStage,
    decisions: tuple[str, ...],
    unresolved_questions: tuple[str, ...],
    assumptions: tuple[str, ...],
    outputs: tuple[str, ...],
    next_read_set: tuple[str | Path, ...],
) -> str:
    stage_purpose = _stage_purpose(stage)
    lines = [
        "# Stage Handoff",
        "",
        f"- order: {order:02d}",
        f"- stage: {stage.value}",
        "",
        "## Stage Purpose",
        f"- {stage_purpose}",
        "",
        "## Decisions",
    ]
    lines.extend(_render_list(decisions))
    lines.extend(
        [
            "",
            "## Unresolved Questions",
        ]
    )
    lines.extend(_render_list(unresolved_questions))
    lines.extend(
        [
            "",
            "## Assumptions",
        ]
    )
    lines.extend(_render_list(assumptions))
    lines.extend(
        [
            "",
            "## Outputs",
        ]
    )
    lines.extend(_render_list(outputs))
    lines.extend(
        [
            "",
            "## Next Read Set",
        ]
    )
    lines.extend(_render_list(str(path) for path in next_read_set))
    lines.append("")
    return "\n".join(lines)


def _stage_purpose(stage: PlanningStage) -> str:
    return stage.value.replace("_", " ")


def _parse_metadata_value(lines: list[str], label: str) -> str:
    prefix = f"- {label}: "
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    raise ValueError(f"missing metadata field: {label}")


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_name = ""
    current_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_name:
                sections[current_name] = current_lines
            current_name = stripped[3:].strip()
            current_lines = []
            continue
        if current_name:
            current_lines.append(line)
    if current_name:
        sections[current_name] = current_lines
    return sections


def _parse_list_section(lines: list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "- none":
            continue
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
        else:
            values.append(stripped)
    return tuple(values)


def _parse_single_value(lines: list[str]) -> str:
    values = _parse_list_section(lines)
    return values[0] if values else ""


def _require_section(sections: dict[str, list[str]], name: str) -> list[str]:
    if name not in sections:
        raise ValueError(f"missing required handoff section: {name}")
    return sections[name]


def _resolve_runtime_log_path(run_dir: Path, runtime_log: Path | str) -> Path:
    candidate = Path(runtime_log)
    if candidate.is_absolute():
        return candidate
    return run_dir / candidate


def _render_list(items: object) -> list[str]:
    values = tuple(items)
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def _dedupe_paths(paths: list[Path]) -> tuple[Path, ...]:
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return tuple(unique_paths)
