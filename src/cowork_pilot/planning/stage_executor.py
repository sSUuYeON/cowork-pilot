from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.codex.event_stream import extract_thread_id
from cowork_pilot.planning.codex_bridge import run_cli_resume, run_exec_resume, run_exec_stage
from cowork_pilot.planning.marker_protocol import MarkerEnvelope, extract_terminal_marker_bundle
from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.question_policy import can_use_assumption
from cowork_pilot.planning.runtime_models import PlanningRuntimeState, ResumeHandleRef
from cowork_pilot.planning.runtime_orchestrator import apply_marker_bundle_to_run, apply_subprocess_failure
from cowork_pilot.planning.runtime_storage import (
    append_answer,
    append_approval_decision,
    append_assumption,
    read_run_state,
    write_run_state,
)

_WAITING_RESUME_STATES = {
    PlanningRuntimeState.WAITING_FOR_INPUT,
    PlanningRuntimeState.WAITING_FOR_APPROVAL,
}
_RESUME_CONTEXT_FILES = ("answer-log.md", "approval-log.md", "assumptions.md")


@dataclass(frozen=True)
class QueuedQuestion:
    event_id: str
    question: str
    blocking: bool


@dataclass(frozen=True)
class QueuedApproval:
    event_id: str
    subject: str
    blocking: bool


@dataclass(frozen=True)
class AssumptionRecord:
    event_id: str
    assumption: str
    confidence: str
    impact: str


@dataclass(frozen=True)
class StageExecutionResult:
    runtime_state: str
    completed_stage: str | None
    emitted_markers: tuple[MarkerEnvelope, ...]
    generated_outputs: tuple[str, ...]
    resume_handle: str | None
    queued_questions: tuple[QueuedQuestion, ...]
    queued_approvals: tuple[QueuedApproval, ...]
    assumption_records: tuple[AssumptionRecord, ...]


def execute_stage_subsession(
    *,
    run_dir: Path,
    stage: PlanningStage,
    prompt: str,
    assumption_scope: str = "broad_product_design",
    project_dir: Path | None = None,
) -> StageExecutionResult:
    initial_metadata = {
        key: value
        for key, value in read_run_state(run_dir).items()
        if key != "state"
    }
    codex_project_dir = str(project_dir) if project_dir is not None else str(run_dir)
    exec_result = run_exec_stage(stage=stage.value, prompt=prompt, run_dir=codex_project_dir)
    markers = tuple(extract_terminal_marker_bundle(exec_result.assistant_message))
    resume_handle = extract_thread_id(exec_result.event_lines) or None
    resume_ref = _build_resume_ref(stage=stage, resume_handle=resume_handle)

    if resume_ref is not None:
        _write_resume_state(
            run_dir=run_dir,
            state=PlanningRuntimeState.RUNNING_EXEC,
            resume_ref=resume_ref,
        )

    if exec_result.exit_code != 0:
        update = apply_subprocess_failure(
            run_dir=run_dir,
            current_state=PlanningRuntimeState.RUNNING_EXEC,
            exit_code=exec_result.exit_code,
            stage=stage.value,
        )
        if resume_ref is not None:
            _persist_resume_metadata(
                run_dir=run_dir,
                state=update.state,
                resume_ref=resume_ref,
                base_metadata=initial_metadata,
            )
        return _build_stage_result(
            update_state=update.state,
            markers=markers,
            resume_handle=resume_handle,
            assumption_records=(),
        )

    update = apply_marker_bundle_to_run(
        run_dir=run_dir,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=exec_result.assistant_message,
    )
    if resume_ref is not None:
        _persist_resume_metadata(
            run_dir=run_dir,
            state=update.state,
            resume_ref=resume_ref,
            base_metadata=initial_metadata,
        )

    assumption_records = _absorb_nonblocking_questions(
        run_dir=run_dir,
        stage=stage,
        markers=markers,
        assumption_scope=assumption_scope,
    )
    return _build_stage_result(
        update_state=update.state,
        markers=markers,
        resume_handle=resume_handle,
        assumption_records=assumption_records,
    )


