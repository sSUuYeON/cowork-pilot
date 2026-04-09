from __future__ import annotations

from dataclasses import dataclass

from cowork_pilot.planning.models import PlanningStage, SizeClass, StageExecutionKind


@dataclass(frozen=True)
class StageSessionProfile:
    stage: PlanningStage
    strategy: str
    resume_unit: str
    substages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactOwnership:
    artifact_owner: str
    completion_artifacts: tuple[str, ...]
    completion_predicate: str
    resume_target: str
    reopen_trigger: str
    next_consumer: str


def _stage_session_profile(
    stage: PlanningStage,
    strategy: str,
    resume_unit: str,
    substages: tuple[str, ...] = (),
) -> StageSessionProfile:
    return StageSessionProfile(
        stage=stage,
        strategy=strategy,
        resume_unit=resume_unit,
        substages=substages,
    )


def _shared_size_profile(profile: StageSessionProfile) -> dict[SizeClass, StageSessionProfile]:
    return {
        SizeClass.SMALL: profile,
        SizeClass.MEDIUM: profile,
        SizeClass.LARGE: profile,
    }


_LOCAL_STAGE_EXECUTION_STAGES: set[PlanningStage] = set()

_BROWNFIELD_EXTRACTION_SLICE_COUNTS = {
    SizeClass.SMALL: 1,
    SizeClass.MEDIUM: 2,
    SizeClass.LARGE: 3,
}


STAGE_SESSION_PROFILE_MATRIX: dict[PlanningStage, dict[SizeClass, StageSessionProfile]] = {
    PlanningStage.CLASSIFICATION: {
        SizeClass.SMALL: _stage_session_profile(
            PlanningStage.CLASSIFICATION,
            strategy="single_session",
            resume_unit="classification session",
        ),
        SizeClass.MEDIUM: _stage_session_profile(
            PlanningStage.CLASSIFICATION,
            strategy="two_phase_classification",
            resume_unit="current classification session",
            substages=("classification-input-audit", "classification-synthesis"),
        ),
        SizeClass.LARGE: _stage_session_profile(
            PlanningStage.CLASSIFICATION,
            strategy="two_phase_classification",
            resume_unit="current classification session",
            substages=("classification-input-audit", "classification-synthesis"),
        ),
    },
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: {
        SizeClass.SMALL: _stage_session_profile(
            PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="lightweight_slices",
            resume_unit="current planned extraction session",
        ),
        SizeClass.MEDIUM: _stage_session_profile(
            PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="domain_module_bundles",
            resume_unit="current planned extraction session",
        ),
        SizeClass.LARGE: _stage_session_profile(
            PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
            strategy="explicit_slice_sessions",
            resume_unit="current planned extraction session",
        ),
    },
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="observation synthesis session",
        )
    ),
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
            strategy="single_synthesis_session",
            resume_unit="gap synthesis session",
        )
    ),
    PlanningStage.CORE_DOCS_CHECK: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.CORE_DOCS_CHECK,
            strategy="single_session",
            resume_unit="core_docs_check session",
        )
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.ADAPTIVE_DOCS_SELECTION,
            strategy="single_session",
            resume_unit="adaptive_docs_selection session",
        )
    ),
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
            strategy="single_session",
            resume_unit="core_docs_presence_review session",
        )
    ),
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: {
        SizeClass.SMALL: _stage_session_profile(
            PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="single_session",
            resume_unit="product completeness review session",
        ),
        SizeClass.MEDIUM: _stage_session_profile(
            PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="two_phase_completeness",
            resume_unit="current completeness session",
            substages=("user-facing completeness", "ops/nonfunctional completeness"),
        ),
        SizeClass.LARGE: _stage_session_profile(
            PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
            strategy="three_phase_completeness",
            resume_unit="current completeness session",
            substages=("pages-and-flows", "roles-and-permissions", "ops-integrations-nfr"),
        ),
    },
    PlanningStage.SCOPE_STRUCTURING: {
        SizeClass.SMALL: _stage_session_profile(
            PlanningStage.SCOPE_STRUCTURING,
            strategy="single_session",
            resume_unit="scope structuring session",
        ),
        SizeClass.MEDIUM: _stage_session_profile(
            PlanningStage.SCOPE_STRUCTURING,
            strategy="domain_group_scope",
            resume_unit="current scope structuring session",
            substages=("domain-group-a", "domain-group-b"),
        ),
        SizeClass.LARGE: _stage_session_profile(
            PlanningStage.SCOPE_STRUCTURING,
            strategy="domain_bundle_scope",
            resume_unit="current scope structuring session",
        ),
    },
    PlanningStage.WORK_SIZING: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.WORK_SIZING,
            strategy="single_session",
            resume_unit="work_sizing session",
        )
    ),
    PlanningStage.PLAN_PACKING: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.PLAN_PACKING,
            strategy="single_session",
            resume_unit="plan_packing session",
        )
    ),
    PlanningStage.PLAN_REVIEW: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.PLAN_REVIEW,
            strategy="two_phase_review",
            resume_unit="current plan review session",
            substages=("coverage-and-sizing", "executionability-and-overdesign"),
        )
    ),
    PlanningStage.EXEC_PLAN_AUTHORING: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.EXEC_PLAN_AUTHORING,
            strategy="single_session",
            resume_unit="exec_plan_authoring session",
        )
    ),
    PlanningStage.EXEC_PLAN_SKELETON: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.EXEC_PLAN_SKELETON,
            strategy="single_session",
            resume_unit="exec_plan_skeleton session",
        )
    ),
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            strategy="single_session",
            resume_unit="exec_plan_feature_outline session",
        )
    ),
    PlanningStage.EXEC_PLAN_DETAIL: _shared_size_profile(
        _stage_session_profile(
            PlanningStage.EXEC_PLAN_DETAIL,
            strategy="single_session",
            resume_unit="exec_plan_detail session",
        )
    ),
}


