"""Execute exec-plan chunks via ``codex exec --dangerously-bypass-approvals-and-sandbox``.

This is the simplest, most independent module in the Codex backend.
It takes a parsed ExecPlan and runs each incomplete chunk as a
subprocess, updating checkboxes on success.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cowork_pilot.codex.command_builder import build_exec_command as _build_exec_command
from cowork_pilot.codex.event_stream import summarize_codex_event as _summarize_codex_event
from cowork_pilot.plan_parser import (
    ExecPlan,
    Chunk,
    parse_exec_plan,
    update_checkboxes,
)
from cowork_pilot.codex.models import (
    ChunkResult,
    ChunkRunStatus,
    PlanRunResult,
)

logger = logging.getLogger("cowork-pilot.codex.exec_runner")

_SUBPROCESS_HEARTBEAT_SECONDS = 15.0
_SUBPROCESS_STALL_SECONDS = 600.0
_STREAM_READ_CHUNK_SIZE = 4096
_EVENT_TEXT_SNIPPET_CHARS = 400
_DEFAULT_SYSTEM_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)

# ── Types ───────────────────────────────────────────────────────────

PromptBuilder = Callable[[Chunk, str], str]
"""(chunk, project_dir) → full prompt string for codex exec -p."""


@dataclass
class _StreamProgress:
    """Track the last time Codex emitted a stdout event."""

    last_activity_at: float

    def touch(self) -> None:
        self.last_activity_at = time.monotonic()


class _ChunkExecutionTimeout(asyncio.TimeoutError):
    """Timeout raised for total-runtime or stalled-output conditions."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ── Default prompt builder ──────────────────────────────────────────

def default_prompt_builder(chunk: Chunk, project_dir: str) -> str:
    """Build the ``-p`` prompt from a chunk's session_prompt.

    Wraps the raw session prompt with project context so the Codex
    agent understands what it needs to do.
    """
    header = (
        f"You are working on: Chunk {chunk.number} — {chunk.name}\n"
        f"Project directory: {project_dir}\n"
        f"\n"
        f"Complete the following tasks. After finishing, do NOT ask questions — "
        f"just implement and verify.\n"
        f"\n"
        f"---\n"
    )
    return header + chunk.session_prompt


def _build_subprocess_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Ensure child processes inherit a sane PATH even if shell init is broken."""
    env = dict(base_env or os.environ)
    existing = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]

    merged: list[str] = []
    seen: set[str] = set()
    for entry in _DEFAULT_SYSTEM_PATHS:
        if entry not in seen:
            merged.append(entry)
            seen.add(entry)
    for entry in existing:
        if entry not in seen:
            merged.append(entry)
            seen.add(entry)

    env["PATH"] = os.pathsep.join(merged)
    return env


async def _read_stream(stream: asyncio.StreamReader | None) -> bytes:
    """Drain a subprocess pipe without blocking the process."""
    if stream is None:
        return b""

    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _truncate_text(text: str, limit: int = _EVENT_TEXT_SNIPPET_CHARS) -> str:
    """Collapse whitespace and trim text for terminal logging."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _record_codex_stdout_line(
    line: str,
    *,
    chunk_number: int,
    event_log_lines: list[str],
) -> str:
    """Parse and log one decoded stdout line from ``codex exec --json``."""
    stripped = line.strip()
    if not stripped:
        return ""

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        summary = f"stdout: {_truncate_text(stripped)}"
        logger.info("Chunk %d codex: %s", chunk_number, summary)
        event_log_lines.append(summary)
        return ""

    lines, message = _summarize_codex_event(payload)
    for summary in lines:
        logger.info("Chunk %d codex: %s", chunk_number, summary)
        event_log_lines.append(summary)
    return message


