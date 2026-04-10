from __future__ import annotations

from pathlib import Path

from cowork_pilot.codex.event_stream import extract_thread_id
from cowork_pilot.planning.codex_bridge import run_exec_resume, run_exec_stage
from cowork_pilot.planning.models import PlanningContext, PlanningPipelineResult, PlanningStage
from cowork_pilot.planning import stage_executor
from cowork_pilot.planning.pipeline import (
    continue_planning_stage_graph,
    load_planning_pipeline_result_from_run_dir,
    run_planning_stage_graph,
)
from cowork_pilot.planning.runtime_models import PlanningRuntimeState, ResumeHandleRef
from cowork_pilot.planning.runtime_orchestrator import apply_marker_bundle_to_run, apply_subprocess_failure
from cowork_pilot.planning.runtime_storage import (
    advance_pipeline_state,
    append_answer,
    append_approval_decision,
    read_run_state,
    write_run_state,
)

_WAITING_RESUME_STATES = {
    PlanningRuntimeState.WAITING_FOR_INPUT,
    PlanningRuntimeState.WAITING_FOR_APPROVAL,
}


def run_planning_pipeline(
    context: PlanningContext | None = None,
    *,
    interactive: bool = False,
) -> PlanningPipelineResult:
    return run_planning_stage_graph(context, interactive=interactive)


def resume_planning_pipeline(
    *,
    run_dir: Path,
    response_text: str = "",
    response_kind: str = "answer",
    interactive: bool = False,
) -> PlanningPipelineResult:
    """Public API for resuming a waiting planning pipeline.

    This is the function called by the CLI ``planning resume`` command.

    When *interactive* is True and *response_text* is empty, the function
    prompts the user in the current terminal for the pending question /
    approval before resuming.
    """
    run_state = read_run_state(run_dir)
    current_state = str(run_state.get("state", ""))

    if current_state in {
        PlanningRuntimeState.WAITING_FOR_INPUT.value,
        PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
    }:
        # Interactive path: prompt in terminal when no explicit response given
        if not response_text and interactive:
            from cowork_pilot.planning.terminal_ui import prompt_for_pending_response

            terminal_response = prompt_for_pending_response(run_dir)
            if terminal_response is not None:
                response_text = terminal_response.text
                response_kind = terminal_response.kind
            else:
                # User cancelled — return current state
                return load_planning_pipeline_result_from_run_dir(run_dir)

        return resume_planning_pipeline_with_user_response(
            run_dir=run_dir,
            response_text=response_text,
            response_kind=response_kind,
            interactive=interactive,
        )

    # Not waiting — try continuing from checkpoint
    return continue_planning_stage_graph(run_dir=run_dir, interactive=interactive)


def resume_planning_pipeline_with_user_response(
    *,
    run_dir: Path,
    response_text: str,
    response_kind: str,
    interactive: bool = False,
) -> PlanningPipelineResult:
    resumed_stage = stage_executor.resume_stage_subsession(
        run_dir=run_dir,
        response_text=response_text,
        response_kind=response_kind,
    )

    # If stage returned another blocking question, try to resolve interactively
    resumed_stage = stage_executor.resolve_blocking_interactions(
        run_dir=run_dir,
        stage_result=resumed_stage,
        interactive=interactive,
    )

    if resumed_stage.runtime_state in {
        PlanningRuntimeState.WAITING_FOR_INPUT.value,
        PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
        PlanningRuntimeState.WAITING_FOR_HUMAN.value,
        PlanningRuntimeState.FAILED.value,
        PlanningRuntimeState.ESCALATED.value,
    }:
        return load_planning_pipeline_result_from_run_dir(run_dir)

    advance_pipeline_state(run_dir)
    return continue_planning_stage_graph(run_dir=run_dir, interactive=interactive)


def _persist_resume_metadata(
    *,
    run_dir: Path,
    state: PlanningRuntimeState,
    resume_ref: ResumeHandleRef,
    surface: str,
) -> None:
    current_metadata = {
        key: value
        for key, value in read_run_state(run_dir).items()
        if key != "state"
    }
    current_metadata["resume_handle"] = resume_ref.resume_handle
    current_metadata["resume_handle_kind"] = resume_ref.resume_handle_kind
    current_metadata["surface"] = surface
    current_metadata.setdefault("stage", resume_ref.stage)
    current_metadata.setdefault("substage", resume_ref.substage)
    current_metadata.pop("pending_event_id", None)

    if state in _WAITING_RESUME_STATES:
        event_id = current_metadata.get("event_id")
        if isinstance(event_id, str) and event_id:
            current_metadata["pending_event_id"] = event_id

    write_run_state(run_dir, state=state.value, metadata=current_metadata)


def run_planning_stage_with_runtime(*, run_dir: Path, stage: str, prompt: str):
    exec_result = run_exec_stage(stage=stage, prompt=prompt, run_dir=str(run_dir))
    resume_ref: ResumeHandleRef | None = None

    thread_id = extract_thread_id(exec_result.event_lines)
    if thread_id:
        resume_ref = ResumeHandleRef(
            surface="exec",
            resume_handle_kind="codex_thread_id",
            resume_handle=thread_id,
            stage=stage,
            substage="",
        )
        write_run_state(
            run_dir,
            state=PlanningRuntimeState.RUNNING_EXEC.value,
            metadata={
                "resume_handle": resume_ref.resume_handle,
                "resume_handle_kind": resume_ref.resume_handle_kind,
                "surface": resume_ref.surface,
                "stage": resume_ref.stage,
                "substage": resume_ref.substage,
            },
        )

    if exec_result.exit_code != 0:
        update = apply_subprocess_failure(
            run_dir=run_dir,
            current_state=PlanningRuntimeState.RUNNING_EXEC,
            exit_code=exec_result.exit_code,
            stage=stage,
        )
        if resume_ref is not None:
            _persist_resume_metadata(
                run_dir=run_dir,
                state=update.state,
                resume_ref=resume_ref,
                surface="exec",
            )
        return update

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
            surface="exec",
        )

    return update


def resume_planning_waiting_run_with_cli(
    *,
    run_dir: Path,
    response_text: str,
    response_kind: str,
):
    """Deprecated — delegates to ``stage_executor.resume_stage_subsession``.

    Kept for backward-compatibility with existing callers / tests.
    Uses exec-resume only (no RUNNING_CLI intermediate).
    """
    result = stage_executor.resume_stage_subsession(
        run_dir=run_dir,
        response_text=response_text,
        response_kind=response_kind,
    )
    from cowork_pilot.planning.runtime_orchestrator import RuntimeUpdate
    return RuntimeUpdate(state=PlanningRuntimeState(result.runtime_state))