def resume_stage_subsession(
    *,
    run_dir: Path,
    response_text: str,
    response_kind: str,
) -> StageExecutionResult:
    run_state = read_run_state(run_dir)
    initial_metadata = {
        key: value
        for key, value in run_state.items()
        if key != "state"
    }
    stage_name = str(run_state.get("stage", PlanningStage.CLASSIFICATION.value))
    resume_handle = str(run_state["resume_handle"])
    pending_event_id = str(run_state.get("pending_event_id", run_state.get("event_id", "resume-1")))
    resume_ref = ResumeHandleRef(
        surface="exec",
        resume_handle_kind=str(run_state.get("resume_handle_kind", "codex_thread_id")),
        resume_handle=resume_handle,
        stage=stage_name,
        substage=str(run_state.get("substage", "")),
    )

    write_run_state(
        run_dir,
        state=PlanningRuntimeState.RUNNING_CLI.value,
        metadata={
            **{key: value for key, value in run_state.items() if key != "state"},
            "surface": "cli",
        },
    )
    run_cli_resume(
        resume_handle=resume_handle,
        project_dir=str(run_dir),
        run_dir=str(run_dir),
    )

    if response_kind == "approval":
        append_approval_decision(run_dir, event_id=pending_event_id, decision=response_text)
        response_line = f"Approval resolved for {pending_event_id}: {response_text}"
    else:
        append_answer(run_dir, event_id=pending_event_id, answer=response_text)
        response_line = f"Answer recorded for {pending_event_id}: {response_text}"

    resume_context = _load_resume_context(run_dir)
    resumed_prompt = "\n".join([resume_context, response_line]).strip()
    write_run_state(
        run_dir,
        state=PlanningRuntimeState.RUNNING_EXEC.value,
        metadata={
            **{key: value for key, value in run_state.items() if key != "state"},
            "surface": "exec",
        },
    )
    exec_result = run_exec_resume(
        resume_handle=resume_handle,
        prompt=resumed_prompt,
        run_dir=str(run_dir),
    )
    markers = tuple(extract_terminal_marker_bundle(exec_result.assistant_message))

    if exec_result.exit_code != 0:
        update = apply_subprocess_failure(
            run_dir=run_dir,
            current_state=PlanningRuntimeState.RUNNING_EXEC,
            exit_code=exec_result.exit_code,
            stage=stage_name,
        )
        _persist_resume_metadata(
            run_dir=run_dir,
            state=update.state,
            resume_ref=resume_ref,
            base_metadata=initial_metadata,
        )
        return _build_stage_result(
            update_state=update.state,
            markers=markers,
            resume_handle=resume_handle,
            assumption_records=(),
        )

    update = apply_marker_bundle_to_run(
        run_dir=run_dir,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=exec_result.assistant_message,
    )
    _persist_resume_metadata(
        run_dir=run_dir,
        state=update.state,
        resume_ref=resume_ref,
        base_metadata=initial_metadata,
    )
    return _build_stage_result(
        update_state=update.state,
        markers=markers,
        resume_handle=resume_handle,
        assumption_records=(),
    )


def _absorb_nonblocking_questions(
    *,
    run_dir: Path,
    stage: PlanningStage,
    markers: tuple[MarkerEnvelope, ...],
    assumption_scope: str,
) -> tuple[AssumptionRecord, ...]:
    records: list[AssumptionRecord] = []

    for marker in markers:
        if marker.type != "INPUT_REQUIRED":
            continue
        blocking = bool(marker.payload["blocking"])
        if not can_use_assumption(stage=stage, assumption_scope=assumption_scope, blocking=blocking):
            continue

        recommended = str(marker.payload.get("recommended", "")).strip()
        question = str(marker.payload["question"])
        assumption_text = recommended or question
        record = AssumptionRecord(
            event_id=marker.event_id,
            assumption=assumption_text,
            confidence="medium",
            impact="medium",
        )
        append_assumption(
            run_dir,
            event_id=record.event_id,
            assumption=record.assumption,
            confidence=record.confidence,
            impact=record.impact,
        )
        records.append(record)

    return tuple(records)


