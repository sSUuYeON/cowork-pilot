"""E2E: mixed project with one overview-needed and one not.

Plan: docs/superpowers/plans/2026-04-12-overview-optional.md — Chunk 5, Task 5.2.

Placeholders resolved from Chunk 0 inventory:
- <QG_MODULE> -> ``cowork_pilot.orchestrator.quality_gate``
- <PR_MODULE> -> ``cowork_pilot.orchestrator_prompts``
"""
from pathlib import Path

from cowork_pilot.orchestrator.quality_gate import evaluate_phase1
from cowork_pilot.orchestrator_prompts import compute_available_extracts


def test_mixed_project_phase1_passes(mixed_project: Path) -> None:
    result = evaluate_phase1(mixed_project)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_mixed_project_extracts_reflect_disk(mixed_project: Path) -> None:
    info = compute_available_extracts(mixed_project / "domain-extracts")
    assert info.shared is True
    assert info.overviews == {"host": True, "voter": False}
    assert sorted(info.features["host"]) == ["close-poll.md", "create-poll.md"]
    assert sorted(info.features["voter"]) == ["cast-vote.md"]


def test_mixed_project_phase2_auto_prompt_has_host_overview(mixed_project: Path) -> None:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("src/cowork_pilot/orchestrator_templates"))
    info = compute_available_extracts(mixed_project / "domain-extracts")
    out = env.get_template("phase2_auto.j2").render(
        extracts=info,
        overview_reasons={"host": "poll lifecycle shared", "voter": "self contained"},
        domain="host",
        project_slug="mixed",
        # phase2_auto.j2 also iterates `features` and references `project_dir`;
        # provide minimal stand-ins so the template renders without raising.
        project_dir=str(mixed_project),
        features=[
            {"domain": "host", "feature": "create-poll"},
            {"domain": "host", "feature": "close-poll"},
        ],
    )
    assert "host/_overview.md" in out
    assert "voter/_overview.md" not in out
