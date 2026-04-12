from __future__ import annotations

from unittest.mock import MagicMock, patch

from cowork_pilot.codex.command_builder import (
    build_cli_resume_command,
    build_exec_command,
    build_exec_resume_command,
)
from cowork_pilot.codex.event_stream import (
    extract_terminal_assistant_message,
    extract_thread_id,
)
from cowork_pilot.planning.codex_bridge import (
    ExecStageResult,
    ResumeStageResult,
    run_cli_resume,
    run_exec_resume,
    run_exec_stage,
)


def test_extract_thread_id_reads_thread_started_event() -> None:
    lines = [
        '{"type":"thread.started","thread_id":"thread-123"}',
        '{"type":"turn.completed"}',
    ]

    assert extract_thread_id(lines) == "thread-123"


def test_extract_thread_id_falls_back_to_session_meta_id() -> None:
    lines = [
        '{"type":"session_meta","payload":{"id":"session-123"}}',
        '{"type":"turn.completed"}',
    ]

    assert extract_thread_id(lines) == "session-123"


def test_extract_terminal_assistant_message_returns_last_completed_message() -> None:
    lines = [
        '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
        '{"type":"item.started","item":{"type":"agent_message","text":"ignored"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"last"}}',
    ]

    assert extract_terminal_assistant_message(lines) == "last"


def test_extract_terminal_assistant_message_reads_response_item_assistant_message() -> None:
    lines = [
        (
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text",'
            '"text":"ignored"}]}}'
        ),
        (
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":'
            '[{"type":"output_text","text":"final-from-response-item"}]}}'
        ),
    ]

    assert extract_terminal_assistant_message(lines) == "final-from-response-item"


def test_extract_terminal_assistant_message_prefers_task_complete_message() -> None:
    lines = [
        (
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":'
            '[{"type":"output_text","text":"mid"}]}}'
        ),
        '{"type":"event_msg","payload":{"type":"agent_message","message":"almost-final"}}',
        (
            '{"type":"event_msg","payload":{"type":"task_complete",'
            '"last_agent_message":"final-from-task-complete"}}'
        ),
    ]

    assert extract_terminal_assistant_message(lines) == "final-from-task-complete"


def test_build_exec_command_matches_harness_contract_exactly() -> None:
    cmd = build_exec_command(
        "hello world",
        "/tmp/project",
        codex_command="/usr/local/bin/codex",
        codex_extra_args=["--json"],
    )

    assert cmd == [
        "/usr/local/bin/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-C",
        "/tmp/project",
        "--json",
        "hello world",
    ]


def test_build_cli_resume_command_includes_project_dir_and_handle() -> None:
    cmd = build_cli_resume_command(
        "thread-123",
        "/tmp/project",
    )

    assert cmd == [
        "codex",
        "resume",
        "--include-non-interactive",
        "-C",
        "/tmp/project",
        "thread-123",
    ]


def test_build_exec_resume_command_uses_exec_resume_json_shape() -> None:
    cmd = build_exec_resume_command(
        "thread-123",
        "continue the work",
    )

    assert cmd == [
        "codex",
        "exec",
        "resume",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--json",
        "thread-123",
        "continue the work",
    ]


def test_run_exec_stage_accepts_stage_prompt_and_run_dir_keyword_api() -> None:
    seen_commands: list[list[str]] = []

    def command_runner(command: list[str]) -> tuple[list[str], str, int]:
        seen_commands.append(command)
        return (['{"type":"thread.started","thread_id":"thread-123"}'], "done", 0)

    result = run_exec_stage(
        stage="classification",
        prompt="do the work",
        run_dir="/tmp/run",
        command_runner=command_runner,
    )

    assert seen_commands == [[
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-C",
        "/tmp/run",
        "--json",
        "do the work",
    ]]
    assert result == ExecStageResult(
        event_lines=['{"type":"thread.started","thread_id":"thread-123"}'],
        assistant_message="done",
        exit_code=0,
    )


def test_run_exec_stage_without_explicit_runner_delegates_to_default() -> None:
    mock_runner = MagicMock(return_value=([], "default-response", 0))
    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_exec_stage(stage="classification", prompt="do the work", run_dir="/tmp/run")
    mock_runner.assert_called_once()
    assert result.assistant_message == "default-response"


def test_run_cli_resume_accepts_run_dir_in_api() -> None:
    seen_commands: list[list[str]] = []

    def command_runner(command: list[str]) -> tuple[list[str], str, int]:
        seen_commands.append(command)
        return ([], "", 0)

    result = run_cli_resume(
        resume_handle="thread-123",
        run_dir="/tmp/run",
        project_dir="/tmp/project",
        command_runner=command_runner,
    )

    assert seen_commands == [[
        "codex",
        "resume",
        "--include-non-interactive",
        "-C",
        "/tmp/project",
        "thread-123",
    ]]
    assert result == ResumeStageResult(event_lines=[], assistant_message="", exit_code=0)


def test_run_cli_resume_without_explicit_runner_delegates_to_default() -> None:
    mock_runner = MagicMock(return_value=([], "default-response", 0))
    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_cli_resume(resume_handle="thread-123", run_dir="/tmp/run", project_dir="/tmp/project")
    mock_runner.assert_called_once()
    assert result.assistant_message == "default-response"


def test_run_exec_resume_returns_exec_stage_result_and_accepts_run_dir() -> None:
    seen_commands: list[list[str]] = []

    def command_runner(command: list[str]) -> tuple[list[str], str, int]:
        seen_commands.append(command)
        return (['{"type":"item.completed"}'], "continued", 0)

    result = run_exec_resume(
        resume_handle="thread-123",
        prompt="continue the work",
        run_dir="/tmp/run",
        command_runner=command_runner,
    )

    assert seen_commands == [[
        "codex",
        "exec",
        "resume",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--json",
        "thread-123",
        "continue the work",
    ]]
    assert result == ExecStageResult(
        event_lines=['{"type":"item.completed"}'],
        assistant_message="continued",
        exit_code=0,
    )


def test_run_exec_resume_without_explicit_runner_delegates_to_default() -> None:
    mock_runner = MagicMock(return_value=([], "default-response", 0))
    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_exec_resume(resume_handle="thread-123", prompt="continue the work", run_dir="/tmp/run")
    mock_runner.assert_called_once()
    assert result.assistant_message == "default-response"


def test_run_exec_stage_uses_default_subprocess_runner_when_no_runner_provided() -> None:
    mock_runner = MagicMock(return_value=(['{"type":"thread.started","thread_id":"t-1"}'], "done", 0))
    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_exec_stage(stage="classification", prompt="do the work", run_dir="/tmp/run")
    mock_runner.assert_called_once()
    assert result.assistant_message == "done"
    assert result.exit_code == 0
