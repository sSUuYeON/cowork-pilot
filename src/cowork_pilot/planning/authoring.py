from __future__ import annotations

from pathlib import PurePath
from pathlib import Path


def _validate_relative_name(value: str, label: str) -> None:
    path = PurePath(value)
    if not value or path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise ValueError(f"unsafe {label}: {value}")


def write_exec_plan(
    source_path: Path | None = None,
    destination_dir: Path | None = None,
    plan_name: str = "exec-plan.md",
) -> Path | None:
    if source_path is None or destination_dir is None:
        return None
    _validate_relative_name(plan_name, "plan_name")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / plan_name
    destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return destination_path


def write_numbered_exec_plan(
    source_path: Path | None = None,
    destination_dir: Path | None = None,
    plan_name: str = "",
) -> Path | None:
    """Write a single numbered exec-plan file (e.g. 02-auth-flow.md)."""
    if source_path is None or destination_dir is None or not plan_name:
        return None
    _validate_relative_name(f"{plan_name}.md", "plan_name")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / f"{plan_name}.md"
    destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return destination_path
