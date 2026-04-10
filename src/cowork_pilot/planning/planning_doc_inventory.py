"""Role-based inventory of project-owned documentation."""
from __future__ import annotations

from pathlib import Path

# Read policy constants
READ_POLICY_NONE = "none"
READ_POLICY_INDEX_ONLY = "index_only"
READ_POLICY_SPEC_DOCUMENTS = "spec_documents"
READ_POLICY_ALL = "all"


def build_doc_role_inventory(project_dir: Path) -> dict[str, tuple[Path, ...]]:
    """
    Build a mapping of doc role -> tuple of existing paths for that role.

    Roles discovered:
    - "spec_documents": all *.md in docs/specs/ + docs/product-specs/ (excluding index.md)
    - "spec_index": docs/specs/index.md, docs/product-specs/index.md (whichever exists)
    - "agents": AGENTS.md
    - "architecture": ARCHITECTURE.md, docs/ARCHITECTURE.md (whichever exists)
    - "design_guide": docs/DESIGN_GUIDE.md
    - "security": docs/SECURITY.md
    - "core_beliefs": docs/design-docs/core-beliefs.md
    - "data_model": docs/design-docs/data-model.md
    """
    inventory: dict[str, list[Path]] = {}

    # spec_documents: all spec files except index
    spec_documents: list[Path] = []
    for spec_dir in [project_dir / "docs" / "specs", project_dir / "docs" / "product-specs"]:
        if spec_dir.exists():
            for md_file in sorted(spec_dir.glob("*.md")):
                if md_file.name != "index.md":
                    spec_documents.append(md_file)
    inventory["spec_documents"] = tuple(spec_documents)

    # spec_index: index.md from either specs or product-specs
    spec_index: list[Path] = []
    for spec_dir in [project_dir / "docs" / "specs", project_dir / "docs" / "product-specs"]:
        index_path = spec_dir / "index.md"
        if index_path.exists():
            spec_index.append(index_path)
    inventory["spec_index"] = tuple(spec_index)

    # agents: AGENTS.md
    agents_path = project_dir / "AGENTS.md"
    inventory["agents"] = (agents_path,) if agents_path.exists() else ()

    # architecture: ARCHITECTURE.md or docs/ARCHITECTURE.md
    arch_paths: list[Path] = []
    for arch_candidate in [project_dir / "ARCHITECTURE.md", project_dir / "docs" / "ARCHITECTURE.md"]:
        if arch_candidate.exists():
            arch_paths.append(arch_candidate)
    inventory["architecture"] = tuple(arch_paths)

    # design_guide: docs/DESIGN_GUIDE.md
    design_guide_path = project_dir / "docs" / "DESIGN_GUIDE.md"
    inventory["design_guide"] = (design_guide_path,) if design_guide_path.exists() else ()

    # security: docs/SECURITY.md
    security_path = project_dir / "docs" / "SECURITY.md"
    inventory["security"] = (security_path,) if security_path.exists() else ()

    # core_beliefs: docs/design-docs/core-beliefs.md
    core_beliefs_path = project_dir / "docs" / "design-docs" / "core-beliefs.md"
    inventory["core_beliefs"] = (core_beliefs_path,) if core_beliefs_path.exists() else ()

    # data_model: docs/design-docs/data-model.md
    data_model_path = project_dir / "docs" / "design-docs" / "data-model.md"
    inventory["data_model"] = (data_model_path,) if data_model_path.exists() else ()

    return inventory


def select_context_paths(
    inventory: dict[str, tuple[Path, ...]],
    required_roles: tuple[str, ...],
    read_policy: str,
) -> tuple[Path, ...]:
    """
    Select a subset of paths from the inventory for the given roles and policy.

    read_policy values:
    - "none": empty tuple
    - "index_only": only spec_index paths
    - "spec_documents": all spec_documents paths
    - "all": all paths for all required_roles
    """
    if read_policy == READ_POLICY_NONE:
        return ()

    if read_policy == READ_POLICY_INDEX_ONLY:
        # Only spec_index
        return inventory.get("spec_index", ())

    if read_policy == READ_POLICY_SPEC_DOCUMENTS:
        # Only spec_documents
        return inventory.get("spec_documents", ())

    if read_policy == READ_POLICY_ALL:
        # All paths from all required roles
        all_paths: list[Path] = []
        for role in required_roles:
            if role in inventory:
                all_paths.extend(inventory[role])
        return tuple(all_paths)

    # Unknown policy defaults to none
    return ()