ARTIFACT_OWNERSHIP_TABLE: dict[PlanningStage, ArtifactOwnership] = {
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: ArtifactOwnership(
        artifact_owner="extraction session",
        completion_artifacts=("code-observations/<slice>.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
        resume_target="current extraction session",
        reopen_trigger="stage_reopen_required",
        next_consumer="brownfield_observation_synthesis",
    ),
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: ArtifactOwnership(
        artifact_owner="observation synthesis session",
        completion_artifacts=("implementation-observation-summary.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
        resume_target="observation synthesis session",
        reopen_trigger="stage_reopen_required",
        next_consumer="brownfield_gap_synthesis",
    ),
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: ArtifactOwnership(
        artifact_owner="gap synthesis session",
        completion_artifacts=("spec-implementation-gap.md", "change-impact-gap.md"),
        completion_predicate="both files exist and each contains <!-- ORCHESTRATOR:DONE -->",
        resume_target="gap synthesis session",
        reopen_trigger="stage_reopen_required",
        next_consumer="scope_structuring",
    ),
    PlanningStage.CLASSIFICATION: ArtifactOwnership(
        artifact_owner="classification session",
        completion_artifacts=("classification-report.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: project_mode, product_type, size_class, core_user_flows, primary_entities, risks",
        resume_target="classification session",
        reopen_trigger="stage_reopen_required",
        next_consumer="core_docs_check",
    ),
    PlanningStage.CORE_DOCS_CHECK: ArtifactOwnership(
        artifact_owner="core_docs_check session",
        completion_artifacts=("core-docs-check.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: required_doc_roles, resolved_existing_paths, missing_roles, substitutions",
        resume_target="core_docs_check session",
        reopen_trigger="stage_reopen_required",
        next_consumer="adaptive_docs_selection",
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: ArtifactOwnership(
        artifact_owner="adaptive_docs_selection session",
        completion_artifacts=("adaptive-docs-selection.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: selected_paths, selected_roles, selection_reasons, rejected_candidates",
        resume_target="adaptive_docs_selection session",
        reopen_trigger="stage_reopen_required",
        next_consumer="scope_structuring",
    ),
    PlanningStage.SCOPE_STRUCTURING: ArtifactOwnership(
        artifact_owner="scope_structuring session",
        completion_artifacts=("scope-map.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: domains, features, user_flows, out_of_scope",
        resume_target="scope_structuring session",
        reopen_trigger="stage_reopen_required",
        next_consumer="work_sizing",
    ),
    PlanningStage.WORK_SIZING: ArtifactOwnership(
        artifact_owner="work_sizing session",
        completion_artifacts=("work-sizing.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with key: work_items (array of {id, title, domain, feature, size, risk, depends_on})",
        resume_target="work_sizing session",
        reopen_trigger="stage_reopen_required",
        next_consumer="plan_packing",
    ),
    PlanningStage.PLAN_PACKING: ArtifactOwnership(
        artifact_owner="plan_packing session",
        completion_artifacts=("plan-packing.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with key: plans (array of {plan_name, goal, included_work_item_ids, why_grouped, dependencies})",
        resume_target="plan_packing session",
        reopen_trigger="stage_reopen_required",
        next_consumer="plan_review",
    ),
    PlanningStage.PLAN_REVIEW: ArtifactOwnership(
        artifact_owner="plan_review session",
        completion_artifacts=("plan-review.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: issues, rollback_recommended, coverage_status, execution_risks, missing_work_items",
        resume_target="plan_review session",
        reopen_trigger="stage_reopen_required",
        next_consumer="exec_plan_skeleton",
    ),
}


def resolve_stage_profile(stage: PlanningStage, size_class: SizeClass) -> StageSessionProfile:
    stage_profiles = STAGE_SESSION_PROFILE_MATRIX.get(stage)
    if stage_profiles is not None:
        return stage_profiles[size_class]
    return _stage_session_profile(stage, strategy="single_session", resume_unit=f"{stage.value} session")


def resolve_stage_execution_kind(stage: PlanningStage, size_class: SizeClass) -> StageExecutionKind:
    resolve_stage_profile(stage, size_class)
    if stage in _LOCAL_STAGE_EXECUTION_STAGES:
        return "local"
    return "ai"


def resolve_brownfield_extraction_slices(size_class: SizeClass) -> tuple[str, ...]:
    profile = resolve_stage_profile(PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION, size_class)
    slice_count = _BROWNFIELD_EXTRACTION_SLICE_COUNTS[size_class]
    return tuple(f"{profile.strategy}-slice-{index}" for index in range(1, slice_count + 1))


def get_artifact_ownership(stage: PlanningStage) -> ArtifactOwnership:
    return ARTIFACT_OWNERSHIP_TABLE[stage]
