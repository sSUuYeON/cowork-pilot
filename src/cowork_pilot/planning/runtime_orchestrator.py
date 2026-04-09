from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.marker_protocol import extract_terminal_marker_bundle
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_storage import (
    append_approval_request,
    append_assumption,
    append_invalidation,
    append_question,
    append_runtime_event,
    write_run_state,
)


@dataclass(frozen=True)
class RuntimeUpdate:
    state: PlanningRuntimeState


_INVALIDATION_REASONS = {"stage_reopen_required", "replan_required"}


def apply_subprocess_failure(
    *,
    run_dir: Path,
    current_state: PlanningRuntimeState,
    exit_code: int,
    stage: str,
) -> RuntimeUpdate:
    if current_state is not PlanningRuntimeState.RUNNING_EXEC or exit_code == 0:
        return RuntimeUpdate(state=current_state)

    append_runtime_event(
        run_dir,
        {
            "event": "subprocess_failure",
            "exit_code": exit_code,
            "stage": stage,
        },
    )
    write_run_state(
        run_dir,
        state=PlanningRuntimeState.FAILED.value,
        metadata={
            "exit_code": exit_code,
            "stage": stage,
        },
    )
    return RuntimeUpdate(state=PlanningRuntimeState.FAILED)


def apply_marker_bundle_to_run(
    *,
    run_dir: Path,
    current_state: PlanningRuntimeState,
    message: str,
) -> RuntimeUpdate:
    state = current_state
    last_metadata: dict[str, object] | None = None

    for marker in extract_terminal_marker_bundle(message):
        append_runtime_event(
            run_dir,
            {
                "event": "marker",
                "type": marker.type,
                "event_id": marker.event_id,
                "stage": marker.stage,
                "reason": marker.reason,
                "payload": marker.payload,
            },
        )
        last_metadata = {
            "event_id": marker.event_id,
            "stage": marker.stage,
        }

        if marker.type == "INPUT_REQUIRED":
            blocking = bool(marker.payload["blocking"])
            append_question(
                run_dir,
                event_id=marker.event_id,
                question=str(marker.payload["question"]),
                blocking=blocking,
            )
            if blocking and state is PlanningRuntimeState.RUNNING_EXEC:
                state = PlanningRuntimeState.WAITING_FOR_INPUT

        elif marker.type == "APPROVAL_REQUIRED":
            blocking = bool(marker.payload["blocking"])
            append_approval_request(
                run_dir,
                event_id=marker.event_id,
                subject=str(marker.payload["subject"]),
                blocking=blocking,
            )
            if blocking and state is PlanningRuntimeState.RUNNING_EXEC:
                state = PlanningRuntimeState.WAITING_FOR_APPROVAL

        elif marker.type == "ASSUMPTION_LOG":
            append_assumption(
                run_dir,
                event_id=marker.event_id,
                assumption=str(marker.payload["assumption"]),
                confidence=str(marker.payload["confidence"]),
                impact=str(marker.payload["impact"]),
            )

        elif marker.type == "NEEDS_HUMAN":
            last_metadata["reason"] = marker.reason
            state = _handle_needs_human(
                run_dir=run_dir,
                current_state=state,
                event_id=marker.event_id,
                reason=marker.reason,
                stage=marker.stage,
            )

        elif marker.type == "STAGE_COMPLETE":
            last_metadata["reason"] = marker.reason
            last_metadata["summary"] = marker.payload["summary"]
            last_metadata["outputs"] = marker.payload["outputs"]

    if last_metadata is not None:
        write_run_state(run_dir, state=state.value, metadata=last_metadata)

    return RuntimeUpdate(state=state)


def _handle_needs_human(
    *,
    run_dir: Path,
    current_state: PlanningRuntimeState,
    event_id: str,
    reason: str,
    stage: str,
) -> PlanningRuntimeState:
    if reason in _INVALIDATION_REASONS:
        if current_state in {
            PlanningRuntimeState.RUNNING_CLI,
            PlanningRuntimeState.RUNNING_EXEC,
            PlanningRuntimeState.COMPLETED,
        }:
            append_invalidation(
                run_dir,
                event_id=event_id,
                reason=reason,
                affected_stage=stage,
            )
        if current_state in {
            PlanningRuntimeState.RUNNING_EXEC,
            PlanningRuntimeState.COMPLETED,
        }:
            return PlanningRuntimeState.WAITING_FOR_HUMAN

    return PlanningRuntimeState.ESCALATED
