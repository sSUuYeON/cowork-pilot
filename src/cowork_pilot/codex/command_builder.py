from __future__ import annotations


def _exec_policy_args() -> list[str]:
    """Return the sandbox/approval flags required for non-interactive exec flows."""
    return [
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ]


def build_exec_command(
    prompt: str,
    project_dir: str,
    *,
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
) -> list[str]:
    """Build the subprocess argv for ``codex exec``."""
    cmd = [
        codex_command,
        "exec",
        *_exec_policy_args(),
        "-C",
        project_dir,
    ]
    if codex_extra_args:
        for arg in codex_extra_args:
            if arg not in cmd:
                cmd.append(arg)
    if "--json" not in cmd:
        cmd.append("--json")

    cmd.append(prompt)
    return cmd


def build_cli_resume_command(
    resume_handle: str,
    project_dir: str,
    *,
    codex_command: str = "codex",
) -> list[str]:
    """Build the argv for resuming a Codex CLI session."""
    return [
        codex_command,
        "resume",
        "--include-non-interactive",
        "-C",
        project_dir,
        resume_handle,
    ]


def build_exec_resume_command(
    resume_handle: str,
    prompt: str,
    *,
    codex_command: str = "codex",
) -> list[str]:
    """Build the argv for resuming a non-interactive ``codex exec`` session."""
    return [
        codex_command,
        "exec",
        "resume",
        *_exec_policy_args(),
        "--json",
        resume_handle,
        prompt,
    ]
