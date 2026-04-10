from pathlib import Path

import pytest

from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_storage import write_run_state
from cowork_pilot.planning.stage_executor import PendingApproval, PendingQuestion
from cowork_pilot.planning.terminal_ui import (
    TerminalResponse,
    prompt_for_pending_response,
    prompt_from_stage_result,
)


# ---------------------------------------------------------------------------
# prompt_from_stage_result — question
# ---------------------------------------------------------------------------


def test_question_enter_returns_recommended():
    pq = PendingQuestion(
        event_id="q-1",
        question="기본 경로는?",
        options=("dashboard", "home"),
        recommended="dashboard",
        blocking=True,
    )
    result = prompt_from_stage_result(
        pending_question=pq,
        input_fn=lambda _: "",  # simulate Enter
    )
    assert result == TerminalResponse(text="dashboard", kind="answer")


def test_question_numeric_picks_option():
    pq = PendingQuestion(
        event_id="q-1",
        question="기본 경로는?",
        options=("dashboard", "home", "settings"),
        recommended="dashboard",
        blocking=True,
    )
    result = prompt_from_stage_result(
        pending_question=pq,
        input_fn=lambda _: "2",
    )
    assert result == TerminalResponse(text="home", kind="answer")


def test_question_freetext():
    pq = PendingQuestion(
        event_id="q-1",
        question="기본 경로는?",
        options=("dashboard", "home"),
        recommended="",
        blocking=True,
    )
    result = prompt_from_stage_result(
        pending_question=pq,
        input_fn=lambda _: "custom_path",
    )
    assert result == TerminalResponse(text="custom_path", kind="answer")


def test_question_eof_returns_none():
    pq = PendingQuestion(
        event_id="q-1",
        question="기본 경로는?",
        options=(),
        recommended="",
        blocking=True,
    )
    result = prompt_from_stage_result(
        pending_question=pq,
        input_fn=_raise_eof,
    )
    assert result is None


def test_question_keyboard_interrupt_returns_none():
    pq = PendingQuestion(
        event_id="q-1",
        question="기본 경로는?",
        options=(),
        recommended="",
        blocking=True,
    )
    result = prompt_from_stage_result(
        pending_question=pq,
        input_fn=_raise_keyboard_interrupt,
    )
    assert result is None


# ---------------------------------------------------------------------------
# prompt_from_stage_result — approval
# ---------------------------------------------------------------------------


def test_approval_yes():
    pa = PendingApproval(event_id="a-1", subject="scope signoff", blocking=True)
    result = prompt_from_stage_result(
        pending_approval=pa,
        input_fn=lambda _: "y",
    )
    assert result == TerminalResponse(text="approved", kind="approval")


def test_approval_no():
    pa = PendingApproval(event_id="a-1", subject="scope signoff", blocking=True)
    result = prompt_from_stage_result(
        pending_approval=pa,
        input_fn=lambda _: "no",
    )
    assert result == TerminalResponse(text="rejected", kind="approval")


def test_approval_eof_returns_none():
    pa = PendingApproval(event_id="a-1", subject="scope signoff", blocking=True)
    result = prompt_from_stage_result(
        pending_approval=pa,
        input_fn=_raise_eof,
    )
    assert result is None


# ---------------------------------------------------------------------------
# prompt_for_pending_response — file-based (crash recovery path)
# ---------------------------------------------------------------------------


def test_file_based_question_prompt(tmp_path: Path):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
        metadata={
            "pending_event_id": "q-1",
            "pending_question": {
                "event_id": "q-1",
                "question": "기본 경로는?",
                "options": ["dashboard", "home"],
                "recommended": "dashboard",
                "blocking": True,
            },
        },
    )
    result = prompt_for_pending_response(tmp_path, input_fn=lambda _: "")
    assert result == TerminalResponse(text="dashboard", kind="answer")


def test_file_based_approval_prompt(tmp_path: Path):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
        metadata={
            "pending_event_id": "a-1",
            "pending_approval": {
                "event_id": "a-1",
                "subject": "scope signoff",
                "blocking": True,
            },
        },
    )
    result = prompt_for_pending_response(tmp_path, input_fn=lambda _: "yes")
    assert result == TerminalResponse(text="approved", kind="approval")


def test_file_based_returns_none_for_non_waiting_state(tmp_path: Path):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.RUNNING_EXEC.value,
        metadata={},
    )
    result = prompt_for_pending_response(tmp_path, input_fn=lambda _: "oops")
    assert result is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_eof(_prompt: str) -> str:
    raise EOFError


def _raise_keyboard_interrupt(_prompt: str) -> str:
    raise KeyboardInterrupt
