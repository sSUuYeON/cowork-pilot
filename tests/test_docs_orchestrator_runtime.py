"""Unit tests for docs_orchestrator_runtime.py.

All tests use tmp_path — no real filesystem side effects.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cowork_pilot.docs_orchestrator_runtime import (
    RUNTIME_FILENAME,
    clear_runtime,
    load_runtime,
    runtime_is_waiting,
    write_runtime,
)


def _runtime_path(project_dir: Path) -> Path:
    return project_dir / "docs" / "generated" / RUNTIME_FILENAME


# ── load_runtime ─────────────────────────────────────────────────────

def test_load_runtime_returns_none_when_missing(tmp_path):
    assert load_runtime(tmp_path) is None


def test_load_runtime_returns_dict_when_present(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "runtime_state": "running_exec"}))
    result = load_runtime(tmp_path)
    assert result is not None
    assert result["backend"] == "codex"


# ── write_runtime / atomic write ────────────────────────────────────

def test_write_runtime_creates_file(tmp_path):
    payload = {
        "backend": "codex",
        "step": "phase_2:payment:refund",
        "runtime_state": "waiting_for_input",
        "resume_handle": "abc-123",
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": "phase_2_payment_refund_q1",
        "pending_question": {"question": "Q?", "options": [], "recommended": "", "blocking": True},
        "pending_approval": None,
        "updated_at": "2026-04-10T14:00:00",
    }
    write_runtime(tmp_path, payload)
    p = _runtime_path(tmp_path)
    assert p.exists()
    loaded = json.loads(p.read_text())
    assert loaded["step"] == "phase_2:payment:refund"


def test_write_runtime_is_atomic(tmp_path, monkeypatch):
    """write_runtime must use temp+rename (no partial writes visible)."""
    import os
    replaced_calls: list[tuple[str, str]] = []
    original_replace = os.replace
    def mock_replace(src, dst):
        replaced_calls.append((src, dst))
        return original_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)

    write_runtime(tmp_path, {"backend": "codex", "runtime_state": "running_exec"})
    assert len(replaced_calls) == 1
    src, dst = replaced_calls[0]
    assert dst == str(_runtime_path(tmp_path))
    assert src != dst


# ── clear_runtime ────────────────────────────────────────────────────

def test_clear_runtime_removes_file(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    clear_runtime(tmp_path)
    assert not p.exists()


def test_clear_runtime_noop_when_missing(tmp_path):
    clear_runtime(tmp_path)  # Must not raise


# ── runtime_is_waiting ───────────────────────────────────────────────

def test_runtime_is_waiting_false_when_no_file(tmp_path):
    assert runtime_is_waiting(tmp_path) is False


def test_runtime_is_waiting_true_for_waiting_states(tmp_path):
    for state in ("waiting_for_input", "waiting_for_approval"):
        p = _runtime_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"runtime_state": state}))
        assert runtime_is_waiting(tmp_path) is True


def test_runtime_is_waiting_false_for_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"runtime_state": "running_exec"}))
    assert runtime_is_waiting(tmp_path) is False


# ── cleanup_stale_runtime ────────────────────────────────────────────

from cowork_pilot.docs_orchestrator_runtime import cleanup_stale_runtime
from cowork_pilot.orchestrator_state import OrchestratorState, StepStatus


def _make_state(status: str, step: str = "phase_2:payment:refund", completed: list[str] | None = None) -> OrchestratorState:
    completed_steps = [StepStatus(step=s, status="completed") for s in (completed or [])]
    return OrchestratorState(
        current={"step": step, "status": status},
        completed=completed_steps,
    )


def test_cleanup_stale_noop_when_no_runtime(tmp_path):
    state = _make_state("running")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)  # Must not raise


def test_cleanup_stale_deletes_when_state_not_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("idle")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert not p.exists()


def test_cleanup_stale_deletes_when_step_already_completed(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("running", step="phase_3_A", completed=["phase_2:x:y"])
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert not p.exists()


def test_cleanup_stale_raises_on_step_mismatch(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    # state.current.step is different from runtime.step, both are "running"
    state = _make_state("running", step="phase_3_A")
    with pytest.raises(RuntimeError, match="inconsistent"):
        cleanup_stale_runtime(state=state, project_dir=tmp_path)


def test_cleanup_stale_noop_when_step_matches_and_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("running", step="phase_2:x:y")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert p.exists()  # Must NOT be deleted
