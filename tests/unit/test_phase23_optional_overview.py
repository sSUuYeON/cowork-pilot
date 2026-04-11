"""Template tests for Chunk 4 · Tasks 4.2 / 4.3.

These render the raw Jinja templates with a fake ``extracts`` object and
assert that:

* ``_overview.md`` paths only appear for domains whose overview file is
  actually present (Task 4.2);
* decision-table reasons from ``analysis-report.md`` are surfaced as
  optional context when ``overview_reasons`` is provided (Task 4.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "cowork_pilot" / "orchestrator_templates"

TEMPLATES = ["phase2_auto.j2", "phase2_manual.j2", "phase3_architecture.j2"]


@dataclass
class FakeExtracts:
    shared: bool = True
    overviews: dict[str, bool] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)


@pytest.fixture
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )


def _features_for(extracts: FakeExtracts) -> list[dict[str, str]]:
    """Build a legacy ``features`` list for templates that still iterate it."""
    rows: list[dict[str, str]] = []
    for domain, files in extracts.features.items():
        for fname in files:
            rows.append({"domain": domain, "feature": Path(fname).stem})
    return rows


@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_absent_removes_path(env: Environment, name: str) -> None:
    extracts = FakeExtracts(
        overviews={"host": False, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    out = env.get_template(name).render(
        extracts=extracts,
        features=_features_for(extracts),
        domain="host",
        project_slug="demo",
        project_dir="/tmp/demo",
    )
    assert "_overview.md" not in out


@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_present_includes_path(env: Environment, name: str) -> None:
    extracts = FakeExtracts(
        overviews={"host": True, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    out = env.get_template(name).render(
        extracts=extracts,
        features=_features_for(extracts),
        domain="host",
        project_slug="demo",
        project_dir="/tmp/demo",
    )
    assert "host/_overview.md" in out
    # voter has overview_needed=False → must not be listed.
    assert "voter/_overview.md" not in out


@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_decision_reasons_are_passed_through(
    env: Environment, name: str
) -> None:
    extracts = FakeExtracts(
        overviews={"host": True, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    overview_reasons = {
        "host": "poll lifecycle shared",
        "voter": "self contained",
    }
    out = env.get_template(name).render(
        extracts=extracts,
        features=_features_for(extracts),
        overview_reasons=overview_reasons,
        domain="host",
        project_slug="demo",
        project_dir="/tmp/demo",
    )
    assert "poll lifecycle shared" in out
    assert "self contained" in out
