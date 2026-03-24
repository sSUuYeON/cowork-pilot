"""Tests for completion_detector — idle detection + CLI verification."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from cowork_pilot.completion_detector import (
    is_idle_trigger,
    build_verification_prompt,
    call_verification_cli,
    parse_verification_result,
    build_feedback_text,
    send_feedback,
)
from cowork_pilot.plan_parser import Chunk, CompletionCriterion


# ── Idle detection ───────────────────────────────────────────────────

class TestIsIdleTrigger:
    """Tests for is_idle_trigger()."""

    def test_none_record_returns_false(self):
        assert is_idle_trigger(None, 0.0, 200.0) is False

    def test_not_enough_time_returns_false(self):
        record = {"type": "summary"}
        assert is_idle_trigger(record, 100.0, 150.0, idle_timeout_seconds=120.0) is False

    def test_summary_record_triggers(self):
        record = {"type": "summary"}
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is True

    def test_assistant_end_turn_no_tool_use_triggers(self):
        record = {
            "type": "assistant",
            "message": {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Done!"}],
            },
        }
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is True

    def test_assistant_end_turn_with_tool_use_does_not_trigger(self):
        record = {
            "type": "assistant",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": "Running..."},
                    {"type": "tool_use", "id": "tu_1", "name": "Bash"},
                ],
            },
        }
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is False

    def test_assistant_not_end_turn_does_not_trigger(self):
        record = {
            "type": "assistant",
            "message": {
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": "..."}],
            },
        }
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is False

    def test_user_record_does_not_trigger(self):
        record = {"type": "user"}
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is False

    def test_custom_timeout(self):
        record = {"type": "summary"}
        # 50 seconds elapsed, timeout=30 → should trigger
        assert is_idle_trigger(record, 0.0, 50.0, idle_timeout_seconds=30.0) is True
        # 50 seconds elapsed, timeout=60 → should not trigger
        assert is_idle_trigger(record, 0.0, 50.0, idle_timeout_seconds=60.0) is False


# ── Verification prompt builder ──────────────────────────────────────

class TestBuildVerificationPrompt:
    def test_contains_criteria(self):
        chunk = Chunk(
            name="Foundation",
            number=1,
            completion_criteria=[
                CompletionCriterion("pytest tests/test_models.py 통과", False),
                CompletionCriterion("src/models.py 파일 존재", True),
            ],
        )
        prompt = build_verification_prompt(chunk)
        assert "Chunk 1" in prompt
        assert "pytest tests/test_models.py 통과" in prompt
        assert "src/models.py 파일 존재" in prompt
        assert "COMPLETED" in prompt
        assert "INCOMPLETE" in prompt


# ── CLI call ─────────────────────────────────────────────────────────

class TestCallVerificationCli:
    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="COMPLETED\n")
        result = call_verification_cli("test prompt", "/tmp")
        assert result == "COMPLETED"

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = call_verification_cli("test prompt", "/tmp")
        assert result is None

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=120)
        result = call_verification_cli("test prompt", "/tmp")
        assert result is None

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_os_error_returns_none(self, mock_run):
        mock_run.side_effect = OSError("No such file")
        result = call_verification_cli("test prompt", "/tmp")
        assert result is None


# ── Result parsing ───────────────────────────────────────────────────

class TestParseVerificationResult:
    def test_completed(self):
        status, detail = parse_verification_result("All checks passed. COMPLETED")
        assert status == "COMPLETED"
        assert detail == ""

    def test_incomplete(self):
        status, detail = parse_verification_result(
            "INCOMPLETE: pytest tests/test_models.py failed"
        )
        assert status == "INCOMPLETE"
        assert "pytest" in detail

    def test_incomplete_without_colon(self):
        status, detail = parse_verification_result("INCOMPLETE tests still failing")
        assert status == "INCOMPLETE"

    def test_none_input(self):
        status, detail = parse_verification_result(None)
        assert status == "ERROR"

    def test_unparseable(self):
        status, detail = parse_verification_result("some random output")
        assert status == "ERROR"

    def test_completed_case_insensitive(self):
        status, _ = parse_verification_result("completed")
        assert status == "COMPLETED"


# ── Feedback ─────────────────────────────────────────────────────────

class TestBuildFeedbackText:
    def test_contains_detail(self):
        text = build_feedback_text("pytest tests/test_X.py 실패")
        assert "미완료" in text
        assert "pytest tests/test_X.py 실패" in text
        assert "마저 진행해" in text


class TestSendFeedback:
    @patch("cowork_pilot.responder.execute_applescript", return_value=True)
    @patch("cowork_pilot.responder.set_clipboard", return_value=True)
    @patch("cowork_pilot.session_opener.build_type_prompt_script", return_value="script")
    def test_success(self, mock_script, mock_clip, mock_exec):
        assert send_feedback("test feedback") is True

    @patch("cowork_pilot.responder.execute_applescript", return_value=True)
    @patch("cowork_pilot.responder.set_clipboard", return_value=False)
    @patch("cowork_pilot.session_opener.build_type_prompt_script", return_value="script")
    def test_clipboard_failure(self, mock_script, mock_clip, mock_exec):
        assert send_feedback("test feedback") is False
