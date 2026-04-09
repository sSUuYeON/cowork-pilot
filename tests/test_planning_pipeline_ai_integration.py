# tests/test_planning_pipeline_ai_integration.py
"""Verify mock AI artifacts pass completion verification and parsers produce valid data."""
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import verify_stage_completion
from cowork_pilot.planning.models import PlanningStage


def _md(data: dict) -> str:
    return f'# Stage Output\n\n```json\n{json.dumps(data, indent=2)}\n```\n\n<!-- ORCHESTRATOR:DONE -->\n'


def _write_all_mock_outputs(run_dir: Path) -> None:
    (run_dir / "classification-report.md").write_text(_md({
        "project_mode": "greenfield", "product_type": "saas-app", "size_class": "small",
        "core_user_flows": ["sign-up", "dashboard"], "primary_entities": ["user", "workspace"],
        "risks": ["none identified"],
    }), encoding="utf-8")

    (run_dir / "core-docs-check.md").write_text(_md({
        "required_doc_roles": ["agents", "spec_index", "design_guide"],
        "resolved_existing_paths": ["docs/AGENTS.md"],
        "missing_roles": ["design_guide"],
        "substitutions": [],
    }), encoding="utf-8")

    (run_dir / "adaptive-docs-selection.md").write_text(_md({
        "selected_paths": ["docs/architecture.md"],
        "selected_roles": ["architecture"],
        "selection_reasons": ["needed for medium project"],
        "rejected_candidates": [],
    }), encoding="utf-8")

    (run_dir / "scope-map.md").write_text(_md({
        "domains": ["user-management", "workspace"],
        "features": [
            {"domain": "user-management", "name": "sign-up"},
            {"domain": "user-management", "name": "login"},
            {"domain": "workspace", "name": "create-workspace"},
        ],
        "user_flows": ["onboarding-flow"],
        "out_of_scope": ["billing"],
    }), encoding="utf-8")

    (run_dir / "work-sizing.md").write_text(_md({
        "work_items": [
            {"id": "w1", "title": "sign-up", "domain": "user-management",
             "feature": "sign-up", "size": "M", "risk": "low", "depends_on": []},
            {"id": "w2", "title": "login", "domain": "user-management",
             "feature": "login", "size": "S", "risk": "low", "depends_on": ["w1"]},
            {"id": "w3", "title": "create-workspace", "domain": "workspace",
             "feature": "create-workspace", "size": "M", "risk": "medium", "depends_on": ["w1"]},
        ],
    }), encoding="utf-8")

    (run_dir / "plan-packing.md").write_text(_md({
        "plans": [
            {"plan_name": "auth-foundation", "goal": "user auth",
             "included_work_item_ids": ["w1", "w2"], "why_grouped": "auth dependency chain",
             "dependencies": []},
            {"plan_name": "workspace-core", "goal": "workspace creation",
             "included_work_item_ids": ["w3"], "why_grouped": "separate domain",
             "dependencies": ["auth-foundation"]},
        ],
    }), encoding="utf-8")

    (run_dir / "plan-review.md").write_text(_md({
        "issues": [],
        "rollback_recommended": False,
        "coverage_status": "full",
        "execution_risks": [],
        "missing_work_items": [],
    }), encoding="utf-8")


@pytest.mark.parametrize("stage", [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
])
def test_mock_outputs_pass_completion_verification(tmp_path: Path, stage: PlanningStage):
    _write_all_mock_outputs(tmp_path)
    verdict = verify_stage_completion(stage, run_dir=tmp_path)
    assert verdict.passed, f"{stage.value}: {verdict.reason or verdict.missing_artifacts}"


def test_all_parsers_produce_valid_data(tmp_path: Path):
    _write_all_mock_outputs(tmp_path)

    from cowork_pilot.planning.classification import parse_classification_report
    from cowork_pilot.planning.docs_inventory import parse_core_docs_check, parse_adaptive_docs_selection
    from cowork_pilot.planning.scope import parse_scope_map
    from cowork_pilot.planning.sizing import parse_work_sizing
    from cowork_pilot.planning.packing import parse_plan_packing
    from cowork_pilot.planning.review import parse_plan_review

    snapshot = parse_classification_report(tmp_path / "classification-report.md")
    assert snapshot.size_class.value == "small"

    core = parse_core_docs_check(tmp_path / "core-docs-check.md")
    assert "agents" in core["required_doc_roles"]

    adaptive = parse_adaptive_docs_selection(tmp_path / "adaptive-docs-selection.md")
    assert "architecture" in adaptive["selected_roles"]

    scope = parse_scope_map(tmp_path / "scope-map.md")
    assert "user-management" in scope
    assert len(scope["user-management"]) >= 2

    work = parse_work_sizing(tmp_path / "work-sizing.md")
    assert len(work) == 3
    assert work[0]["id"] == "w1"

    plans = parse_plan_packing(tmp_path / "plan-packing.md")
    assert len(plans) == 2

    review = parse_plan_review(tmp_path / "plan-review.md")
    assert review.coverage_pass is True
    assert len(review.issues) == 0


def test_scope_map_with_doc_roles_fails_verification(tmp_path: Path):
    """The completion verifier must reject scope maps that use doc role names as domains."""
    (tmp_path / "scope-map.md").write_text(_md({
        "domains": ["agents", "spec_index"],
        "features": [],
        "user_flows": [],
        "out_of_scope": [],
    }), encoding="utf-8")
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed


def test_plan_review_rollback_deterministic(tmp_path: Path):
    """should_rollback() must work on parsed AI review output."""
    from cowork_pilot.planning.review import parse_plan_review, should_rollback

    (tmp_path / "plan-review.md").write_text(_md({
        "issues": [{"category": "coverage", "severity": "blocking", "description": "gap"}],
        "rollback_recommended": True,
        "coverage_status": "incomplete",
        "execution_risks": [],
        "missing_work_items": ["missing-feature"],
    }), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert should_rollback(verdict) is True
