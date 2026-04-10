from __future__ import annotations

import json
from pathlib import Path

from cowork_pilot.planning.models import PlanningContext, ProjectMode

_PIPELINE_STATE_FILENAME = "pipeline-state.json"
_PLANNING_CONTEXT_KEY = "planning_context"


def _append_markdown_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


_PENDING_KEYS = ("pending_event_id", "pending_question", "pending_approval")
_WAITING_STATES = {"waiting_for_input", "waiting_for_approval"}


def _normalize_pending_keys(state: str, metadata: dict[str, object]) -> dict[str, object]:
    """Strip pending_* keys when state is not a waiting state.

    This is the single enforcement point for the cleanup rule:
    pending payload must only exist while the run is waiting.
    """
    if state in _WAITING_STATES:
        return metadata
    return {k: v for k, v in metadata.items() if k not in _PENDING_KEYS}


def write_run_state(run_dir: Path, *, state: str, metadata: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    cleaned = _normalize_pending_keys(state, metadata)
    payload = {
        "state": state,
        **cleaned,
    }
    (run_dir / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_question(run_dir: Path, *, event_id: str, question: str, blocking: bool) -> None:
    _append_markdown_line(
        run_dir / "question-queue.md",
        f"- [{event_id}] (blocking={_bool_text(blocking)}) {question}",
    )


def append_answer(run_dir: Path, *, event_id: str, answer: str) -> None:
    _append_markdown_line(run_dir / "answer-log.md", f"- [{event_id}] {answer}")


def append_approval_decision(run_dir: Path, *, event_id: str, decision: str) -> None:
    _append_markdown_line(run_dir / "approval-log.md", f"- [{event_id}] decision={decision}")


def append_assumption(
    run_dir: Path,
    *,
    event_id: str,
    assumption: str,
    confidence: str,
    impact: str,
) -> None:
    _append_markdown_line(
        run_dir / "assumptions.md",
        f"- [{event_id}] confidence={confidence} impact={impact} {assumption}",
    )


def append_approval_request(
    run_dir: Path,
    *,
    event_id: str,
    subject: str,
    blocking: bool,
) -> None:
    _append_markdown_line(
        run_dir / "approval-log.md",
        f"- [{event_id}] (blocking={_bool_text(blocking)}) {subject}",
    )


def append_invalidation(
    run_dir: Path,
    *,
    event_id: str,
    reason: str,
    affected_stage: str,
) -> None:
    _append_markdown_line(
        run_dir / "assumption-invalidations.md",
        f"- [{event_id}] reason={reason} affected_stage={affected_stage}",
    )


def append_runtime_event(run_dir: Path, payload: dict[str, object]) -> None:
    path = run_dir / "runtime-events.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_run_state(run_dir: Path) -> dict[str, object]:
    path = run_dir / "run-state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_pipeline_state(run_dir: Path, *, context: PlanningContext, next_dispatch_index: int) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    serialized_context = _serialize_planning_context(context)
    payload = {
        "context": serialized_context,
        "next_dispatch_index": next_dispatch_index,
    }
    (run_dir / _PIPELINE_STATE_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    current_run_state = read_run_state(run_dir)
    write_run_state(
        run_dir,
        state=str(current_run_state.get("state", "pending")),
        metadata={
            **{key: value for key, value in current_run_state.items() if key != "state"},
            _PLANNING_CONTEXT_KEY: serialized_context,
            "next_dispatch_index": next_dispatch_index,
        },
    )


def read_pipeline_state(run_dir: Path) -> dict[str, object]:
    path = run_dir / _PIPELINE_STATE_FILENAME
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    run_state = read_run_state(run_dir)
    context_data = run_state.get(_PLANNING_CONTEXT_KEY)
    if isinstance(context_data, dict):
        return {
            "context": context_data,
            "next_dispatch_index": int(run_state.get("next_dispatch_index", 0)),
        }
    return {}


def advance_pipeline_state(run_dir: Path) -> int:
    state = read_pipeline_state(run_dir)
    next_dispatch_index = int(state.get("next_dispatch_index", 0)) + 1
    context_data = state.get("context", {})
    if not isinstance(context_data, dict):
        context_data = {}
    write_pipeline_state(
        run_dir,
        context=_deserialize_planning_context(context_data, run_dir=run_dir),
        next_dispatch_index=next_dispatch_index,
    )
    return next_dispatch_index


def _serialize_planning_context(context: PlanningContext) -> dict[str, object]:
    return {
        "run_dir": str(context.run_dir) if context.run_dir is not None else "",
        "project_dir": str(context.project_dir) if context.project_dir is not None else "",
        "target_version": context.target_version,
        "mode": context.mode.value if context.mode is not None else "",
        "explicit_mode": context.explicit_mode,
        "request_text": context.request_text,
        "request_source": context.request_source,
        "change_request_text": context.change_request_text,
        "change_request_source": context.change_request_source,
    }


def _deserialize_planning_context(
    data: dict[str, object],
    *,
    run_dir: Path,
) -> PlanningContext:
    mode_text = str(data.get("mode", ""))
    return PlanningContext(
        run_dir=Path(str(data.get("run_dir", ""))) if data.get("run_dir") else run_dir,
        project_dir=Path(str(data.get("project_dir", ""))) if data.get("project_dir") else None,
        target_version=str(data.get("target_version", "")),
        mode=ProjectMode(mode_text) if mode_text else None,
        explicit_mode=bool(data.get("explicit_mode", False)),
        request_text=str(data.get("request_text", "")),
        request_source=str(data.get("request_source", "")),
        change_request_text=str(data.get("change_request_text", "")),
        change_request_source=str(data.get("change_request_source", "")),
    )


_COMPLETED_STAGES_FILENAME = "completed-stages.json"


def write_completed_stage(
    run_dir: Path,
    *,
    stage: str,
    dispatch_index: int,
    outputs: tuple[str, ...] = (),
) -> None:
    """Record a stage as completed. Idempotent: skips if dispatch_index already exists."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _COMPLETED_STAGES_FILENAME
    entries = _read_json_list(path)

    # Dedup by dispatch_index
    existing_indices = {entry.get("dispatch_index") for entry in entries}
    if dispatch_index in existing_indices:
        return

    entries.append({
        "stage": stage,
        "dispatch_index": dispatch_index,
        "outputs": list(outputs),
    })
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_completed_stages(run_dir: Path) -> list[dict[str, object]]:
    return _read_json_list(run_dir / _COMPLETED_STAGES_FILENAME)


def _read_json_list(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
