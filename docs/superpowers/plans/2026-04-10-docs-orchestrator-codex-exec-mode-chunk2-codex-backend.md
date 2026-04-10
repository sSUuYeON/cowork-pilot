# Docs-Orchestrator Codex Exec Mode — Chunk 3: Codex Backend

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단일 step의 Codex exec/resume 실행을 담당하는 `docs_orchestrator_codex.py`를 만든다.

**Architecture:** `run_exec_stage()` / `run_exec_resume()` (codex_bridge)와 `extract_terminal_marker_bundle()` (marker_protocol)을 재사용한다. Phase progression은 이 파일이 결정하지 않는다. 입력은 prompt + expected_files, 출력은 `CodexStepResult`.

**Tech Stack:** `cowork_pilot.planning.codex_bridge`, `cowork_pilot.planning.marker_protocol`, `cowork_pilot.codex.event_stream`, `cowork_pilot.codex.command_builder`

**선행 조건:** Chunk 1+2 완료 (prompt wrapper, runtime sidecar)

**Spec:** `docs/superpowers/plans/2026-04-10-docs-orchestrator-codex-exec-mode-design.md` §9

---

## Chunk 3: Codex Backend

**Files:**
- Create: `src/cowork_pilot/docs_orchestrator_codex.py`
- Create: `tests/test_docs_orchestrator_codex.py`

