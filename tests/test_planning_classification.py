from pathlib import Path

from cowork_pilot.planning.classification import (
    ClassificationInputs,
    ClassificationReport,
    build_classification_report,
    classify_project,
    reclassify_brownfield_after_observation,
    reclassify_greenfield_after_completeness,
)
from cowork_pilot.planning.completeness import CompletenessResult, CoverageResult
from cowork_pilot.planning.models import (
    ClassificationSnapshot,
    PlanningContext,
    ProjectConventionProfile,
    ProjectMode,
    SizeClass,
)
from cowork_pilot.planning.spec_sources import resolve_document_role_mapping


def test_classify_project_smoke():
    snapshot = classify_project()

    assert isinstance(snapshot, ClassificationSnapshot)


def test_build_classification_report_small_anchor():
    report = build_classification_report(
        ClassificationInputs(
            project_mode=ProjectMode.GREENFIELD,
            feature_estimate=1,
            role_estimate=1,
            flow_estimate=1,
            integration_estimate=0,
        )
    )

    assert isinstance(report, ClassificationReport)
    assert report.size_class.value == "small"
    assert report.borderline is False
    assert report.axis_observations["feature_groups"] == 1
    assert report.rationale[0].startswith("score=")


def test_build_classification_report_medium_anchor():
    report = build_classification_report(
        ClassificationInputs(
            project_mode=ProjectMode.GREENFIELD,
            feature_estimate=3,
            role_estimate=2,
            flow_estimate=2,
            integration_estimate=1,
        )
    )

    assert report.size_class.value == "medium"
    assert report.borderline is False


def test_build_classification_report_large_anchor():
    report = build_classification_report(
        ClassificationInputs(
            project_mode=ProjectMode.BROWNFIELD,
            has_existing_code=True,
            feature_estimate=5,
            role_estimate=4,
            flow_estimate=4,
            integration_estimate=2,
            brownfield_change_impact="high",
        )
    )

    assert report.size_class.value == "large"
    assert report.borderline is False


def test_build_classification_report_medium_large_borderline():
    report = build_classification_report(
        ClassificationInputs(
            project_mode=ProjectMode.GREENFIELD,
            feature_estimate=4,
            role_estimate=2,
            flow_estimate=3,
            integration_estimate=1,
            brownfield_change_impact="medium",
        )
    )

    assert report.size_class.value == "medium"
    assert report.borderline is True


def test_classify_project_uses_discovered_project_mode(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    snapshot = classify_project(PlanningContext(run_dir=tmp_path))

    assert snapshot.project_mode is ProjectMode.BROWNFIELD
    assert snapshot.axis_observations["has_existing_code"] is True
    assert snapshot.brownfield_uncertainty == "medium"


def test_classify_project_uses_project_dir_without_run_dir(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    snapshot = classify_project(PlanningContext(project_dir=tmp_path))

    assert snapshot.project_mode is ProjectMode.BROWNFIELD
    assert snapshot.axis_observations["has_existing_code"] is True


def test_classify_project_uses_auto_detect_when_mode_is_not_explicit(tmp_path: Path):
    snapshot = classify_project(
        PlanningContext(
            run_dir=tmp_path,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=False,
        )
    )

    assert snapshot.project_mode is ProjectMode.GREENFIELD


def test_classify_project_respects_explicit_mode_override(tmp_path: Path):
    snapshot = classify_project(
        PlanningContext(
            run_dir=tmp_path,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=True,
        )
    )

    assert snapshot.project_mode is ProjectMode.BROWNFIELD


def test_classify_project_accepts_resolved_document_role_mapping():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)

    snapshot = classify_project(
        inputs=ClassificationInputs(
            project_mode=ProjectMode.GREENFIELD,
            document_role_mapping=mapping,
            canonical_spec_paths=(Path("docs/specs/index.md"),),
            feature_estimate=2,
            role_estimate=1,
            flow_estimate=1,
        )
    )

    assert snapshot.project_mode is ProjectMode.GREENFIELD
    assert snapshot.size_class.value == "small"
    assert snapshot.axis_observations["document_roles"][0] == "agents"


def test_greenfield_reclassification_happens_once_after_completeness():
    initial_snapshot = ClassificationSnapshot(
        project_mode=ProjectMode.GREENFIELD,
        size_class=SizeClass.SMALL,
        product_type="greenfield-app",
        confidence="high",
        borderline=False,
    )
    completeness_result = CompletenessResult(
        category_results=(
            CoverageResult(
                category="architecture",
                observed_level="mentioned",
                required_minimum="scoped",
                passed=False,
                follow_up_action="expand architecture",
            ),
            CoverageResult(
                category="security",
                observed_level="mentioned",
                required_minimum="scoped",
                passed=False,
                follow_up_action="expand security",
            ),
        ),
        coverage_gap_path=None,
        review_path=None,
        passed=False,
    )

    result = reclassify_greenfield_after_completeness(
        current_snapshot=initial_snapshot,
        completeness_result=completeness_result,
        already_reclassified=False,
    )
    assert result.classification_snapshot_kind == "confirmed"
    assert result.initial_size_class == initial_snapshot.size_class
    assert result.confirmed_size_class == result.size_class

    noop = reclassify_greenfield_after_completeness(
        current_snapshot=result,
        completeness_result=completeness_result,
        already_reclassified=True,
    )
    assert noop is result


def test_brownfield_reclassification_preserves_initial_and_confirmed():
    initial_snapshot = ClassificationSnapshot(
        project_mode=ProjectMode.BROWNFIELD,
        size_class=SizeClass.MEDIUM,
        product_type="brownfield-service",
        confidence="medium",
        borderline=True,
    )

    confirmed = reclassify_brownfield_after_observation(
        current_snapshot=initial_snapshot,
        observation_summary="unknowns remain across auth and billing",
        confirmed_change_impact="high",
        already_reclassified=False,
    )
    assert confirmed.confirmed_size_class is not None
    assert confirmed.confirmed_borderline is not None
    assert confirmed.confirmed_change_impact == "high"
    assert confirmed.initial_size_class == initial_snapshot.size_class