async def _read_codex_event_stream(
    stream: asyncio.StreamReader | None,
    *,
    chunk_number: int,
    progress: _StreamProgress | None = None,
) -> tuple[str, str, str]:
    """Read Codex JSONL stdout, logging summarized progress in real time."""
    if stream is None:
        return ("", "", "")

    raw_chunks: list[bytes] = []
    event_log_lines: list[str] = []
    last_message = ""
    buffered = b""

    while True:
        chunk = await stream.read(_STREAM_READ_CHUNK_SIZE)
        if not chunk:
            break

        raw_chunks.append(chunk)
        if progress is not None:
            progress.touch()
        buffered += chunk

        while True:
            newline_index = buffered.find(b"\n")
            if newline_index < 0:
                break

            line_bytes = buffered[: newline_index + 1]
            buffered = buffered[newline_index + 1 :]
            message = _record_codex_stdout_line(
                line_bytes.decode(errors="replace"),
                chunk_number=chunk_number,
                event_log_lines=event_log_lines,
            )
            if message:
                last_message = message

    if buffered:
        message = _record_codex_stdout_line(
            buffered.decode(errors="replace"),
            chunk_number=chunk_number,
            event_log_lines=event_log_lines,
        )
        if message:
            last_message = message

    return (
        b"".join(raw_chunks).decode(errors="replace"),
        "\n".join(event_log_lines),
        last_message,
    )


# ── Single chunk execution ──────────────────────────────────────────

async def run_chunk(
    chunk: Chunk,
    project_dir: str,
    *,
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
    timeout_seconds: float = 600.0,
    stalled_output_timeout_seconds: float | None = None,
    prompt_builder: PromptBuilder | None = None,
) -> ChunkResult:
    """Run a single chunk via ``codex exec``.

    Returns a ``ChunkResult`` regardless of success or failure.
    """
    builder = prompt_builder or default_prompt_builder
    prompt = builder(chunk, project_dir)
    cmd = _build_exec_command(
        prompt,
        project_dir,
        codex_command=codex_command,
        codex_extra_args=codex_extra_args,
    )
    env = _build_subprocess_env()

    logger.info("Running chunk %d: %s", chunk.number, chunk.name)
    logger.info(
        "Launching codex exec in %s with %d-char prompt",
        project_dir,
        len(prompt),
    )
    logger.debug("Command: %s", " ".join(cmd[:6]) + " ...")

    start = time.monotonic()
    stall_timeout = stalled_output_timeout_seconds or _SUBPROCESS_STALL_SECONDS
    progress = _StreamProgress(last_activity_at=start)
    proc: asyncio.subprocess.Process | None = None
    stdout_task: asyncio.Task[tuple[str, str, str]] | None = None
    stderr_task: asyncio.Task[bytes] | None = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_dir,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_task = asyncio.create_task(
            _read_codex_event_stream(
                proc.stdout,
                chunk_number=chunk.number,
                progress=progress,
            )
        )
        stderr_task = asyncio.create_task(_read_stream(proc.stderr))
        logger.info("codex exec started (pid=%s)", proc.pid)

        deadline = start + timeout_seconds
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise _ChunkExecutionTimeout(
                    f"overall timeout after {timeout_seconds:.1f}s",
                )

            stalled_for = now - progress.last_activity_at
            if stalled_for >= stall_timeout:
                raise _ChunkExecutionTimeout(
                    f"no codex event output for {stalled_for:.1f}s",
                )

            wait_slice = min(_SUBPROCESS_HEARTBEAT_SECONDS, remaining)
            try:
                await asyncio.wait_for(proc.wait(), timeout=wait_slice)
                break
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - start
                logger.info(
                    (
                        "Chunk %d still running via codex exec "
                        "(pid=%s, %.1fs elapsed, %.1fs since last event)"
                    ),
                    chunk.number,
                    proc.pid,
                    elapsed,
                    stalled_for,
                )

        stdout, event_log, last_message = await stdout_task
        stderr_bytes = await stderr_task

        elapsed = time.monotonic() - start
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode == 0:
            logger.info(
                "Chunk %d succeeded (%.1fs)", chunk.number, elapsed,
            )
            return ChunkResult(
                chunk_number=chunk.number,
                chunk_name=chunk.name,
                status=ChunkRunStatus.SUCCESS,
                returncode=0,
                stdout=stdout,
                stderr=stderr,
                event_log=event_log,
                last_message=last_message,
                duration_seconds=elapsed,
            )
        else:
            logger.warning(
                "Chunk %d failed (rc=%d, %.1fs)",
                chunk.number, proc.returncode, elapsed,
            )
            return ChunkResult(
                chunk_number=chunk.number,
                chunk_name=chunk.name,
                status=ChunkRunStatus.FAILED,
                returncode=proc.returncode or -1,
                stdout=stdout,
                stderr=stderr,
                event_log=event_log,
                last_message=last_message,
                duration_seconds=elapsed,
            )

    except _ChunkExecutionTimeout as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "Chunk %d timed out after %.1fs (%s)",
            chunk.number,
            elapsed,
            exc.reason,
        )
        # Kill the process
        try:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception:
            pass

        stdout = ""
        stderr = ""
        event_log = ""
        last_message = ""
        if stdout_task is not None:
            stdout, event_log, last_message = await stdout_task
        if stderr_task is not None:
            stderr = (await stderr_task).decode(errors="replace")
        if stderr.strip():
            stderr = stderr.rstrip() + "\n" + exc.reason
        else:
            stderr = exc.reason
        return ChunkResult(
            chunk_number=chunk.number,
            chunk_name=chunk.name,
            status=ChunkRunStatus.TIMEOUT,
            stdout=stdout,
            stderr=stderr,
            event_log=event_log,
            last_message=last_message,
            duration_seconds=elapsed,
        )

    except FileNotFoundError:
        logger.error("codex command not found: %s", codex_command)
        return ChunkResult(
            chunk_number=chunk.number,
            chunk_name=chunk.name,
            status=ChunkRunStatus.FAILED,
            returncode=-1,
            stderr=f"codex command not found: {codex_command}",
        )


