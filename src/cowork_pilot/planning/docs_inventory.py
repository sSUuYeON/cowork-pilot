from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ClassificationSnapshot, ProjectConventionProfile, SizeClass
from cowork_pilot.planning.spec_sources import resolve_document_role_mapping


@dataclass(frozen=True)
class CoreDocInventory:
    core_doc_axes: tuple[str, ...]
    required_core_docs: tuple[str, ...]
    conditional_core_docs: tuple[str, ...]
    not_applicable_core_docs: tuple[str, ...]


def check_core_docs(snapshot: ClassificationSnapshot | None = None) -> list[str]:
    inventory = resolve_core_doc_inventory(snapshot)
    return list(inventory.required_core_docs)


def select_adaptive_docs(
    snapshot: ClassificationSnapshot | None = None,
    core_docs: list[str] | None = None,
) -> list[str]:
    _ = core_docs
    inventory = resolve_core_doc_inventory(snapshot)
    return list(inventory.conditional_core_docs)


def resolve_core_doc_inventory(
    snapshot: ClassificationSnapshot | None = None,
    profile: ProjectConventionProfile = ProjectConventionProfile.SPECS_CENTERED,
) -> CoreDocInventory:
    _ = resolve_document_role_mapping(profile)
    size_class = snapshot.size_class if snapshot is not None else SizeClass.SMALL

    required = ["agents", "spec_index", "design_guide"]
    conditional = ["architecture", "security", "core_beliefs", "data_model", "spec_documents"]
    not_applicable: list[str] = []

    if size_class in {SizeClass.MEDIUM, SizeClass.LARGE}:
        required.extend(["architecture", "security", "spec_documents"])
        conditional = [role for role in conditional if role not in required]
    if size_class is SizeClass.LARGE:
        required.extend(["core_beliefs", "data_model"])
        conditional = [role for role in conditional if role not in required]

    return CoreDocInventory(
        core_doc_axes=("agents", "spec_index", "design_guide", "architecture", "security"),
        required_core_docs=tuple(required),
        conditional_core_docs=tuple(conditional),
        not_applicable_core_docs=tuple(not_applicable),
    )


def parse_core_docs_check(path: Path) -> dict:
    """Parse AI-generated core-docs-check.md JSON block."""
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    return data


def parse_adaptive_docs_selection(path: Path) -> dict:
    """Parse AI-generated adaptive-docs-selection.md JSON block."""
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    return data
