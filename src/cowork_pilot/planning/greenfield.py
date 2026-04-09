from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectConventionProfile
from cowork_pilot.planning.spec_sources import resolve_document_role_mapping


@dataclass(frozen=True)
class EmptyProjectSeed:
    required_outputs: tuple[str, ...]
    always_required_outputs: tuple[str, ...]
    conditional_outputs: tuple[str, ...]
    canonical_spec_draft_path: Path


@dataclass(frozen=True)
class UploadedSpecNormalization:
    source_material_path: Path
    planning_artifact_path: Path
    canonical_draft_path: Path
    target_stage: str


def bootstrap_empty_project_inputs(
    project_dir: Path,
    *,
    profile: ProjectConventionProfile = ProjectConventionProfile.SPECS_CENTERED,
) -> EmptyProjectSeed:
    _ = project_dir
    mapping = resolve_document_role_mapping(profile)
    canonical_spec_draft_path = mapping["spec_index"].preferred_write_target
    always_required_outputs = (
        "AGENTS.md",
        str(canonical_spec_draft_path),
        "docs/DESIGN_GUIDE.md",
        "docs/product-specs/index.md",
    )
    required_outputs = (
        "AGENTS.md",
        str(canonical_spec_draft_path.parent),
        "docs/DESIGN_GUIDE.md",
        "docs/product-specs/index.md",
    )
    conditional_outputs = (
        "ARCHITECTURE.md",
        "docs/SECURITY.md",
        "docs/design-docs/core-beliefs.md",
        "docs/design-docs/data-model.md",
        "docs/product-specs/feature-spec.md",
    )
    return EmptyProjectSeed(
        required_outputs=required_outputs,
        always_required_outputs=always_required_outputs,
        conditional_outputs=conditional_outputs,
        canonical_spec_draft_path=canonical_spec_draft_path,
    )


def normalize_uploaded_spec(
    source_material_path: Path,
    *,
    profile: ProjectConventionProfile = ProjectConventionProfile.SPECS_CENTERED,
) -> UploadedSpecNormalization:
    mapping = resolve_document_role_mapping(profile)
    planning_artifact_path = (
        source_material_path.parent
        / ".planning"
        / f"{source_material_path.stem}.normalized.md"
    )
    planning_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    planning_artifact_path.write_text(
        source_material_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return UploadedSpecNormalization(
        source_material_path=source_material_path,
        planning_artifact_path=planning_artifact_path,
        canonical_draft_path=mapping["spec_index"].preferred_write_target,
        target_stage="project_classification",
    )
