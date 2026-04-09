# Codex Bridge Production Runner Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a real `subprocess.run()`-based command runner into `codex_bridge.py` so AI planning stages actually execute codex subprocess calls instead of returning empty placeholders.

**Architecture:** Create a `subprocess_command_runner()` factory in a new `codex_runner.py` module. Replace the `if command_runner is None: return placeholder` pattern in all three bridge functions with a call to this default runner. Existing test injection via `command_runner=` parameter remains unchanged.

**Tech Stack:** Python stdlib `subprocess`, existing `event_stream.py` parser, existing `command_builder.py`

---

## Critical Design Decisions

1. **New module, not inline**: The subprocess runner lives in `src/cowork_pilot/codex/codex_runner.py`, not inside `codex_bridge.py`. This keeps the bridge as pure command-construction + dispatch, and the runner as I/O concern.
2. **Factory function**: `create_subprocess_runner(*, timeout: int | None = None, env: dict | None = None) -> CommandRunner` returns a closure. This allows future configuration (timeouts, env vars) without changing the `CommandRunner` signature.
3. **Default runner singleton**: `codex_bridge.py` uses a module-level `_default_runner` so it's only constructed once. Tests can still override via `command_runner=` parameter.
4. **NDJSON stdout parsing**: codex `--json` mode emits NDJSON on stdout. The runner reads stdout line-by-line, collects event_lines, and uses `extract_terminal_assistant_message()` to derive the assistant_message.
5. **stderr → logging**: stderr output goes to Python `logging.warning()` for diagnostics, not discarded.
6. **Backward-compatible test**: The existing `test_*_without_runner_returns_placeholder_default` tests must be UPDATED — they currently assert empty placeholder, but after this change `command_runner=None` will use the real runner. We add a new `_NO_RUNNER` sentinel for explicit "no runner" testing.

## File Structure

- **Create**: `src/cowork_pilot/codex/codex_runner.py` — subprocess runner factory + NDJSON parsing
- **Modify**: `src/cowork_pilot/planning/codex_bridge.py` — replace placeholder returns with default runner
- **Create**: `tests/test_codex_runner.py` — unit tests for the runner itself (mocked subprocess)
- **Modify**: `tests/test_planning_codex_bridge.py` — update placeholder tests to use sentinel

---

## Chunk 1: Subprocess Runner Module

### Task 1: Write failing test for subprocess runner NDJSON parsing

**Files:**
- Create: `tests/test_codex_runner.py`

- [ ] **Step 1: Write the failing test for basic NDJSON stdout parsing**

```python
from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

from cowork_pilot.codex.codex_runner import create_subprocess_runner


def _make_completed_process(
    stdout: str,
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["codex", "exec"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_subprocess_runner_parses_ndjson_stdout() -> None:
    ndjson = "\n".join([
        '{"type":"thread.started","thread_id":"t-1"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello world"}}',
    ]) + "\n"

    with patch("subprocess.run", return_value=_make_completed_process(stdout=ndjson)):
        runner = create_subprocess_runner()
        event_lines, assistant_message, exit_code = runner(["codex", "exec", "test"])

    assert len(event_lines) == 2
    assert assistant_message == "hello world"
    assert exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_codex_runner.py::test_subprocess_runner_parses_ndjson_stdout -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cowork_pilot.codex.codex_runner'`

### Task 2: Implement subprocess runner

**Files:**
- Create: `src/cowork_pilot/codex/codex_runner.py`

- [ ] **Step 3: Write the codex_runner module**

```python
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
    """

    def _run(command: list[str]) -> tuple[list[str], str, int]:
        logger.info("codex runner: %s", " ".join(command[:4]) + " ...")
        try:
            result = subprocess.run(
                command,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_codex_runner.py::test_subprocess_runner_parses_ndjson_stdout -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/codex/codex_runner.py tests/test_codex_runner.py
git commit -m "feat(codex): add subprocess-based command runner with NDJSON parsing"
```

### Task 3: Test edge cases — timeout, command not found, non-zero exit, stderr

**Files:**
- Modify: `tests/test_codex_runner.py`

- [ ] **Step 6: Add edge case tests**

```python
def test_subprocess_runner_returns_exit_code_on_failure() -> None:
    ndjson = '{"type":"thread.started","thread_id":"t-1"}\n'

    with patch("subprocess.run", return_value=_make_completed_process(stdout=ndjson, returncode=1)):
        runner = create_subprocess_runner()
        event_lines, assistant_message, exit_code = runner(["codex", "exec", "test"])

    assert exit_code == 1
    assert len(event_lines) == 1
    assert assistant_message == ""


def test_subprocess_runner_handles_timeout() -> None:
    exc = subprocess.TimeoutExpired(cmd=["codex"], timeout=30, stdout="", stderr="")

    with patch("subprocess.run", side_effect=exc):
        runner = create_subprocess_runner(timeout=30)
        event_lines, assistant_message, exit_code = runner(["codex", "exec", "test"])

    assert exit_code == 1
    assert assistant_message == ""


def test_subprocess_runner_handles_command_not_found() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        runner = create_subprocess_runner()
        event_lines, assistant_message, exit_code = runner(["codex", "exec", "test"])

    assert exit_code == 127
    assert event_lines == []


def test_subprocess_runner_logs_stderr(caplog) -> None:
    import logging

    ndjson = '{"type":"thread.started","thread_id":"t-1"}\n'
    stderr_text = "warning: something happened\n"

    with patch("subprocess.run", return_value=_make_completed_process(stdout=ndjson, stderr=stderr_text)):
        with caplog.at_level(logging.WARNING):
            runner = create_subprocess_runner()
            runner(["codex", "exec", "test"])

    assert "warning: something happened" in caplog.text


def test_subprocess_runner_handles_empty_stdout() -> None:
    with patch("subprocess.run", return_value=_make_completed_process(stdout="")):
        runner = create_subprocess_runner()
        event_lines, assistant_message, exit_code = runner(["codex", "exec", "test"])

    assert event_lines == []
    assert assistant_message == ""
    assert exit_code == 0
```

