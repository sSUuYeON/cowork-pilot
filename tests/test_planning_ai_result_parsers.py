# tests/test_planning_ai_result_parsers.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.docs_inventory import parse_core_docs_check, parse_adaptive_docs_selection
from cowork_pilot.planning.scope import parse_scope_map
from cowork_pilot.planning.sizing import parse_work_sizing
from cowork_pilot.planning.packing import parse_plan_packing
from cowork_pilot.planning.review import parse_plan_review, ReviewVerdict


def _md(json_data: dict) -> str:
    return f'```json\n{json.dumps(json_data)}\n```\n<!-- ORCHESTRATOR:DONE -->\n'


def test_parse_core_docs_check(tmp_path: Path):
    data = {
        "required_doc_roles": ["agents", "spec_index"],
        "resolved_existing_paths": ["docs/AGENTS.md"],
        "missing_roles": ["design_guide"],
        "substitutions": [{"role": "design_guide", "alternative": "README.md"}],
    }
    (tmp_path / "core-docs-check.md").write_text(_md(data), encoding="utf-8")
    result = parse_core_docs_check(tmp_path / "core-docs-check.md")
    assert result["required_doc_roles"] == ["agents", "spec_index"]
    assert result["missing_roles"] == ["design_guide"]


def test_parse_adaptive_docs_selection(tmp_path: Path):
    data = {
        "selected_paths": ["docs/architecture.md"],
        "selected_roles": ["architecture"],
        "selection_reasons": ["needed for medium project"],
        "rejected_candidates": [{"role": "security", "reason": "not applicable"}],
    }
    (tmp_path / "adaptive-docs-selection.md").write_text(_md(data), encoding="utf-8")
    result = parse_adaptive_docs_selection(tmp_path / "adaptive-docs-selection.md")
    assert "architecture" in result["selected_roles"]


def test_parse_scope_map(tmp_path: Path):
    data = {
        "domains": ["auth", "payments"],
        "features": [
            {"domain": "auth", "name": "email-login"},
            {"domain": "auth", "name": "oauth"},
            {"domain": "payments", "name": "checkout"},
        ],
        "user_flows": ["sign-up-and-pay"],
        "out_of_scope": ["admin-panel"],
    }
    (tmp_path / "scope-map.md").write_text(_md(data), encoding="utf-8")
    result = parse_scope_map(tmp_path / "scope-map.md")
    assert "auth" in result
    assert len(result["auth"]) >= 2


def test_parse_work_sizing(tmp_path: Path):
    data = {
        "work_items": [
            {"id": "w1", "title": "email-login", "domain": "auth",
             "feature": "email-login", "size": "M", "risk": "low", "depends_on": []},
            {"id": "w2", "title": "oauth", "domain": "auth",
             "feature": "oauth", "size": "L", "risk": "medium", "depends_on": ["w1"]},
        ]
    }
    (tmp_path / "work-sizing.md").write_text(_md(data), encoding="utf-8")
    result = parse_work_sizing(tmp_path / "work-sizing.md")
    assert len(result) == 2
    assert result[0]["id"] == "w1"


def test_parse_plan_packing(tmp_path: Path):
    data = {
        "plans": [
            {"plan_name": "auth-foundation", "goal": "basic auth",
             "included_work_item_ids": ["w1"], "why_grouped": "prerequisite",
             "dependencies": []},
            {"plan_name": "auth-advanced", "goal": "oauth",
             "included_work_item_ids": ["w2"], "why_grouped": "depends on w1",
             "dependencies": ["auth-foundation"]},
        ]
    }
    (tmp_path / "plan-packing.md").write_text(_md(data), encoding="utf-8")
    result = parse_plan_packing(tmp_path / "plan-packing.md")
    assert len(result) == 2
    assert result[0]["plan_name"] == "auth-foundation"


def test_parse_plan_review(tmp_path: Path):
    data = {
        "issues": [],
        "rollback_recommended": False,
        "coverage_status": "full",
        "execution_risks": [],
        "missing_work_items": [],
    }
    (tmp_path / "plan-review.md").write_text(_md(data), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert isinstance(verdict, ReviewVerdict)
    assert verdict.coverage_pass is True
    assert len(verdict.issues) == 0


def test_parse_plan_review_with_issues(tmp_path: Path):
    data = {
        "issues": [{"category": "coverage", "severity": "blocking", "description": "missing payments"}],
        "rollback_recommended": True,
        "coverage_status": "incomplete",
        "execution_risks": ["tight timeline"],
        "missing_work_items": ["payment-flow"],
    }
    (tmp_path / "plan-review.md").write_text(_md(data), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert verdict.coverage_pass is False
    assert len(verdict.issues) == 1
    assert verdict.issues[0].severity == "blocking"
