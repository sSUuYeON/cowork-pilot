"""Phase 1.5 extraction quality gate.

Validates Phase 1 outputs (domain-extracts) against source planning documents
**without any AI session** — pure Python file-based checks.

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
    """Result of the Phase 1.5 quality gate."""

    passed: bool
    coverage_ratio: float  # 검증 1: extracts / source line ratio
    uncovered_sections: list[str]  # 검증 2: source sections missing from SOURCE tags
    missing_features: list[str]  # 검증 3: features with no file or < 10 lines
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RE_SECTION_HEADER = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_RE_SOURCE_TAG = re.compile(
    r"<!--\s*SOURCE:\s*(?P<file>[^#]+)#(?P<section>[^>]+?)\s*-->",
)
_RE_FEATURE_ROW = re.compile(
    r"^\|\s*(?P<domain>[^|]+?)\s*\|\s*(?P<feature>[^|]+?)\s*\|",
    re.MULTILINE,
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


def _parse_features_from_report(report_path: Path) -> list[tuple[str, str]]:
    """Parse the feature table in *analysis-report.md*.

    Looks for a table whose header contains both '도메인' and '기능' (or
    'domain' and 'feature') columns.  Only rows from that specific table
    are parsed — other tables in the report are ignored.

    Also supports the ``domain-extracts/{domain}/{feature}.md`` file listing
    format where file paths themselves encode domain/feature.

    Returns a list of ``(domain, feature)`` tuples.
    """
    if not report_path.exists():
        return []
    text = report_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    features: list[tuple[str, str]] = []

    # --- Strategy 1: Find a table with domain/feature header columns ---
    in_feature_table = False
    domain_col = -1
    feature_col = -1

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_feature_table = False
            domain_col = -1
            feature_col = -1
            continue

        cols = [c.strip() for c in stripped.split("|")]
        # split on | gives empty first/last elements: ['', 'col1', 'col2', '']
        cols = [c for c in cols if c]

        # Detect header row
        if not in_feature_table:
            for i, col in enumerate(cols):
                col_lower = col.lower()
                if col_lower in ("도메인", "domain"):
                    domain_col = i
                elif col_lower in ("기능", "feature", "기능명"):
                    feature_col = i
            if domain_col >= 0 and feature_col >= 0:
                in_feature_table = True
            continue

        # Skip separator row (|---|---|)
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cols):
            continue

        # Parse data row
        if len(cols) > max(domain_col, feature_col):
            domain = cols[domain_col].strip()
            feature = cols[feature_col].strip()
            if domain and feature and not domain.startswith("-") and not feature.startswith("-"):
                features.append((domain, feature))

    if features:
        return features

    # --- Strategy 2: Parse domain-extract file paths from report text ---
    # Matches lines like: `domain-extracts/security/auth-model.md`
    # or `- security/auth-model.md`
    _RE_EXTRACT_PATH = re.compile(
        r"(?:domain-extracts/)?(?P<domain>[\w-]+)/(?P<feature>[\w-]+)\.md"
    )
    seen: set[tuple[str, str]] = set()
    for m in _RE_EXTRACT_PATH.finditer(text):
        pair = (m.group("domain"), m.group("feature"))
        if pair not in seen:
            seen.add(pair)
            features.append(pair)

    return features


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_phase1_quality(
    project_dir: Path,
    config: DocsOrchestratorConfig,
) -> GateResult:
    """Phase 1 output quality gate.  Runs without AI — pure Python checks.

    Validates three aspects of the Phase 1 extraction output:

    1. **Coverage ratio** — total extract lines / total source lines >= threshold.
    2. **SOURCE tag coverage** — every ``## `` section in the sources maps to at
       least one ``<!-- SOURCE: … -->`` tag in the extracts.
    3. **Empty-file check** — every feature in *analysis-report.md* has a
       corresponding extract file with >= 10 lines.
    """
    generated_dir = project_dir / "docs" / "generated"
    source_dir = project_dir / "sources"
    extracts_dir = generated_dir / "domain-extracts"
    report_path = generated_dir / "analysis-report.md"

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

    section_passed = len(uncovered_sections) == 0

    # --- Validation 3: empty / missing extract files --------------------
    features = _parse_features_from_report(report_path)
    missing_features: list[str] = []

    for domain, feature in features:
        # Convention: extract files live under ``{domain}/{feature}.md``
        # (nested directory structure per §2.5).
        # Also try flat ``{domain}-{feature}.md`` for backward compatibility.
        nested_path = extracts_dir / domain / f"{feature}.md"
        flat_path = extracts_dir / f"{domain}-{feature}.md"
        extract_path = nested_path if nested_path.exists() else flat_path
        if not extract_path.exists():
            missing_features.append(f"{domain}/{feature}")
        elif _count_lines(extract_path) < 10:
            missing_features.append(f"{domain}/{feature}")
            warnings.append(
                f"Extract '{extract_path.relative_to(extracts_dir)}' exists but has < 10 lines."
            )

    feature_passed = len(missing_features) == 0

    # --- Final verdict --------------------------------------------------
    # SOURCE tag coverage (검증 2) is advisory only — AI output format
    # varies too much for reliable exact matching.  It is recorded as
    # warnings but does NOT block the gate.
    if uncovered_sections:
        warnings.append(
            f"SOURCE 태그 미커버 섹션 {len(uncovered_sections)}개 (warning only): "
            + ", ".join(uncovered_sections[:5])
            + ("..." if len(uncovered_sections) > 5 else "")
        )
    passed = coverage_passed and feature_passed

    return GateResult(
        passed=passed,
        coverage_ratio=coverage_ratio,
        uncovered_sections=uncovered_sections,
        missing_features=missing_features,
        warnings=warnings,
    )