### Task 3-1: `CodexStepResult` dataclass + `run_codex_step()` 스켈레톤

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_docs_orchestrator_codex.py` 신규 생성:

```python
"""Unit tests for docs_orchestrator_codex.py.

All subprocess calls are mocked via command_runner injection.
No real codex binary is invoked.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.docs_orchestrator_codex import CodexStepResult, run_codex_step


# ── helpers ──────────────────────────────────────────────────────────

_STAGE_COMPLETE_BUNDLE = json.dumps({
    "type": "STAGE_COMPLETE",
    "stage": "phase_2:pay:refund",
    "event_id": "phase_2_pay_refund_done",
    "reason": "done",
    "payload": {"summary": "ok", "outputs": ["docs/generated/gap-reports/pay_refund.md"]},
})
_STAGE_COMPLETE_MARKER = f"<COWORK_PILOT_EVENT>\n{_STAGE_COMPLETE_BUNDLE}\n</COWORK_PILOT_EVENT>"

_INPUT_REQUIRED_BUNDLE = json.dumps({
    "type": "INPUT_REQUIRED",
    "stage": "phase_2:pay:refund",
    "event_id": "phase_2_pay_refund_q1",
    "reason": "need info",
    "payload": {"question": "Who approves?", "options": ["admin", "auto"], "recommended": "admin", "blocking": True},
})
_INPUT_REQUIRED_MARKER = f"<COWORK_PILOT_EVENT>\n{_INPUT_REQUIRED_BUNDLE}\n</COWORK_PILOT_EVENT>"


def _make_runner(event_lines: list[str], assistant_message: str, exit_code: int = 0):
    """Return a fake command_runner that ignores args and returns fixed values."""
    def runner(cmd: list[str]) -> tuple[list[str], str, int]:
        return (event_lines, assistant_message, exit_code)
    return runner


def _thread_id_line(thread_id: str = "tid-001") -> str:
    return json.dumps({"type": "thread.started", "thread_id": thread_id})


# ── CodexStepResult ──────────────────────────────────────────────────

def test_codex_step_result_is_dataclass():
    r = CodexStepResult(
        status="completed",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-001",
        waiting_kind=None,
        pending_event_id=None,
        pending_question=None,
        pending_approval=None,
        error="",
    )
    assert r.status == "completed"


# ── run_codex_step: completed path ───────────────────────────────────

def test_run_codex_step_completed(tmp_path):
    """STAGE_COMPLETE + exit 0 + expected file exists → completed."""
    # Create expected output file
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-abc")],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )

    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[out_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )

    assert result.status == "completed"
    assert result.resume_handle == "tid-abc"
    assert result.error == ""


# ── run_codex_step: waiting path ─────────────────────────────────────

def test_run_codex_step_waiting_on_input_required(tmp_path):
    """blocking INPUT_REQUIRED → waiting, even without STAGE_COMPLETE."""
    runner = _make_runner(
        event_lines=[_thread_id_line("tid-xyz")],
        assistant_message=_INPUT_REQUIRED_MARKER,
        exit_code=0,
    )

    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )

    assert result.status == "waiting"
    assert result.waiting_kind == "input"
    assert result.pending_event_id == "phase_2_pay_refund_q1"
    assert result.resume_handle == "tid-xyz"


# ── run_codex_step: failed paths ─────────────────────────────────────

def test_run_codex_step_failed_on_nonzero_exit(tmp_path):
    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message="",
        exit_code=1,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert result.exit_code == 1


def test_run_codex_step_failed_when_no_stage_complete(tmp_path):
    """No STAGE_COMPLETE and no waiting marker → failed."""
    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message="I did some stuff but forgot the marker",
        exit_code=0,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "STAGE_COMPLETE" in result.error


def test_run_codex_step_failed_when_expected_file_missing(tmp_path):
    """STAGE_COMPLETE present but expected file absent → failed."""
    missing_file = tmp_path / "docs" / "generated" / "gap-reports" / "missing.md"

    runner = _make_runner(
        event_lines=[_thread_id_line()],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )
    result = run_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        prompt="do the thing",
        expected_files=[missing_file],
        codex_command="codex",
        codex_extra_args=None,
        command_runner=runner,
    )
    assert result.status == "failed"
    assert "missing" in result.error.lower() or "expected" in result.error.lower()
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_docs_orchestrator_codex.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'cowork_pilot.docs_orchestrator_codex'`

- [ ] **Step 3: `docs_orchestrator_codex.py` 구현**

`src/cowork_pilot/docs_orchestrator_codex.py` 신규 생성:

```python
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from cowork_pilot.codex.event_stream import extract_thread_id
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
        return extract_terminal_marker_bundle(assistant_message)
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


def _verify_expected_files(expected_files: list[Path]) -> str:
    """Return empty string if all files exist, else an error description."""
    missing = [str(f) for f in expected_files if not f.exists()]
    if missing:
        return f"Expected output files missing: {missing}"
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
    return _build_result(status, detail, exec_result.event_lines, exec_result.assistant_message, exec_result.exit_code)


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
    return _build_result(status, detail, exec_result.event_lines, exec_result.assistant_message, exec_result.exit_code)
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator_codex.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator_codex.py tests/test_docs_orchestrator_codex.py
git commit -m "feat(orchestrator-codex): add run_codex_step() and CodexStepResult"
```

---

### Task 3-2: `resume_codex_step()` 테스트 추가

- [ ] **Step 1: 테스트 추가**

`tests/test_docs_orchestrator_codex.py`에 추가:

```python
from cowork_pilot.docs_orchestrator_codex import resume_codex_step


def test_resume_codex_step_completed(tmp_path):
    """resume that gets STAGE_COMPLETE → completed."""
    out_file = tmp_path / "docs" / "generated" / "gap-reports" / "pay_refund.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

    runtime_payload = {
        "backend": "codex",
        "step": "phase_2:pay:refund",
        "runtime_state": "waiting_for_input",
        "resume_handle": "tid-resume-001",
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": "phase_2_pay_refund_q1",
    }

    runner = _make_runner(
        event_lines=[_thread_id_line("tid-resume-001")],
        assistant_message=_STAGE_COMPLETE_MARKER,
        exit_code=0,
    )

    result = resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="관리자가 수동 승인한다",
        response_kind="answer",
        runtime_payload=runtime_payload,
        expected_files=[out_file],
        codex_command="codex",
        command_runner=runner,
    )
    assert result.status == "completed"


def test_resume_codex_step_re_waits(tmp_path):
    """resume that gets another INPUT_REQUIRED → waiting again."""
    runtime_payload = {
        "resume_handle": "tid-resume-002",
        "pending_event_id": "phase_2_pay_refund_q1",
    }
    runner = _make_runner(
        event_lines=[_thread_id_line("tid-resume-002")],
        assistant_message=_INPUT_REQUIRED_MARKER,
        exit_code=0,
    )
    result = resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="some answer",
        response_kind="answer",
        runtime_payload=runtime_payload,
        expected_files=[],
        codex_command="codex",
        command_runner=runner,
    )
    assert result.status == "waiting"
    assert result.waiting_kind == "input"


def test_resume_codex_step_continuation_prompt_format(tmp_path, monkeypatch):
    """continuation prompt must include step, pending_event_id, resolution kind."""
    captured_prompts: list[str] = []

    def capturing_runner(cmd: list[str]) -> tuple[list[str], str, int]:
        # prompt is the last element of codex exec resume argv
        captured_prompts.append(cmd[-1])
        return ([_thread_id_line()], _STAGE_COMPLETE_MARKER, 0)

    runtime_payload = {
        "resume_handle": "tid-003",
        "pending_event_id": "phase_2_pay_refund_q1",
    }
    resume_codex_step(
        project_dir=tmp_path,
        step="phase_2:pay:refund",
        response_text="auto",
        response_kind="approval",
        runtime_payload=runtime_payload,
        expected_files=[],
        codex_command="codex",
        command_runner=capturing_runner,
    )
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "phase_2:pay:refund" in prompt
    assert "phase_2_pay_refund_q1" in prompt
    assert "Resolution kind: approval" in prompt
    assert "auto" in prompt
```

- [ ] **Step 2: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator_codex.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 3: 커밋**

```bash
git add tests/test_docs_orchestrator_codex.py
git commit -m "test(orchestrator-codex): add resume_codex_step() tests"
```

---

### Task 3-3: spec §14.2 항목 5/6 cross-reference + Chunk 3 회귀 확인

Spec §14.2의 테스트 케이스 5 (stale runtime cleanup)와 6 (inconsistent runtime)은
`test_docs_orchestrator_runtime.py`의 Task 2-2에서 이미 커버된다.
(`test_cleanup_stale_deletes_when_step_already_completed`, `test_cleanup_stale_raises_on_step_mismatch`)

`test_docs_orchestrator_codex.py` 파일 상단에 아래 참조 주석을 추가해 spec 추적성을 확보한다.

- [ ] **Step 1: spec §14.2 cross-reference 주석 추가**

`tests/test_docs_orchestrator_codex.py` 파일 모듈 docstring을 아래로 교체:

```python
"""Unit tests for docs_orchestrator_codex.py.

All subprocess calls are mocked via command_runner injection.
No real codex binary is invoked.

Spec §14.2 test coverage map:
  #1 run_codex_step() success         → test_run_codex_step_completed
  #2 run_codex_step() waiting         → test_run_codex_step_waiting_on_input_required
  #3 resume_codex_step() complete     → test_resume_codex_step_completed
  #4 resume_codex_step() re-wait      → test_resume_codex_step_re_waits
  #5 stale runtime cleanup            → tests/test_docs_orchestrator_runtime.py::test_cleanup_stale_*
  #6 inconsistent runtime             → tests/test_docs_orchestrator_runtime.py::test_cleanup_stale_raises_on_step_mismatch
"""
```

- [ ] **Step 2: 관련 테스트 전체 실행**

```bash
python -m pytest tests/test_docs_orchestrator_codex.py tests/test_docs_orchestrator_runtime.py tests/test_orchestrator_prompts.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 3: 기존 orchestrator + codex_bridge 회귀 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py tests/test_planning_codex_bridge.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 4: 커밋**

```bash
git add tests/test_docs_orchestrator_codex.py
git commit -m "docs(test): add spec §14.2 coverage map cross-reference"
```
