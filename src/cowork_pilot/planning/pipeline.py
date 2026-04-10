from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cowork_pilot.planning.authoring import write_exec_plan
from cowork_pilot.planning.brownfield import (
    run_code_observation_extraction,
    run_gap_synthesis,
    run_observation_synthesis,
)
from cowork_pilot.planning.classification import (
    classify_project,
    reclassify_brownfield_after_observation,
    reclassify_greenfield_after_completeness,
)
from cowork_pilot.planning.completion_verifier import verify_stage_completion
from cowork_pilot.planning.completeness import run_completeness_review
from cowork_pilot.planning.docs_inventory import check_core_docs, select_adaptive_docs
from cowork_pilot.planning.handoffs import build_stage_read_set, load_stage_handoff, write_stage_handoff
from cowork_pilot.planning.models import (
    ClassificationSnapshot,
    PlanningContext,
    PlanningPipelineResult,
    PlanningStage,
    ProjectMode,
    SizeClass,
    StageDispatch,
)
from cowork_pilot.planning.packing import pack_plans
from cowork_pilot.planning.quality_gate import evaluate_stage_gate, rollback_stage
from cowork_pilot.planning.prompts import render_stage_prompt
from cowork_pilot.planning.request_normalization import (
    NormalizedPlanningRequest,
    normalize_planning_request,
)
from cowork_pilot.planning.review import run_plan_review
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.recovery import recover_interrupted_stage, RecoveryDecision
from cowork_pilot.planning.runtime_storage import (
    read_completed_stages,
    read_pipeline_state,
    read_run_state,
    write_completed_stage,
    write_pipeline_state,
    write_run_state,
)
from cowork_pilot.planning.scope import build_scope_map
from cowork_pilot.planning.session_profiles import (
    ARTIFACT_OWNERSHIP_TABLE,
    resolve_brownfield_extraction_slices,
    resolve_stage_execution_kind,
    resolve_stage_profile,
)
from cowork_pilot.planning.sizing import size_work_items
from cowork_pilot.planning.spec_sources import (
    detect_project_convention_profile,
    resolve_document_role_mapping,
)
from cowork_pilot.planning import stage_executor
from cowork_pilot.planning.summary import build_pipeline_summary, print_pipeline_summary

_STOP_STATES = {
    PlanningRuntimeState.WAITING_FOR_INPUT.value,
    PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
    PlanningRuntimeState.WAITING_FOR_HUMAN.value,
    PlanningRuntimeState.FAILED.value,
    PlanningRuntimeState.ESCALATED.value,
}
_RUNTIME_LOGS = ("assumptions.md", "answer-log.md", "approval-log.md")
_PIPELINE_SNAPSHOT_KEY = "pipeline_snapshot"


@dataclass
class _PipelineRuntime:
    result_context: PlanningContext
    runtime_context: PlanningContext
    project_dir: Path
    run_dir: Path
    snapshot: ClassificationSnapshot
    normalized_request: NormalizedPlanningRequest
    core_docs: list[str] = field(default_factory=list)
    adaptive_docs: list[str] = field(default_factory=list)
    scope_map: dict[str, list[str]] = field(default_factory=dict)
    work_items: list[str] = field(default_factory=list)
    packed_plans: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    gap_artifacts: dict[str, list[str]] = field(default_factory=dict)
    exec_plan_path: Path | None = None
    exec_plan_paths: tuple[Path, ...] = ()


def build_stage_dispatch_plan(
    context: PlanningContext,
    *,
    size_class: SizeClass,
) -> tuple[StageDispatch, ...]:
    dispatches: list[StageDispatch] = []
    order = 1

    order = _append_stage_dispatches(dispatches, PlanningStage.CLASSIFICATION, size_class, order)

    if context.mode is ProjectMode.BROWNFIELD:
        for slice_name in resolve_brownfield_extraction_slices(size_class):
            dispatches.append(
                _build_stage_dispatch(
                    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
                    size_class,
                    order,
                    slice_name=slice_name,
                )
            )
            order += 1
        dispatches.append(
            _build_stage_dispatch(PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS, size_class, order)
        )
        order += 1
        dispatches.append(
            _build_stage_dispatch(PlanningStage.BROWNFIELD_GAP_SYNTHESIS, size_class, order)
        )
        order += 1
        order = _append_stage_dispatches(dispatches, PlanningStage.CORE_DOCS_CHECK, size_class, order)
        order = _append_stage_dispatches(
            dispatches, PlanningStage.ADAPTIVE_DOCS_SELECTION, size_class, order
        )
        order = _append_stage_dispatches(
            dispatches, PlanningStage.CORE_DOCS_PRESENCE_REVIEW, size_class, order
        )
    else:
        order = _append_stage_dispatches(dispatches, PlanningStage.CORE_DOCS_CHECK, size_class, order)
        order = _append_stage_dispatches(
            dispatches, PlanningStage.ADAPTIVE_DOCS_SELECTION, size_class, order
        )
        order = _append_stage_dispatches(
            dispatches, PlanningStage.PRODUCT_COMPLETENESS_REVIEW, size_class, order
        )

    order = _append_stage_dispatches(dispatches, PlanningStage.SCOPE_STRUCTURING, size_class, order)
    order = _append_stage_dispatches(dispatches, PlanningStage.WORK_SIZING, size_class, order)
    order = _append_stage_dispatches(dispatches, PlanningStage.PLAN_PACKING, size_class, order)
    order = _append_stage_dispatches(dispatches, PlanningStage.PLAN_REVIEW, size_class, order)
    order = _append_stage_dispatches(dispatches, PlanningStage.EXEC_PLAN_SKELETON, size_class, order)

    return tuple(dispatches)


