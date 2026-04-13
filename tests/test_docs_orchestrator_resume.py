"""Unit tests for docs_orchestrator_resume.py (Test Chunk 2).

Covers the pure resume helper ``resume_waiting_docs_step`` across all
five relevant paths defined in the interactive-resume spec:

- completed
- waiting (waiting → waiting re-entry)
- failed
- missing runtime (RuntimeError)
- not-waiting runtime (RuntimeError)

All tests stub out ``resume_codex_step`` at the binding site inside
``cowork_pilot.docs_orchestrator_resume`` — NOT at the original module —
because ``docs_orchestrator_resume`` imports the symbol at module load
time into its own namespace.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator_codex import CodexStepResult
from cowork_pilot.docs_orchestrator_resume import (
    DocsResumeOutcome,
    _docs_resume_expected_files,
    resume_waiting_docs_step,
)


# ── Fixtures / helpers ───────────────────────────────────────────────


def _make_codex_result(
    status: str,
    *,
    waiting_kind: str | None = None,
    pending_question: dict | None = None,
    pending_approval: dict | None = None,
    pending_event_id: str | None = None,
    error: str = "",
    resume_handle: str = "tid-001",
) -> CodexStepResult:
    return CodexStepResult(
        status=status,  # type: ignore[arg-type]
        event_lines=[],
        assistant_message="",
        exit_code=0 if status == "completed" else 1,
        resume_handle=resume_handle,
        waiting_kind=waiting_kind,
        pending_event_id=pending_event_id,
        pending_question=pending_question,
        pending_approval=pending_approval,
        error=error,
    )


def _seed_state_file(project_dir: Path, step: str = "phase_2:x:y") -> Path:
    gen_dir = project_dir / "docs" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    state_path = gen_dir / "orchestrator-state.json"
    state_path.write_text(
        json.dumps(
            {
                "current": {"step": step, "status": "running"},
                "completed": [],
                "pending": [],
                "errors": [],
                "project_summary": {
                    "domains": [],
                    "features": {},
                    "source_docs": [],
                    "source_line_count": 0,
                },
                "updated_at": "",
                "mode": "auto",
                "manual_override": [],
                "project_dir": str(project_dir),
            }
        )
    )
    return state_path


def _seed_runtime_file(
    project_dir: Path,
    *,
    step: str = "phase_2:x:y",
    runtime_state: str = "waiting_for_input",
    resume_handle: str = "tid-001",
) -> Path:
    gen_dir = project_dir / "docs" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = gen_dir / "orchestrator-runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "backend": "codex",
                "step": step,
                "runtime_state": runtime_state,
                "resume_handle": resume_handle,
                "resume_handle_kind": "codex_thread_id",
                "pending_event_id": "q1",
                "pending_question": {
                    "question": "Q?",
                    "options": [],
                    "recommended": "",
                    "blocking": True,
                },
                "pending_approval": None,
            }
        )
    )
    return runtime_path


def _make_configs(project_dir: Path) -> tuple[Config, DocsOrchestratorConfig]:
    config = Config(project_dir=str(project_dir), engine="codex")
    orch_config = DocsOrchestratorConfig(engine="codex")
    return config, orch_config


def test_docs_resume_expected_files_for_phase2_conflict(tmp_path: Path) -> None:
    expected = _docs_resume_expected_files(
        "phase_2_conflict:host--edit-poll--edit_window",
        tmp_path,
    )
    assert expected == [
        tmp_path
        / "docs"
        / "generated"
        / "contradiction-resolutions"
        / "host--edit-poll--edit_window.md"
    ]


# ── completed ────────────────────────────────────────────────────────


def test_resume_waiting_docs_step_completed_saves_state_and_clears_runtime(
    tmp_path: Path,
) -> None:
    state_path = _seed_state_file(tmp_path)
    runtime_path = _seed_runtime_file(tmp_path)
    config, orch_config = _make_configs(tmp_path)

    mock_result = _make_codex_result("completed")

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=mock_result,
    ) as mock_resume:
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text="admin approves",
            response_kind="answer",
        )

    # --- outcome contract -----------------------------------------------
    assert isinstance(outcome, DocsResumeOutcome)
    assert outcome.status == "completed"
    assert outcome.step == "phase_2:x:y"
    assert outcome.error == ""
    # MUST 4: returned state is the single source of truth
    completed_steps = [s.step for s in outcome.state.completed]
    assert "phase_2:x:y" in completed_steps

    # --- write-ordering contract ----------------------------------------
    # runtime must be cleared, state must be persisted
    assert not runtime_path.exists()
    assert state_path.exists()
    persisted = json.loads(state_path.read_text())
    persisted_steps = [s["step"] for s in persisted["completed"]]
    assert "phase_2:x:y" in persisted_steps

    # --- resume_codex_step was called with the correct response ---------
    kwargs = mock_resume.call_args.kwargs
    assert kwargs["response_text"] == "admin approves"
    assert kwargs["response_kind"] == "answer"
    assert kwargs["step"] == "phase_2:x:y"
    # expected_files routing: phase_2:x:y → gap-reports/x--y.md
    assert kwargs["expected_files"] == [
        tmp_path / "docs" / "generated" / "gap-reports" / "x--y.md"
    ]


# ── waiting (waiting → waiting re-entry) ─────────────────────────────


def test_resume_waiting_docs_step_waiting_writes_new_runtime_and_leaves_state(
    tmp_path: Path,
) -> None:
    state_path = _seed_state_file(tmp_path)
    runtime_path = _seed_runtime_file(tmp_path)
    original_state_bytes = state_path.read_bytes()
    config, orch_config = _make_configs(tmp_path)

    mock_result = _make_codex_result(
        "waiting",
        waiting_kind="input",
        pending_question={
            "question": "Next?",
            "options": ["A", "B"],
            "recommended": "A",
            "blocking": True,
        },
        pending_event_id="q2",
        resume_handle="tid-002",
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=mock_result,
    ):
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text="A",
            response_kind="answer",
        )

    # waiting → the helper must NOT touch the persisted state
    assert outcome.status == "waiting"
    assert outcome.step == "phase_2:x:y"
    assert outcome.error == ""
    assert state_path.read_bytes() == original_state_bytes
    # returned state is still the latest (loaded) state
    assert isinstance(outcome.state.current, dict)

    # runtime file must have been rewritten with the new question payload
    assert runtime_path.exists()
    persisted_runtime = json.loads(runtime_path.read_text())
    assert persisted_runtime["runtime_state"] == "waiting_for_input"
    assert persisted_runtime["resume_handle"] == "tid-002"
    assert persisted_runtime["pending_question"]["question"] == "Next?"
    assert persisted_runtime["pending_event_id"] == "q2"


def test_resume_waiting_docs_step_passes_ai_decision_envelope_verbatim(
    tmp_path: Path,
) -> None:
    _seed_state_file(tmp_path)
    _seed_runtime_file(tmp_path)
    config, orch_config = _make_configs(tmp_path)
    ai_decision_text = (
        "[AI_DECISION]\n"
        "selected_option: A. Keep v1 minimal\n"
        "resolver_reason: insufficient_evidence\n"
        "applied_policy: recommended_plus_consistency\n"
        "note: recommended option과 기존 패턴이 가장 일관적입니다.\n"
        "[/AI_DECISION]\n\n"
        "최종 확정 답변:\n"
        "A. Keep v1 minimal"
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=_make_codex_result("completed"),
    ) as mock_resume:
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text=ai_decision_text,
            response_kind="answer",
        )

    assert outcome.status == "completed"
    assert mock_resume.call_args.kwargs["response_text"] == ai_decision_text


def test_resume_waiting_docs_step_waiting_approval_writes_waiting_for_approval(
    tmp_path: Path,
) -> None:
    _seed_state_file(tmp_path)
    runtime_path = _seed_runtime_file(tmp_path)
    config, orch_config = _make_configs(tmp_path)

    mock_result = _make_codex_result(
        "waiting",
        waiting_kind="approval",
        pending_approval={"subject": "drop table", "blocking": True},
        pending_event_id="a1",
        resume_handle="tid-003",
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=mock_result,
    ):
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text="approved",
            response_kind="approval",
        )

    assert outcome.status == "waiting"
    persisted_runtime = json.loads(runtime_path.read_text())
    assert persisted_runtime["runtime_state"] == "waiting_for_approval"
    assert persisted_runtime["pending_approval"]["subject"] == "drop table"


# ── failed ───────────────────────────────────────────────────────────


def test_resume_waiting_docs_step_failed_saves_error_and_marks_runtime_failed(
    tmp_path: Path,
) -> None:
    state_path = _seed_state_file(tmp_path)
    runtime_path = _seed_runtime_file(tmp_path)
    config, orch_config = _make_configs(tmp_path)

    mock_result = _make_codex_result(
        "failed",
        error="codex exec exited with code 1",
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=mock_result,
    ):
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text="ignored",
            response_kind="answer",
        )

    assert outcome.status == "failed"
    assert outcome.step == "phase_2:x:y"
    assert "exited with code 1" in outcome.error

    # MUST 4: returned state has the error recorded
    assert any(e["step"] == "phase_2:x:y" for e in outcome.state.errors)

    # persisted state also has the error
    persisted = json.loads(state_path.read_text())
    assert any(e["step"] == "phase_2:x:y" for e in persisted["errors"])

    # runtime is kept but marked "failed"
    assert runtime_path.exists()
    persisted_runtime = json.loads(runtime_path.read_text())
    assert persisted_runtime["runtime_state"] == "failed"
    # resume_handle is preserved so operators can re-issue a resume if
    # they decide to — the helper only flips the state label.
    assert persisted_runtime["resume_handle"] == "tid-001"


# ── programmer errors: missing / wrong runtime ──────────────────────


def test_resume_waiting_docs_step_raises_when_runtime_missing(
    tmp_path: Path,
) -> None:
    _seed_state_file(tmp_path)
    # intentionally no runtime file
    config, orch_config = _make_configs(tmp_path)

    with pytest.raises(RuntimeError, match="No orchestrator-runtime.json"):
        resume_waiting_docs_step(
            config,
            orch_config,
            response_text="x",
            response_kind="answer",
        )


def test_resume_waiting_docs_step_raises_when_runtime_not_waiting(
    tmp_path: Path,
) -> None:
    _seed_state_file(tmp_path)
    _seed_runtime_file(tmp_path, runtime_state="running_exec")
    config, orch_config = _make_configs(tmp_path)

    with pytest.raises(RuntimeError, match="not in a waiting state"):
        resume_waiting_docs_step(
            config,
            orch_config,
            response_text="x",
            response_kind="answer",
        )


def test_resume_waiting_docs_step_raises_when_resume_handle_missing(
    tmp_path: Path,
) -> None:
    _seed_state_file(tmp_path)
    _seed_runtime_file(tmp_path, resume_handle="")
    config, orch_config = _make_configs(tmp_path)

    with pytest.raises(RuntimeError, match="resume_handle"):
        resume_waiting_docs_step(
            config,
            orch_config,
            response_text="x",
            response_kind="answer",
        )
