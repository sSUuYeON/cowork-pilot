from __future__ import annotations

import shutil
from pathlib import Path, PurePath


def create_run_id(mode: str, target_version: str) -> str:
    return f"{mode.strip()}-{target_version.strip()}"


def _validate_relative_name(value: str, label: str) -> None:
    path = PurePath(value)
    if not value or path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise ValueError(f"unsafe {label}: {value}")


_PLANNING_REFERENCES_DIR = Path(__file__).parent / "planning_references"


def copy_planning_references(run_dir: Path) -> Path:
    """Copy planning reference docs into *run_dir*/planning-references/.

    Mirrors the docs-orchestrator ``_copy_references()`` pattern: reference
    files ship inside the package and are copied into the run directory so
    that every stage can ``RE-READ`` them from a stable, predictable path.
    """
    dest = run_dir / "planning-references"
    dest.mkdir(parents=True, exist_ok=True)
    if _PLANNING_REFERENCES_DIR.is_dir():
        for src_file in sorted(_PLANNING_REFERENCES_DIR.glob("*.md")):
            shutil.copy2(src_file, dest / src_file.name)
    return dest


def bootstrap_run_dir(base_dir: Path, run_id: str) -> Path:
    _validate_relative_name(run_id, "run_id")
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    copy_planning_references(run_dir)
    return run_dir


def write_intermediate_doc(run_dir: Path, filename: str, content: str) -> Path:
    candidate = (run_dir / filename).resolve(strict=False)
    run_root = run_dir.resolve(strict=False)
    if candidate != run_root and run_root not in candidate.parents:
        raise ValueError(f"filename escapes run_dir: {filename}")
    doc_path = candidate
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(content, encoding="utf-8")
    return doc_path


def write_input_doc(run_dir: Path, filename: str, content: str) -> Path:
    return write_intermediate_doc(run_dir, f"inputs/{filename}", content)
