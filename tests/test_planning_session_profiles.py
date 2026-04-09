import pytest

from cowork_pilot.planning.models import PlanningStage, SizeClass
from cowork_pilot.planning.session_profiles import (
    ARTIFACT_OWNERSHIP_TABLE,
    STAGE_SESSION_PROFILE_MATRIX,
    ArtifactOwnership,
    StageSessionProfile,
    resolve_brownfield_extraction_slices,
    resolve_stage_execution_kind,
    get_artifact_ownership,
    resolve_stage_profile,
)


CURRENT_STAGE_PROFILE_CASES = (
    (
        PlanningStage.CLASSIFICATION,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.CLASSIFICATION,
            strategy="single_session",
            resume_unit="classification session",
        ),
    ),
    (
        PlanningStage.CLASSIFICATION,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.CLASSIFICATION,
            strategy="two_phase_classification",
            resume_unit="current classification session",
            substages=("classification-input-audit", "classification-synthesis"),
        ),
    ),
    (
        PlanningStage.CLASSIFICATION,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.CLASSIFICATION,
            strategy="two_phase_classification",
            resume_unit="current classification session",
            substages=("classification-input-audit", "classification-synthesis"),
        ),
    ),
    (
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="lightweight_slices",
            resume_unit="current planned extraction session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="domain_module_bundles",
            resume_unit="current planned extraction session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="explicit_slice_sessions",
            resume_unit="current planned extraction session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="observation synthesis session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="observation synthesis session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="observation synthesis session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="gap synthesis session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="gap synthesis session",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="gap synthesis session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_CHECK,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_CHECK,
            strategy="single_session",
            resume_unit="core_docs_check session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_CHECK,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_CHECK,
            strategy="single_session",
            resume_unit="core_docs_check session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_CHECK,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_CHECK,
            strategy="single_session",
            resume_unit="core_docs_check session",
        ),
    ),
    (
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.ADAPTIVE_DOCS_SELECTION,
            strategy="single_session",
            resume_unit="adaptive_docs_selection session",
        ),
    ),
    (
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.ADAPTIVE_DOCS_SELECTION,
            strategy="single_session",
            resume_unit="adaptive_docs_selection session",
        ),
    ),
    (
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.ADAPTIVE_DOCS_SELECTION,
            strategy="single_session",
            resume_unit="adaptive_docs_selection session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
            strategy="single_session",
            resume_unit="core_docs_presence_review session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
            strategy="single_session",
            resume_unit="core_docs_presence_review session",
        ),
    ),
    (
        PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
            strategy="single_session",
            resume_unit="core_docs_presence_review session",
        ),
    ),
    (
        PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="single_session",
            resume_unit="product completeness review session",
        ),
    ),
    (
        PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="two_phase_completeness",
            resume_unit="current completeness session",
            substages=("user-facing completeness", "ops/nonfunctional completeness"),
        ),
    ),
    (
        PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="three_phase_completeness",
            resume_unit="current completeness session",
            substages=("pages-and-flows", "roles-and-permissions", "ops-integrations-nfr"),
        ),
    ),
    (
        PlanningStage.SCOPE_STRUCTURING,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.SCOPE_STRUCTURING,
            strategy="single_session",
            resume_unit="scope structuring session",
        ),
    ),
    (
        PlanningStage.SCOPE_STRUCTURING,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.SCOPE_STRUCTURING,
            strategy="domain_group_scope",
            resume_unit="current scope structuring session",
            substages=("domain-group-a", "domain-group-b"),
        ),
    ),
    (
        PlanningStage.SCOPE_STRUCTURING,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.SCOPE_STRUCTURING,
            strategy="domain_bundle_scope",
            resume_unit="current scope structuring session",
        ),
    ),
    (
        PlanningStage.WORK_SIZING,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.WORK_SIZING,
            strategy="single_session",
            resume_unit="work_sizing session",
        ),
    ),
    (
        PlanningStage.WORK_SIZING,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.WORK_SIZING,
            strategy="single_session",
            resume_unit="work_sizing session",
        ),
    ),
    (
        PlanningStage.WORK_SIZING,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.WORK_SIZING,
            strategy="single_session",
            resume_unit="work_sizing session",
        ),
    ),
    (
        PlanningStage.PLAN_PACKING,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.PLAN_PACKING,
            strategy="single_session",
            resume_unit="plan_packing session",
        ),
    ),
    (
        PlanningStage.PLAN_PACKING,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.PLAN_PACKING,
            strategy="single_session",
            resume_unit="plan_packing session",
        ),
    ),
    (
        PlanningStage.PLAN_PACKING,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.PLAN_PACKING,
            strategy="single_session",
            resume_unit="plan_packing session",
        ),
    ),
    (
        PlanningStage.PLAN_REVIEW,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.PLAN_REVIEW,
            strategy="two_phase_review",
            resume_unit="current plan review session",
            substages=("coverage-and-sizing", "executionability-and-overdesign"),
        ),
    ),
    (
        PlanningStage.PLAN_REVIEW,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.PLAN_REVIEW,
            strategy="two_phase_review",
            resume_unit="current plan review session",
            substages=("coverage-and-sizing", "executionability-and-overdesign"),
        ),
    ),
    (
        PlanningStage.PLAN_REVIEW,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.PLAN_REVIEW,
            strategy="two_phase_review",
            resume_unit="current plan review session",
            substages=("coverage-and-sizing", "executionability-and-overdesign"),
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_AUTHORING,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_AUTHORING,
            strategy="single_session",
            resume_unit="exec_plan_authoring session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_AUTHORING,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_AUTHORING,
            strategy="single_session",
            resume_unit="exec_plan_authoring session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_AUTHORING,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_AUTHORING,
            strategy="single_session",
            resume_unit="exec_plan_authoring session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_SKELETON,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_SKELETON,
            strategy="single_session",
            resume_unit="exec_plan_skeleton session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_SKELETON,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_SKELETON,
            strategy="single_session",
            resume_unit="exec_plan_skeleton session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_SKELETON,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_SKELETON,
            strategy="single_session",
            resume_unit="exec_plan_skeleton session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            strategy="single_session",
            resume_unit="exec_plan_feature_outline session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            strategy="single_session",
            resume_unit="exec_plan_feature_outline session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            strategy="single_session",
            resume_unit="exec_plan_feature_outline session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_DETAIL,
        SizeClass.SMALL,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            strategy="single_session",
            resume_unit="exec_plan_detail session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_DETAIL,
        SizeClass.MEDIUM,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            strategy="single_session",
            resume_unit="exec_plan_detail session",
        ),
    ),
    (
        PlanningStage.EXEC_PLAN_DETAIL,
        SizeClass.LARGE,
        StageSessionProfile(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            strategy="single_session",
            resume_unit="exec_plan_detail session",
        ),
    ),
)


