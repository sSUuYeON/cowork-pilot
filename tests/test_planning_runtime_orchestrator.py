import json
from pathlib import Path

from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_orchestrator import (
    RuntimeUpdate,
    apply_marker_bundle_to_run,
    apply_subprocess_failure,
)
from cowork_pilot.planning.runtime_storage import (
    append_answer,
    append_approval_decision,
    read_run_state,
)


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in _read_lines(path)]


def _message(body: str) -> str:
    return f"{body}\n"


def test_read_run_state_returns_empty_dict_when_missing(tmp_path: Path):
    assert read_run_state(tmp_path) == {}


def test_append_answer_writes_expected_markdown_line(tmp_path: Path):
    append_answer(tmp_path, event_id="answer-1", answer="dashboard로 유지")

    assert _read_lines(tmp_path / "answer-log.md") == [
        "- [answer-1] dashboard로 유지"
    ]


def test_append_approval_decision_writes_expected_markdown_line(tmp_path: Path):
    append_approval_decision(tmp_path, event_id="approval-1", decision="approved")

    assert _read_lines(tmp_path / "approval-log.md") == [
        "- [approval-1] decision=approved"
    ]


def test_subprocess_failure_moves_running_exec_to_failed(tmp_path: Path):
    update = apply_subprocess_failure(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        exit_code=7,
        stage="plan_review",
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.FAILED)
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.FAILED.value,
        "exit_code": 7,
        "stage": "plan_review",
    }

    event_lines = _read_lines(tmp_path / "runtime-events.ndjson")
    assert len(event_lines) == 1
    assert json.loads(event_lines[0]) == {
        "event": "subprocess_failure",
        "exit_code": 7,
        "stage": "plan_review",
    }


def test_subprocess_failure_is_noop_when_not_running_exec(tmp_path: Path):
    update = apply_subprocess_failure(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.WAITING_FOR_INPUT,
        exit_code=7,
        stage="plan_review",
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_INPUT)
    assert not (tmp_path / "runtime-events.ndjson").exists()
    assert not (tmp_path / "run-state.json").exists()


def test_blocking_input_required_moves_run_to_waiting_for_input(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing_redirect
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_INPUT)
    assert _read_lines(tmp_path / "question-queue.md") == [
        "- [pcr-1] (blocking=true) 로그인 후 기본 이동 경로는?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.WAITING_FOR_INPUT.value,
        "event_id": "pcr-1",
        "stage": "product_completeness_review",
    }
    assert _read_events(tmp_path / "runtime-events.ndjson") == [
        {
            "event": "marker",
            "type": "INPUT_REQUIRED",
            "event_id": "pcr-1",
            "stage": "product_completeness_review",
            "reason": "missing_redirect",
            "payload": {
                "question": "로그인 후 기본 이동 경로는?",
                "options": ["dashboard"],
                "recommended": "dashboard",
                "blocking": True,
            },
        }
    ]


