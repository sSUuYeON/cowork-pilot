from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.question_policy import can_use_assumption, should_allow_question


def test_front_loaded_policy_allows_questions_in_product_completeness_review():
    assert should_allow_question(
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        phase_strategy="question_heavy_then_auto",
    ) is True


def test_front_loaded_policy_discourages_questions_in_exec_plan_authoring():
    assert should_allow_question(
        stage=PlanningStage.EXEC_PLAN_AUTHORING,
        phase_strategy="question_heavy_then_auto",
    ) is False


def test_broad_product_design_allows_nonblocking_assumptions():
    assert can_use_assumption(
        stage=PlanningStage.SCOPE_STRUCTURING,
        assumption_scope="broad_product_design",
        blocking=False,
    ) is True


def test_conservative_scope_blocks_assumption_absorption():
    assert can_use_assumption(
        stage=PlanningStage.SCOPE_STRUCTURING,
        assumption_scope="conservative",
        blocking=False,
    ) is False
