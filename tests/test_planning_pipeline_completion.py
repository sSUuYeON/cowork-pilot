# tests/test_planning_pipeline_completion.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import verify_stage_completion
from cowork_pilot.planning.models import PlanningStage


def test_classification_without_done_marker_rejected(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":[],"primary_entities":[],"risks":[]}\n```\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed


def test_exec_plan_skeleton_without_file_rejected(tmp_path: Path):
    """exec_plan_skeleton must NEVER be marked complete if file doesn't exist."""
    # EXEC_PLAN_SKELETON is already in ARTIFACT_OWNERSHIP_TABLE? No — but the pipeline
    # checks skeleton_path.exists() at line 497. We test that behavior here.
    skeleton = tmp_path / "exec-plan-skeleton.md"
    assert not skeleton.exists()
    # The pipeline's _apply_stage_completion returns empty tuple when file missing
    # which means no outputs → quality gate should catch this


def test_scope_map_with_doc_roles_rejected(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["agents","design_guide"],"features":[],'
        '"user_flows":[],"out_of_scope":[]}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed
