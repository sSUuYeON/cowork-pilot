"""Phase 1.5 extraction quality gate (legacy — coverage owner only).

Validates Phase 1 outputs (domain-extracts) against source planning documents
**without any AI session** — pure Python file-based checks.

This module is the **coverage owner** after the single-gate refactor
(plan 2026-04-12-overview-optional.md, Chunk 3). The presence / shape of
shared.md, per-feature files, and `_overview.md` artefacts is owned
exclusively by :mod:`cowork_pilot.orchestrator.quality_gate`. Only the
following legacy responsibilities remain here:

* Validation 1 — coverage ratio (``extract_total / source_total``).
* Validation 2 — SOURCE-tag section coverage (advisory, warnings only).

``GateResult.missing_features`` is retained as an empty list for backward
compatibility with existing call-sites and tests, but is no longer
populated by this gate.

Design reference: §5.1.1 (Phase 1.5 추출 품질 게이트), §12.1 (모듈 분할).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cowork_pilot.config import DocsOrchestratorConfig

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """Result of the Phase 1.5 quality gate (legacy coverage-only)."""

    passed: bool
    coverage_ratio: float  # 검증 1: extracts / source line ratio
    uncovered_sections: list[str]  # 검증 2: source sections missing from SOURCE tags
    missing_features: list[str] = field(default_factory=list)  # legacy, always []
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RE_SECTION_HEADER = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_RE_SOURCE_TAG = re.compile(
    r"<!--\s*SOURCE:\s*(?P<file>[^#]+)#(?P<section>[^>]+?)\s*-->",
)


def _count_lines(path: Path) -> int:
    """Return the number of lines in *path*.  Returns 0 if file does not exist."""
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _extract_sections(source_file: Path) -> list[str]:
    """Extract ``## `` header titles from *source_file*."""
    if not source_file.exists():
        return []
    text = source_file.read_text(encoding="utf-8")
    return [m.group(1).strip() for m in _RE_SECTION_HEADER.finditer(text)]


def _extract_source_tags(extracts_dir: Path) -> set[str]:
    """Collect all ``<!-- SOURCE: file#section -->`` references from *extracts_dir*.

    Returns a set of *section* names (normalised to stripped strings).
    """
    tags: set[str] = set()
    if not extracts_dir.is_dir():
        return tags
    for md_file in sorted(extracts_dir.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for m in _RE_SOURCE_TAG.finditer(text):
            tags.add(m.group("section").strip())
    return tags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_phase1_quality(
    project_dir: Path,
    config: DocsOrchestratorConfig,
) -> GateResult:
    """Phase 1 coverage check (legacy).  Runs without AI — pure Python checks.

    Validates two aspects of the Phase 1 extraction output:

    1. **Coverage ratio** — total extract lines / total source lines >= threshold.
    2. **SOURCE tag coverage** — every ``## `` section in the sources maps to at
       least one ``<!-- SOURCE: … -->`` tag in the extracts (advisory only).

    Presence of shared.md, per-feature files, and ``_overview.md`` artefacts
    is **no longer** validated here — that responsibility now lives in
    :func:`cowork_pilot.orchestrator.quality_gate.evaluate_phase1` (single-gate
    refactor, plan 2026-04-12-overview-optional.md, Chunk 3).
    """
    generated_dir = project_dir / "docs" / "generated"
    source_dir = project_dir / "sources"
    extracts_dir = generated_dir / "domain-extracts"

    warnings: list[str] = []

    # --- Validation 1: coverage ratio -----------------------------------
    source_total = 0
    source_files: list[Path] = []
    if source_dir.is_dir():
        source_files = sorted(source_dir.glob("*.md"))
    # Fallback: find planning docs in project root (same as Phase 0)
    if not source_files:
        for pattern in ["기획서*.md", "planning*.md", "spec*.md", "요구사항*.md"]:
            source_files.extend(sorted(project_dir.glob(pattern)))
    for sf in source_files:
        source_total += _count_lines(sf)

    extract_total = 0
    if extracts_dir.is_dir():
        for ef in sorted(extracts_dir.rglob("*.md")):
            extract_total += _count_lines(ef)

    if source_total == 0:
        coverage_ratio = 0.0
        warnings.append("No source files found — coverage ratio is 0.")
    else:
        coverage_ratio = extract_total / source_total

    coverage_passed = coverage_ratio >= config.coverage_ratio_threshold

    # --- Validation 2: SOURCE tag coverage ------------------------------
    all_sections: list[str] = []
    for sf in source_files:
        all_sections.extend(_extract_sections(sf))

    source_tags = _extract_source_tags(extracts_dir)

    uncovered_sections: list[str] = []
    for section in all_sections:
        # Normalize: strip leading numbering like "1. ", "2.1 ", etc.
        normalized_section = re.sub(r"^\d+(\.\d+)*\.?\s*", "", section).strip()
        matched = False
        if section in source_tags or normalized_section in source_tags:
            matched = True
        else:
            # Fuzzy: check if any source tag contains the normalized section or vice versa
            for tag in source_tags:
                normalized_tag = re.sub(r"^\d+(\.\d+)*\.?\s*", "", tag).strip()
                if (normalized_section and normalized_tag and
                    (normalized_section in normalized_tag or normalized_tag in normalized_section)):
                    matched = True
                    break
        if not matched:
            uncovered_sections.append(section)

    # --- Final verdict --------------------------------------------------
    # SOURCE tag coverage (검증 2) is advisory only — AI output format
    # varies too much for reliable exact matching.  It is recorded as
    # warnings but does NOT block the gate.
    #
    # Validation 3 (shared / per-feature / overview presence) has moved to
    # :mod:`cowork_pilot.orchestrator.quality_gate`. This legacy gate only
    # owns coverage. ``missing_features`` is always ``[]`` from now on.
    if uncovered_sections:
        warnings.append(
            f"SOURCE 태그 미커버 섹션 {len(uncovered_sections)}개 (warning only): "
            + ", ".join(uncovered_sections[:5])
            + ("..." if len(uncovered_sections) > 5 else "")
        )
    passed = coverage_passed

    return GateResult(
        passed=passed,
        coverage_ratio=coverage_ratio,
        uncovered_sections=uncovered_sections,
        missing_features=[],
        warnings=warnings,
    )