def test_nonblocking_input_required_keeps_run_running_exec(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-2
reason: ask_preference
question: 관리자 보고서 기본 범위를 주간으로 둘까요?
options:
  - yes
  - no
recommended: yes
blocking: false
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert _read_lines(tmp_path / "question-queue.md") == [
        "- [pcr-2] (blocking=false) 관리자 보고서 기본 범위를 주간으로 둘까요?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "event_id": "pcr-2",
        "stage": "product_completeness_review",
    }


def test_blocking_approval_required_moves_run_to_waiting_for_approval(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: APPROVAL_REQUIRED
stage: plan_review
event_id: pr-approval-1
reason: scope_signoff
subject: 현재 작업 분할로 진행할까요?
proposed_decision: proceed
blocking: true
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_APPROVAL)
    assert _read_lines(tmp_path / "approval-log.md") == [
        "- [pr-approval-1] (blocking=true) 현재 작업 분할로 진행할까요?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
        "event_id": "pr-approval-1",
        "stage": "plan_review",
    }


def test_nonblocking_approval_required_keeps_run_running_exec(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: APPROVAL_REQUIRED
stage: plan_review
event_id: pr-approval-2
reason: optional_signoff
subject: 이 naming을 기본안으로 둘까요?
proposed_decision: proceed
blocking: false
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert _read_lines(tmp_path / "approval-log.md") == [
        "- [pr-approval-2] (blocking=false) 이 naming을 기본안으로 둘까요?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "event_id": "pr-approval-2",
        "stage": "plan_review",
    }


def test_assumption_log_appends_and_keeps_current_state(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-assumption-1
reason: continue
assumption: 기존 chunk split을 유지한다
confidence: medium
impact: low
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert _read_lines(tmp_path / "assumptions.md") == [
        "- [pr-assumption-1] confidence=medium impact=low 기존 chunk split을 유지한다"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "event_id": "pr-assumption-1",
        "stage": "plan_review",
    }
    assert _read_events(tmp_path / "runtime-events.ndjson") == [
        {
            "event": "marker",
            "type": "ASSUMPTION_LOG",
            "event_id": "pr-assumption-1",
            "stage": "plan_review",
            "reason": "continue",
            "payload": {
                "assumption": "기존 chunk split을 유지한다",
                "confidence": "medium",
                "impact": "low",
            },
        }
    ]


def test_stage_complete_keeps_current_state_and_writes_summary_metadata(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-stage-1
reason: complete
summary: review complete
outputs:
  - docs/exec-plans/active/01-plan.md
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "event_id": "pr-stage-1",
        "stage": "plan_review",
        "reason": "complete",
        "summary": "review complete",
        "outputs": ["docs/exec-plans/active/01-plan.md"],
    }
    assert _read_events(tmp_path / "runtime-events.ndjson") == [
        {
            "event": "marker",
            "type": "STAGE_COMPLETE",
            "event_id": "pr-stage-1",
            "stage": "plan_review",
            "reason": "complete",
            "payload": {
                "summary": "review complete",
                "outputs": ["docs/exec-plans/active/01-plan.md"],
            },
        }
    ]


def test_assumption_then_stage_complete_bundle_applies_all_side_effects(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-bundle-1
reason: continue
assumption: 현재 review scope를 유지한다
confidence: medium
impact: low
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-bundle-2
reason: complete
summary: bundled review complete
outputs:
  - docs/exec-plans/active/01-plan.md
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert _read_lines(tmp_path / "assumptions.md") == [
        "- [pr-bundle-1] confidence=medium impact=low 현재 review scope를 유지한다"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_EXEC.value,
        "event_id": "pr-bundle-2",
        "stage": "plan_review",
        "reason": "complete",
        "summary": "bundled review complete",
        "outputs": ["docs/exec-plans/active/01-plan.md"],
    }
    assert _read_events(tmp_path / "runtime-events.ndjson") == [
        {
            "event": "marker",
            "type": "ASSUMPTION_LOG",
            "event_id": "pr-bundle-1",
            "stage": "plan_review",
            "reason": "continue",
            "payload": {
                "assumption": "현재 review scope를 유지한다",
                "confidence": "medium",
                "impact": "low",
            },
        },
        {
            "event": "marker",
            "type": "STAGE_COMPLETE",
            "event_id": "pr-bundle-2",
            "stage": "plan_review",
            "reason": "complete",
            "payload": {
                "summary": "bundled review complete",
                "outputs": ["docs/exec-plans/active/01-plan.md"],
            },
        },
    ]


def test_cli_input_required_keeps_run_running_cli(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: plan_review
event_id: cli-input-1
reason: ask_human
question: 이 문구를 그대로 보낼까요?
options:
  - yes
recommended: yes
blocking: true
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_CLI)
    assert _read_lines(tmp_path / "question-queue.md") == [
        "- [cli-input-1] (blocking=true) 이 문구를 그대로 보낼까요?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_CLI.value,
        "event_id": "cli-input-1",
        "stage": "plan_review",
    }


def test_cli_approval_required_keeps_run_running_cli(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: APPROVAL_REQUIRED
stage: plan_review
event_id: cli-approval-1
reason: ask_human
subject: 이 초안을 전송 승인할까요?
proposed_decision: approve
blocking: true
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_CLI)
    assert _read_lines(tmp_path / "approval-log.md") == [
        "- [cli-approval-1] (blocking=true) 이 초안을 전송 승인할까요?"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.RUNNING_CLI.value,
        "event_id": "cli-approval-1",
        "stage": "plan_review",
    }


def test_assumption_invalidation_moves_run_to_waiting_for_human(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-3
reason: replan_required
issue: earlier assumption was invalid
why_ai_stopped: the work split needs human confirmation
suggested_next_action: update the active plan
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_HUMAN)
    assert _read_lines(tmp_path / "assumption-invalidations.md") == [
        "- [pr-3] reason=replan_required affected_stage=plan_review"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.WAITING_FOR_HUMAN.value,
        "event_id": "pr-3",
        "stage": "plan_review",
        "reason": "replan_required",
    }


def test_running_cli_escalates_on_needs_human(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-4
reason: insufficient_context
issue: legal copy requires owner review
why_ai_stopped: approval boundary reached
suggested_next_action: escalate to owner
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.ESCALATED)
    assert not (tmp_path / "assumption-invalidations.md").exists()
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.ESCALATED.value,
        "event_id": "pr-4",
        "stage": "plan_review",
        "reason": "insufficient_context",
    }


def test_running_cli_escalates_even_on_stage_reopen_required(tmp_path: Path):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-5
reason: stage_reopen_required
issue: review findings invalidate the closed stage
why_ai_stopped: human decision required before reopening
suggested_next_action: reopen the stage and update scope
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.ESCALATED)
    assert _read_lines(tmp_path / "assumption-invalidations.md") == [
        "- [pr-5] reason=stage_reopen_required affected_stage=plan_review"
    ]


def test_completed_transitions_to_waiting_for_human_on_post_validation(
    tmp_path: Path,
):
    message = _message(
        """
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: post_validation
event_id: pv-1
reason: stage_reopen_required
issue: validation failed after completion
why_ai_stopped: reopening needs human confirmation
suggested_next_action: inspect the failed validation and reopen
</COWORK_PILOT_EVENT>
""".strip()
    )

    update = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.COMPLETED,
        message=message,
    )

    assert update == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_HUMAN)
    assert _read_lines(tmp_path / "assumption-invalidations.md") == [
        "- [pv-1] reason=stage_reopen_required affected_stage=post_validation"
    ]
    assert read_run_state(tmp_path) == {
        "state": PlanningRuntimeState.WAITING_FOR_HUMAN.value,
        "event_id": "pv-1",
        "stage": "post_validation",
        "reason": "stage_reopen_required",
    }
