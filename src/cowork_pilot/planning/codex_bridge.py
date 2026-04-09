from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from cowork_pilot.codex.codex_runner import create_subprocess_runner
from cowork_pilot.codex.command_builder import (
    build_cli_resume_command,
    build_exec_command,
    build_exec_resume_command,
)

CommandRunner = Callable[[list[str]], tuple[list[str], str, int]]

_default_runner: CommandRunner = create_subprocess_runner()


@dataclass(frozen=True)
class ExecStageResult:
    event_lines: list[str]
    assistant_message: str
    exit_code: int = 0


@dataclass(frozen=True)
class ResumeStageResult:
    event_lines: list[str]
    assistant_message: str
    exit_code: int = 0


def run_exec_stage(
    *,
    stage: str,
    prompt: str,
    run_dir: str,
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
    command_runner: CommandRunner | None = None,
) -> ExecStageResult:
    """Build an exec-stage command and return the normalized stage result."""
    _ = stage
    command = build_exec_command(
        prompt,
        run_dir,
        codex_command=codex_command,
        codex_extra_args=codex_extra_args,
    )
    runner = command_runner if command_runner is not None else _default_runner
    event_lines, assistant_message, exit_code = runner(command)
    return ExecStageResult(
        event_lines=event_lines,
        assistant_message=assistant_message,
        exit_code=exit_code,
    )


def run_cli_resume(
    *,
    resume_handle: str,
    run_dir: str,
    project_dir: str,
    codex_command: str = "codex",
    command_runner: CommandRunner | None = None,
) -> ResumeStageResult:
    """Build a CLI resume command and return the normalized stage result."""
    _ = run_dir
    command = build_cli_resume_command(
        resume_handle,
        project_dir,
        codex_command=codex_command,
    )
    runner = command_runner if command_runner is not None else _default_runner
    event_lines, assistant_message, exit_code = runner(command)
    return ResumeStageResult(
        event_lines=event_lines,
        assistant_message=assistant_message,
        exit_code=exit_code,
    )


def run_exec_resume(
    *,
    resume_handle: str,
    prompt: str,
    run_dir: str,
    codex_command: str = "codex",
    command_runner: CommandRunner | None = None,
) -> ExecStageResult:
    """Build an exec resume command and return the normalized stage result."""
    _ = run_dir
    command = build_exec_resume_command(
        resume_handle,
        prompt,
        codex_command=codex_command,
    )
    runner = command_runner if command_runner is not None else _default_runner
    event_lines, assistant_message, exit_code = runner(command)
    return ExecStageResult(
        event_lines=event_lines,
        assistant_message=assistant_message,
        exit_code=exit_code,
    )
