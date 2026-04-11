"""Runtime sidecar state management for docs-orchestrator Codex backend.

Manages ``docs/generated/orchestrator-runtime.json`` — the single source of
truth for Codex handoff state (resume_handle, waiting status, pending events).

This file is SEPARATE from ``orchestrator-state.json`` which tracks phase
progression.  The two files must never be merged.

Write ordering contract (from §5.2):
- On waiting: write runtime file only (do NOT advance orchestrator-state.json)
- On completion: advance orchestrator-state.json FIRST, then delete runtime file
- Crash recovery: if state.current.status != "running", runtime file is stale → delete
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cowork_pilot.orchestrator_state import OrchestratorState


# ── Constants ────────────────────────────────────────────────────────

RUNTIME_FILENAME = "orchestrator-runtime.json"

_WAITING_STATES = frozenset({"waiting_for_input", "waiting_for_approval"})
_VALID_STATES = frozenset({"running_exec", "waiting_for_input", "waiting_for_approval", "failed"})


def _runtime_path(project_dir: Path) -> Path:
    return project_dir / "docs" / "generated" / RUNTIME_FILENAME


# ── Public API ───────────────────────────────────────────────────────

def load_runtime(project_dir: Path) -> dict[str, object] | None:
    """Return the runtime payload dict, or None if the file does not exist."""
    p = _runtime_path(project_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_runtime(project_dir: Path, payload: dict[str, object]) -> None:
    """Write *payload* to the runtime file atomically (temp + os.replace).

    The parent directory is created if it does not exist.
    ``updated_at`` is always set to the current UTC time.
    """
    p = _runtime_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(payload)
    payload["updated_at"] = datetime.now(tz=timezone.utc).isoformat()

    content = json.dumps(payload, ensure_ascii=False, indent=2)

    # Write to a temp file in the same directory, then atomically rename.
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(p))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_runtime(project_dir: Path) -> None:
    """Delete the runtime file if it exists (no-op if already absent)."""
    p = _runtime_path(project_dir)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def cleanup_stale_runtime(
    *,
    state: OrchestratorState,
    project_dir: Path,
) -> None:
    """Delete the runtime file if it is stale; raise if state is inconsistent.

    Stale: state.current.status != "running", OR runtime.step is already
           in state.completed.

    Inconsistent: state.current.status == "running" AND runtime.step !=
                  state.current.step.  This indicates a write-ordering bug
                  or manual file mutation.  Human review required.

    Call this at startup BEFORE any recovery logic.
    """
    payload = load_runtime(project_dir)
    if payload is None:
        return

    current_status = str(state.current.get("status", ""))
    current_step = str(state.current.get("step", ""))
    completed_steps = {s.step for s in state.completed}
    runtime_step = str(payload.get("step", ""))

    # Case 1: state is no longer running → stale
    if current_status != "running":
        clear_runtime(project_dir)
        return

    # Case 2: runtime step already completed → stale
    if runtime_step in completed_steps:
        clear_runtime(project_dir)
        return

    # Case 3: step mismatch with running state → inconsistent, abort
    if runtime_step != current_step:
        raise RuntimeError(
            f"Orchestrator runtime is inconsistent: "
            f"state.current.step={current_step!r} but runtime.step={runtime_step!r}. "
            f"Human review required. "
            f"Do NOT auto-recover. Check docs/generated/orchestrator-runtime.json "
            f"and docs/generated/orchestrator-state.json manually."
        )

    # Case 4: step matches and running → valid waiting state, leave as-is


def runtime_is_waiting(project_dir: Path) -> bool:
    """Return True iff the runtime file exists and its state is waiting."""
    payload = load_runtime(project_dir)
    if payload is None:
        return False
    return payload.get("runtime_state") in _WAITING_STATES
