from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectConventionProfile, ProjectMode

_SPEC_DIRS = ("docs/specs", "docs/product-specs")
_CODE_DIRS = ("src", "app", "lib", "backend", "frontend")
_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}
_ALL_PROFILES = (
    ProjectConventionProfile.SPECS_CENTERED.value,
    ProjectConventionProfile.PRODUCT_SPECS_CENTERED.value,
)


@dataclass(frozen=True)
class PlanningInputs:
    project_mode: ProjectMode
    canonical_spec_paths: tuple[Path, ...]
    uploaded_spec_path: Path | None
    empty_project: bool
    has_existing_code: bool
    source_material_only: bool


@dataclass(frozen=True)
class DocumentRoleMapping:
    role: str
    allowed_path_aliases: tuple[str, ...]
    preferred_read_order: tuple[str, ...]
    preferred_write_target: Path
    required_by_profile: tuple[str, ...]


def detect_project_convention_profile(
    project_dir: Path,
    explicit_override: str | None = None,
    agents_text: str = "",
) -> ProjectConventionProfile:
    profile_text = explicit_override or _extract_profile_override(agents_text)
    if profile_text:
        return ProjectConventionProfile(profile_text)

    if (project_dir / "docs" / "product-specs").exists():
        return ProjectConventionProfile.PRODUCT_SPECS_CENTERED
    if (project_dir / "docs" / "specs").exists():
        return ProjectConventionProfile.SPECS_CENTERED
    return ProjectConventionProfile.SPECS_CENTERED


def resolve_document_role_mapping(
    profile: ProjectConventionProfile,
) -> dict[str, DocumentRoleMapping]:
    spec_index_aliases = ("docs/specs/index.md", "docs/product-specs/index.md")
    spec_document_aliases = ("docs/specs/*.md", "docs/product-specs/*.md")
    if profile is ProjectConventionProfile.PRODUCT_SPECS_CENTERED:
        spec_index_read_order = (
            "docs/product-specs/index.md",
            "docs/specs/index.md",
        )
        spec_documents_read_order = (
            "docs/product-specs/*.md",
            "docs/specs/*.md",
        )
        spec_index_target = Path("docs/product-specs/index.md")
        spec_document_target = Path("docs/product-specs/feature-spec.md")
    else:
        spec_index_read_order = (
            "docs/specs/index.md",
            "docs/product-specs/index.md",
        )
        spec_documents_read_order = (
            "docs/specs/*.md",
            "docs/product-specs/*.md",
        )
        spec_index_target = Path("docs/specs/index.md")
        spec_document_target = Path("docs/specs/feature-spec.md")

    return {
        "agents": DocumentRoleMapping(
            role="agents",
            allowed_path_aliases=("AGENTS.md",),
            preferred_read_order=("AGENTS.md",),
            preferred_write_target=Path("AGENTS.md"),
            required_by_profile=_ALL_PROFILES,
        ),
        "spec_index": DocumentRoleMapping(
            role="spec_index",
            allowed_path_aliases=spec_index_aliases,
            preferred_read_order=spec_index_read_order,
            preferred_write_target=spec_index_target,
            required_by_profile=_ALL_PROFILES,
        ),
        "spec_documents": DocumentRoleMapping(
            role="spec_documents",
            allowed_path_aliases=spec_document_aliases,
            preferred_read_order=spec_documents_read_order,
            preferred_write_target=spec_document_target,
            required_by_profile=_ALL_PROFILES,
        ),
        "architecture": DocumentRoleMapping(
            role="architecture",
            allowed_path_aliases=("ARCHITECTURE.md", "docs/ARCHITECTURE.md"),
            preferred_read_order=("ARCHITECTURE.md", "docs/ARCHITECTURE.md"),
            preferred_write_target=Path("docs/ARCHITECTURE.md"),
            required_by_profile=_ALL_PROFILES,
        ),
        "design_guide": DocumentRoleMapping(
            role="design_guide",
            allowed_path_aliases=("docs/DESIGN_GUIDE.md",),
            preferred_read_order=("docs/DESIGN_GUIDE.md",),
            preferred_write_target=Path("docs/DESIGN_GUIDE.md"),
            required_by_profile=_ALL_PROFILES,
        ),
        "security": DocumentRoleMapping(
            role="security",
            allowed_path_aliases=("docs/SECURITY.md",),
            preferred_read_order=("docs/SECURITY.md",),
            preferred_write_target=Path("docs/SECURITY.md"),
            required_by_profile=_ALL_PROFILES,
        ),
        "core_beliefs": DocumentRoleMapping(
            role="core_beliefs",
            allowed_path_aliases=("docs/design-docs/core-beliefs.md",),
            preferred_read_order=("docs/design-docs/core-beliefs.md",),
            preferred_write_target=Path("docs/design-docs/core-beliefs.md"),
            required_by_profile=_ALL_PROFILES,
        ),
        "data_model": DocumentRoleMapping(
            role="data_model",
            allowed_path_aliases=("docs/design-docs/data-model.md",),
            preferred_read_order=("docs/design-docs/data-model.md",),
            preferred_write_target=Path("docs/design-docs/data-model.md"),
            required_by_profile=_ALL_PROFILES,
        ),
    }