ARTIFACT_OWNERSHIP_CASES = (
    (
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        ArtifactOwnership(
            artifact_owner="extraction session",
            completion_artifacts=("code-observations/<slice>.md",),
            completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="current extraction session",
            reopen_trigger="stage_reopen_required",
            next_consumer="brownfield_observation_synthesis",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        ArtifactOwnership(
            artifact_owner="observation synthesis session",
            completion_artifacts=("implementation-observation-summary.md",),
            completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="observation synthesis session",
            reopen_trigger="stage_reopen_required",
            next_consumer="brownfield_gap_synthesis",
        ),
    ),
    (
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        ArtifactOwnership(
            artifact_owner="gap synthesis session",
            completion_artifacts=("spec-implementation-gap.md", "change-impact-gap.md"),
            completion_predicate="both files exist and each contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="gap synthesis session",
            reopen_trigger="stage_reopen_required",
            next_consumer="scope_structuring",
        ),
    ),
)


def test_all_current_stages_have_explicit_session_policy_entries():
    assert set(STAGE_SESSION_PROFILE_MATRIX) == set(PlanningStage)


@pytest.mark.parametrize(("stage", "size_class", "expected"), CURRENT_STAGE_PROFILE_CASES)
def test_stage_profile_matrix_contract(stage: PlanningStage, size_class: SizeClass, expected: StageSessionProfile):
    assert resolve_stage_profile(stage, size_class) == expected


def test_brownfield_artifact_ownership_table_is_explicit():
    """Brownfield stages are a subset of the full ARTIFACT_OWNERSHIP_TABLE."""
    brownfield_stages = {
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
    }
    assert brownfield_stages.issubset(set(ARTIFACT_OWNERSHIP_TABLE))


@pytest.mark.parametrize(("stage", "expected"), ARTIFACT_OWNERSHIP_CASES)
def test_brownfield_artifact_ownership_contract(stage: PlanningStage, expected: ArtifactOwnership):
    assert get_artifact_ownership(stage) == expected


def test_all_planning_stages_are_ai():
    assert resolve_stage_execution_kind(PlanningStage.WORK_SIZING, SizeClass.SMALL) == "ai"
    assert resolve_stage_execution_kind(PlanningStage.PLAN_REVIEW, SizeClass.SMALL) == "ai"
    assert resolve_stage_execution_kind(PlanningStage.CLASSIFICATION, SizeClass.SMALL) == "ai"


def test_brownfield_extraction_slices_expand_for_large_projects():
    assert resolve_brownfield_extraction_slices(SizeClass.LARGE) == (
        "explicit_slice_sessions-slice-1",
        "explicit_slice_sessions-slice-2",
        "explicit_slice_sessions-slice-3",
    )


def test_exec_plan_skeleton_is_ai_stage():
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_SKELETON, SizeClass.SMALL) == "ai"


