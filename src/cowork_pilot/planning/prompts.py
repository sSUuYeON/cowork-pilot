from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cowork_pilot.planning.models import PlanningContext, PlanningStage
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE


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


_STAGE_TEMPLATE_MAP: dict[PlanningStage, str] = {
    PlanningStage.CLASSIFICATION: "classification.j2",
    PlanningStage.CORE_DOCS_CHECK: "core_docs_check.j2",
    PlanningStage.ADAPTIVE_DOCS_SELECTION: "adaptive_docs_selection.j2",
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: "core_docs_presence_review.j2",
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: "product_completeness_review.j2",
    PlanningStage.SCOPE_STRUCTURING: "scope_structuring.j2",
    PlanningStage.WORK_SIZING: "work_sizing.j2",
    PlanningStage.PLAN_PACKING: "plan_packing.j2",
    PlanningStage.PLAN_REVIEW: "plan_review.j2",
    PlanningStage.EXEC_PLAN_SKELETON: "exec_plan_skeleton.j2",
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: "exec_plan_feature_outline.j2",
    PlanningStage.EXEC_PLAN_DETAIL: "exec_plan_detail.j2",
    PlanningStage.EXEC_PLAN_AUTHORING: "exec_plan_authoring.j2",
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: "brownfield_code_observation_extraction.j2",
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: "brownfield_observation_synthesis.j2",
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: "brownfield_gap_synthesis.j2",
}


def _get_jinja_env(template_dir: Path | None = None) -> Environment:
    """Create Jinja2 environment with the planning_templates directory."""
    if template_dir is None:
        template_dir = Path(__file__).parent / "planning_templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )


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
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: StageContract(
        purpose=(
            "Verify that all required core documents physically exist on disk "
            "and contain meaningful content. Flag empty or placeholder files."
        ),
        output_description="Markdown report with presence/absence verdicts.",
        json_keys=(),
        forbidden=(
            "Do NOT create or modify documents — only verify presence.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("core-docs-check.md",),
    ),
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: StageContract(
        purpose=(
            "Review product specification completeness by checking whether all "
            "required sections, user flows, and data models are defined."
        ),
        output_description="Markdown report with completeness verdicts.",
        json_keys=(),
        forbidden=(
            "Do NOT write missing content — only identify gaps.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("classification-report.md",),
    ),
    PlanningStage.EXEC_PLAN_SKELETON: StageContract(
        purpose=(
            "Produce an exec-plan skeleton with feature list, execution order, "
            "and dependency table."
        ),
        output_description="Markdown table with features and dependencies.",
        json_keys=(),
        forbidden=(
            "Do NOT write chunk details — only features, ordering, and dependencies.",
        ),
        input_files=("scope-map.md", "plan-packing.md"),
    ),
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: StageContract(
        purpose=(
            "Produce a detailed chunk decomposition for a specific feature, "
            "including completion criteria and task list for each chunk."
        ),
        output_description="Markdown with chunk breakdown per feature.",
        json_keys=(),
        forbidden=(
            "Do NOT fill in session prompts — only outline chunks and criteria.",
        ),
        input_files=("exec-plan-skeleton.md",),
    ),
    PlanningStage.EXEC_PLAN_DETAIL: StageContract(
        purpose=(
            "Fill in session prompts for each chunk of a specific plan, "
            "providing actionable instructions for each execution session."
        ),
        output_description="Markdown with detailed session prompts per chunk.",
        json_keys=(),
        forbidden=(
            "Do NOT modify chunk structure — only add session prompt content.",
        ),
        input_files=("exec-plan-skeleton.md",),
    ),
    PlanningStage.EXEC_PLAN_AUTHORING: StageContract(
        purpose=(
            "Integrate all feature outlines into a final exec-plan document, "
            "verifying chunk numbering, dependencies, and completeness."
        ),
        output_description="Final exec-plan Markdown file.",
        json_keys=(),
        forbidden=(
            "Do NOT change content from feature outlines — only integrate.",
            "Do NOT re-number chunks unless ordering is inconsistent.",
        ),
        input_files=("exec-plan-skeleton.md",),
    ),
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: StageContract(
        purpose=(
            "Explore existing source code and record objective observations "
            "about architecture, data models, APIs, tests, and configuration."
        ),
        output_description="Markdown observation files in code-observations/ directory.",
        json_keys=(),
        forbidden=(
            "Do NOT evaluate or judge code quality — only observe.",
            "Do NOT suggest improvements or refactoring.",
        ),
        input_files=("planning-references/observation-format.md",),
    ),
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: StageContract(
        purpose=(
            "Synthesize all code observation slices into a unified summary, "
            "categorizing by architecture, data models, APIs, dependencies, and patterns."
        ),
        output_description="Markdown summary file (implementation-observation-summary.md).",
        json_keys=(),
        forbidden=(
            "Do NOT add information not present in observation slices.",
            "Do NOT suggest improvements — only describe current state.",
        ),
        input_files=("planning-references/observation-format.md", "code-observations/"),
    ),
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: StageContract(
        purpose=(
            "Analyze gaps between current implementation and change requests, "
            "identifying spec-implementation gaps and change impact areas."
        ),
        output_description="Gap analysis files (spec-implementation-gap.md, change-impact-gap.md).",
        json_keys=(),
        forbidden=(
            "Do NOT propose solutions — only identify gaps.",
            "Do NOT create scope, work items, or plans.",
        ),
        input_files=(
            "planning-references/gap-analysis-criteria.md",
            "implementation-observation-summary.md",
            "normalized-request.md",
        ),
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
    restored_context = ""
    resolved_target_version = target_version or ""
    if isinstance(context, PlanningContext):
        resolved_target_version = target_version if target_version is not None else context.target_version
    elif context is not None:
        if target_version is None:
            resolved_target_version = str(context.get("target_version", ""))
        restored_context = str(context.get("restored_context", ""))

    template_name = _STAGE_TEMPLATE_MAP.get(stage)
    contract = _STAGE_CONTRACTS.get(stage)

    if template_name is not None:
        output_file = _resolve_output_file(stage) or f"{stage.value}-output.md"
        env = _get_jinja_env()
        template = env.get_template(template_name)
        return template.render(
            stage=stage.value,
            target_version=resolved_target_version,
            read_set=tuple(str(p) for p in (read_set or ())),
            handoff_summary=handoff_summary,
            restored_context=restored_context,
            output_file=output_file,
            json_keys=contract.json_keys if contract else (),
            forbidden=contract.forbidden if contract else (),
            input_files=contract.input_files if contract else (),
            purpose=contract.purpose if contract else "",
            substage=substage,
        )

    # Safety fallback for unmapped stages
    prompt = f"{stage.value}:{resolved_target_version}\n완료 시 <!-- ORCHESTRATOR:DONE --> 마커 기록\n"
    if restored_context:
        prompt += f"\nrestored_context:\n{restored_context}"
    return prompt


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
