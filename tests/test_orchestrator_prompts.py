"""Tests for orchestrator_prompts — Jinja2 template rendering.

Covers:
- Each Phase template renders with required keywords (§12.4):
  project path, files to read, <!-- ORCHESTRATOR:DONE --> marker instruction.
- Phase 4-1 prompt includes section keywords.
- Empty features list renders without error.
- Unknown phase raises ValueError.
- get_section_keywords returns defaults when file missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cowork_pilot.orchestrator_prompts import (
    build_session_prompt,
    get_section_keywords,
)

# ── Helpers ──────────────────────────────────────────────────────────

PROJECT_DIR = "/tmp/test-project"

SAMPLE_FEATURES = [
    {"domain": "payment", "feature": "checkout"},
    {"domain": "payment", "feature": "refund"},
]

SAMPLE_SOURCE_DOCS = [
    "/tmp/test-project/planning/spec1.md",
    "/tmp/test-project/planning/spec2.md",
]


def _assert_common_keywords(prompt: str) -> None:
    """All prompts must contain project path and ORCHESTRATOR:DONE marker."""
    assert PROJECT_DIR in prompt, "Project path missing from rendered prompt"
    assert "<!-- ORCHESTRATOR:DONE -->" in prompt, (
        "Completion marker instruction missing from rendered prompt"
    )


# ── Phase 1 ─────────────────────────────────────────────────────────


class TestPhase1Single:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase1_single",
            project_dir=PROJECT_DIR,
            source_docs=SAMPLE_SOURCE_DOCS,
        )
        _assert_common_keywords(prompt)
        # Must mention source docs (files to read)
        for doc in SAMPLE_SOURCE_DOCS:
            assert doc in prompt

    def test_includes_output_files(self) -> None:
        prompt = build_session_prompt(
            "phase1_single",
            project_dir=PROJECT_DIR,
            source_docs=SAMPLE_SOURCE_DOCS,
        )
        assert "analysis-report.md" in prompt
        assert "domain-extracts" in prompt


class TestPhase1Domain:
    def test_renders_with_domain(self) -> None:
        prompt = build_session_prompt(
            "phase1_domain",
            project_dir=PROJECT_DIR,
            domain="payment",
            source_docs=SAMPLE_SOURCE_DOCS,
        )
        _assert_common_keywords(prompt)
        assert "payment" in prompt

    def test_includes_analysis_report(self) -> None:
        prompt = build_session_prompt(
            "phase1_domain",
            project_dir=PROJECT_DIR,
            domain="auth",
            source_docs=SAMPLE_SOURCE_DOCS,
        )
        assert "analysis-report.md" in prompt


# ── Phase 2 ─────────────────────────────────────────────────────────


class TestPhase2Auto:
    def test_renders_with_features(self) -> None:
        prompt = build_session_prompt(
            "phase2_auto",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
        )
        _assert_common_keywords(prompt)
        assert "payment/checkout" in prompt
        assert "payment/refund" in prompt
        assert "auto" in prompt.lower()

    def test_includes_files_to_read(self) -> None:
        prompt = build_session_prompt(
            "phase2_auto",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
        )
        assert "checklists.md" in prompt
        assert "analysis-report.md" in prompt
        assert "shared.md" in prompt

    def test_includes_ai_decision_instruction(self) -> None:
        prompt = build_session_prompt(
            "phase2_auto",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
        )
        assert "[AI_DECISION]" in prompt

    def test_empty_features_no_error(self) -> None:
        prompt = build_session_prompt(
            "phase2_auto",
            project_dir=PROJECT_DIR,
            features=[],
        )
        _assert_common_keywords(prompt)


class TestPhase2Manual:
    def test_renders_with_features(self) -> None:
        prompt = build_session_prompt(
            "phase2_manual",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
        )
        _assert_common_keywords(prompt)
        assert "manual" in prompt.lower()
        assert "AskUserQuestion" in prompt

    def test_empty_features_no_error(self) -> None:
        prompt = build_session_prompt(
            "phase2_manual",
            project_dir=PROJECT_DIR,
            features=[],
        )
        _assert_common_keywords(prompt)


# ── Phase 3 ─────────────────────────────────────────────────────────


class TestPhase3DesignDocs:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase3_design_docs",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
            project_conventions=None,
        )
        _assert_common_keywords(prompt)
        assert "output-formats.md" in prompt
        assert "RE-READ" in prompt
        assert "VALIDATE" in prompt


class TestPhase3ProductSpec:
    def test_renders_with_features(self) -> None:
        prompt = build_session_prompt(
            "phase3_product_spec",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
            project_conventions=None,
        )
        _assert_common_keywords(prompt)
        assert "checkout" in prompt
        assert "refund" in prompt
        assert "RE-READ" in prompt

    def test_empty_features_no_error(self) -> None:
        prompt = build_session_prompt(
            "phase3_product_spec",
            project_dir=PROJECT_DIR,
            features=[],
            project_conventions=None,
        )
        _assert_common_keywords(prompt)

    def test_with_project_conventions(self) -> None:
        prompt = build_session_prompt(
            "phase3_product_spec",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
            project_conventions="/tmp/test-project/project-conventions.md",
        )
        assert "project-conventions.md" in prompt


class TestPhase3Architecture:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase3_architecture",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
            project_conventions=None,
        )
        _assert_common_keywords(prompt)
        assert "ARCHITECTURE.md" in prompt
        assert "DESIGN_GUIDE.md" in prompt
        assert "SECURITY.md" in prompt


class TestPhase3Agents:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase3_agents",
            project_dir=PROJECT_DIR,
            project_conventions=None,
        )
        _assert_common_keywords(prompt)
        assert "AGENTS.md" in prompt
        assert "Directory Map" in prompt


# ── Phase 4 ─────────────────────────────────────────────────────────


class TestPhase4Consistency:
    def test_renders_with_section_keywords(self) -> None:
        keywords = ["데이터", "API", "Schema", "엔티티"]
        prompt = build_session_prompt(
            "phase4_consistency",
            project_dir=PROJECT_DIR,
            section_keywords=keywords,
        )
        _assert_common_keywords(prompt)
        # Phase 4-1 must have section keywords injected
        for kw in keywords:
            assert kw in prompt, f"Section keyword {kw!r} missing from prompt"
        assert "phase4-consistency.md" in prompt

    def test_empty_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase4_consistency",
            project_dir=PROJECT_DIR,
            section_keywords=[],
        )
        _assert_common_keywords(prompt)


class TestPhase4Rescore:
    def test_renders_with_features(self) -> None:
        prompt = build_session_prompt(
            "phase4_rescore",
            project_dir=PROJECT_DIR,
            features=SAMPLE_FEATURES,
        )
        _assert_common_keywords(prompt)
        assert "checklists.md" in prompt
        assert "phase4-rescore.md" in prompt

    def test_empty_features_no_error(self) -> None:
        prompt = build_session_prompt(
            "phase4_rescore",
            project_dir=PROJECT_DIR,
            features=[],
        )
        _assert_common_keywords(prompt)


class TestPhase4Quality:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase4_quality",
            project_dir=PROJECT_DIR,
        )
        _assert_common_keywords(prompt)
        assert "QUALITY_SCORE.md" in prompt
        assert "quality-criteria.md" in prompt
        assert "grep" in prompt


# ── Phase 5 ─────────────────────────────────────────────────────────


class TestPhase5Outline:
    def test_renders_with_required_keywords(self) -> None:
        prompt = build_session_prompt(
            "phase5_outline",
            project_dir=PROJECT_DIR,
        )
        _assert_common_keywords(prompt)
        assert "exec-plan-outline.md" in prompt
        assert "output-formats.md" in prompt

    def test_includes_output_format(self) -> None:
        prompt = build_session_prompt(
            "phase5_outline",
            project_dir=PROJECT_DIR,
        )
        assert "Completion Criteria" in prompt
        assert "Session Prompt" in prompt


class TestPhase5Detail:
    def test_renders_with_plan_info(self) -> None:
        prompt = build_session_prompt(
            "phase5_detail",
            project_dir=PROJECT_DIR,
            plan_number="02",
            plan_name="data-layer",
            relevant_specs=[
                "/tmp/test-project/docs/product-specs/payment--checkout.md",
            ],
        )
        _assert_common_keywords(prompt)
        assert "02-data-layer.md" in prompt
        assert "exec-plan-outline.md" in prompt
        assert "RE-READ" in prompt

    def test_empty_relevant_specs(self) -> None:
        prompt = build_session_prompt(
            "phase5_detail",
            project_dir=PROJECT_DIR,
            plan_number="01",
            plan_name="setup",
            relevant_specs=[],
        )
        _assert_common_keywords(prompt)


# ── Error handling ──────────────────────────────────────────────────


class TestUnknownPhase:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown phase"):
            build_session_prompt("nonexistent_phase", project_dir=PROJECT_DIR)


# ── get_section_keywords ────────────────────────────────────────────


class TestGetSectionKeywords:
    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        keywords = get_section_keywords(
            tmp_path / "nonexistent.md", "webapp"
        )
        assert "데이터" in keywords
        assert "API" in keywords
        assert "Schema" in keywords

    def test_extracts_from_output_formats(self, tmp_path: Path) -> None:
        output_formats = tmp_path / "output-formats.md"
        output_formats.write_text(
            "# output-formats\n\n"
            "## 데이터 모델\n\n내용\n\n"
            "## API 엔드포인트\n\n내용\n\n"
            "## 사용자 인터페이스\n\n내용\n\n"
            "## Security Policy\n\n내용\n",
            encoding="utf-8",
        )
        keywords = get_section_keywords(output_formats, "webapp")
        assert "데이터" in keywords
        assert "API" in keywords
        assert "모델" in keywords
        assert "엔드포인트" in keywords
        assert "Security" in keywords
        assert "Policy" in keywords

    def test_deduplicates(self, tmp_path: Path) -> None:
        output_formats = tmp_path / "output-formats.md"
        output_formats.write_text(
            "## API 설계\n\n## API 구현\n", encoding="utf-8"
        )
        keywords = get_section_keywords(output_formats, "webapp")
        assert keywords.count("API") == 1
