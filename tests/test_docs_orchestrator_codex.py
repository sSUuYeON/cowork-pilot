"""Unit tests for docs_orchestrator_codex.py.

All subprocess calls are mocked via command_runner injection.
No real codex binary is invoked.

Spec §14.2 test coverage map:
  #1 run_codex_step() success         → test_run_codex_step_completed
  #2 run_codex_step() waiting         → test_run_codex_step_waiting_on_input_required
  #3 resume_codex_step() complete     → test_resume_codex_step_completed
  #4 resume_codex_step() re-wait      → test_resume_codex_step_re_waits
  #5 stale runtime cleanup            → tests/test_docs_orchestrator_runtime.py::test_cleanup_stale_*
  #6 inconsistent runtime             → tests/test_docs_orchestrator_runtime.py::test_cleanup_stale_raises_on_step_mismatch
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.docs_orchestrator_codex import (
    CodexStepResult,
    resume_codex_step,
    run_codex_step,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "marker_protocol"


# ── helpers ──────────────────────────────────────────────────────────

_STAGE_COMPLETE_MARKER = (
    "<COWORK_PILOT_EVENT>\n"
    "type: STAGE_COMPLETE\n"
    "stage: phase_2:pay:refund\n"
    "event_id: phase_2_pay_refund_done\n"
    "reason: done\n"
    "summary: ok\n"
    "outputs:\n"
    "  - docs/generated/gap-reports/pay_refund.md\n"
    "</COWORK_PILOT_EVENT>"
)

_INPUT_REQUIRED_MARKER = (
    "<COWORK_PILOT_EVENT>\n"
    "type: INPUT_REQUIRED\n"
    "stage: phase_2:pay:refund\n"
    "event_id: phase_2_pay_refund_q1\n"
    "reason: need info\n"
    "question: Who approves?\n"
    "options:\n"
    "  - admin\n"
    "  - auto\n"
    "recommended: admin\n"
    "blocking: true\n"
    "</COWORK_PILOT_EVENT>"
)


def _make_runner(event_lines: list[str], assistant_message: str, exit_code: int = 0):
    """Return a fake command_runner that ignores args and returns fixed values."""
    def runner(cmd: list[str]) -> tuple[list[str], str, int]:
        return (event_lines, assistant_message, exit_code)
    return runner


def _thread_id_line(thread_id: str = "tid-001") -> str:
    return json.dumps({"type": "thread.started", "thread_id": thread_id})


def _fixture(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


# ── CodexStepResult ──────────────────────────────────────────────────

def test_codex_step_result_is_dataclass():
    r = CodexStepResult(
        status="completed",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-001",
        waiting_kind=None,
        pending_event_id=None,
        pending_question=None,
        pending_approval=None,
        error="",
    )
    assert r.status == "completed"


# ── run_codex_step: completed path ───────────────────────────────────

def test_run_codex_step_completed(tmp_path):
    """STAGE_COMPLETE + exit 0 + expected file exists → completed."""
    # Create expected output file
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-abc")],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )

    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[out_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )

    assert result.status == "completed"
    assert result.resume_handle == "tid-abc"
    assert result.error == ""


def test_run_codex_step_completed_with_repeated_assumption_logs(tmp_path):
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    assistant_message = (
        "<COWORK_PILOT_EVENT>\n"
        "type: ASSUMPTION_LOG\n"
        "stage: phase_2:pay:refund\n"
        "event_id: phase_2_pay_refund_assumption_1\n"
        "reason: continue\n"
        "assumption: refund requests default to admin review\n"
        "confidence: medium\n"
        "impact: low\n"
        "</COWORK_PILOT_EVENT>\n"
        "<COWORK_PILOT_EVENT>\n"
        "type: ASSUMPTION_LOG\n"
        "stage: phase_2:pay:refund\n"
        "event_id: phase_2_pay_refund_assumption_2\n"
        "reason: continue\n"
        "assumption: manual refund notes live in the same report\n"
        "confidence: low\n"
        "impact: medium\n"
        "</COWORK_PILOT_EVENT>\n"
        "<COWORK_PILOT_EVENT>\n"
        "type: STAGE_COMPLETE\n"
        "stage: phase_2:pay:refund\n"
        "event_id: phase_2_pay_refund_done\n"
        "reason: done\n"
        "summary: ok\n"
        "outputs:\n"
        "  - docs/generated/gap-reports/pay_refund.md\n"
        "</COWORK_PILOT_EVENT>"
    )

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-multi-assumption")],
        assistant_message=assistant_message,
        exit_code=0,
    )

    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[out_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )

    assert result.status == "completed"
    assert result.resume_handle == "tid-multi-assumption"
    assert result.error == ""


# ── run_codex_step: waiting path ─────────────────────────────────────

def test_run_codex_step_waiting_on_input_required(tmp_path):
    """blocking INPUT_REQUIRED → waiting, even without STAGE_COMPLETE."""
    runner = _make_runner(
        event_lines=[_thread_id_line("tid-xyz")],
        assistant_message=_INPUT_REQUIRED_MARKER,
        exit_code=0,
    )

    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )

    assert result.status == "waiting"
    assert result.waiting_kind == "input"
    assert result.pending_event_id == "phase_2_pay_refund_q1"
    assert result.resume_handle == "tid-xyz"


# ── run_codex_step: failed paths ─────────────────────────────────────

def test_run_codex_step_failed_on_nonzero_exit(tmp_path):
    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message="",
        exit_code=1,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert result.exit_code == 1


def test_run_codex_step_failed_when_no_stage_complete(tmp_path):
    """No STAGE_COMPLETE and no waiting marker → failed."""
    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message="I did some stuff but forgot the marker",
        exit_code=0,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "STAGE_COMPLETE" in result.error


def test_run_codex_step_failed_when_expected_file_missing(tmp_path):
    """STAGE_COMPLETE present but expected file absent → failed."""
    missing_file = tmp_path / "docs" / "generated" / "gap-reports" / "missing.md"

    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[missing_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "missing" in result.error.lower() or "expected" in result.error.lower()


def test_run_codex_step_failed_when_done_marker_missing(tmp_path):
    """STAGE_COMPLETE present but output lacks done marker → failed."""
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content only", encoding="utf-8")

    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[out_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "ORCHESTRATOR:DONE" in result.error


def test_run_codex_step_salvages_valid_stage_complete_after_invalid_assumption(tmp_path, caplog):
    out_file = tmp_path / "docs" / "generated" / "analysis-report.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-salvage")],
        assistant_message=_fixture("malformed_assumption_then_stage_complete.txt"),
        exit_code=0,
    )

    with caplog.at_level("WARNING"):
        result = run_codex_step(
            project_dir=tmp_path,
            step="phase_1",
            prompt="do the thing",
            expected_files=[out_file],
            codex_command="codex",
            codex_extra_args=None,
            command_runner=runner,
        )

    assert result.status == "completed"
    assert any(
        "marker bundle salvage" in record.message
        and "STAGE_COMPLETE" in record.message
        and "ASSUMPTION_LOG" in record.message
        for record in caplog.records
    )


# ── resume_codex_step ────────────────────────────────────────────────


def test_resume_codex_step_completed(tmp_path):
    """resume that gets STAGE_COMPLETE → completed."""
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    runtime_payload = {
        "backend": "codex",
        "step": "phase_2:pay:refund",
        "runtime_state": "waiting_for_input",
        "resume_handle": "tid-resume-001",
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": "phase_2_pay_refund_q1",
    }

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-resume-001")],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )

    result = resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="관리자가 수동 승인한다",
        response_kind="answer",
        runtime_payload=runtime_payload,
        expected_files=[out_file],
        codex_command="codex",
        command_runner=runner,
    )
    assert result.status == "completed"


def test_resume_codex_step_re_waits(tmp_path):
    """resume that gets another INPUT_REQUIRED → waiting again."""
    runtime_payload = {
        "resume_handle": "tid-resume-002",
        "pending_event_id": "phase_2_pay_refund_q1",
    }
    runner = _make_runner(
        event_lines=[_thread_id_line("tid-resume-002")],
        assistant_message=_INPUT_REQUIRED_MARKER,
        exit_code=0,
    )
    result = resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="some answer",
        response_kind="answer",
        runtime_payload=runtime_payload,
        expected_files=[],
        codex_command="codex",
        command_runner=runner,
    )
    assert result.status == "waiting"
    assert result.waiting_kind == "input"


def test_resume_codex_step_failed_when_expected_files_are_empty(tmp_path):
    """resume must not accept STAGE_COMPLETE without expected-file verification."""
    runtime_payload = {
        "resume_handle": "tid-resume-003",
        "pending_event_id": "phase_2_pay_refund_q1",
    }
    runner = _make_runner(
        event_lines=[_thread_id_line("tid-resume-003")],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )
    result = resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="관리자가 수동 승인한다",
        response_kind="answer",
        runtime_payload=runtime_payload,
        expected_files=[],
        codex_command="codex",
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "could not be determined" in result.error


def test_resume_codex_step_continuation_prompt_format(tmp_path, monkeypatch):
    """continuation prompt must include step, pending_event_id, resolution kind."""
    captured_prompts: list[str] = []

    def capturing_runner(cmd: list[str]) -> tuple[list[str], str, int]:
        # prompt is the last element of codex exec resume argv
        captured_prompts.append(cmd[-1])
        return ([_thread_id_line()], _STAGE_COMPLETE_MARKER, 0)

    runtime_payload = {
        "resume_handle": "tid-003",
        "pending_event_id": "phase_2_pay_refund_q1",
    }
    resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="auto",
        response_kind="approval",
        runtime_payload=runtime_payload,
        expected_files=[],
        codex_command="codex",
        command_runner=capturing_runner,
    )
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "phase_2:pay:refund" in prompt
    assert "phase_2_pay_refund_q1" in prompt
    assert "Resolution kind: approval" in prompt
    assert "auto" in prompt