def _build_stage_result(
    *,
    update_state: PlanningRuntimeState,
    markers: tuple[MarkerEnvelope, ...],
    resume_handle: str | None,
    assumption_records: tuple[AssumptionRecord, ...],
) -> StageExecutionResult:
    queued_questions = tuple(
        QueuedQuestion(
            event_id=marker.event_id,
            question=str(marker.payload["question"]),
            blocking=bool(marker.payload["blocking"]),
        )
        for marker in markers
        if marker.type == "INPUT_REQUIRED"
    )
    queued_approvals = tuple(
        QueuedApproval(
            event_id=marker.event_id,
            subject=str(marker.payload["subject"]),
            blocking=bool(marker.payload["blocking"]),
        )
        for marker in markers
        if marker.type == "APPROVAL_REQUIRED"
    )
    stage_complete = next((marker for marker in reversed(markers) if marker.type == "STAGE_COMPLETE"), None)
    return StageExecutionResult(
        runtime_state=update_state.value,
        completed_stage=stage_complete.stage if stage_complete is not None else None,
        emitted_markers=markers,
        generated_outputs=(
            tuple(str(path) for path in stage_complete.payload["outputs"])
            if stage_complete is not None
            else ()
        ),
        resume_handle=resume_handle,
        queued_questions=queued_questions,
        queued_approvals=queued_approvals,
        assumption_records=assumption_records,
    )


def _build_resume_ref(
    *,
    stage: PlanningStage,
    resume_handle: str | None,
) -> ResumeHandleRef | None:
    if not resume_handle:
        return None
    return ResumeHandleRef(
        surface="exec",
        resume_handle_kind="codex_thread_id",
        resume_handle=resume_handle,
        stage=stage.value,
        substage="",
    )


def _write_resume_state(
    *,
    run_dir: Path,
    state: PlanningRuntimeState,
    resume_ref: ResumeHandleRef,
) -> None:
    current_metadata = {
        key: value
        for key, value in read_run_state(run_dir).items()
        if key != "state"
    }
    current_metadata.update(
        {
            "resume_handle": resume_ref.resume_handle,
            "resume_handle_kind": resume_ref.resume_handle_kind,
            "surface": resume_ref.surface,
            "stage": resume_ref.stage,
            "substage": resume_ref.substage,
        }
    )
    write_run_state(
        run_dir,
        state=state.value,
        metadata=current_metadata,
    )


def _persist_resume_metadata(
    *,
    run_dir: Path,
    state: PlanningRuntimeState,
    resume_ref: ResumeHandleRef,
    base_metadata: dict[str, object] | None = None,
) -> None:
    metadata = {
        **(base_metadata or {}),
        **{key: value for key, value in read_run_state(run_dir).items() if key != "state"},
    }
    metadata["resume_handle"] = resume_ref.resume_handle
    metadata["resume_handle_kind"] = resume_ref.resume_handle_kind
    metadata["surface"] = "exec"
    metadata.setdefault("stage", resume_ref.stage)
    metadata.setdefault("substage", resume_ref.substage)
    metadata.pop("pending_event_id", None)
    if state in _WAITING_RESUME_STATES:
        event_id = metadata.get("event_id")
        if isinstance(event_id, str) and event_id:
            metadata["pending_event_id"] = event_id
    write_run_state(run_dir, state=state.value, metadata=metadata)


def _load_resume_context(run_dir: Path) -> str:
    sections: list[str] = []
    for name in _RESUME_CONTEXT_FILES:
        path = run_dir / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if content:
            sections.append(f"{name}:\n{content}")
    return "\n\n".join(sections)