def discover_planning_inputs(project_dir: Path) -> PlanningInputs:
    visible_entries = [path for path in project_dir.rglob("*") if _is_visible(path)]
    empty_project = not visible_entries
    has_existing_code = _detect_existing_code(project_dir)
    canonical_spec_paths = _discover_canonical_spec_paths(project_dir)
    uploaded_spec_path = _discover_uploaded_spec(project_dir, canonical_spec_paths)
    source_material_only = (
        uploaded_spec_path is not None
        and not canonical_spec_paths
        and not has_existing_code
    )

    return PlanningInputs(
        project_mode=ProjectMode.BROWNFIELD if has_existing_code else ProjectMode.GREENFIELD,
        canonical_spec_paths=canonical_spec_paths,
        uploaded_spec_path=uploaded_spec_path,
        empty_project=empty_project,
        has_existing_code=has_existing_code,
        source_material_only=source_material_only,
    )


def resolve_planning_project_mode(
    project_dir: Path,
    explicit_override: ProjectMode | None = None,
) -> ProjectMode:
    if explicit_override is not None:
        return explicit_override
    return discover_planning_inputs(project_dir).project_mode


def _extract_profile_override(agents_text: str) -> str | None:
    for profile in _ALL_PROFILES:
        if profile in agents_text:
            return profile
    return None


def _discover_canonical_spec_paths(project_dir: Path) -> tuple[Path, ...]:
    discovered: list[Path] = []
    for relative_dir in _SPEC_DIRS:
        spec_dir = project_dir / relative_dir
        if not spec_dir.exists():
            continue

        index_path = spec_dir / "index.md"
        if index_path.exists():
            discovered.append(index_path)

        for path in sorted(spec_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            if index_path.exists():
                discovered.append(path)

    return tuple(discovered)


def _discover_uploaded_spec(
    project_dir: Path,
    canonical_spec_paths: tuple[Path, ...],
) -> Path | None:
    if canonical_spec_paths:
        return None

    for relative_dir in _SPEC_DIRS:
        spec_dir = project_dir / relative_dir
        if not spec_dir.exists():
            continue

        for path in sorted(spec_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            return path

    return None


def _detect_existing_code(project_dir: Path) -> bool:
    for relative_dir in _CODE_DIRS:
        code_dir = project_dir / relative_dir
        if not code_dir.exists():
            continue
        for path in code_dir.rglob("*"):
            if path.is_file() and path.suffix in _CODE_SUFFIXES:
                return True
    return False


def _is_visible(path: Path) -> bool:
    return not any(part.startswith(".") for part in path.parts if part not in (".", ""))
