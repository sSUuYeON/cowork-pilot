from pathlib import Path

from cowork_pilot.planning.completeness import evaluate_coverage, run_completeness_review
from cowork_pilot.planning.models import ClassificationSnapshot, ProjectMode, SizeClass


def test_completeness_smoke():
    result = run_completeness_review()

    assert result.category_results == ()


def test_small_page_function_coverage_passes_at_scoped():
    result = evaluate_coverage(
        category="page_function",
        observed_level="scoped",
        size_class=SizeClass.SMALL,
    )

    assert result.passed is True


def test_medium_page_function_coverage_fails_at_mentioned():
    result = evaluate_coverage(
        category="page_function",
        observed_level="mentioned",
        size_class=SizeClass.MEDIUM,
    )

    assert result.passed is False


def test_small_nonfunctional_requirements_pass_at_mentioned():
    result = evaluate_coverage(
        category="non_functional",
        observed_level="mentioned",
        size_class=SizeClass.SMALL,
    )

    assert result.passed is True


def test_not_applicable_skips_failure():
    result = evaluate_coverage(
        category="integration",
        observed_level="not_applicable",
        size_class=SizeClass.LARGE,
        integration_heavy=True,
    )

    assert result.passed is True


def test_greenfield_completeness_writes_coverage_gap(tmp_path: Path):
    snapshot = ClassificationSnapshot(
        project_mode=ProjectMode.GREENFIELD,
        size_class=SizeClass.SMALL,
        product_type="greenfield-app",
        confidence="high",
        borderline=False,
    )

    result = run_completeness_review(
        core_docs=["agents", "design_guide"],
        adaptive_docs=["architecture"],
        snapshot=snapshot,
        run_dir=tmp_path,
    )

    assert (tmp_path / "product-completeness-review.md").exists()
    assert (tmp_path / "coverage-gap.md").exists()
    assert "architecture" in (tmp_path / "coverage-gap.md").read_text(encoding="utf-8")
    assert result.coverage_gap_path == tmp_path / "coverage-gap.md"
