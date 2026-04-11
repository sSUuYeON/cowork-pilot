"""E2E: small project that produces no overview at all.

Plan: docs/superpowers/plans/2026-04-12-overview-optional.md — Chunk 5, Task 5.3.

Placeholders resolved from Chunk 0 inventory:
- <QG_MODULE> -> ``cowork_pilot.orchestrator.quality_gate``
- <PR_MODULE> -> ``cowork_pilot.orchestrator_prompts``
"""
from pathlib import Path

from cowork_pilot.orchestrator.quality_gate import evaluate_phase1
from cowork_pilot.orchestrator_prompts import compute_available_extracts


def test_small_project_passes_without_overview(small_project: Path) -> None:
    result = evaluate_phase1(small_project)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_small_project_phase3_prompt_has_no_overview_path(small_project: Path) -> None:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("src/cowork_pilot/orchestrator_templates"))
    info = compute_available_extracts(small_project / "domain-extracts")
    out = env.get_template("phase3_architecture.j2").render(
        extracts=info,
        overview_reasons={"core": "single feature domain"},
        domain="core",
        project_slug="small",
        # phase3_architecture.j2 references project_dir; provide it so the
        # template renders without raising on Undefined.
        project_dir=str(small_project),
    )
    assert "_overview.md" not in out