def continue_planning_stage_graph(*, run_dir: Path, interactive: bool = False) -> PlanningPipelineResult:
    pipeline_state = read_pipeline_state(run_dir)
    start_index = int(pipeline_state.get("next_dispatch_index", 0))
    restored_context = _restore_context_from_pipeline_state(run_dir)
    return _run_planning_stage_graph(restored_context, start_index=start_index, interactive=interactive)


def load_planning_pipeline_result_from_run_dir(run_dir: Path) -> PlanningPipelineResult:
    restored_context = _restore_context_from_pipeline_state(run_dir)
    runtime = _initialize_runtime(restored_context)
    run_state = read_run_state(run_dir)
    exec_plan_path = runtime.project_dir / "docs" / "exec-plans" / "planning" / "exec-plan.md"
    return PlanningPipelineResult(
        context=runtime.result_context,
        snapshot=runtime.snapshot,
        core_docs=runtime.core_docs,
        adaptive_docs=runtime.adaptive_docs,
        scope_map=runtime.scope_map,
        work_items=runtime.work_items,
        packed_plans=runtime.packed_plans,
        review_notes=runtime.review_notes,
        stage_prompt=render_stage_prompt(PlanningStage.CLASSIFICATION, runtime.result_context),
        exec_plan_path=exec_plan_path if exec_plan_path.exists() else None,
        runtime_state=str(run_state.get("state", PlanningRuntimeState.PENDING.value)),
        stopped_stage=str(run_state.get("stage", "")),
    )


def run_planning_stage_graph(
    context: PlanningContext | None = None,
    interactive: bool = False,
) -> PlanningPipelineResult:
    return _run_planning_stage_graph(
        context if context is not None else PlanningContext(),
        start_index=0,
        interactive=interactive,
    )