def test_exec_plan_feature_outline_is_ai_stage():
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_FEATURE_OUTLINE, SizeClass.SMALL) == "ai"


def test_exec_plan_detail_is_ai_stage():
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_DETAIL, SizeClass.SMALL) == "ai"


@pytest.mark.parametrize("stage", [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
])
def test_converted_stages_are_ai_execution_kind(stage: PlanningStage):
    for size_class in SizeClass:
        assert resolve_stage_execution_kind(stage, size_class) == "ai", (
            f"{stage.value} should be 'ai' for {size_class.value}"
        )


_CONVERTED_ARTIFACT_CASES = (
    (PlanningStage.CLASSIFICATION, ("classification-report.md",), "core_docs_check"),
    (PlanningStage.CORE_DOCS_CHECK, ("core-docs-check.md",), "adaptive_docs_selection"),
    (PlanningStage.ADAPTIVE_DOCS_SELECTION, ("adaptive-docs-selection.md",), "scope_structuring"),
    (PlanningStage.SCOPE_STRUCTURING, ("scope-map.md",), "work_sizing"),
    (PlanningStage.WORK_SIZING, ("work-sizing.md",), "plan_packing"),
    (PlanningStage.PLAN_PACKING, ("plan-packing.md",), "plan_review"),
    (PlanningStage.PLAN_REVIEW, ("plan-review.md",), "exec_plan_skeleton"),
)


@pytest.mark.parametrize("stage,expected_artifacts,expected_consumer", _CONVERTED_ARTIFACT_CASES)
def test_converted_stage_artifact_ownership(stage, expected_artifacts, expected_consumer):
    ownership = get_artifact_ownership(stage)
    assert ownership.completion_artifacts == expected_artifacts
    assert ownership.next_consumer == expected_consumer
    assert "ORCHESTRATOR:DONE" in ownership.completion_predicate


def test_artifact_ownership_table_covers_all_contracted_stages():
    expected = {
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        PlanningStage.CLASSIFICATION,
        PlanningStage.CORE_DOCS_CHECK,
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        PlanningStage.SCOPE_STRUCTURING,
        PlanningStage.WORK_SIZING,
        PlanningStage.PLAN_PACKING,
        PlanningStage.PLAN_REVIEW,
    }
    assert set(ARTIFACT_OWNERSHIP_TABLE) == expected
