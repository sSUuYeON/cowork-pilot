"""Dispatch-unit path authority and IO contract for planning stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from cowork_pilot.planning.models import (
    PlanningStage,
    StageDispatch,
    ClassificationSnapshot,
)
from cowork_pilot.planning.planning_doc_inventory import (
    build_doc_role_inventory,
    select_context_paths,
    READ_POLICY_NONE,
    READ_POLICY_INDEX_ONLY,
    READ_POLICY_SPEC_DOCUMENTS,
    READ_POLICY_ALL,
)

# Type alias for snapshot (per spec, it's a type alias or protocol)
PlanningSnapshot: TypeAlias = ClassificationSnapshot


# Stage-to-read-policy mapping
STAGE_READ_POLICY: dict[PlanningStage, str] = {
    PlanningStage.CLASSIFICATION: READ_POLICY_NONE,
    PlanningStage.CORE_DOCS_CHECK: READ_POLICY_INDEX_ONLY,
    PlanningStage.ADAPTIVE_DOCS_SELECTION: READ_POLICY_INDEX_ONLY,
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: READ_POLICY_ALL,
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: READ_POLICY_SPEC_DOCUMENTS,
    PlanningStage.SCOPE_STRUCTURING: READ_POLICY_SPEC_DOCUMENTS,
    PlanningStage.WORK_SIZING: READ_POLICY_NONE,
    PlanningStage.PLAN_PACKING: READ_POLICY_NONE,
    PlanningStage.PLAN_REVIEW: READ_POLICY_NONE,
    PlanningStage.EXEC_PLAN_AUTHORING: READ_POLICY_NONE,
    PlanningStage.EXEC_PLAN_SKELETON: READ_POLICY_NONE,
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: READ_POLICY_SPEC_DOCUMENTS,
    PlanningStage.EXEC_PLAN_DETAIL: READ_POLICY_SPEC_DOCUMENTS,
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: READ_POLICY_NONE,
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: READ_POLICY_NONE,
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: READ_POLICY_NONE,
}

# Stage-to-required-doc-roles mapping
STAGE_REQUIRED_DOC_ROLES: dict[PlanningStage, tuple[str, ...]] = {
    PlanningStage.CLASSIFICATION: (),
    PlanningStage.CORE_DOCS_CHECK: ("agents", "spec_index"),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: ("spec_index",),
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: ("spec_documents", "agents", "architecture"),
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: ("spec_documents", "spec_index"),
    PlanningStage.SCOPE_STRUCTURING: ("spec_documents", "spec_index"),
    PlanningStage.WORK_SIZING: (),
    PlanningStage.PLAN_PACKING: (),
    PlanningStage.PLAN_REVIEW: (),
    PlanningStage.EXEC_PLAN_AUTHORING: (),
    PlanningStage.EXEC_PLAN_SKELETON: (),
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: ("spec_documents",),
    PlanningStage.EXEC_PLAN_DETAIL: ("spec_documents",),
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: (),
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: (),
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: (),
}


# Stage-specific input/output configuration
STAGE_IO_CONFIG: dict[PlanningStage, dict[str, tuple[str, ...] | str]] = {
    PlanningStage.CLASSIFICATION: {
        "primary_inputs": ("run_dir/inputs/request.md", "run_dir/inputs/normalized-request.md"),
        "output_path": "canonical_generated_root/classification-report.md",
    },
    PlanningStage.CORE_DOCS_CHECK: {
        "primary_inputs": ("canonical_generated_root/classification-report.md", "run_dir/inputs/normalized-request.md"),
        "output_path": "canonical_generated_root/core-docs-check.md",
    },
    PlanningStage.ADAPTIVE_DOCS_SELECTION: {
        "primary_inputs": ("canonical_generated_root/classification-report.md", "canonical_generated_root/core-docs-check.md"),
        "output_path": "canonical_generated_root/adaptive-docs-selection.md",
    },
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: {
        "primary_inputs": ("canonical_generated_root/classification-report.md", "run_dir/inputs/normalized-request.md"),
        "output_paths": ("canonical_generated_root/product-completeness-review.md", "canonical_generated_root/coverage-gap.md"),
    },
    PlanningStage.SCOPE_STRUCTURING: {
        "primary_inputs": (
            "canonical_generated_root/classification-report.md",
            "canonical_generated_root/core-docs-check.md",
            "canonical_generated_root/adaptive-docs-selection.md",
            "canonical_generated_root/product-completeness-review.md",
            "canonical_generated_root/coverage-gap.md",
        ),
        "output_path": "canonical_generated_root/scope-map.md",
    },
    PlanningStage.WORK_SIZING: {
        "primary_inputs": ("canonical_generated_root/scope-map.md", "run_dir/inputs/normalized-request.md"),
        "output_path": "canonical_generated_root/work-sizing.md",
    },
    PlanningStage.PLAN_PACKING: {
        "primary_inputs": ("canonical_generated_root/work-sizing.md", "canonical_generated_root/scope-map.md"),
        "output_path": "canonical_generated_root/plan-packing.md",
    },
    PlanningStage.PLAN_REVIEW: {
        "primary_inputs": ("canonical_generated_root/plan-packing.md", "canonical_generated_root/work-sizing.md", "canonical_generated_root/scope-map.md"),
        "output_path": "canonical_generated_root/plan-review.md",
    },
    PlanningStage.EXEC_PLAN_AUTHORING: {
        "primary_inputs": ("canonical_generated_root/plan-review.md",),
        "output_path": "canonical_generated_root/exec-plan-authoring.md",
    },
    PlanningStage.EXEC_PLAN_SKELETON: {
        "primary_inputs": (
            "canonical_generated_root/scope-map.md",
            "canonical_generated_root/work-sizing.md",
            "canonical_generated_root/plan-packing.md",
            "canonical_generated_root/plan-review.md",
        ),
        "output_path": "canonical_generated_root/exec-plan-skeleton.md",
    },
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: {
        "primary_inputs": ("canonical_generated_root/exec-plan-skeleton.md", "canonical_generated_root/plan-review.md"),
        "output_path": "canonical_generated_root/feature-outlines/{slice_name}.md",
    },
    PlanningStage.EXEC_PLAN_DETAIL: {
        "primary_inputs": ("canonical_generated_root/exec-plan-skeleton.md", "canonical_generated_root/feature-outlines/{slice_name}.md"),
        "output_path": "canonical_exec_plan_root/{plan_slug}.md",
    },
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: {
        "primary_inputs": ("run_dir/inputs/normalized-request.md", "run_dir/inputs/change-request.md"),
        "output_path": "canonical_generated_root/code-observations/{slice_name}.md",
    },
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: {
        "primary_inputs": ("canonical_generated_root/code-observations/{slice_name}.md", "run_dir/inputs/normalized-request.md", "run_dir/inputs/change-request.md"),
        "output_path": "canonical_generated_root/implementation-observation-summary.md",
    },
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: {
        "primary_inputs": (
            "canonical_generated_root/implementation-observation-summary.md",
            "canonical_generated_root/classification-report.md",
            "run_dir/inputs/normalized-request.md",
            "run_dir/inputs/change-request.md",
        ),
        "output_paths": ("canonical_generated_root/spec-implementation-gap.md", "canonical_generated_root/change-impact-gap.md"),
    },
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: {
        "primary_inputs": ("canonical_generated_root/classification-report.md", "canonical_generated_root/core-docs-check.md"),
        "output_path": "canonical_generated_root/core-docs-presence-review.md",
    },
}


@dataclass(frozen=True)
class StageIOContract:
    """IO contract for a dispatch unit (stage + substage + slice)."""
    stage: PlanningStage
    substage: str
    slice_name: str
    required_doc_roles: tuple[str, ...]
    resolved_role_paths: dict[str, tuple[Path, ...]]
    selected_context_paths: tuple[Path, ...]
    read_policy: str
    read_paths: tuple[Path, ...]
    primary_inputs: tuple[Path, ...]
    input_paths: dict[str, Path | tuple[Path, ...]]
    missing_input_paths: tuple[Path, ...]
    output_paths: tuple[Path, ...]
    primary_output_path: Path | None
    upstream_output_paths: tuple[Path, ...]
    runtime_log_paths: tuple[Path, ...]
    stage_handoff_path: Path
    canonical_generated_root: Path
    canonical_exec_plan_root: Path
    canonical_spec_root: Path | None
    plan_slug: str | None


def build_stage_io_contract(
    *,
    project_dir: Path,
    run_dir: Path,
    dispatch: StageDispatch,
    previous_handoff: Path | None,
    snapshot: PlanningSnapshot,
    core_docs: tuple[Path, ...],
    adaptive_docs: tuple[Path, ...],
) -> StageIOContract:
    """
    Build a StageIOContract for the given dispatch.

    Computes all paths according to stage-specific I/O rules.
    """
    # Compute canonical roots
    canonical_generated_root = project_dir / "docs" / "generated" / "planning"
    canonical_exec_plan_root = project_dir / "docs" / "exec-plans" / "planning"

    # Determine canonical_spec_root (first existing of docs/specs or docs/product-specs)
    canonical_spec_root: Path | None = None
    for spec_dir in [project_dir / "docs" / "specs", project_dir / "docs" / "product-specs"]:
        if spec_dir.exists():
            canonical_spec_root = spec_dir
            break

    # Get read policy and required doc roles for this stage
    read_policy = STAGE_READ_POLICY.get(dispatch.stage, READ_POLICY_NONE)
    required_doc_roles = STAGE_REQUIRED_DOC_ROLES.get(dispatch.stage, ())

    # Build doc role inventory and resolve role paths
    doc_inventory = build_doc_role_inventory(project_dir)
    resolved_role_paths = {
        role: doc_inventory.get(role, ())
        for role in required_doc_roles
    }

    # Select context paths based on policy
    selected_context_paths = select_context_paths(
        inventory=doc_inventory,
        required_roles=required_doc_roles,
        read_policy=read_policy,
    )

    # Resolve primary inputs and outputs using the stage config
    stage_config = STAGE_IO_CONFIG.get(dispatch.stage, {})

    # Resolve primary input paths
    primary_inputs_spec = stage_config.get("primary_inputs", ())
    primary_inputs = _resolve_paths(
        primary_inputs_spec,
        run_dir=run_dir,
        canonical_generated_root=canonical_generated_root,
        canonical_exec_plan_root=canonical_exec_plan_root,
        slice_name=dispatch.slice_name,
    )

    # Determine which primary inputs exist
    existing_primary_inputs = tuple(p for p in primary_inputs if p.exists())
    missing_primary_inputs = tuple(p for p in primary_inputs if not p.exists())

    # Resolve output paths
    output_paths_spec = stage_config.get("output_paths", ())
    if not output_paths_spec:
        # Fall back to single output_path
        output_path_spec = stage_config.get("output_path", "")
        output_paths_spec = (output_path_spec,) if output_path_spec else ()

    output_paths = _resolve_paths(
        output_paths_spec,
        run_dir=run_dir,
        canonical_generated_root=canonical_generated_root,
        canonical_exec_plan_root=canonical_exec_plan_root,
        slice_name=dispatch.slice_name,
        plan_slug=_resolve_plan_slug(dispatch),
    )

    # Primary output is the first output path
    primary_output_path = output_paths[0] if output_paths else None

    # Build input_paths dict (informational)
    input_paths_dict: dict[str, Path | tuple[Path, ...]] = {}
    for i, path_spec in enumerate(primary_inputs_spec):
        key = f"input_{i}" if i > 0 else _path_spec_to_key(path_spec)
        resolved = _resolve_path(
            path_spec,
            run_dir=run_dir,
            canonical_generated_root=canonical_generated_root,
            canonical_exec_plan_root=canonical_exec_plan_root,
            slice_name=dispatch.slice_name,
        )
        input_paths_dict[key] = resolved

    # Build upstream output paths
    upstream_outputs: list[Path] = []
    if previous_handoff is not None:
        upstream_outputs.append(previous_handoff)
    # Also collect output paths from primary inputs that reference canonical_generated_root
    for primary_input in existing_primary_inputs:
        if "generated/planning" in str(primary_input):
            upstream_outputs.append(primary_input)

    # Build runtime log paths (always included, even if they don't exist)
    runtime_logs = (
        run_dir / "assumptions.md",
        run_dir / "answer-log.md",
        run_dir / "approval-log.md",
    )

    # Build stage handoff path
    # Format: run_dir/stage-handoffs/{stage}-{substage or slice_name or main}.md
    handoff_suffix = dispatch.substage or dispatch.slice_name or "main"
    stage_handoff_path = run_dir / "stage-handoffs" / f"{dispatch.stage.value}-{handoff_suffix}.md"

    # Build read_paths in order:
    # 1. normalized-request.md
    # 2. change-request.md (if exists in primary_inputs)
    # 3. previous handoff
    # 4. project-owned canonical docs (resolved_role_paths + selected_context_paths + core_docs + adaptive_docs)
    # 5. upstream planning-generated canonical outputs
    # 6. log files
    read_paths_list: list[Path] = []
    read_paths_set: set[Path] = set()

    # 1. normalized-request
    normalized_request = run_dir / "inputs" / "normalized-request.md"
    if normalized_request.exists():
        read_paths_list.append(normalized_request)
        read_paths_set.add(normalized_request)

    # 2. change-request (if in primary_inputs)
    change_request = run_dir / "inputs" / "change-request.md"
    if change_request in primary_inputs and change_request.exists():
        read_paths_list.append(change_request)
        read_paths_set.add(change_request)

    # 3. previous handoff
    if previous_handoff is not None and previous_handoff.exists():
        read_paths_list.append(previous_handoff)
        read_paths_set.add(previous_handoff)

    # 4. project-owned docs
    for path in selected_context_paths:
        if path not in read_paths_set and path.exists():
            read_paths_list.append(path)
            read_paths_set.add(path)

    for core_doc in core_docs:
        if core_doc not in read_paths_set and core_doc.exists():
            read_paths_list.append(core_doc)
            read_paths_set.add(core_doc)

    for adaptive_doc in adaptive_docs:
        if adaptive_doc not in read_paths_set and adaptive_doc.exists():
            read_paths_list.append(adaptive_doc)
            read_paths_set.add(adaptive_doc)

    # 5. upstream planning-generated outputs
    for upstream_path in upstream_outputs:
        if upstream_path not in read_paths_set and upstream_path.exists():
            read_paths_list.append(upstream_path)
            read_paths_set.add(upstream_path)

    # 6. log files (include even if they don't exist, but filter at read time)
    for log_path in runtime_logs:
        if log_path not in read_paths_set and log_path.exists():
            read_paths_list.append(log_path)
            read_paths_set.add(log_path)

    return StageIOContract(
        stage=dispatch.stage,
        substage=dispatch.substage,
        slice_name=dispatch.slice_name,
        required_doc_roles=required_doc_roles,
        resolved_role_paths=resolved_role_paths,
        selected_context_paths=selected_context_paths,
        read_policy=read_policy,
        read_paths=tuple(read_paths_list),
        primary_inputs=existing_primary_inputs,
        input_paths=input_paths_dict,
        missing_input_paths=missing_primary_inputs,
        output_paths=output_paths,
        primary_output_path=primary_output_path,
        upstream_output_paths=tuple(upstream_outputs),
        runtime_log_paths=runtime_logs,
        stage_handoff_path=stage_handoff_path,
        canonical_generated_root=canonical_generated_root,
        canonical_exec_plan_root=canonical_exec_plan_root,
        canonical_spec_root=canonical_spec_root,
        plan_slug=_resolve_plan_slug(dispatch),
    )


def _resolve_plan_slug(dispatch: StageDispatch) -> str | None:
    """Resolve plan_slug from dispatch for exec_plan_detail stage."""
    if dispatch.stage != PlanningStage.EXEC_PLAN_DETAIL:
        return None
    # Use substage if available, else "exec-plan"
    return dispatch.substage if dispatch.substage else "exec-plan"


def _resolve_paths(
    path_specs: tuple[str, ...],
    *,
    run_dir: Path,
    canonical_generated_root: Path,
    canonical_exec_plan_root: Path,
    slice_name: str = "",
    plan_slug: str | None = None,
) -> tuple[Path, ...]:
    """Resolve a tuple of path specifications to actual paths."""
    resolved = []
    for spec in path_specs:
        path = _resolve_path(
            spec,
            run_dir=run_dir,
            canonical_generated_root=canonical_generated_root,
            canonical_exec_plan_root=canonical_exec_plan_root,
            slice_name=slice_name,
            plan_slug=plan_slug,
        )
        resolved.append(path)
    return tuple(resolved)


def _resolve_path(
    path_spec: str,
    *,
    run_dir: Path,
    canonical_generated_root: Path,
    canonical_exec_plan_root: Path,
    slice_name: str = "",
    plan_slug: str | None = None,
) -> Path:
    """Resolve a single path specification to an actual path."""
    # Handle template variables
    spec = path_spec
    spec = spec.replace("{slice_name}", slice_name)
    if plan_slug:
        spec = spec.replace("{plan_slug}", plan_slug)

    # Handle prefixes
    if spec.startswith("run_dir/"):
        return run_dir / spec[8:]  # Remove "run_dir/" prefix
    elif spec.startswith("canonical_generated_root/"):
        return canonical_generated_root / spec[25:]  # Remove prefix
    elif spec.startswith("canonical_exec_plan_root/"):
        return canonical_exec_plan_root / spec[25:]  # Remove prefix
    else:
        # Assume relative to run_dir
        return run_dir / spec


def _path_spec_to_key(spec: str) -> str:
    """Convert a path spec to a dictionary key."""
    # Extract the last path component without extension
    if "/" in spec:
        basename = spec.split("/")[-1]
    else:
        basename = spec

    # Remove .md extension and replace hyphens with underscores
    key = basename.replace(".md", "").replace("-", "_")
    return key
