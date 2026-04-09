from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.storage import write_input_doc, write_intermediate_doc


@dataclass(frozen=True)
class NormalizedPlanningRequest:
    request_snapshot_path: Path
    normalized_request_path: Path
    change_request_path: Path | None
    change_request_summary: str
    waiting_for_change_request: bool


def normalize_planning_request(
    *,
    run_dir: Path,
    project_mode: ProjectMode,
    raw_request_text: str,
    raw_change_request_text: str,
    project_dir: Path | None = None,
) -> NormalizedPlanningRequest:
    request_text = _ensure_trailing_newline(raw_request_text.strip())
    request_snapshot_path = write_input_doc(run_dir, "request.md", request_text)
    canonical_root = project_dir if project_dir is not None else run_dir
    change_request_text = raw_change_request_text.strip()
    if (
        project_mode is ProjectMode.BROWNFIELD
        and not change_request_text
        and project_dir is not None
    ):
        canonical_change_request_path = canonical_root / "docs" / "planning" / "change-request.md"
        if canonical_change_request_path.exists():
            change_request_text = canonical_change_request_path.read_text(encoding="utf-8").strip()
    normalized_request_path = write_input_doc(
        run_dir,
        "normalized-request.md",
        _render_normalized_request(project_mode, raw_request_text, change_request_text),
    )

    if project_mode is ProjectMode.BROWNFIELD and not change_request_text:
        change_request_document = _render_change_request_document(
            raw_request_text=raw_request_text,
            raw_change_request_text=raw_change_request_text,
        )
        write_intermediate_doc(
            canonical_root / "docs" / "planning",
            "change-request.md",
            change_request_document,
        )
        change_request_path = write_input_doc(
            run_dir,
            "change-request.md",
            change_request_document,
        )
        return NormalizedPlanningRequest(
            request_snapshot_path=request_snapshot_path,
            normalized_request_path=normalized_request_path,
            change_request_path=change_request_path,
            change_request_summary="",
            waiting_for_change_request=True,
        )

    if project_mode is ProjectMode.BROWNFIELD:
        if _is_structured_change_request(change_request_text):
            change_request_document = _ensure_trailing_newline(change_request_text)
            change_request_summary = _summarize_structured_change_request(change_request_text)
        else:
            change_request_document = _render_change_request_document(
                raw_request_text=raw_request_text,
                raw_change_request_text=change_request_text,
            )
            change_request_summary = _summarize_change_request(change_request_text)
        write_intermediate_doc(
            canonical_root / "docs" / "planning",
            "change-request.md",
            change_request_document,
        )
        change_request_path = write_input_doc(
            run_dir,
            "change-request.md",
            change_request_document,
        )
    else:
        change_request_path = None
        change_request_summary = ""

    return NormalizedPlanningRequest(
        request_snapshot_path=request_snapshot_path,
        normalized_request_path=normalized_request_path,
        change_request_path=change_request_path,
        change_request_summary=change_request_summary,
        waiting_for_change_request=False,
    )


def _render_normalized_request(
    project_mode: ProjectMode,
    raw_request_text: str,
    raw_change_request_text: str,
) -> str:
    lines = [
        "# Normalized Planning Request",
        "",
        f"- project_mode: {project_mode.value}",
        "",
        "## Request",
        "",
        raw_request_text.strip() or "(empty)",
    ]
    if project_mode is ProjectMode.BROWNFIELD:
        lines.extend(
            [
                "",
                "## Change Request",
                "",
                raw_change_request_text.strip() or "(missing)",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _render_change_request_document(
    *,
    raw_request_text: str,
    raw_change_request_text: str,
) -> str:
    request_text = raw_request_text.strip() or "needs confirmation"
    change_request_text = raw_change_request_text.strip()
    has_change_request = bool(change_request_text)
    background_text = request_text if has_change_request else "needs confirmation"
    scope_text = "needs confirmation"
    out_of_scope_text = "needs confirmation"
    impact_text = "unknown" if has_change_request else "needs confirmation"
    constraint_text = "unknown"
    approval_text = "needs confirmation"
    return "\n".join(
        [
            "# Brownfield Change Request",
            "",
            "## 변경 목표",
            "",
            change_request_text or "needs confirmation",
            "",
            "## 배경",
            "",
            background_text,
            "",
            "## in scope",
            "",
            scope_text,
            "",
            "## out of scope",
            "",
            out_of_scope_text,
            "",
            "## 영향받는 영역",
            "",
            impact_text,
            "",
            "## 제약사항",
            "",
            constraint_text,
            "",
            "## 승인 기준",
            "",
            approval_text,
            "",
        ]
    )


def _summarize_change_request(change_request_text: str) -> str:
    for line in change_request_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _summarize_structured_change_request(change_request_text: str) -> str:
    lines = change_request_text.splitlines()
    in_goal_section = False
    goal_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_goal_section:
                break
            in_goal_section = stripped == "## 변경 목표"
            continue
        if in_goal_section:
            goal_lines.append(line)

    for line in goal_lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return _summarize_change_request(change_request_text)


def _is_structured_change_request(change_request_text: str) -> bool:
    return "## 변경 목표" in change_request_text


def _ensure_trailing_newline(text: str) -> str:
    if not text:
        return "\n"
    return text.rstrip("\n") + "\n"
