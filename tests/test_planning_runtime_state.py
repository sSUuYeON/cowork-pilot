from pathlib import Path

from cowork_pilot.config import PlanningConfig, load_planning_config
from cowork_pilot.planning.runtime_models import (
    ApprovalPolicy,
    AssumptionScope,
    PhaseStrategy,
    PlanningRuntimeState,
    QuestionStrategy,
    ResumeHandleRef,
)


def test_runtime_state_enum_values():
    assert PlanningRuntimeState.RUNNING_EXEC.value == "running_exec"
    assert PlanningRuntimeState.WAITING_FOR_INPUT.value == "waiting_for_input"


def test_resume_handle_ref_uses_kind_and_value():
    ref = ResumeHandleRef(
        surface="exec",
        resume_handle_kind="codex_thread_id",
        resume_handle="thread-123",
        stage="product_completeness_review",
        substage="user-facing completeness",
    )
    assert ref.resume_handle_kind == "codex_thread_id"
    assert ref.resume_handle == "thread-123"
    assert ref.stage == "product_completeness_review"


def test_runtime_enum_defaults_are_importable():
    assert QuestionStrategy.FRONT_LOADED.value == "front_loaded"
    assert AssumptionScope.BROAD_PRODUCT_DESIGN.value == "broad_product_design"
    assert ApprovalPolicy.FINAL_DRAFT_ONLY.value == "final_draft_only"
    assert PhaseStrategy.QUESTION_HEAVY_THEN_AUTO.value == "question_heavy_then_auto"


def test_planning_config_defaults_match_runtime_enums():
    config = PlanningConfig()
    assert config.question_strategy == QuestionStrategy.FRONT_LOADED.value
    assert config.assumption_scope == AssumptionScope.BROAD_PRODUCT_DESIGN.value
    assert config.approval_policy == ApprovalPolicy.FINAL_DRAFT_ONLY.value
    assert config.phase_strategy == PhaseStrategy.QUESTION_HEAVY_THEN_AUTO.value


def test_checked_in_planning_config_matches_runtime_defaults():
    cfg = load_planning_config(Path("config.toml"))
    assert cfg == PlanningConfig()
    assert cfg.question_strategy == QuestionStrategy.FRONT_LOADED.value
    assert cfg.assumption_scope == AssumptionScope.BROAD_PRODUCT_DESIGN.value
    assert cfg.approval_policy == ApprovalPolicy.FINAL_DRAFT_ONLY.value
    assert cfg.phase_strategy == PhaseStrategy.QUESTION_HEAVY_THEN_AUTO.value


def test_completed_stages_roundtrip(tmp_path):
    from cowork_pilot.planning.runtime_storage import write_completed_stage, read_completed_stages

    write_completed_stage(tmp_path, stage="classification", dispatch_index=0, outputs=("mode=greenfield",))
    write_completed_stage(tmp_path, stage="core_docs_check", dispatch_index=1, outputs=("product-spec",))

    completed = read_completed_stages(tmp_path)
    assert len(completed) == 2
    assert completed[0]["stage"] == "classification"
    assert completed[1]["stage"] == "core_docs_check"


def test_read_completed_stages_returns_empty_when_no_file(tmp_path):
    from cowork_pilot.planning.runtime_storage import read_completed_stages
    assert read_completed_stages(tmp_path) == []