def _run_planning_stage_graph(
    context: PlanningContext,
    *,
    start_index: int,
    interactive: bool = False,
) -> PlanningPipelineResult:
    runtime = _initialize_runtime(context)

    if runtime.normalized_request.waiting_for_change_request:
        _persist_runtime_state(runtime, next_dispatch_index=start_index)
        return PlanningPipelineResult(
            context=runtime.result_context,
            snapshot=runtime.snapshot,
            core_docs=[],
            adaptive_docs=[],
            scope_map={},
            work_items=[],
            packed_plans=[],
            review_notes=[],
            stage_prompt=render_stage_prompt(PlanningStage.CLASSIFICATION, runtime.result_context),
            exec_plan_path=None,
            runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
            stopped_stage="request_normalization",
        )

    dispatch_context = PlanningContext(
        run_dir=runtime.run_dir,
        project_dir=runtime.project_dir,
        target_version=runtime.runtime_context.target_version,
        mode=runtime.snapshot.project_mode,
        explicit_mode=True,
        request_text=runtime.runtime_context.request_text,
        request_source=runtime.runtime_context.request_source,
        change_request_text=runtime.runtime_context.change_request_text,
        change_request_source=runtime.runtime_context.change_request_source,
    )
    dispatches = build_stage_dispatch_plan(dispatch_context, size_class=runtime.snapshot.size_class)
    _restore_runtime_snapshot(runtime)
    _persist_runtime_state(runtime, next_dispatch_index=start_index)
    previous_handoff = _find_previous_handoff(runtime.run_dir, dispatches, start_index)

    dispatches_list: list[StageDispatch] = list(dispatches)
    dispatch_index = start_index

    # Recovery preamble: check if last run was interrupted
    run_state = read_run_state(runtime.run_dir)
    if run_state.get("state") == PlanningRuntimeState.RUNNING_EXEC.value and start_index > 0:
        interrupted_stage = str(run_state.get("stage", ""))
        if interrupted_stage and start_index < len(dispatches_list):
            interrupted_dispatch = dispatches_list[start_index]
            ai_outputs = tuple(
                str(runtime.run_dir / f"{interrupted_stage}-output.md"),
            )
            decision = recover_interrupted_stage(
                run_dir=runtime.run_dir,
                stage=interrupted_stage,
                expected_outputs=ai_outputs,
            )
            if decision == RecoveryDecision.MARK_COMPLETED:
                write_completed_stage(
                    runtime.run_dir,
                    stage=interrupted_stage,
                    dispatch_index=start_index,
                )

    # Load completed stages for skip logic
    completed_indices = {
        entry.get("dispatch_index")
        for entry in read_completed_stages(runtime.run_dir)
    }

    while dispatch_index < len(dispatches_list):
        dispatch = dispatches_list[dispatch_index]

        # Skip already-completed stages
        if dispatch_index in completed_indices:
            outputs = _apply_stage_completion(runtime, dispatch)
            previous_handoff = _write_dispatch_handoff(
                runtime=runtime,
                dispatch=dispatch,
                previous_handoff=previous_handoff,
                outputs=outputs,
                stage_result=None,
            )
            _persist_runtime_state(runtime, next_dispatch_index=dispatch_index + 1)
            dispatch_index += 1
            continue

        if dispatch.execution_kind == "local":
            outputs = _apply_stage_completion(runtime, dispatch)
            file_verdict = verify_stage_completion(dispatch.stage, run_dir=runtime.run_dir)
            if not file_verdict.passed and dispatch.stage in ARTIFACT_OWNERSHIP_TABLE:
                write_run_state(
                    runtime.run_dir,
                    state=PlanningRuntimeState.ESCALATED.value,
                    metadata={"stage": dispatch.stage.value, "reason": "local_stage_file_evidence_failed"},
                )
                _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
                return _build_pipeline_result(
                    runtime,
                    runtime_state=PlanningRuntimeState.ESCALATED.value,
                    stopped_stage=dispatch.stage.value,
                )
            previous_handoff = _write_dispatch_handoff(
                runtime=runtime,
                dispatch=dispatch,
                previous_handoff=previous_handoff,
                outputs=outputs,
                stage_result=None,
            )
            _persist_runtime_state(runtime, next_dispatch_index=dispatch_index + 1)
            dispatch_index += 1
            continue

        stage_prompt = _render_dispatch_prompt(runtime, dispatch, previous_handoff)
        stage_result = stage_executor.execute_stage_subsession(
            run_dir=runtime.run_dir,
            stage=dispatch.stage,
            prompt=stage_prompt,
            project_dir=runtime.project_dir,
        )
        stage_result = stage_executor.resolve_blocking_interactions(
            run_dir=runtime.run_dir,
            stage_result=stage_result,
            interactive=interactive,
        )
        if stage_result.runtime_state in _STOP_STATES and stage_result.completed_stage is None:
            _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
            return _build_pipeline_result(
                runtime,
                runtime_state=stage_result.runtime_state,
                stopped_stage=dispatch.stage.value,
            )

        outputs = _apply_stage_completion(runtime, dispatch)

        # Post-stage quality gate check on AI-generated file outputs
        ai_file_outputs = tuple(
            o for o in (stage_result.generated_outputs or ())
            if ("/" in o or o.endswith(".md"))
            and (Path(o).is_absolute() and Path(o).exists() or (runtime.run_dir / o).exists())
        )
        if ai_file_outputs:
            gate_result = evaluate_stage_gate(
                stage=dispatch.stage.value,
                run_dir=runtime.run_dir,
                expected_outputs=ai_file_outputs,
            )
            if not gate_result.passed and gate_result.retry_recommended:
                rb = rollback_stage(
                    run_dir=runtime.run_dir,
                    dispatch_index=dispatch_index,
                    outputs_to_remove=outputs,
                )
                if rb.rolled_back:
                    # Don't advance — retry this dispatch
                    continue
                if rb.escalated:
                    write_run_state(
                        runtime.run_dir,
                        state=PlanningRuntimeState.ESCALATED.value,
                        metadata={"escalated_dispatch_index": dispatch_index, "stage": dispatch.stage.value},
                    )
                    _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
                    return _build_pipeline_result(
                        runtime,
                        runtime_state=PlanningRuntimeState.ESCALATED.value,
                        stopped_stage=dispatch.stage.value,
                    )

        # File-evidence completion check (authoritative — STAGE_COMPLETE.outputs is hint only)
        file_verdict = verify_stage_completion(dispatch.stage, run_dir=runtime.run_dir)
        if not file_verdict.passed:
            rb = rollback_stage(
                run_dir=runtime.run_dir,
                dispatch_index=dispatch_index,
                outputs_to_remove=outputs,
            )
            if rb.rolled_back:
                continue
            if rb.escalated:
                write_run_state(
                    runtime.run_dir,
                    state=PlanningRuntimeState.ESCALATED.value,
                    metadata={
                        "escalated_dispatch_index": dispatch_index,
                        "stage": dispatch.stage.value,
                        "reason": f"file_evidence_failed: {file_verdict.reason or file_verdict.missing_artifacts}",
                    },
                )
                _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
                return _build_pipeline_result(
                    runtime,
                    runtime_state=PlanningRuntimeState.ESCALATED.value,
                    stopped_stage=dispatch.stage.value,
                )

        # Dynamic injection phase 1: after SKELETON, inject per-feature outline dispatches
        if dispatch.stage is PlanningStage.EXEC_PLAN_SKELETON:
            skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"
            if skeleton_path.exists():
                from cowork_pilot.planning.outline import parse_skeleton_features, build_feature_outline_dispatches
                features = parse_skeleton_features(skeleton_path.read_text(encoding="utf-8"))
                if features:
                    fo_dispatches = build_feature_outline_dispatches(features, start_order=dispatch.order + 1)
                    dispatches_list[dispatch_index + 1:dispatch_index + 1] = list(fo_dispatches)

        # Dynamic injection phase 2: after ALL feature outlines done, run local merge + inject detail dispatches
        if dispatch.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
            remaining_fo = any(
                d.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE
                for d in dispatches_list[dispatch_index + 1:]
            )
            if not remaining_fo:
                from cowork_pilot.planning.outline import merge_feature_outlines, parse_outline_plans, build_detail_dispatches
                outline_path = merge_feature_outlines(run_dir=runtime.run_dir)
                plans = parse_outline_plans(outline_path.read_text(encoding="utf-8"))
                if plans:
                    detail_dispatches = build_detail_dispatches(plans, start_order=dispatch.order + 1)
                    dispatches_list[dispatch_index + 1:dispatch_index + 1] = list(detail_dispatches)

        previous_handoff = _write_dispatch_handoff(
            runtime=runtime,
            dispatch=dispatch,
            previous_handoff=previous_handoff,
            outputs=outputs or stage_result.generated_outputs,
            stage_result=stage_result,
        )
        write_completed_stage(
            runtime.run_dir,
            stage=dispatch.stage.value,
            dispatch_index=dispatch_index,
            outputs=outputs or stage_result.generated_outputs or (),
        )
        _persist_runtime_state(runtime, next_dispatch_index=dispatch_index + 1)
        dispatch_index += 1

    current_state = read_run_state(runtime.run_dir)
    write_run_state(
        runtime.run_dir,
        state=PlanningRuntimeState.COMPLETED.value,
        metadata={key: value for key, value in current_state.items() if key != "state"},
    )
    _persist_runtime_state(runtime, next_dispatch_index=len(dispatches_list))

    summary = build_pipeline_summary(run_dir=runtime.run_dir, project_dir=runtime.project_dir)
    print_pipeline_summary(summary)

    return _build_pipeline_result(runtime, runtime_state=PlanningRuntimeState.COMPLETED.value, stopped_stage="")