# ── Retry wrapper ───────────────────────────────────────────────────

async def run_chunk_with_retry(
    chunk: Chunk,
    project_dir: str,
    *,
    max_retries: int = 3,
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
    timeout_seconds: float = 600.0,
    stalled_output_timeout_seconds: float | None = None,
    prompt_builder: PromptBuilder | None = None,
) -> ChunkResult:
    """Run a chunk, retrying on failure.

    On retry, the previous error output is appended to the prompt
    so the agent can learn from the failure.
    """
    builder = prompt_builder or default_prompt_builder
    last_result: ChunkResult | None = None

    for attempt in range(1, max_retries + 1):
        # Build a retry-aware prompt if this is a retry
        if last_result is not None and last_result.status != ChunkRunStatus.SUCCESS:
            diagnostics: list[str] = [f"Return code: {last_result.returncode}"]  # type: ignore[union-attr]
            if last_result.stderr:  # type: ignore[union-attr]
                diagnostics.append(
                    "Stderr (last 2000 chars):\n"
                    + last_result.stderr[-2000:]  # type: ignore[union-attr]
                )
            if last_result.event_log:  # type: ignore[union-attr]
                diagnostics.append(
                    "Codex event log (last 2000 chars):\n"
                    + last_result.event_log[-2000:]  # type: ignore[union-attr]
                )
            if last_result.last_message:  # type: ignore[union-attr]
                diagnostics.append(
                    "Last assistant message:\n"
                    + last_result.last_message[-1000:]  # type: ignore[union-attr]
                )

            def retry_builder(c: Chunk, p: str) -> str:
                base = builder(c, p)
                error_ctx = (
                    f"\n\n--- PREVIOUS ATTEMPT FAILED (attempt {attempt - 1}/{max_retries}) ---\n"
                    + "\n\n".join(diagnostics)
                    + "\n---\n"
                    f"Fix the issues above and try again.\n"
                )
                return base + error_ctx
            current_builder = retry_builder
        else:
            current_builder = builder

        result = await run_chunk(
            chunk,
            project_dir,
            codex_command=codex_command,
            codex_extra_args=codex_extra_args,
            timeout_seconds=timeout_seconds,
            stalled_output_timeout_seconds=stalled_output_timeout_seconds,
            prompt_builder=current_builder,
        )
        result.attempt = attempt

        if result.status == ChunkRunStatus.SUCCESS:
            return result

        last_result = result
        logger.warning(
            "Chunk %d attempt %d/%d failed (%s)",
            chunk.number, attempt, max_retries, result.status.value,
        )

    # All retries exhausted
    assert last_result is not None
    return last_result


