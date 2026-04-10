# tests/test_planning_completion_verifier.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import (
    verify_stage_completion,
    CompletionVerdict,
    extract_json_block,
)
from cowork_pilot.planning.models import PlanningStage


# --- extract_json_block utility ---

def test_extract_json_block_from_fenced_md():
    content = "Some prose\n```json\n{\"a\": 1}\n```\n<!-- ORCHESTRATOR:DONE -->"
    data = extract_json_block(content)
    assert data == {"a": 1}


def test_extract_json_block_returns_none_when_missing():
    assert extract_json_block("No json here\n<!-- ORCHESTRATOR:DONE -->") is None


def test_extract_json_block_returns_none_for_invalid_json():
    content = "```json\n{invalid}\n```\n<!-- ORCHESTRATOR:DONE -->"
    assert extract_json_block(content) is None


# --- done marker ---

def test_verify_fails_when_done_marker_missing(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":[],"primary_entities":[],"risks":[]}\n```\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "ORCHESTRATOR:DONE" in verdict.reason


# --- file existence ---

def test_verify_fails_when_file_missing(tmp_path: Path):
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "classification-report.md" in verdict.missing_artifacts


# --- JSON key validation ---

def test_verify_fails_when_json_key_missing(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield"}\n```\n<!-- ORCHESTRATOR:DONE -->',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "size_class" in verdict.reason


# --- happy path ---

def _write_valid_classification(tmp_path: Path) -> None:
    (tmp_path / "classification-report.md").write_text(
        '# Classification Report\n\n```json\n'
        '{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":["login"],"primary_entities":["user"],"risks":["none"]}\n'
        '```\n\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )


def test_verify_passes_valid_classification(tmp_path: Path):
    _write_valid_classification(tmp_path)
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert verdict.passed


def test_verify_passes_valid_scope_map(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["auth"],"features":["login"],'
        '"user_flows":["sign-in"],"out_of_scope":["admin"]}\n```\n'
        '<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert verdict.passed


def test_verify_passes_valid_work_sizing(tmp_path: Path):
    item = {"id":"w1","title":"login","domain":"auth","feature":"login","size":"S","risk":"low","depends_on":[]}
    (tmp_path / "work-sizing.md").write_text(
        f'```json\n{{"work_items":[{json.dumps(item)}]}}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.WORK_SIZING, run_dir=tmp_path)
    assert verdict.passed


def test_verify_stage_without_ownership_always_passes(tmp_path: Path):
    verdict = verify_stage_completion(PlanningStage.EXEC_PLAN_AUTHORING, run_dir=tmp_path)
    assert verdict.passed


# --- scope validation: doc roles forbidden ---

# --- Chunk 6: _get_required_keys deduplication ---

def test_completion_verifier_uses_stage_contracts_keys():
    """After dedup, verifier should get keys from _STAGE_CONTRACTS."""
    from cowork_pilot.planning.completion_verifier import _get_required_keys
    from cowork_pilot.planning.models import PlanningStage
    keys = _get_required_keys(PlanningStage.CLASSIFICATION)
    assert keys is not None
    assert "project_mode" in keys
    assert "size_class" in keys


def test_get_required_keys_returns_none_for_empty_json_keys():
    """Stages with empty json_keys should return None."""
    from cowork_pilot.planning.completion_verifier import _get_required_keys
    from cowork_pilot.planning.models import PlanningStage
    keys = _get_required_keys(PlanningStage.CORE_DOCS_PRESENCE_REVIEW)
    assert keys is None


def test_verify_scope_map_rejects_doc_role_as_domain(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["agents","spec_index"],"features":[],'
        '"user_flows":[],"out_of_scope":[]}\n```\n'
        '<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed
    assert "doc role" in verdict.reason.lower() or "agents" in verdict.reason
