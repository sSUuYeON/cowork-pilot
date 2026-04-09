from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ClassificationSnapshot, ProjectMode, SizeClass


_COVERAGE_ORDER = {
    "missing": 0,
    "mentioned": 1,
    "scoped": 2,
    "implementation_ready": 3,
    "not_applicable": 4,
}


@dataclass(frozen=True)
class CoverageResult:
    category: str
    observed_level: str
    required_minimum: str
    passed: bool
    follow_up_action: str


@dataclass(frozen=True)
class CompletenessResult:
    category_results: tuple[CoverageResult, ...]
    coverage_gap_path: Path | None
    review_path: Path | None
    passed: bool


def evaluate_coverage(
    *,
    category: str,
    observed_level: str,
    size_class: SizeClass,
    integration_heavy: bool = False,
) -> CoverageResult:
    required_minimum = _required_minimum_for_category(
        category=category,
        size_class=size_class,
        integration_heavy=integration_heavy,
    )
    if observed_level == "not_applicable":
        return CoverageResult(
            category=category,
            observed_level=observed_level,
            required_minimum=required_minimum,
            passed=True,
            follow_up_action="skip",
        )

    passed = _COVERAGE_ORDER[observed_level] >= _COVERAGE_ORDER[required_minimum]
    follow_up_action = "none" if passed else f"raise {category} to {required_minimum}"
    return CoverageResult(
        category=category,
        observed_level=observed_level,
        required_minimum=required_minimum,
        passed=passed,
        follow_up_action=follow_up_action,
    )

def run_completeness_review(
    core_docs: list[str] | None = None,
    adaptive_docs: list[str] | None = None,
    snapshot: ClassificationSnapshot | None = None,
    run_dir: Path | None = None,
) -> CompletenessResult:
    if snapshot is None:
        return CompletenessResult(
            category_results=(),
            coverage_gap_path=None,
            review_path=None,
            passed=True,
        )

    required_docs = list(core_docs or [])
    conditional_docs = list(adaptive_docs or [])
    category_results = [
        CoverageResult(
            category=doc_name,
            observed_level="scoped",
            required_minimum="mentioned",
            passed=True,
            follow_up_action="none",
        )
        for doc_name in required_docs
    ]
    category_results.extend(
        CoverageResult(
            category=doc_name,
            observed_level="mentioned",
            required_minimum="scoped",
            passed=False,
            follow_up_action=f"expand {doc_name}",
        )
        for doc_name in conditional_docs
    )

    review_path: Path | None = None
    coverage_gap_path: Path | None = None
    if run_dir is not None and snapshot.project_mode is ProjectMode.GREENFIELD:
        review_path = run_dir / "product-completeness-review.md"
        review_path.write_text(
            _render_completeness_review(category_results),
            encoding="utf-8",
        )
        coverage_gap_path = run_dir / "coverage-gap.md"
        uncovered = [result.category for result in category_results if not result.passed]
        coverage_gap_path.write_text(
            _render_coverage_gap(uncovered),
            encoding="utf-8",
        )

    return CompletenessResult(
        category_results=tuple(category_results),
        coverage_gap_path=coverage_gap_path,
        review_path=review_path,
        passed=all(result.passed for result in category_results),
    )


def _required_minimum_for_category(
    *,
    category: str,
    size_class: SizeClass,
    integration_heavy: bool,
) -> str:
    if category == "non_functional" and size_class is SizeClass.SMALL:
        return "mentioned"
    if integration_heavy or category == "integration":
        return "scoped"
    if category == "page_function":
        return "scoped"
    return "mentioned"


def _render_completeness_review(results: list[CoverageResult]) -> str:
    lines = ["# Product Completeness Review", ""]
    for result in results:
        lines.append(
            f"- {result.category}: observed={result.observed_level} "
            f"minimum={result.required_minimum} passed={str(result.passed).lower()}"
        )
    return "\n".join(lines) + "\n"


def _render_coverage_gap(uncovered: list[str]) -> str:
    lines = ["# Coverage Gap", ""]
    if not uncovered:
        lines.append("- fully covered")
    else:
        for category in uncovered:
            lines.append(f"- {category}")
    return "\n".join(lines) + "\n"
