from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.spec_sources import resolve_planning_project_mode


@dataclass(frozen=True)
class PlanningInputBundle:
    project_mode: ProjectMode
    explicit_mode: bool
    request_text: str
    request_source: str
    change_request_text: str
    change_request_source: str


def resolve_planning_input_bundle(
    *,
    project_dir: Path,
    project_mode_arg: str = "",
    request_arg: str = "",
    request_file_arg: str = "",
    change_request_arg: str = "",
    change_request_file_arg: str = "",
) -> PlanningInputBundle:
    explicit_mode = bool(project_mode_arg)
    explicit_project_mode = ProjectMode(project_mode_arg) if explicit_mode else None
    project_mode = resolve_planning_project_mode(project_dir, explicit_project_mode)

    request_text, request_source = _resolve_text_input(
        direct_text=request_arg,
        direct_path=request_file_arg,
        fallback_path=project_dir / "docs" / "planning" / "request.md",
    )
    change_request_text, change_request_source = _resolve_text_input(
        direct_text=change_request_arg,
        direct_path=change_request_file_arg,
        fallback_path=project_dir / "docs" / "planning" / "change-request.md",
    )

    return PlanningInputBundle(
        project_mode=project_mode,
        explicit_mode=explicit_mode,
        request_text=request_text,
        request_source=request_source,
        change_request_text=change_request_text,
        change_request_source=change_request_source,
    )


def _resolve_text_input(
    *,
    direct_text: str,
    direct_path: str,
    fallback_path: Path,
) -> tuple[str, str]:
    if direct_text:
        return direct_text, "cli"

    if direct_path:
        path = Path(direct_path)
        if not path.exists():
            label = "request" if fallback_path.name == "request.md" else "change-request"
            raise ValueError(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8"), str(path)

    if fallback_path.exists():
        return fallback_path.read_text(encoding="utf-8"), str(fallback_path)

    return "", ""
