"""Tests for codex_runner — subprocess-based command execution with NDJSON parsing."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from cowork_pilot.codex.codex_runner import create_subprocess_runner


class TestCreateSubprocessRunner:
    """Tests for create_subprocess_runner() and the returned CommandRunner."""

    def test_subprocess_runner_parses_ndjson_stdout(self):
        """Basic NDJSON with thread.started + agent_message."""
        ndjson_output = (
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}) + "\n"
            + json.dumps({"type": "turn.started"}) + "\n"
            + json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Task completed successfully"}
            }) + "\n"
        )

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=ndjson_output,
                stderr=""
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test", "command"])

            assert len(event_lines) == 3
            assert assistant_message == "Task completed successfully"
            assert exit_code == 0

    def test_subprocess_runner_returns_exit_code_on_failure(self):
        """Non-zero exit code is propagated."""
        ndjson_output = json.dumps({"type": "thread.started", "thread_id": "thread-456"}) + "\n"

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout=ndjson_output,
                stderr="Error occurred"
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test"])

            assert exit_code == 1
            assert len(event_lines) == 1

    def test_subprocess_runner_handles_timeout(self):
        """subprocess.TimeoutExpired returns exit_code=1 and empty assistant_message."""
        partial_output = json.dumps({"type": "thread.started", "thread_id": "thread-timeout"}) + "\n"

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            timeout_exc = subprocess.TimeoutExpired(cmd=["codex"], timeout=30)
            timeout_exc.stdout = partial_output
            timeout_exc.stderr = None
            mock_run.side_effect = timeout_exc

            runner = create_subprocess_runner(timeout=30)
            event_lines, assistant_message, exit_code = runner(["codex", "slow"])

            assert exit_code == 1
            assert assistant_message == ""
            assert len(event_lines) == 1  # partial output is preserved

    def test_subprocess_runner_handles_command_not_found(self):
        """FileNotFoundError returns exit_code=127, empty lists."""
        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("codex command not found")

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["nonexistent-codex"])

            assert exit_code == 127
            assert event_lines == []
            assert assistant_message == ""

    def test_subprocess_runner_logs_stderr(self, caplog):
        """stderr text appears in caplog at WARNING level."""
        ndjson_output = json.dumps({"type": "thread.started", "thread_id": "thread-789"}) + "\n"
        stderr_text = "warning line 1\nwarning line 2"

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=ndjson_output,
                stderr=stderr_text
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test"])

            # Check that stderr was logged at WARNING level
            assert any("codex stderr" in record.message for record in caplog.records)
            assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_subprocess_runner_handles_empty_stdout(self):
        """Empty stdout returns empty event_lines and empty assistant_message."""
        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "empty"])

            assert event_lines == []
            assert assistant_message == ""
            assert exit_code == 0

    def test_subprocess_runner_passes_timeout_to_run(self):
        """timeout parameter is passed to subprocess.run."""
        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            runner = create_subprocess_runner(timeout=60)
            runner(["codex", "test"])

            # Verify timeout was passed
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["timeout"] == 60

    def test_subprocess_runner_passes_env_to_run(self):
        """env parameter is passed to subprocess.run."""
        custom_env = {"CUSTOM_VAR": "value", "PATH": "/custom/path"}

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            runner = create_subprocess_runner(env=custom_env)
            runner(["codex", "test"])

            # Verify env was passed
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"] == custom_env

    def test_subprocess_runner_uses_capture_output_and_text(self):
        """subprocess.run is called with capture_output=True and text=True."""
        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            runner = create_subprocess_runner()
            runner(["codex", "test"])

            # Verify subprocess.run was called with correct flags
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["capture_output"] is True
            assert call_kwargs["text"] is True

    def test_subprocess_runner_extracts_multiple_assistant_messages(self):
        """Last completed agent_message is extracted when multiple exist."""
        ndjson_output = (
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "First message"}
            }) + "\n"
            + json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Second message"}
            }) + "\n"
            + json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Final message"}
            }) + "\n"
        )

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=ndjson_output,
                stderr=""
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test"])

            # Should get the last one
            assert assistant_message == "Final message"
            assert len(event_lines) == 3

    def test_subprocess_runner_ignores_incomplete_agent_messages(self):
        """Only completed agent_messages are considered."""
        ndjson_output = (
            json.dumps({
                "type": "item.started",
                "item": {"type": "agent_message", "text": "In progress"}
            }) + "\n"
            + json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Completed"}
            }) + "\n"
        )

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=ndjson_output,
                stderr=""
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test"])

            # Should only get the completed one
            assert assistant_message == "Completed"

    def test_subprocess_runner_filters_empty_lines(self):
        """Empty lines in stdout are filtered out."""
        ndjson_output = (
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}) + "\n"
            + "\n"  # Empty line
            + json.dumps({"type": "turn.started"}) + "\n"
            + "  \n"  # Whitespace-only line
            + json.dumps({"type": "turn.completed"}) + "\n"
        )

        with patch("cowork_pilot.codex.codex_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=ndjson_output,
                stderr=""
            )

            runner = create_subprocess_runner()
            event_lines, assistant_message, exit_code = runner(["codex", "test"])

            # Should only have 3 non-empty lines
            assert len(event_lines) == 3
