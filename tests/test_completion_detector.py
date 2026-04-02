"""Tests for completion_detector — idle detection + CLI verification."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cowork_pilot.completion_detector import (
    is_idle_trigger,
    build_verification_prompt,
    call_verification_cli,
    parse_verification_result,
    build_feedback_text,
    send_feedback,
    run_local_build,
    run_build_criteria,
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

    def test_last_prompt_record_triggers(self):
        """'last-prompt' is a bookkeeping record appended after the assistant's
        final turn — treat it as a session-end signal (safety net)."""
        record = {"type": "last-prompt", "message": {"content": ""}}
        assert is_idle_trigger(record, 0.0, 200.0, idle_timeout_seconds=120.0) is True

    def test_last_prompt_not_enough_time(self):
        record = {"type": "last-prompt"}
        assert is_idle_trigger(record, 100.0, 150.0, idle_timeout_seconds=120.0) is False

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


# ── Local build execution ────────────────────────────────────────────

class TestRunLocalBuild:
    """Tests for run_local_build()."""

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        success, stdout, stderr = run_local_build("npm run build", "/tmp/project")
        assert success is True
        assert stdout == "OK\n"
        mock_run.assert_called_once_with(
            "npm run build",
            shell=True,
            cwd="/tmp/project",
            capture_output=True,
            text=True,
            timeout=600.0,
        )

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_failure_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: lint failed")
        success, stdout, stderr = run_local_build("npm run lint", "/tmp/project")
        assert success is False
        assert "lint failed" in stderr

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="build", timeout=600)
        success, stdout, stderr = run_local_build("cargo build", "/tmp/project", timeout=600.0)
        assert success is False
        assert "timed out" in stderr.lower()

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_os_error(self, mock_run):
        mock_run.side_effect = OSError("No such command")
        success, stdout, stderr = run_local_build("nonexistent", "/tmp/project")
        assert success is False
        assert "No such command" in stderr


class TestRunBuildCriteria:
    """Tests for run_build_criteria()."""

    def _make_chunk(self, criteria):
        return Chunk(
            name="Test", number=1,
            completion_criteria=criteria,
            session_prompt="test",
        )

    @patch("cowork_pilot.completion_detector.run_local_build")
    def test_no_build_criteria_returns_passed(self, mock_build):
        """[BUILD] 태그 없으면 즉시 PASSED."""
        chunk = self._make_chunk([
            CompletionCriterion("파일 존재", False),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        mock_build.assert_not_called()

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_all_builds_pass(self, mock_update, mock_build):
        """모든 [BUILD] 성공 시 PASSED + 체크박스 업데이트."""
        mock_build.return_value = (True, "OK", "")
        chunk = self._make_chunk([
            CompletionCriterion("파일 존재", False),
            CompletionCriterion("npm run lint", False, build_command="npm run lint"),
            CompletionCriterion("npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        assert mock_build.call_count == 2
        assert mock_update.call_count == 2

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_first_build_fails_stops_early(self, mock_update, mock_build):
        """첫 빌드 실패 시 즉시 FAILED 반환."""
        mock_build.return_value = (False, "", "Error: lint failed")
        chunk = self._make_chunk([
            CompletionCriterion("npm run lint", False, build_command="npm run lint"),
            CompletionCriterion("npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "FAILED"
        assert "npm run lint" in detail
        mock_build.assert_called_once()
        mock_update.assert_not_called()

    @patch("cowork_pilot.completion_detector.run_local_build")
    def test_checked_build_skipped(self, mock_build):
        """이미 [x]인 [BUILD] 항목은 스킵."""
        chunk = self._make_chunk([
            CompletionCriterion("npm run lint", True, build_command="npm run lint"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        mock_build.assert_not_called()

    def test_invalid_project_dir(self):
        """project_dir이 유효하지 않으면 FAILED."""
        chunk = self._make_chunk([
            CompletionCriterion("npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "", Path("/tmp/plan.md"))
        assert status == "FAILED"
        assert "project_dir" in detail

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_stderr_truncated_to_2000(self, mock_update, mock_build):
        """에러 로그가 2000자로 잘린다."""
        long_err = "x" * 5000
        mock_build.return_value = (False, "", long_err)
        chunk = self._make_chunk([
            CompletionCriterion("cargo build", False, build_command="cargo build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "FAILED"
        assert len(detail) < 2200
