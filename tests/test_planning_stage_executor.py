from pathlib import Path

from cowork_pilot.planning.codex_bridge import ExecStageResult, ResumeStageResult
from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.prompts import render_stage_prompt
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_storage import read_run_state, write_run_state
from cowork_pilot.planning.stage_executor import execute_stage_subsession, resume_stage_subsession


def test_execute_stage_subsession_absorbs_nonblocking_question_as_assumption(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_exec_stage",
        lambda **kwargs: ExecStageResult(
            event_lines=['{"type":"thread.started","thread_id":"thread-123"}'],
            assistant_message="""
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-ask-1
reason: ask_preference
question: 기본 랜딩 경로를 dashboard로 둘까요?
options:
  - dashboard
recommended: dashboard
blocking: false
</COWORK_PILOT_EVENT>
""".strip(),
            exit_code=0,
        ),
    )

    result = execute_stage_subsession(
        run_dir=tmp_path,
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        prompt="continue",
    )

    assert result.runtime_state == PlanningRuntimeState.RUNNING_EXEC.value
    assert result.resume_handle == "thread-123"
    assert result.queued_questions[0].event_id == "pcr-ask-1"
    assert result.assumption_records[0].assumption == "dashboard"
    assert "dashboard" in (tmp_path / "assumptions.md").read_text(encoding="utf-8")


def test_resume_stage_subsession_rehydrates_persisted_context_into_resume_prompt(
    tmp_path: Path,
    monkeypatch,
):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
        metadata={
            "resume_handle": "thread-123",
            "resume_handle_kind": "codex_thread_id",
            "surface": "exec",
            "stage": PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value,
            "substage": "",
            "pending_event_id": "pcr-1",
        },
    )
    (tmp_path / "answer-log.md").write_text("- [old-answer] previous\n", encoding="utf-8")
    (tmp_path / "approval-log.md").write_text(
        "- [old-approval] decision=approved\n",
        encoding="utf-8",
    )
    (tmp_path / "assumptions.md").write_text(
        "- [old-assumption] confidence=medium impact=low dashboard\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_cli_resume",
        lambda **kwargs: ResumeStageResult(event_lines=[], assistant_message="", exit_code=0),
    )

    captured_prompt: dict[str, str] = {}

    def fake_run_exec_resume(**kwargs):
        captured_prompt["prompt"] = kwargs["prompt"]
        return ExecStageResult(
            event_lines=[],
            assistant_message="""
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ready
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
""".strip(),
            exit_code=0,
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_exec_resume",
        fake_run_exec_resume,
    )

    result = resume_stage_subsession(
        run_dir=tmp_path,
        response_text="dashboard",
        response_kind="answer",
    )

    assert result.runtime_state == PlanningRuntimeState.RUNNING_EXEC.value
    assert "answer-log.md:" in captured_prompt["prompt"]
    assert "approval-log.md:" in captured_prompt["prompt"]
    assert "assumptions.md:" in captured_prompt["prompt"]
    assert "Answer recorded for pcr-1: dashboard" in captured_prompt["prompt"]


def test_render_stage_prompt_supports_explicit_read_sets_and_handoff_summary(
    tmp_path: Path,
):
    read_set = (tmp_path / "inputs" / "normalized-request.md",)
    prompt = render_stage_prompt(
        PlanningStage.SCOPE_STRUCTURING,
        read_set=read_set,
        handoff_summary="previous handoff summary",
        target_version="v2",
    )

    assert "scope_structuring" in prompt
    assert "inputs/normalized-request.md" in prompt
    assert "previous handoff summary" in prompt
    assert "authoritative boundary" in prompt


def test_execute_stage_subsession_preserves_existing_continuation_metadata(
    tmp_path: Path,
    monkeypatch,
):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.PENDING.value,
        metadata={
            "project_mode": "greenfield",
            "size_class": "small",
            "current_stage_order": 4,
            "last_completed_order": 3,
        },
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_exec_stage",
        lambda **kwargs: ExecStageResult(
            event_lines=['{"type":"thread.started","thread_id":"thread-123"}'],
            assistant_message="""
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ready
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
""".strip(),
            exit_code=0,
        ),
    )

    execute_stage_subsession(
        run_dir=tmp_path,
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        prompt="continue",
    )

    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "project_mode": "greenfield",
        "size_class": "small",
        "current_stage_order": 4,
        "last_completed_order": 3,
        "event_id": "pcr-2",
        "stage": "product_completeness_review",
        "reason": "complete",
        "summary": "ready",
        "outputs": ["product-completeness-review.md"],
        "resume_handle": "thread-123",
        "resume_handle_kind": "codex_thread_id",
        "surface": "exec",
        "substage": "",
    }


def test_render_stage_prompt_for_exec_plan_skeleton():
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_SKELETON)
    assert "skeleton" in prompt.lower() or "순서" in prompt or "의존" in prompt


def test_render_stage_prompt_for_exec_plan_feature_outline():
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_FEATURE_OUTLINE, substage="auth")
    assert "auth" in prompt


def test_render_stage_prompt_for_exec_plan_detail():
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_DETAIL, substage="02-auth-flow")
    assert "02-auth-flow" in prompt
