"""Tests for quality_gate.py — Phase 1.5 extraction quality gate.

Design reference: §12.4 (테스트 전략) — test_quality_gate.py section.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cowork_pilot.config import DocsOrchestratorConfig
from cowork_pilot.quality_gate import (
    GateResult,
    _count_lines,
    _extract_sections,
    _extract_source_tags,
    _parse_features_from_report,
    check_phase1_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lines(n: int) -> str:
    """Return a string with exactly *n* lines."""
    return "\n".join(f"line {i}" for i in range(1, n + 1)) + "\n"


def _setup_project(
    tmp_path: Path,
    *,
    source_lines: int = 100,
    extract_lines: int = 85,
    source_sections: list[str] | None = None,
    source_tags: list[tuple[str, str]] | None = None,
    features: list[tuple[str, str]] | None = None,
    extract_files: dict[str, int] | None = None,
) -> Path:
    """Build a minimal project directory structure in *tmp_path*.

    Returns the project directory path.
    """
    project = tmp_path / "project"
    sources = project / "sources"
    generated = project / "docs" / "generated"
    extracts = generated / "domain-extracts"
    sources.mkdir(parents=True)
    extracts.mkdir(parents=True)

    # Source file(s)
    sections = source_sections or []
    source_content = ""
    for sec in sections:
        source_content += f"## {sec}\n\n"
    remaining = max(0, source_lines - source_content.count("\n"))
    source_content += _make_lines(remaining)
    (sources / "plan.md").write_text(source_content, encoding="utf-8")

    # Default extract file
    if extract_files is None:
        tag_block = ""
        if source_tags:
            for fname, sec in source_tags:
                tag_block += f"<!-- SOURCE: {fname}#{sec} -->\n"
        extract_content = tag_block + _make_lines(max(0, extract_lines - tag_block.count("\n")))
        (extracts / "default-extract.md").write_text(extract_content, encoding="utf-8")
    else:
        # Create specific extract files with given line counts
        for filename, line_count in extract_files.items():
            tag_block = ""
            if source_tags:
                for fname, sec in source_tags:
                    tag_block += f"<!-- SOURCE: {fname}#{sec} -->\n"
            ef_content = tag_block + _make_lines(max(0, line_count - tag_block.count("\n")))
            (extracts / filename).write_text(ef_content, encoding="utf-8")

    # Analysis report
    if features:
        report_lines = [
            "# Analysis Report\n",
            "## 도메인/기능 목록\n",
            "| 도메인 | 기능 |",
            "|--------|------|",
        ]
        for domain, feature in features:
            report_lines.append(f"| {domain} | {feature} |")
        (generated / "analysis-report.md").write_text(
            "\n".join(report_lines) + "\n", encoding="utf-8"
        )

    return project


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


class TestCountLines:
    """_count_lines helper."""

    def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("one\ntwo\nthree\n")
        assert _count_lines(f) == 3

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert _count_lines(tmp_path / "missing.md") == 0


class TestExtractSections:
    """_extract_sections helper."""

    def test_extracts_h2_headers(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Title\n## SectionA\ntext\n## SectionB\nmore\n### Sub\n")
        assert _extract_sections(f) == ["SectionA", "SectionB"]

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert _extract_sections(tmp_path / "nope.md") == []


class TestExtractSourceTags:
    """_extract_source_tags helper."""

    def test_parses_tags(self, tmp_path: Path) -> None:
        d = tmp_path / "extracts"
        d.mkdir()
        (d / "a.md").write_text("<!-- SOURCE: plan.md#SectionA -->\nstuff\n")
        (d / "b.md").write_text("<!-- SOURCE: plan.md#SectionB -->\nmore\n")
        tags = _extract_source_tags(d)
        assert tags == {"SectionA", "SectionB"}

    def test_empty_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "extracts"
        d.mkdir()
        assert _extract_source_tags(d) == set()

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert _extract_source_tags(tmp_path / "nope") == set()


class TestParseFeaturesFromReport:
    """_parse_features_from_report helper."""

    def test_parses_table(self, tmp_path: Path) -> None:
        report = tmp_path / "report.md"
        report.write_text(textwrap.dedent("""\
            # Report

            | 도메인 | 기능 |
            |--------|------|
            | auth | 로그인 |
            | payment | 결제 |
        """))
        assert _parse_features_from_report(report) == [
            ("auth", "로그인"),
            ("payment", "결제"),
        ]

    def test_nonexistent_report(self, tmp_path: Path) -> None:
        assert _parse_features_from_report(tmp_path / "nope.md") == []


# ---------------------------------------------------------------------------
# Integration tests — check_phase1_quality
# ---------------------------------------------------------------------------


class TestCoverageRatio:
    """검증 1: coverage ratio — extracts / source line count."""

    def test_pass_when_above_threshold(self, tmp_path: Path) -> None:
        """100줄 원본 + 85줄 extracts → ratio 0.85 ≥ 0.8 → pass."""
        project = _setup_project(tmp_path, source_lines=100, extract_lines=85)
        config = DocsOrchestratorConfig(coverage_ratio_threshold=0.8)
        result = check_phase1_quality(project, config)
        assert result.coverage_ratio >= 0.8
        # Coverage alone should pass (other checks may or may not)

    def test_fail_when_below_threshold(self, tmp_path: Path) -> None:
        """100줄 원본 + 70줄 extracts → ratio 0.70 < 0.8 → fail."""
        project = _setup_project(tmp_path, source_lines=100, extract_lines=70)
        config = DocsOrchestratorConfig(coverage_ratio_threshold=0.8)
        result = check_phase1_quality(project, config)
        assert result.coverage_ratio < 0.8
        assert result.passed is False


class TestSourceTagCoverage:
    """검증 2: SOURCE tag coverage — every source section mapped."""

    def test_uncovered_section_detected(self, tmp_path: Path) -> None:
        """원본에 ## 섹션A, ## 섹션B → extracts에 SOURCE: file#섹션A만 → uncovered: [섹션B]."""
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A", "섹션B"],
            source_tags=[("plan.md", "섹션A")],
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert "섹션B" in result.uncovered_sections
        assert "섹션A" not in result.uncovered_sections

    def test_all_sections_covered(self, tmp_path: Path) -> None:
        """All sections present in SOURCE tags → uncovered_sections empty."""
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A", "섹션B"],
            source_tags=[("plan.md", "섹션A"), ("plan.md", "섹션B")],
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert result.uncovered_sections == []


