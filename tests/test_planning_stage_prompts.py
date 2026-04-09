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
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "PURPOSE:" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_forbidden(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "FORBIDDEN:" in prompt


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


def test_scope_prompt_forbids_doc_role_names():
    prompt = render_stage_prompt(
        PlanningStage.SCOPE_STRUCTURING,
        read_set=(Path("dummy.md"),),
        target_version="v1",
    )
    assert "agents" in prompt.lower() or "doc role" in prompt.lower(), (
        "scope prompt must explicitly forbid doc role names as domains"
    )
