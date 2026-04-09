from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import PlanningContext, PlanningStage
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE

_MARKER_INSTRUCTIONS = (
    "Emit a final COWORK_PILOT_EVENT bundle when the stage needs input, approval, "
    "assumption logging, completion, or human escalation."
)


@dataclass(frozen=True)
class StageContract:
    purpose: str
    output_description: str
    json_keys: tuple[str, ...]
    forbidden: tuple[str, ...]
    input_files: tuple[str, ...] = ()


def _resolve_output_file(stage: PlanningStage) -> str | None:
    """Derive expected output filename from ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return ownership.completion_artifacts[0]


_STAGE_CONTRACTS: dict[PlanningStage, StageContract] = {
    PlanningStage.CLASSIFICATION: StageContract(
        purpose=(
            "Analyze project inputs and produce a classification report. "
            "Determine project_mode, product_type, size_class, core user flows, "
            "primary entities, and risks."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("project_mode", "product_type", "size_class", "core_user_flows", "primary_entities", "risks"),
        forbidden=(
            "Do NOT produce a plan or scope — only classify.",
            "Do NOT skip any required JSON key.",
        ),
    ),
    PlanningStage.CORE_DOCS_CHECK: StageContract(
        purpose=(
            "Identify which document roles are required, resolve existing file paths, "
            "flag missing roles, and note substitution options."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("required_doc_roles", "resolved_existing_paths", "missing_roles", "substitutions"),
        forbidden=(
            "Do NOT invent document content — only check presence and role necessity.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("classification-report.md",),
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: StageContract(
        purpose=(
            "Select additional documents to read beyond the core set, "
            "based on project size, classification, and what's available on disk."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("selected_paths", "selected_roles", "selection_reasons", "rejected_candidates"),
        forbidden=(
            "Do NOT repeat core docs — only list additional/conditional docs.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("classification-report.md", "core-docs-check.md"),
    ),
    PlanningStage.SCOPE_STRUCTURING: StageContract(
        purpose=(
            "Decompose the product into functional domains, user flows, and feature groups. "
            "This is about PRODUCT structure derived from normalized-request.md, completeness results, "
            "and the actual documents read — NOT about listing document roles."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("domains", "features", "user_flows", "out_of_scope"),
        forbidden=(
            "Do NOT list document roles (agents, spec_index, design_guide, etc.) as domains or features.",
            "Do NOT produce work estimates or plan chunks.",
            "Do NOT use doc-role names as scope group names.",
        ),
        input_files=("classification-report.md", "core-docs-check.md", "adaptive-docs-selection.md"),
    ),
    PlanningStage.WORK_SIZING: StageContract(
        purpose=(
            "For each feature in the scope map, produce a work item with "
            "id, title, domain, feature, size, risk, and dependency info."
        ),
        output_description="Markdown with a fenced JSON block containing a `work_items` array.",
        json_keys=("work_items",),
        forbidden=(
            "Do NOT redefine scope — take scope-map.md as given input.",
            "Do NOT produce plan chunks or execution order.",
        ),
        input_files=("scope-map.md",),
    ),
    PlanningStage.PLAN_PACKING: StageContract(
        purpose=(
            "Group sized work items into executable plan chunks, respecting "
            "dependency order and parallel-execution opportunities."
        ),
        output_description="Markdown with a fenced JSON block containing a `plans` array.",
        json_keys=("plans",),
        forbidden=(
            "Do NOT re-estimate work — take work-sizing.md as given input.",
            "Do NOT produce review verdicts.",
        ),
        input_files=("work-sizing.md", "scope-map.md"),
    ),
    PlanningStage.PLAN_REVIEW: StageContract(
        purpose=(
            "Review the packed plan for coverage gaps, over-design, sizing issues, "
            "and executionability. Produce structured verdicts."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("issues", "rollback_recommended", "coverage_status", "execution_risks", "missing_work_items"),
        forbidden=(
            "Do NOT modify the plan — only review it.",
            "Do NOT skip any verdict field.",
        ),
        input_files=("plan-packing.md", "work-sizing.md", "scope-map.md"),
    ),
}


def render_stage_prompt(
    stage: PlanningStage,
    context: PlanningContext | Mapping[str, object] | None = None,
    *,
    read_set: tuple[Path, ...] | tuple[str, ...] | None = None,
    handoff_summary: str = "",
    target_version: str | None = None,
    substage: str = "",
) -> str:
    # Stage-specific prompt templates for outline/detail flow
    if stage is PlanningStage.EXEC_PLAN_SKELETON:
        return (
            "stage=exec_plan_skeleton\n"
            "Produce an exec-plan skeleton with feature list, execution order, and dependency table.\n"
            "Do NOT write chunk details — only features, ordering, and dependencies.\n"
            "Output: exec-plan-skeleton.md\n"
            f"\n{_MARKER_INSTRUCTIONS}"
        )

    if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
        return (
            f"stage=exec_plan_feature_outline\n"
            f"feature={substage}\n"
            f"Produce a detailed chunk decomposition for the '{substage}' feature.\n"
            "Include completion criteria and task list for each chunk.\n"
            f"Output: feature-outlines/{substage}.md\n"
            f"\n{_MARKER_INSTRUCTIONS}"
        )

    if stage is PlanningStage.EXEC_PLAN_DETAIL:
        return (
            f"stage=exec_plan_detail\n"
            f"plan={substage}\n"
            f"Fill in session prompts for each chunk of plan '{substage}'.\n"
            f"Read the merged exec-plan-outline.md for context.\n"
            f"Output: detail-{substage}.md\n"
            f"\n{_MARKER_INSTRUCTIONS}"
        )

    restored_context = ""
    resolved_target_version = target_version or ""
    if isinstance(context, PlanningContext):
        resolved_target_version = target_version if target_version is not None else context.target_version
    elif context is not None:
        if target_version is None:
            resolved_target_version = str(context.get("target_version", ""))
        restored_context = str(context.get("restored_context", ""))

    contract = _STAGE_CONTRACTS.get(stage)

    if read_set is None and not handoff_summary and target_version is None and contract is None:
        prompt = f"{stage.value}:{resolved_target_version}\n{_MARKER_INSTRUCTIONS}"
        if restored_context:
            prompt += f"\nrestored_context:\n{restored_context}"
        return prompt

    lines = [
        f"stage={stage.value}",
        f"target_version={resolved_target_version}",
    ]

    if contract is not None:
        output_file = _resolve_output_file(stage)
        lines.append("")
        lines.append(f"PURPOSE: {contract.purpose}")
        lines.append("")
        if output_file is not None:
            lines.append(f"OUTPUT FILE: {output_file}")
        lines.append(f"OUTPUT FORMAT: {contract.output_description}")
        lines.append(f"REQUIRED JSON KEYS: {', '.join(contract.json_keys)}")
        lines.append("")
        lines.append("After the JSON block, append this exact marker on its own line:")
        lines.append("<!-- ORCHESTRATOR:DONE -->")
        lines.append("")
        if contract.input_files:
            lines.append("REQUIRED INPUTS (must exist before this stage):")
            for f in contract.input_files:
                lines.append(f"- {f}")
            lines.append("")
        lines.append("FORBIDDEN:")
        for item in contract.forbidden:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("Read these files before acting:")
    lines.extend(f"- {path}" for path in (read_set or ()))
    lines.append(
        "Treat the provided read set and persisted handoff summary as the authoritative boundary for this stage."
    )
    if handoff_summary:
        lines.extend(("", "handoff_summary:", handoff_summary))
    if restored_context:
        lines.extend(("", "restored_context:", restored_context))
    lines.extend(("", _MARKER_INSTRUCTIONS))
    return "\n".join(lines)


def render_greenfield_entry_prompt(
    *,
    required_outputs: tuple[str, ...],
    canonical_spec_draft_path: Path,
) -> str:
    required = ", ".join(required_outputs)
    return (
        "greenfield-entry\n"
        f"required_outputs={required}\n"
        f"canonical_spec_draft_path={canonical_spec_draft_path}"
    )


def render_brownfield_stage_prompt(
    *,
    stage_name: str,
    slices: tuple[str, ...] = (),
) -> str:
    rendered_slices = ", ".join(slices) if slices else "default"
    return f"brownfield-stage\nstage={stage_name}\nslices={rendered_slices}"