- [ ] **Step 7: Run all runner tests**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_codex_runner.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add tests/test_codex_runner.py
git commit -m "test(codex): add edge case tests for subprocess runner"
```

---

## Chunk 2: Wire Default Runner into codex_bridge

### Task 4: Write failing test that codex_bridge uses real runner by default

**Files:**
- Modify: `tests/test_planning_codex_bridge.py`

- [ ] **Step 9: Add test that default runner is called**

```python
from unittest.mock import patch, MagicMock


def test_run_exec_stage_uses_default_subprocess_runner_when_no_runner_provided() -> None:
    """When command_runner is not passed, codex_bridge should use the subprocess runner."""
    mock_runner = MagicMock(return_value=(['{"type":"thread.started","thread_id":"t-1"}'], "done", 0))

    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_exec_stage(
            stage="classification",
            prompt="do the work",
            run_dir="/tmp/run",
        )

    mock_runner.assert_called_once()
    assert result.assistant_message == "done"
    assert result.exit_code == 0
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_codex_bridge.py::test_run_exec_stage_uses_default_subprocess_runner_when_no_runner_provided -v`
Expected: FAIL (codex_bridge still returns placeholder)

### Task 5: Modify codex_bridge to use default runner

**Files:**
- Modify: `src/cowork_pilot/planning/codex_bridge.py`

- [ ] **Step 11: Update codex_bridge.py**

Replace the entire file with:

```python
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
```

- [ ] **Step 12: Run the new default-runner test**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_codex_bridge.py::test_run_exec_stage_uses_default_subprocess_runner_when_no_runner_provided -v`
Expected: PASS

### Task 6: Update existing placeholder tests

**Files:**
- Modify: `tests/test_planning_codex_bridge.py`

The three `*_without_runner_returns_placeholder_default` tests currently pass `command_runner=None` implicitly and expect empty results. After our change, `None` means "use default runner". These tests need to either:
- Mock `_default_runner` to return empty (preserving their intent of "what happens with no real codex"), OR
- Be rewritten to test the actual default-runner path.

We choose to mock, since the runner's own behavior is tested in `test_codex_runner.py`.

- [ ] **Step 13: Update the three placeholder tests**

Replace:

```python
def test_run_exec_stage_without_runner_returns_placeholder_default() -> None:
    result = run_exec_stage(
        stage="classification",
        prompt="do the work",
        run_dir="/tmp/run",
    )

    assert result == ExecStageResult(event_lines=[], assistant_message="", exit_code=0)
```

With:

```python
def test_run_exec_stage_without_explicit_runner_delegates_to_default() -> None:
    """Without explicit command_runner, the bridge delegates to _default_runner."""
    mock_runner = MagicMock(return_value=([], "default-response", 0))

    with patch("cowork_pilot.planning.codex_bridge._default_runner", mock_runner):
        result = run_exec_stage(
            stage="classification",
            prompt="do the work",
            run_dir="/tmp/run",
        )

    mock_runner.assert_called_once()
    assert result.assistant_message == "default-response"
```

Apply the same pattern to:
- `test_run_cli_resume_without_runner_returns_placeholder_default` → `test_run_cli_resume_without_explicit_runner_delegates_to_default`
- `test_run_exec_resume_without_runner_returns_placeholder_default` → `test_run_exec_resume_without_explicit_runner_delegates_to_default`

- [ ] **Step 14: Run all bridge tests**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_codex_bridge.py -v`
Expected: All PASS

- [ ] **Step 15: Run the full test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest --tb=short -q`
Expected: All PASS, no regressions

- [ ] **Step 16: Commit**

```bash
git add src/cowork_pilot/planning/codex_bridge.py tests/test_planning_codex_bridge.py
git commit -m "feat(codex-bridge): wire subprocess runner as default, remove empty placeholders"
```

---

## Chunk 3: Verification

### Task 7: Integration smoke test

- [ ] **Step 17: Verify the import chain works**

```bash
cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -c "
from cowork_pilot.planning.codex_bridge import run_exec_stage, _default_runner
print('default runner type:', type(_default_runner))
print('runner is callable:', callable(_default_runner))
"
```
Expected: prints callable function, no import errors.

- [ ] **Step 18: Verify stage_executor picks up the runner without changes**

```bash
cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -c "
from cowork_pilot.planning.stage_executor import execute_stage_subsession
print('stage_executor imports successfully')
"
```
Expected: no import errors. `stage_executor.py` calls `run_exec_stage()` without `command_runner=`, which now uses the real subprocess runner.

- [ ] **Step 19: Verify runner.py picks up the runner without changes**

```bash
cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -c "
from cowork_pilot.planning.runner import run_planning_stage_with_runtime
print('runner imports successfully')
"
```
Expected: no import errors.

- [ ] **Step 20: Run full test suite one more time**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest --tb=short -q`
Expected: All PASS

- [ ] **Step 21: Final commit (if any remaining changes)**

```bash
git status
# Only commit if there are unstaged changes
```
