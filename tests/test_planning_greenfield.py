from pathlib import Path

from cowork_pilot.planning.greenfield import (
    bootstrap_empty_project_inputs,
    normalize_uploaded_spec,
)
from cowork_pilot.planning.models import ProjectConventionProfile, ProjectMode
from cowork_pilot.planning.prompts import (
    render_brownfield_stage_prompt,
    render_greenfield_entry_prompt,
)
from cowork_pilot.planning.spec_sources import (
    detect_project_convention_profile,
    discover_planning_inputs,
    resolve_document_role_mapping,
)


def test_discover_inputs_marks_empty_project_as_greenfield(tmp_path: Path):
    result = discover_planning_inputs(tmp_path)

    assert result.project_mode is ProjectMode.GREENFIELD
    assert result.empty_project is True
    assert result.has_existing_code is False
    assert result.source_material_only is False
    assert result.canonical_spec_paths == ()
    assert result.uploaded_spec_path is None


def test_discover_inputs_treats_existing_spec_as_source_material(tmp_path: Path):
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    incoming_spec = spec_dir / "incoming.md"
    incoming_spec.write_text("# Legacy Spec", encoding="utf-8")

    result = discover_planning_inputs(tmp_path)

    assert result.project_mode is ProjectMode.GREENFIELD
    assert result.uploaded_spec_path == incoming_spec
    assert result.source_material_only is True
    assert result.canonical_spec_paths == ()


def test_discover_inputs_marks_existing_codebase_as_brownfield(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = discover_planning_inputs(tmp_path)

    assert result.project_mode is ProjectMode.BROWNFIELD
    assert result.has_existing_code is True
    assert result.empty_project is False


def test_detect_convention_profile_uses_explicit_override(tmp_path: Path):
    profile = detect_project_convention_profile(
        tmp_path,
        explicit_override="product_specs_centered",
    )

    assert profile is ProjectConventionProfile.PRODUCT_SPECS_CENTERED


def test_detect_convention_profile_follows_existing_layout(tmp_path: Path):
    (tmp_path / "docs" / "product-specs").mkdir(parents=True)

    profile = detect_project_convention_profile(tmp_path)

    assert profile is ProjectConventionProfile.PRODUCT_SPECS_CENTERED


def test_resolve_role_mapping_covers_all_8_roles():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)

    assert set(mapping.keys()) == {
        "agents",
        "spec_index",
        "spec_documents",
        "architecture",
        "design_guide",
        "security",
        "core_beliefs",
        "data_model",
    }


def test_role_mapping_includes_preferred_read_order():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)

    assert mapping["spec_index"].preferred_read_order[0] == "docs/specs/index.md"


def test_role_mapping_write_target_follows_profile():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)

    assert mapping["spec_index"].preferred_write_target == Path("docs/specs/index.md")


def test_bootstrap_empty_project_inputs_creates_seed_context(tmp_path: Path):
    seed = bootstrap_empty_project_inputs(tmp_path)

    assert "AGENTS.md" in seed.required_outputs
    assert "docs/specs" in seed.required_outputs
    assert "docs/product-specs/index.md" in seed.required_outputs
    assert seed.canonical_spec_draft_path == Path("docs/specs/index.md")
    assert "ARCHITECTURE.md" in seed.conditional_outputs


def test_normalize_uploaded_spec_preserves_original_reference(tmp_path: Path):
    source_path = tmp_path / "legacy.md"
    source_path.write_text("# Legacy", encoding="utf-8")

    normalized = normalize_uploaded_spec(source_path)

    assert normalized.source_material_path == source_path
    assert normalized.target_stage == "project_classification"
    assert normalized.planning_artifact_path.name.endswith(".normalized.md")
    assert normalized.planning_artifact_path.read_text(encoding="utf-8") == "# Legacy"


def test_render_greenfield_entry_prompt_mentions_required_outputs(tmp_path: Path):
    seed = bootstrap_empty_project_inputs(tmp_path)

    prompt = render_greenfield_entry_prompt(
        required_outputs=seed.required_outputs,
        canonical_spec_draft_path=seed.canonical_spec_draft_path,
    )

    assert "AGENTS.md" in prompt
    assert "docs/specs/index.md" in prompt


def test_render_brownfield_stage_prompt_mentions_slices():
    prompt = render_brownfield_stage_prompt(
        stage_name="brownfield_code_observation_extraction",
        slices=("auth", "dashboard"),
    )

    assert "auth" in prompt
    assert "dashboard" in prompt