# ── Full plan execution ─────────────────────────────────────────────

async def run_exec_plan(
    plan_path: Path,
    project_dir: str,
    *,
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
    timeout_seconds: float = 600.0,
    stalled_output_timeout_seconds: float | None = None,
    max_retries: int = 3,
    prompt_builder: PromptBuilder | None = None,
    dry_run: bool = False,
    on_chunk_done: Callable[[ChunkResult], None] | None = None,
) -> PlanRunResult:
    """Execute all incomplete chunks in an exec-plan sequentially.

    For each successful chunk, checkboxes are updated in the plan file.
    If a chunk fails after all retries, execution stops (fail-fast).

    Args:
        plan_path: Path to the exec-plan Markdown file.
        project_dir: Working directory for codex exec.
        dry_run: If True, print what would run without executing.
        on_chunk_done: Optional callback after each chunk completes.

    Returns:
        PlanRunResult with per-chunk outcomes.
    """
    plan = parse_exec_plan(plan_path)
    plan_result = PlanRunResult(
        plan_title=plan.title,
        plan_path=str(plan_path),
    )

    for chunk in plan.chunks:
        if chunk.status == "completed":
            logger.info("Chunk %d already completed, skipping", chunk.number)
            plan_result.chunk_results.append(ChunkResult(
                chunk_number=chunk.number,
                chunk_name=chunk.name,
                status=ChunkRunStatus.SKIPPED,
            ))
            continue

        if dry_run:
            builder = prompt_builder or default_prompt_builder
            prompt = builder(chunk, project_dir)
            print(f"\n{'='*60}")
            print(f"[DRY RUN] Chunk {chunk.number}: {chunk.name}")
            print(f"  Command: codex exec --dangerously-bypass-approvals-and-sandbox")
            print(f"  CWD: {project_dir}")
            print(f"  Prompt ({len(prompt)} chars):")
            print(f"  {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
            print(f"{'='*60}")
            plan_result.chunk_results.append(ChunkResult(
                chunk_number=chunk.number,
                chunk_name=chunk.name,
                status=ChunkRunStatus.SKIPPED,
            ))
            continue

        result = await run_chunk_with_retry(
            chunk,
            project_dir,
            max_retries=max_retries,
            codex_command=codex_command,
            codex_extra_args=codex_extra_args,
            timeout_seconds=timeout_seconds,
            stalled_output_timeout_seconds=stalled_output_timeout_seconds,
            prompt_builder=prompt_builder,
        )

        plan_result.chunk_results.append(result)

        if on_chunk_done:
            on_chunk_done(result)

        if result.status == ChunkRunStatus.SUCCESS:
            # Mark all criteria as checked
            update_checkboxes(plan_path, chunk.number)
            logger.info("Chunk %d checkboxes updated", chunk.number)
        else:
            # Fail-fast: stop on first unrecoverable failure
            logger.error(
                "Chunk %d failed after %d attempts — stopping plan execution",
                chunk.number, result.attempt,
            )
            break

    plan_result.all_succeeded = all(
        r.status in (ChunkRunStatus.SUCCESS, ChunkRunStatus.SKIPPED)
        for r in plan_result.chunk_results
    ) and len(plan_result.chunk_results) == len(plan.chunks)

    return plan_result
