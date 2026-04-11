"""Unit tests for Phase 1 prompt templates — boundary rules and decision table contract.

These tests drive Chunk 2 of the overview-optional refactor plan
(docs/superpowers/plans/2026-04-12-overview-optional.md).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "cowork_pilot"
    / "orchestrator_templates"
)


@pytest.fixture
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )


BOUNDARY_PHRASES = [
    "shared.md",
    "2개 이상 도메인",
    "_overview.md",
    "한 도메인의 2개 이상 feature",
    "feature.md",
    "단일 feature",
]


DECISION_TABLE_REQUIRED_PHRASES = [
    "Domain Overview Decisions",
    "| domain | overview_needed | reason |",
    "overview_needed",
    "yes",
    "no",
]


def _render(env: Environment, name: str, **ctx) -> str:
    return env.get_template(name).render(**ctx)


def _render_phase1_single(env: Environment) -> str:
    return _render(
        env,
        "phase1_single.j2",
        project_slug="demo",
        project_dir="/tmp/demo",
        source_docs=["/tmp/demo/inputs/brief.md"],
    )


def _render_phase1_domain(env: Environment) -> str:
    return _render(
        env,
        "phase1_domain.j2",
        project_slug="demo",
        project_dir="/tmp/demo",
        domain="host",
        source_docs=["/tmp/demo/inputs/brief.md"],
    )


def test_phase1_single_contains_boundary_rules(env):
    out = _render_phase1_single(env)
    for phrase in BOUNDARY_PHRASES:
        assert phrase in out, f"phase1_single.j2 missing boundary phrase: {phrase!r}"


def test_phase1_domain_contains_boundary_rules(env):
    out = _render_phase1_domain(env)
    for phrase in BOUNDARY_PHRASES:
        assert phrase in out, f"phase1_domain.j2 missing boundary phrase: {phrase!r}"


def test_phase1_single_requires_decision_table(env):
    out = _render_phase1_single(env)
    for phrase in DECISION_TABLE_REQUIRED_PHRASES:
        assert phrase in out, f"phase1_single.j2 missing decision-table phrase: {phrase!r}"


def test_phase1_domain_requires_decision_table(env):
    out = _render_phase1_domain(env)
    for phrase in DECISION_TABLE_REQUIRED_PHRASES:
        assert phrase in out, f"phase1_domain.j2 missing decision-table phrase: {phrase!r}"


def test_phase1_domain_output_bullets_do_not_force_overview(env):
    out = _render_phase1_domain(env)

    # Find the '출력 파일:' machine-readable block. Grab everything from that
    # line up to the next blank-line-separated section.
    import re

    m = re.search(r"출력 파일:\s*\n((?:- .*\n)+)", out)
    assert m is not None, "phase1_domain.j2 must have a '출력 파일:' bullet block"
    bullet_block = m.group(1)

    # The machine-readable block must NOT list _overview.md as a required path.
    assert "_overview.md" not in bullet_block, (
        "phase1_domain.j2 machine-readable 출력 파일 block must not force _overview.md; "
        "it must be described conditionally outside the bullet list"
    )

    # But the template must still mention _overview.md conditionally somewhere outside the block.
    prose = out.replace(bullet_block, "")
    assert "_overview.md" in prose
    assert "overview_needed" in prose


def test_phase1_single_describes_conditional_overview(env):
    out = _render_phase1_single(env)
    assert "_overview.md" in out
    assert "조건부" in out or "overview_needed" in out