def _resolve_stage_artifact_path(stage: PlanningStage, run_dir: Path) -> Path | None:
    """Resolve primary artifact path from ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return run_dir / ownership.completion_artifacts[0]


def _apply_stage_completion(
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
) -> tuple[str, ...]:
    stage = dispatch.stage
    if stage is PlanningStage.CLASSIFICATION:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.classification import parse_classification_report
            new_snapshot = parse_classification_report(result_file)
            if new_snapshot.size_class != runtime.snapshot.size_class:
                import logging
                logging.getLogger(__name__).warning(
                    "AI classification changed size_class from %s to %s",
                    runtime.snapshot.size_class.value,
                    new_snapshot.size_class.value,
                )
            runtime.snapshot = new_snapshot
        return (
            f"project_mode={runtime.snapshot.project_mode.value}",
            f"size_class={runtime.snapshot.size_class.value}",
        )

    if stage is PlanningStage.CORE_DOCS_CHECK:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.docs_inventory import parse_core_docs_check
            parsed = parse_core_docs_check(result_file)
            runtime.core_docs = list(parsed.get("required_doc_roles", []))
        else:
            runtime.core_docs = check_core_docs(runtime.snapshot)
        return tuple(runtime.core_docs)

    if stage is PlanningStage.ADAPTIVE_DOCS_SELECTION:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.docs_inventory import parse_adaptive_docs_selection
            parsed = parse_adaptive_docs_selection(result_file)
            runtime.adaptive_docs = list(parsed.get("selected_roles", []))
        else:
            runtime.adaptive_docs = select_adaptive_docs(runtime.snapshot, runtime.core_docs)
        return tuple(runtime.adaptive_docs)

    if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
        completeness_result = run_completeness_review(
            runtime.core_docs,
            runtime.adaptive_docs,
            snapshot=runtime.snapshot,
            run_dir=runtime.run_dir,
        )
        runtime.snapshot = reclassify_greenfield_after_completeness(
            current_snapshot=runtime.snapshot,
            completeness_result=completeness_result,
            already_reclassified=False,
        )
        runtime.gap_artifacts = {
            "coverage-gap.md": [
                result.category
                for result in completeness_result.category_results
                if not result.passed
            ]
        }
        outputs: list[str] = []
        if completeness_result.review_path is not None:
            outputs.append(str(completeness_result.review_path.relative_to(runtime.run_dir)))
        if completeness_result.coverage_gap_path is not None:
            outputs.append(str(completeness_result.coverage_gap_path.relative_to(runtime.run_dir)))
        return tuple(outputs)

    if stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION:
        slices = (dispatch.slice_name,) if dispatch.slice_name else resolve_brownfield_extraction_slices(
            runtime.snapshot.size_class
        )
        extraction_result = run_code_observation_extraction(
            project_dir=runtime.run_dir,
            slices=slices,
            size_class=runtime.snapshot.size_class,
        )
        return extraction_result.generated_files

    if stage is PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS:
        synthesis_result = run_observation_synthesis(run_dir=runtime.run_dir)
        return synthesis_result.generated_files

    if stage is PlanningStage.BROWNFIELD_GAP_SYNTHESIS:
        gap_result = run_gap_synthesis(
            run_dir=runtime.run_dir,
            canonical_specs=("docs/specs/index.md",),
            change_request_summary=(
                runtime.normalized_request.change_request_summary
                or "Review existing implementation gaps"
            ),
        )
        observation_summary_path = runtime.run_dir / "implementation-observation-summary.md"
        runtime.snapshot = reclassify_brownfield_after_observation(
            current_snapshot=runtime.snapshot,
            observation_summary=observation_summary_path.read_text(encoding="utf-8"),
            confirmed_change_impact="medium",
            already_reclassified=False,
        )
        runtime.gap_artifacts = {
            "spec-implementation-gap.md": [
                entry.path for entry in gap_result.gap_entries if entry.path != "change-impact-gap.md"
            ],
            "change-impact-gap.md": ["change-impact-gap.md"],
        }
        return gap_result.generated_files

    if stage is PlanningStage.CORE_DOCS_PRESENCE_REVIEW:
        return tuple(runtime.core_docs + runtime.adaptive_docs)

    if stage is PlanningStage.SCOPE_STRUCTURING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.scope import parse_scope_map
            runtime.scope_map = parse_scope_map(result_file)
        else:
            runtime.scope_map = build_scope_map(
                runtime.core_docs,
                runtime.adaptive_docs,
                snapshot=runtime.snapshot,
            )
        return tuple(runtime.scope_map.keys())

    if stage is PlanningStage.WORK_SIZING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.sizing import parse_work_sizing
            parsed_items = parse_work_sizing(result_file)
            runtime.work_items = [item["id"] if isinstance(item, dict) else str(item) for item in parsed_items]
        else:
            runtime.work_items = size_work_items(runtime.scope_map)
        return tuple(runtime.work_items)

    if stage is PlanningStage.PLAN_PACKING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.packing import parse_plan_packing
            parsed_plans = parse_plan_packing(result_file)
            runtime.packed_plans = [p["plan_name"] if isinstance(p, dict) else str(p) for p in parsed_plans]
        else:
            runtime.packed_plans = pack_plans(runtime.work_items)
        return tuple(runtime.packed_plans)

    if stage is PlanningStage.PLAN_REVIEW:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.review import parse_plan_review
            review_verdict = parse_plan_review(result_file)
        else:
            review_verdict = run_plan_review(runtime.packed_plans, gap_artifacts=runtime.gap_artifacts)
        runtime.review_notes = [issue.description for issue in review_verdict.issues]
        return tuple(runtime.review_notes)

    if stage is PlanningStage.EXEC_PLAN_AUTHORING:
        runtime.exec_plan_path = _write_pipeline_exec_plan(runtime)
        return (str(runtime.exec_plan_path),) if runtime.exec_plan_path is not None else ()

    if stage is PlanningStage.EXEC_PLAN_SKELETON:
        skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"
        return (str(skeleton_path),) if skeleton_path.exists() else ()

    if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
        feature_name = dispatch.substage
        outline_file = runtime.run_dir / "feature-outlines" / f"{feature_name}.md"
        return (str(outline_file),) if outline_file.exists() else ()

    if stage is PlanningStage.EXEC_PLAN_DETAIL:
        detail_source = runtime.run_dir / f"detail-{dispatch.substage}.md"
        if detail_source.exists():
            from cowork_pilot.planning.authoring import write_numbered_exec_plan
            dest_dir = runtime.project_dir / "docs" / "exec-plans" / "planning"
            result_path = write_numbered_exec_plan(detail_source, dest_dir, plan_name=dispatch.substage)
            if result_path is not None:
                runtime.exec_plan_paths = runtime.exec_plan_paths + (result_path,)
                return (str(result_path),)
        return ()

    return ()


def _append_stage_dispatches(
    dispatches: list[StageDispatch],
    stage: PlanningStage,
    size_class: SizeClass,
    order: int,
) -> int:
    profile = resolve_stage_profile(stage, size_class)
    if profile.substages:
        for substage in profile.substages:
            dispatches.append(_build_stage_dispatch(stage, size_class, order, substage=substage))
            order += 1
        return order

    dispatches.append(_build_stage_dispatch(stage, size_class, order))
    return order + 1


def _build_dispatch_decisions(dispatch: StageDispatch, outputs: tuple[str, ...]) -> tuple[str, ...]:
    decisions = [f"Completed {dispatch.stage.value}."]
    if dispatch.substage:
        decisions.append(f"Substage: {dispatch.substage}")
    if dispatch.slice_name:
        decisions.append(f"Slice: {dispatch.slice_name}")
    if outputs:
        decisions.append(f"Produced {len(outputs)} output item(s).")
    return tuple(decisions)


def _build_result_context(context: PlanningContext | None) -> PlanningContext:
    return context if context is not None else PlanningContext()


def _build_runtime_context(result_context: PlanningContext) -> PlanningContext:
    project_dir = (
        result_context.project_dir
        or _infer_project_dir_from_run_dir(result_context.run_dir)
        or result_context.run_dir
        or Path.cwd()
    )
    run_dir = result_context.run_dir or project_dir
    return PlanningContext(
        run_dir=run_dir,
        project_dir=project_dir,
        target_version=result_context.target_version,
        mode=result_context.mode,
        explicit_mode=result_context.explicit_mode,
        request_text=result_context.request_text,
        request_source=result_context.request_source,
        change_request_text=result_context.change_request_text,
        change_request_source=result_context.change_request_source,
    )


def _build_pipeline_result(
    runtime: _PipelineRuntime,
    *,
    runtime_state: str,
    stopped_stage: str,
) -> PlanningPipelineResult:
    return PlanningPipelineResult(
        context=runtime.result_context,
        snapshot=runtime.snapshot,
        core_docs=runtime.core_docs,
        adaptive_docs=runtime.adaptive_docs,
        scope_map=runtime.scope_map,
        work_items=runtime.work_items,
        packed_plans=runtime.packed_plans,
        review_notes=runtime.review_notes,
        stage_prompt=render_stage_prompt(PlanningStage.CLASSIFICATION, runtime.result_context),
        exec_plan_path=runtime.exec_plan_path,
        exec_plan_paths=runtime.exec_plan_paths,
        runtime_state=runtime_state,
        stopped_stage=stopped_stage,
    )


def _build_stage_dispatch(
    stage: PlanningStage,
    size_class: SizeClass,
    order: int,
    *,
    substage: str = "",
    slice_name: str = "",
) -> StageDispatch:
    return StageDispatch(
        stage=stage,
        execution_kind=resolve_stage_execution_kind(stage, size_class),
        order=order,
        substage=substage,
        slice_name=slice_name,
    )


def _canonical_doc_paths(runtime: _PipelineRuntime) -> tuple[Path, ...]:
    profile = detect_project_convention_profile(runtime.project_dir)
    mapping = resolve_document_role_mapping(profile)
    resolved: list[Path] = []

    for role in runtime.core_docs + runtime.adaptive_docs:
        doc_role = mapping.get(role)
        if doc_role is None:
            continue

        existing_path = next(
            (
                runtime.project_dir / candidate
                for candidate in doc_role.preferred_read_order
                if "*" not in candidate and (runtime.project_dir / candidate).exists()
            ),
            None,
        )
        resolved.append(existing_path or (runtime.project_dir / doc_role.preferred_write_target))

    return tuple(_dedupe_paths(resolved))


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _handoff_summary(previous_handoff: Path | None) -> str:
    if previous_handoff is None or not previous_handoff.exists():
        return ""
    handoff = load_stage_handoff(previous_handoff)
    summary_lines = [handoff.stage_purpose]
    summary_lines.extend(f"decision: {item}" for item in handoff.decisions)
    summary_lines.extend(f"assumption: {item}" for item in handoff.assumptions)
    summary_lines.extend(f"output: {item}" for item in handoff.outputs)
    return "\n".join(summary_lines)


def _infer_project_dir_from_run_dir(run_dir: Path | None) -> Path | None:
    if run_dir is None:
        return None

    if run_dir.parent.name != "planning-runs":
        return None
    if run_dir.parent.parent.name != "generated":
        return None
    if run_dir.parent.parent.parent.name != "docs":
        return None
    return run_dir.parent.parent.parent.parent


def _initialize_runtime(context: PlanningContext | None) -> _PipelineRuntime:
    result_context = _build_result_context(context)
    runtime_context = _build_runtime_context(result_context)
    snapshot = classify_project(runtime_context)
    normalized_request = normalize_planning_request(
        run_dir=runtime_context.run_dir or runtime_context.project_dir or Path.cwd(),
        project_dir=runtime_context.project_dir,
        project_mode=snapshot.project_mode,
        raw_request_text=runtime_context.request_text,
        raw_change_request_text=runtime_context.change_request_text,
    )
    return _PipelineRuntime(
        result_context=result_context,
        runtime_context=runtime_context,
        project_dir=runtime_context.project_dir or Path.cwd(),
        run_dir=runtime_context.run_dir or runtime_context.project_dir or Path.cwd(),
        snapshot=snapshot,
        normalized_request=normalized_request,
    )


def _render_dispatch_prompt(
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
    previous_handoff: Path | None,
) -> str:
    read_set = build_stage_read_set(
        run_dir=runtime.run_dir,
        canonical_docs=_canonical_doc_paths(runtime),
        previous_handoff=previous_handoff,
        runtime_logs=_RUNTIME_LOGS,
    )
    return render_stage_prompt(
        dispatch.stage,
        read_set=read_set,
        handoff_summary=_handoff_summary(previous_handoff),
        target_version=runtime.runtime_context.target_version,
    )


def _restore_context_from_pipeline_state(run_dir: Path) -> PlanningContext:
    pipeline_state = read_pipeline_state(run_dir)
    context_data = pipeline_state.get("context")
    if not isinstance(context_data, dict):
        return PlanningContext(run_dir=run_dir)

    mode_text = str(context_data.get("mode", ""))
    return PlanningContext(
        run_dir=Path(str(context_data.get("run_dir", ""))) if context_data.get("run_dir") else run_dir,
        project_dir=(
            Path(str(context_data.get("project_dir", "")))
            if context_data.get("project_dir")
            else _infer_project_dir_from_run_dir(run_dir)
        ),
        target_version=str(context_data.get("target_version", "")),
        mode=ProjectMode(mode_text) if mode_text else None,
        explicit_mode=bool(context_data.get("explicit_mode", False)),
        request_text=str(context_data.get("request_text", "")),
        request_source=str(context_data.get("request_source", "")),
        change_request_text=str(context_data.get("change_request_text", "")),
        change_request_source=str(context_data.get("change_request_source", "")),
    )


def _restore_runtime_snapshot(runtime: _PipelineRuntime) -> None:
    run_state = read_run_state(runtime.run_dir)
    snapshot_data = run_state.get(_PIPELINE_SNAPSHOT_KEY)
    if not isinstance(snapshot_data, dict):
        return

    classification_snapshot = snapshot_data.get("classification_snapshot")
    if isinstance(classification_snapshot, dict):
        runtime.snapshot = _deserialize_classification_snapshot(classification_snapshot)
    runtime.core_docs = list(snapshot_data.get("core_docs", []))
    runtime.adaptive_docs = list(snapshot_data.get("adaptive_docs", []))
    runtime.scope_map = {
        str(key): [str(item) for item in value]
        for key, value in dict(snapshot_data.get("scope_map", {})).items()
    }
    runtime.work_items = [str(item) for item in snapshot_data.get("work_items", [])]
    runtime.packed_plans = [str(item) for item in snapshot_data.get("packed_plans", [])]
    runtime.review_notes = [str(item) for item in snapshot_data.get("review_notes", [])]
    runtime.gap_artifacts = {
        str(key): [str(item) for item in value]
        for key, value in dict(snapshot_data.get("gap_artifacts", {})).items()
    }
    exec_plan_path = str(snapshot_data.get("exec_plan_path", "")).strip()
    runtime.exec_plan_path = Path(exec_plan_path) if exec_plan_path else None


def _persist_runtime_state(runtime: _PipelineRuntime, *, next_dispatch_index: int) -> None:
    write_pipeline_state(
        runtime.run_dir,
        context=runtime.runtime_context,
        next_dispatch_index=next_dispatch_index,
    )
    current_state = read_run_state(runtime.run_dir)
    write_run_state(
        runtime.run_dir,
        state=str(current_state.get("state", PlanningRuntimeState.PENDING.value)),
        metadata={
            **{key: value for key, value in current_state.items() if key != "state"},
            _PIPELINE_SNAPSHOT_KEY: _serialize_pipeline_snapshot(runtime),
        },
    )


def _write_dispatch_handoff(
    *,
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
    previous_handoff: Path | None,
    outputs: tuple[str, ...],
    stage_result: stage_executor.StageExecutionResult | None,
) -> Path:
    assumptions = (
        tuple(record.assumption for record in stage_result.assumption_records)
        if stage_result is not None
        else ()
    )
    unresolved_questions = (
        tuple(question.question for question in stage_result.queued_questions if question.blocking)
        if stage_result is not None
        else ()
    )
    read_set = build_stage_read_set(
        run_dir=runtime.run_dir,
        canonical_docs=_canonical_doc_paths(runtime),
        previous_handoff=previous_handoff,
        runtime_logs=_RUNTIME_LOGS,
    )
    return write_stage_handoff(
        run_dir=runtime.run_dir,
        order=dispatch.order,
        stage=dispatch.stage,
        decisions=_build_dispatch_decisions(dispatch, outputs),
        unresolved_questions=unresolved_questions,
        assumptions=assumptions,
        outputs=outputs,
        next_read_set=read_set,
    )


def _write_pipeline_exec_plan(runtime: _PipelineRuntime) -> Path:
    source_path = runtime.run_dir / "draft-exec-plan.md"
    source_path.write_text(
        "# Planning Exec Plan\n\n" + "\n".join(f"- {item}" for item in runtime.packed_plans) + "\n",
        encoding="utf-8",
    )
    return write_exec_plan(
        source_path,
        runtime.project_dir / "docs" / "exec-plans" / "planning",
        plan_name="exec-plan.md",
    ) or source_path


def _serialize_pipeline_snapshot(runtime: _PipelineRuntime) -> dict[str, object]:
    return {
        "classification_snapshot": _serialize_classification_snapshot(runtime.snapshot),
        "core_docs": list(runtime.core_docs),
        "adaptive_docs": list(runtime.adaptive_docs),
        "scope_map": runtime.scope_map,
        "work_items": list(runtime.work_items),
        "packed_plans": list(runtime.packed_plans),
        "review_notes": list(runtime.review_notes),
        "gap_artifacts": runtime.gap_artifacts,
        "exec_plan_path": str(runtime.exec_plan_path) if runtime.exec_plan_path is not None else "",
    }


def _serialize_classification_snapshot(snapshot: ClassificationSnapshot) -> dict[str, object]:
    return {
        "project_mode": snapshot.project_mode.value,
        "size_class": snapshot.size_class.value,
        "product_type": snapshot.product_type,
        "confidence": snapshot.confidence,
        "borderline": snapshot.borderline,
        "axis_observations": snapshot.axis_observations,
        "rationale": list(snapshot.rationale),
        "classification_snapshot_kind": snapshot.classification_snapshot_kind,
        "initial_size_class": snapshot.initial_size_class.value if snapshot.initial_size_class is not None else "",
        "confirmed_size_class": snapshot.confirmed_size_class.value if snapshot.confirmed_size_class is not None else "",
        "initial_borderline": snapshot.initial_borderline,
        "confirmed_borderline": snapshot.confirmed_borderline,
        "confirmed_change_impact": snapshot.confirmed_change_impact or "",
        "brownfield_uncertainty": snapshot.brownfield_uncertainty or "",
        "requires_observation_reclassification": snapshot.requires_observation_reclassification,
    }


def _deserialize_classification_snapshot(data: dict[str, object]) -> ClassificationSnapshot:
    initial_size_class = str(data.get("initial_size_class", ""))
    confirmed_size_class = str(data.get("confirmed_size_class", ""))
    confirmed_change_impact = str(data.get("confirmed_change_impact", ""))
    brownfield_uncertainty = str(data.get("brownfield_uncertainty", ""))
    return ClassificationSnapshot(
        project_mode=ProjectMode(str(data["project_mode"])),
        size_class=SizeClass(str(data["size_class"])),
        product_type=str(data.get("product_type", "")),
        confidence=str(data.get("confidence", "")),
        borderline=bool(data.get("borderline", False)),
        axis_observations=dict(data.get("axis_observations", {})),
        rationale=tuple(str(item) for item in data.get("rationale", [])),
        classification_snapshot_kind=str(data.get("classification_snapshot_kind", "initial")),
        initial_size_class=SizeClass(initial_size_class) if initial_size_class else None,
        confirmed_size_class=SizeClass(confirmed_size_class) if confirmed_size_class else None,
        initial_borderline=data.get("initial_borderline"),
        confirmed_borderline=data.get("confirmed_borderline"),
        confirmed_change_impact=confirmed_change_impact or None,
        brownfield_uncertainty=brownfield_uncertainty or None,
        requires_observation_reclassification=bool(
            data.get("requires_observation_reclassification", False)
        ),
    )


def _find_previous_handoff(
    run_dir: Path,
    dispatches: tuple[StageDispatch, ...],
    start_index: int,
) -> Path | None:
    if start_index <= 0:
        return None

    upper_bound = min(start_index - 1, len(dispatches) - 1)
    for dispatch_index in range(upper_bound, -1, -1):
        dispatch = dispatches[dispatch_index]
        candidate = run_dir / "stage-handoffs" / f"{dispatch.order:02d}-{dispatch.stage.value}.md"
        if candidate.exists():
            return candidate
    return None
