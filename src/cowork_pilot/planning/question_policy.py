from __future__ import annotations

from cowork_pilot.planning.models import PlanningStage

_QUESTION_HEAVY_STAGES = {
    PlanningStage.CLASSIFICATION,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.PLAN_REVIEW,
}

_LOW_QUESTION_STAGES = {
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.EXEC_PLAN_AUTHORING,
}


def should_allow_question(stage: PlanningStage, phase_strategy: str) -> bool:
    if phase_strategy != "question_heavy_then_auto":
        return True
    if stage in _QUESTION_HEAVY_STAGES:
        return True
    if stage in _LOW_QUESTION_STAGES:
        return False
    return True


def can_use_assumption(
    *,
    stage: PlanningStage,
    assumption_scope: str,
    blocking: bool,
) -> bool:
    if blocking:
        return False
    if assumption_scope != "broad_product_design":
        return False
    return stage in _QUESTION_HEAVY_STAGES