class TestMissingFeatures:
    """검증 3: empty file check — feature extract files exist with ≥ 10 lines."""

    def test_missing_feature_detected(self, tmp_path: Path) -> None:
        """analysis-report에 기능 3개 → extract 2개만 존재 → missing: [기능3]."""
        features = [
            ("auth", "로그인"),
            ("auth", "회원가입"),
            ("payment", "결제"),
        ]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A"],
            source_tags=[("plan.md", "섹션A")],
            features=features,
            extract_files={
                "auth-로그인.md": 15,
                "auth-회원가입.md": 12,
                # payment-결제.md is missing
            },
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert "payment/결제" in result.missing_features
        assert "auth/로그인" not in result.missing_features

    def test_short_file_treated_as_missing(self, tmp_path: Path) -> None:
        """Extract file exists but has < 10 lines → treated as missing."""
        features = [("auth", "로그인")]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A"],
            source_tags=[("plan.md", "섹션A")],
            features=features,
            extract_files={"auth-로그인.md": 5},
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert "auth/로그인" in result.missing_features


class TestPassedField:
    """passed 필드: 3종 검증 모두 통과해야 True."""

    def test_all_pass(self, tmp_path: Path) -> None:
        """모든 검증 통과 → passed is True."""
        features = [("auth", "로그인")]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A"],
            source_tags=[("plan.md", "섹션A")],
            features=features,
            extract_files={"auth-로그인.md": 100},
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert result.passed is True
        assert result.coverage_ratio >= 0.8
        assert result.uncovered_sections == []
        assert result.missing_features == []

    def test_coverage_fail_causes_overall_fail(self, tmp_path: Path) -> None:
        """Coverage ratio alone failing → passed is False."""
        features = [("auth", "로그인")]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=50,  # 0.50 < 0.8
            source_sections=["섹션A"],
            source_tags=[("plan.md", "섹션A")],
            features=features,
            extract_files={"auth-로그인.md": 15},
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert result.passed is False

    def test_uncovered_section_is_warning_only(self, tmp_path: Path) -> None:
        """Uncovered section alone → passed is True (warning only, not hard fail)."""
        features = [("auth", "로그인")]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A", "섹션B"],
            source_tags=[("plan.md", "섹션A")],  # 섹션B missing
            features=features,
            extract_files={"auth-로그인.md": 100},
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert result.passed is True  # 검증 2 is warning-only
        assert "섹션B" in result.uncovered_sections
        assert any("SOURCE 태그 미커버" in w for w in result.warnings)

    def test_missing_feature_causes_overall_fail(self, tmp_path: Path) -> None:
        """Missing feature alone → passed is False."""
        features = [("auth", "로그인"), ("payment", "결제")]
        project = _setup_project(
            tmp_path,
            source_lines=100,
            extract_lines=100,
            source_sections=["섹션A"],
            source_tags=[("plan.md", "섹션A")],
            features=features,
            extract_files={"auth-로그인.md": 15},
            # payment-결제.md missing
        )
        config = DocsOrchestratorConfig()
        result = check_phase1_quality(project, config)
        assert result.passed is False
        assert "payment/결제" in result.missing_features
