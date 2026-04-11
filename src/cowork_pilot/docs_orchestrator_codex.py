"""Codex exec backend for docs-orchestrator.

Responsible for executing a single orchestrator step via ``codex exec``
and determining whether it completed, is waiting for user input/approval,
or has failed.

Does NOT manage phase progression.  Callers (docs_orchestrator.py) decide
what to do with the result.

Reuses:
- cowork_pilot.planning.codex_bridge.run_exec_stage / run_exec_resume
- cowork_pilot.planning.marker_protocol.extract_terminal_marker_bundle
- cowork_pilot.codex.event_stream.extract_thread_id
- cowork_pilot.codex.command_builder.build_exec_resume_command
- cowork_pilot.docs_orchestrator.(_check_output_files via expected_files arg)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cowork_pilot.codex.event_stream import extract_thread_id
from cowork_pilot.orchestrator_state import _file_has_done_marker
from cowork_pilot.planning.codex_bridge import (
    CommandRunner,
    run_exec_resume,
    run_exec_stage,
)
from cowork_pilot.planning.marker_protocol import (
    MarkerEnvelope,
    extract_terminal_marker_bundle,
)


# ── Result dataclass ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CodexStepResult:
    status: Literal["completed", "waiting", "failed"]
    event_lines: list[str]
    assistant_message: str
    exit_code: int
    resume_handle: str
    waiting_kind: str | None          # "input" | "approval" | None
    pending_event_id: str | None
    pending_question: dict[str, object] | None
    pending_approval: dict[str, object] | None
    error: str


# ── Internal helpers ─────────────────────────────────────────────────


def _parse_markers(assistant_message: str) -> list[MarkerEnvelope]:
    """Return the terminal marker bundle from the assistant message."""
    try:
        return list(
            extract_terminal_marker_bundle(
                assistant_message,
                allow_stage_complete_salvage=True,
            )
        )
    except Exception:
        return []


def _find_marker(markers: list[MarkerEnvelope], type_: str) -> MarkerEnvelope | None:
    return next((m for m in markers if m.type == type_), None)


def _find_blocking_waiting(markers: list[MarkerEnvelope]) -> MarkerEnvelope | None:
    """Return the first blocking INPUT_REQUIRED or APPROVAL_REQUIRED marker."""
    for m in markers:
        if m.type in ("INPUT_REQUIRED", "APPROVAL_REQUIRED"):
            if m.payload.get("blocking"):
                return m
    return None


def _resolve_separator_fallback(path: Path) -> Path:
    """Return canonical ``--`` filename, renaming a single-hyphen variant if needed."""
    if path.exists() or path.is_dir() or "--" not in path.name:
        return path

    alt_path = path.with_name(path.name.replace("--", "-", 1))
    if alt_path.exists():
        alt_path.rename(path)
    return path


def _verify_expected_files(expected_files: list[Path]) -> str:
    """Return empty string if all outputs have done markers, else an error description."""
    if not expected_files:
        return "Expected output files could not be determined for this step"

    for raw_path in expected_files:
        path = _resolve_separator_fallback(raw_path)
        if path.is_dir():
            md_files = sorted(path.glob("*.md"))
            if not md_files:
                return f"Expected markdown outputs missing in directory: {path}"
            if not any(_file_has_done_marker(md_file) for md_file in md_files):
                return (
                    f"Expected markdown outputs in {path} are missing "
                    "the ORCHESTRATOR:DONE marker"
                )
            continue

        if not path.exists():
            return f"Expected output file missing: {path}"
        if not _file_has_done_marker(path):
            return f"Expected output file missing ORCHESTRATOR:DONE marker: {path}"
    return ""


def _determine_outcome(
    *,
    exit_code: int,
    assistant_message: str,
    event_lines: list[str],
    expected_files: list[Path],
) -> tuple[Literal["completed", "waiting", "failed"], dict[str, object]]:
    """Core outcome decision logic (pure — no side effects).

    Priority order (from spec §9.4):
    1. non-zero exit → failed
    2. waiting check (INPUT_REQUIRED / APPROVAL_REQUIRED blocking) → waiting
       NOTE: waiting check MUST come before STAGE_COMPLETE check
    3. no STAGE_COMPLETE → failed
    4. expected files missing → failed
    5. everything ok → completed

    Returns (status, detail_dict).
    """
    resume_handle = extract_thread_id(event_lines)
    markers = _parse_markers(assistant_message)

    # 1. exit code
    if exit_code != 0:
        return "failed", {
            "error": f"codex exec exited with code {exit_code}",
            "resume_handle": resume_handle,
        }

    # 2. waiting — MUST come before STAGE_COMPLETE check (spec §9.4 priority rule).
    #    Blocking INPUT_REQUIRED / APPROVAL_REQUIRED can exist WITHOUT STAGE_COMPLETE
    #    and must resolve to "waiting", not "failed". Do NOT reorder these checks.
    waiting_marker = _find_blocking_waiting(markers)
    if waiting_marker is not None:
        wk = "input" if waiting_marker.type == "INPUT_REQUIRED" else "approval"
        payload = waiting_marker.payload
        return "waiting", {
            "waiting_kind": wk,
            "pending_event_id": waiting_marker.event_id,
            "pending_question": payload if wk == "input" else None,
            "pending_approval": payload if wk == "approval" else None,
            "resume_handle": resume_handle,
        }

    # 3. STAGE_COMPLETE required
    complete_marker = _find_marker(markers, "STAGE_COMPLETE")
    if complete_marker is None:
        return "failed", {
            "error": "STAGE_COMPLETE marker missing from assistant message",
            "resume_handle": resume_handle,
        }

    # 4. expected files
    file_error = _verify_expected_files(expected_files)
    if file_error:
        return "failed", {"error": file_error, "resume_handle": resume_handle}

    # 5. success
    return "completed", {"resume_handle": resume_handle}


def _build_result(
    status: Literal["completed", "waiting", "failed"],
    detail: dict[str, object],
    event_lines: list[str],
    assistant_message: str,
    exit_code: int,
) -> CodexStepResult:
    return CodexStepResult(
        status=status,
        event_lines=event_lines,
        assistant_message=assistant_message,
        exit_code=exit_code,
        resume_handle=str(detail.get("resume_handle", "")),
        waiting_kind=detail.get("waiting_kind"),  # type: ignore[arg-type]
        pending_event_id=detail.get("pending_event_id"),  # type: ignore[arg-type]
        pending_question=detail.get("pending_question"),  # type: ignore[arg-type]
        pending_approval=detail.get("pending_approval"),  # type: ignore[arg-type]
        error=str(detail.get("error", "")),
    )


# ── Public API ───────────────────────────────────────────────────────


def run_codex_step(
    *,
    project_dir: Path,
    step: str,
    prompt: str,
    expected_files: list[Path],
    codex_command: str = "codex",
    codex_extra_args: list[str] | None = None,
    command_runner: CommandRunner | None = None,
) -> CodexStepResult:
    """Execute a single docs-orchestrator step via ``codex exec``.

    Parameters
    ----------
    project_dir:
        Root of the project being documented.
    step:
        Step identifier, e.g. ``"phase_2:payment:refund"``.
    prompt:
        The full Codex session prompt (rendered from codex_wrapper.j2).
    expected_files:
        Output paths that must exist after completion.
    codex_command:
        Path/name of the codex binary.
    codex_extra_args:
        Extra args forwarded to codex exec.
    command_runner:
        Dependency-injected runner for testing.  If None, uses the default
        subprocess runner from codex_bridge.

    Returns
    -------
    CodexStepResult
        status="completed" | "waiting" | "failed"
    """
    exec_result = run_exec_stage(
        stage=step,
        prompt=prompt,
        run_dir=str(project_dir),
        codex_command=codex_command,
        codex_extra_args=codex_extra_args,
        command_runner=command_runner,
    )

    status, detail = _determine_outcome(
        exit_code=exec_result.exit_code,
        assistant_message=exec_result.assistant_message,
        event_lines=exec_result.event_lines,
        expected_files=expected_files,
    )
    return _build_result(
        status,
        detail,
        exec_result.event_lines,
        exec_result.assistant_message,
        exec_result.exit_code,
    )


def resume_codex_step(
    *,
    project_dir: Path,
    step: str,
    response_text: str,
    response_kind: str,
    runtime_payload: dict[str, object],
    expected_files: list[Path],
    codex_command: str = "codex",
    command_runner: CommandRunner | None = None,
) -> CodexStepResult:
    """Resume a waiting Codex step with a user response.

    Builds a short deterministic continuation prompt and calls
    ``codex exec resume`` on the existing thread.

    Parameters
    ----------
    project_dir:
        Root of the project being documented.
    step:
        Step identifier (used in the continuation prompt).
    response_text:
        The user's answer or approval text.
    response_kind:
        ``"answer"`` | ``"approval"``.
    runtime_payload:
        The full runtime sidecar dict (provides resume_handle, pending_event_id).
    expected_files:
        Output paths validated on STAGE_COMPLETE.
    codex_command:
        Path/name of the codex binary.
    command_runner:
        Dependency-injected runner for testing.
    """
    resume_handle = str(runtime_payload["resume_handle"])
    pending_event_id = str(runtime_payload.get("pending_event_id", "resume-1"))
    resolution_kind = "approval" if response_kind == "approval" else "answer"

    continuation_prompt = (
        f"You are resuming the same docs-orchestrator step.\n\n"
        f"Step: {step}\n"
        f"Pending event: {pending_event_id}\n"
        f"Resolution kind: {resolution_kind}\n"
        f"User response: {response_text}\n\n"
        f"Continue the same step without restarting from scratch.\n"
        f"Update the required output files.\n"
        f"If more user input is still required, emit INPUT_REQUIRED or APPROVAL_REQUIRED.\n"
        f"If the step completes, emit STAGE_COMPLETE and ensure every output file "
        f"ends with <!-- ORCHESTRATOR:DONE -->."
    )

    exec_result = run_exec_resume(
        resume_handle=resume_handle,
        prompt=continuation_prompt,
        run_dir=str(project_dir),
        codex_command=codex_command,
        command_runner=command_runner,
    )

    status, detail = _determine_outcome(
        exit_code=exec_result.exit_code,
        assistant_message=exec_result.assistant_message,
        event_lines=exec_result.event_lines,
        expected_files=expected_files,
    )
    return _build_result(
        status,
        detail,
        exec_result.event_lines,
        exec_result.assistant_message,
        exec_result.exit_code,
    )
