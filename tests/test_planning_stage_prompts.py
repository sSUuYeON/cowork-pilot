# tests/test_planning_stage_prompts.py
import pytest
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.prompts import render_stage_prompt
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE


_CONVERTED_STAGES = [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
]


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_declares_output_file_from_artifact_table(stage: PlanningStage):
    """Output filename in prompt must match ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    expected_file = ARTIFACT_OWNERSHIP_TABLE[stage].completion_artifacts[0]
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert expected_file in prompt, (
        f"Prompt for {stage.value} must declare output file '{expected_file}'"
    )


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_purpose(stage: PlanningStage):
    from cowork_pilot.planning.prompts import _STAGE_CONTRACTS
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    contract = _STAGE_CONTRACTS[stage]
    assert contract.purpose[:30] in prompt or "다음을 수행하라" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_forbidden(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "품질 규칙" in prompt or "금지" in prompt.lower()


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_json_schema(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "JSON" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_done_marker_instruction(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "ORCHESTRATOR:DONE" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_marker_instructions(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "COWORK_PILOT_EVENT" in prompt


def test_jinja_env_loads_templates_directory():
    from cowork_pilot.planning.prompts import _get_jinja_env
    env = _get_jinja_env()
    # Should be able to list templates
    templates = env.loader.list_templates()
    assert len(templates) > 0, "No templates found in planning_templates/"


def test_classification_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.CLASSIFICATION])
    result = template.render(
        stage="classification",
        target_version="v1",
        read_set=("file1.md", "file2.md"),
        handoff_summary="",
        restored_context="",
        output_file="classification-report.md",
        json_keys=("project_mode", "product_type", "size_class"),
        forbidden=("Do NOT produce a plan.",),
        input_files=(),
        purpose="Analyze project inputs.",
        substage="",
    )
    assert "classification-report.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "file1.md" in result
    assert "다음을 수행하라" in result


def test_core_docs_check_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.CORE_DOCS_CHECK])
    result = template.render(
        stage="core_docs_check",
        target_version="v1",
        read_set=("input.md",),
        handoff_summary="",
        restored_context="",
        output_file="core-docs-check.md",
        json_keys=("required_doc_roles", "resolved_existing_paths"),
        forbidden=("Do NOT invent document content.",),
        input_files=("classification-report.md",),
        purpose="Check docs.",
        substage="",
    )
    assert "core-docs-check.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "다음을 수행하라" in result


def test_adaptive_docs_selection_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.ADAPTIVE_DOCS_SELECTION])
    result = template.render(
        stage="adaptive_docs_selection",
        target_version="v1",
        read_set=("input.md",),
        handoff_summary="",
        restored_context="",
        output_file="adaptive-docs-selection.md",
        json_keys=("selected_paths", "selected_roles"),
        forbidden=(),
        input_files=(),
        purpose="Select docs.",
        substage="",
    )
    assert "adaptive-docs-selection.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_core_docs_presence_review_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.CORE_DOCS_PRESENCE_REVIEW])
    result = template.render(
        stage="core_docs_presence_review",
        target_version="v1",
        read_set=("input.md",),
        handoff_summary="",
        restored_context="",
        output_file="core-docs-presence-review.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="Verify docs.",
        substage="",
    )
    assert "core-docs-presence-review.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_scope_prompt_forbids_doc_role_names():
    prompt = render_stage_prompt(
        PlanningStage.SCOPE_STRUCTURING,
        read_set=(Path("dummy.md"),),
        target_version="v1",
    )
    assert "agents" in prompt.lower() or "doc role" in prompt.lower(), (
        "scope prompt must explicitly forbid doc role names as domains"
    )


# --- Chunk 2 template render tests ---


def test_product_completeness_review_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.PRODUCT_COMPLETENESS_REVIEW])
    result = template.render(
        stage="product_completeness_review",
        target_version="v1",
        read_set=("input.md",),
        handoff_summary="",
        restored_context="",
        output_file="product-completeness-review.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="Review completeness.",
        substage="",
    )
    assert "product-completeness-review.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "다음을 수행하라" in result


def test_scope_structuring_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.SCOPE_STRUCTURING])
    result = template.render(
        stage="scope_structuring",
        target_version="v1",
        read_set=("input.md",),
        handoff_summary="",
        restored_context="",
        output_file="scope-map.md",
        json_keys=("domains",),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "scope-map.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_scope_structuring_template_contains_forbidden_doc_roles():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.SCOPE_STRUCTURING])
    result = template.render(
        stage="scope_structuring", target_version="v1",
        read_set=(), handoff_summary="", restored_context="",
        output_file="scope-map.md", json_keys=("domains",),
        forbidden=(), input_files=(), purpose="", substage="",
    )
    assert "agents" in result.lower()
    assert "spec_index" in result.lower()


def test_work_sizing_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.WORK_SIZING])
    result = template.render(
        stage="work_sizing",
        target_version="v1",
        read_set=("scope-map.md",),
        handoff_summary="",
        restored_context="",
        output_file="work-sizing.md",
        json_keys=("work_items",),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "work-sizing.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_plan_packing_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.PLAN_PACKING])
    result = template.render(
        stage="plan_packing",
        target_version="v1",
        read_set=("work-sizing.md",),
        handoff_summary="",
        restored_context="",
        output_file="plan-packing.md",
        json_keys=("plans",),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "plan-packing.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_plan_review_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.PLAN_REVIEW])
    result = template.render(
        stage="plan_review",
        target_version="v1",
        read_set=("plan-packing.md",),
        handoff_summary="",
        restored_context="",
        output_file="plan-review.md",
        json_keys=("issues", "rollback_recommended"),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "plan-review.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


# --- Chunk 3 template render tests ---


def test_exec_plan_skeleton_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_SKELETON])
    result = template.render(
        stage="exec_plan_skeleton",
        target_version="v1",
        read_set=("scope-map.md",),
        handoff_summary="",
        restored_context="",
        output_file="exec-plan-skeleton.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "exec-plan-skeleton.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_exec_plan_feature_outline_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_FEATURE_OUTLINE])
    result = template.render(
        stage="exec_plan_feature_outline",
        target_version="v1",
        read_set=(),
        handoff_summary="",
        restored_context="",
        output_file="feature-outlines/authentication.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="authentication",
    )
    assert "authentication" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_exec_plan_feature_outline_template_uses_substage():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_FEATURE_OUTLINE])
    result = template.render(
        stage="exec_plan_feature_outline", target_version="v1",
        read_set=(), handoff_summary="", restored_context="",
        output_file="feature-outlines/authentication.md",
        json_keys=(), forbidden=(), input_files=(),
        purpose="", substage="authentication",
    )
    assert "authentication" in result


def test_exec_plan_detail_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_DETAIL])
    result = template.render(
        stage="exec_plan_detail",
        target_version="v1",
        read_set=(),
        handoff_summary="",
        restored_context="",
        output_file="detail-authentication.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="authentication",
    )
    assert "authentication" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


def test_exec_plan_authoring_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_AUTHORING])
    result = template.render(
        stage="exec_plan_authoring",
        target_version="v1",
        read_set=("exec-plan-skeleton.md",),
        handoff_summary="",
        restored_context="",
        output_file="exec-plan.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "exec-plan.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "다음을 수행하라" in result


# --- Chunk 4 brownfield template render tests ---


def test_brownfield_code_observation_extraction_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION])
    result = template.render(
        stage="brownfield_code_observation_extraction",
        target_version="v1",
        read_set=("src/main.py",),
        handoff_summary="",
        restored_context="",
        output_file="code-observations/slice-1.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="slice-1",
    )
    assert "code-observations/slice-1.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "다음을 수행하라" in result
    assert "slice-1" in result
    assert "객관적으로 관찰만 하라" in result


def test_brownfield_observation_synthesis_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS])
    result = template.render(
        stage="brownfield_observation_synthesis",
        target_version="v1",
        read_set=("code-observations/slice-1.md",),
        handoff_summary="",
        restored_context="",
        output_file="implementation-observation-summary.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "implementation-observation-summary.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "다음을 수행하라" in result
    assert "종합" in result


def test_brownfield_gap_synthesis_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.BROWNFIELD_GAP_SYNTHESIS])
    result = template.render(
        stage="brownfield_gap_synthesis",
        target_version="v1",
        read_set=("implementation-observation-summary.md", "normalized-request.md"),
        handoff_summary="",
        restored_context="",
        output_file="spec-implementation-gap.md",
        json_keys=(),
        forbidden=(),
        input_files=(),
        purpose="",
        substage="",
    )
    assert "spec-implementation-gap.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "다음을 수행하라" in result
    assert "갭" in result


# --- Chunk 5 tests ---


def test_all_stages_have_contracts():
    from cowork_pilot.planning.prompts import _STAGE_CONTRACTS
    for stage in PlanningStage:
        assert stage in _STAGE_CONTRACTS, f"{stage.value} missing from _STAGE_CONTRACTS"


def test_render_stage_prompt_produces_procedure_instructions():
    prompt = render_stage_prompt(
        PlanningStage.CLASSIFICATION,
        read_set=(Path("dummy.md"),),
        target_version="v1",
    )
    assert "다음을 수행하라" in prompt
    assert "품질 규칙" in prompt


# --- Chunk 7: Parametrized coverage test ---


@pytest.mark.parametrize("stage", list(PlanningStage))
def test_all_stage_templates_render_without_error(stage: PlanningStage):
    """Every PlanningStage must have a working Jinja2 template."""
    prompt = render_stage_prompt(
        stage,
        read_set=(Path("test-input.md"),),
        target_version="v1",
        substage="test-feature" if "outline" in stage.value or "detail" in stage.value else "",
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50, f"Prompt for {stage.value} is suspiciously short"
    assert "ORCHESTRATOR:DONE" in prompt
    assert "COWORK_PILOT_EVENT" in prompt


@pytest.mark.parametrize("stage", list(PlanningStage))
def test_all_stage_prompts_require_tty_for_interactive_command_sessions(stage: PlanningStage):
    prompt = render_stage_prompt(
        stage,
        read_set=(Path("test-input.md"),),
        target_version="v1",
        substage="test-feature" if "outline" in stage.value or "detail" in stage.value else "",
    )
    assert "tty=true" in prompt
    assert "write_stdin" in prompt
