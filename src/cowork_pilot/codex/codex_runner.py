from __future__ import annotations

import logging
import subprocess
from typing import Callable

from cowork_pilot.codex.event_stream import extract_terminal_assistant_message

logger = logging.getLogger(__name__)

CommandRunner = Callable[[list[str]], tuple[list[str], str, int]]


def create_subprocess_runner(
    *,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> CommandRunner:
    """Return a CommandRunner that executes commands via subprocess.run().

    The runner expects the command to produce NDJSON on stdout (codex --json mode).
    It parses each line as an event, extracts the terminal assistant message,
    and returns (event_lines, assistant_message, exit_code).

    The prompt (last element of the command list) is passed via stdin using
    the ``-`` sentinel instead of as a CLI argument, because multiline prompts
    can cause the codex arg parser to hang when passed as argv.
    """

    def _run(command: list[str]) -> tuple[list[str], str, int]:
        # Separate the prompt from the rest of the command.
        # The prompt is always the last element; replace it with "-" so codex
        # reads from stdin instead.
        prompt = command[-1]
        cmd_with_stdin = command[:-1] + ["-"]

        logger.info("codex runner: %s", " ".join(cmd_with_stdin[:6]) + " ...")
        try:
            result = subprocess.run(
                cmd_with_stdin,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error("codex runner timed out after %s seconds", timeout)
            partial_stdout = exc.stdout or ""
            partial_lines = _parse_ndjson_lines(partial_stdout if isinstance(partial_stdout, str) else "")
            return (partial_lines, "", 1)
        except FileNotFoundError:
            logger.error("codex command not found: %s", command[0])
            return ([], "", 127)

        if result.stderr:
            for line in result.stderr.strip().splitlines():
                logger.warning("codex stderr: %s", line)

        event_lines = _parse_ndjson_lines(result.stdout)
        assistant_message = extract_terminal_assistant_message(event_lines)
        return (event_lines, assistant_message, result.returncode)

    return _run


def _parse_ndjson_lines(raw: str) -> list[str]:
    """Split raw stdout into non-empty lines."""
    return [line for line in raw.splitlines() if line.strip()]
