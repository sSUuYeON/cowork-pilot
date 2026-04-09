from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cowork_pilot.planning.models import ClassificationSnapshot, PlanningContext, ProjectMode, SizeClass
from cowork_pilot.planning.spec_sources import (
    DocumentRoleMapping,
    discover_planning_inputs,
    detect_project_convention_profile,
    resolve_planning_project_mode,
    resolve_document_role_mapping,
)


@dataclass(frozen=True)
class ClassificationInputs:
    project_mode: ProjectMode
    canonical_spec_paths: tuple[Path, ...] = ()
    uploaded_spec_path: Path | None = None
    feature_estimate: int = 0
    role_estimate: int = 0
    flow_estimate: int = 0
    integration_estimate: int = 0
    brownfield_change_impact: str = "low"
    source_material_only: bool = False
    has_existing_code: bool = False
    core_doc_requirement_strength: str = "baseline"
    document_role_mapping: dict[str, DocumentRoleMapping] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationReport:
    size_class: SizeClass
    product_type: str
    axis_observations: dict[str, object]
    rationale: tuple[str, ...]
    confidence: str
    borderline: bool


def build_classification_report(inputs: ClassificationInputs) -> ClassificationReport:
    score = _estimate_score(inputs)
    size_class, borderline, confidence = _classify_size(inputs, score)
    axis_observations = {
        "feature_groups": inputs.feature_estimate,
        "roles": inputs.role_estimate,
        "user_flows": inputs.flow_estimate,
        "integrations": inputs.integration_estimate,
        "change_surface_estimate": inputs.brownfield_change_impact,
        "source_material_only": inputs.source_material_only,
        "has_existing_code": inputs.has_existing_code,
        "canonical_spec_count": len(inputs.canonical_spec_paths),
        "document_roles": sorted(inputs.document_role_mapping.keys()),
    }
    rationale = (
        f"score={score} derived from feature/role/flow/integration estimates",
        f"brownfield_change_impact={inputs.brownfield_change_impact}",
        f"project_mode={inputs.project_mode.value}",
    )
    return ClassificationReport(
        size_class=size_class,
        product_type=_infer_product_type(inputs),
        axis_observations=axis_observations,
        rationale=rationale,
        confidence=confidence,
        borderline=borderline,
    )


def classify_project(
    context: PlanningContext | None = None,
    inputs: ClassificationInputs | None = None,
) -> ClassificationSnapshot:
    classification_inputs = inputs if inputs is not None else _build_inputs_from_context(context)
    report = build_classification_report(classification_inputs)
    return ClassificationSnapshot(
        project_mode=classification_inputs.project_mode,
        size_class=report.size_class,
        product_type=report.product_type,
        confidence=report.confidence,
        borderline=report.borderline,
        axis_observations=report.axis_observations,
        rationale=report.rationale,
        brownfield_uncertainty=(
            "medium"
            if classification_inputs.project_mode is ProjectMode.BROWNFIELD
            else None
        ),
        requires_observation_reclassification=(
            classification_inputs.project_mode is ProjectMode.BROWNFIELD
        ),
    )


def reclassify_greenfield_after_completeness(
    current_snapshot: ClassificationSnapshot,
    completeness_result,
    already_reclassified: bool,
) -> ClassificationSnapshot:
    if already_reclassified:
        return current_snapshot

    failed_items = sum(
        1
        for result in completeness_result.category_results
        if not result.passed
    )
    new_size = current_snapshot.size_class
    if failed_items >= 2 and current_snapshot.size_class is SizeClass.SMALL:
        new_size = SizeClass.MEDIUM
    confirmed_borderline = failed_items == 1

    return ClassificationSnapshot(
        project_mode=current_snapshot.project_mode,
        size_class=new_size,
        product_type=current_snapshot.product_type,
        confidence="medium" if confirmed_borderline else current_snapshot.confidence,
        borderline=confirmed_borderline,
        axis_observations=current_snapshot.axis_observations,
        rationale=current_snapshot.rationale,
        classification_snapshot_kind="confirmed",
        initial_size_class=current_snapshot.size_class,
        confirmed_size_class=new_size,
        initial_borderline=current_snapshot.borderline,
        confirmed_borderline=confirmed_borderline,
        confirmed_change_impact=current_snapshot.confirmed_change_impact,
        brownfield_uncertainty=current_snapshot.brownfield_uncertainty,
        requires_observation_reclassification=False,
    )


def reclassify_brownfield_after_observation(
    current_snapshot: ClassificationSnapshot,
    observation_summary: str,
    confirmed_change_impact: str,
    already_reclassified: bool,
) -> ClassificationSnapshot:
    if already_reclassified:
        return current_snapshot

    _ = observation_summary
    if confirmed_change_impact == "high":
        new_size = SizeClass.LARGE
        confirmed_borderline = False
    elif confirmed_change_impact == "medium":
        new_size = max(current_snapshot.size_class, SizeClass.MEDIUM, key=lambda item: _SIZE_ORDER[item])
        confirmed_borderline = True
    else:
        new_size = current_snapshot.size_class
        confirmed_borderline = current_snapshot.borderline

    return ClassificationSnapshot(
        project_mode=current_snapshot.project_mode,
        size_class=new_size,
        product_type=current_snapshot.product_type,
        confidence="medium" if confirmed_borderline else current_snapshot.confidence,
        borderline=confirmed_borderline,
        axis_observations=current_snapshot.axis_observations,
        rationale=current_snapshot.rationale,
        classification_snapshot_kind="confirmed",
        initial_size_class=current_snapshot.size_class,
        confirmed_size_class=new_size,
        initial_borderline=current_snapshot.borderline,
        confirmed_borderline=confirmed_borderline,
        confirmed_change_impact=confirmed_change_impact,
        brownfield_uncertainty=current_snapshot.brownfield_uncertainty,
        requires_observation_reclassification=False,
    )


def _build_inputs_from_context(context: PlanningContext | None) -> ClassificationInputs:
    if context is None:
        return ClassificationInputs(project_mode=ProjectMode.GREENFIELD)

    project_dir = context.project_dir or context.run_dir
    if project_dir is None:
        return ClassificationInputs(project_mode=ProjectMode.GREENFIELD)

    discovered = discover_planning_inputs(project_dir)
    profile = detect_project_convention_profile(project_dir)
    document_role_mapping = resolve_document_role_mapping(profile)
    canonical_count = len(discovered.canonical_spec_paths)
    feature_estimate = canonical_count or (1 if discovered.uploaded_spec_path else 0)
    explicit_project_mode = context.mode if context.explicit_mode else None

    return ClassificationInputs(
        project_mode=resolve_planning_project_mode(project_dir, explicit_project_mode),
        canonical_spec_paths=discovered.canonical_spec_paths,
        uploaded_spec_path=discovered.uploaded_spec_path,
        feature_estimate=feature_estimate,
        role_estimate=2 if discovered.has_existing_code else (1 if feature_estimate else 0),
        flow_estimate=canonical_count or (1 if discovered.uploaded_spec_path else 0),
        integration_estimate=1 if discovered.has_existing_code else 0,
        brownfield_change_impact="medium" if discovered.has_existing_code else "low",
        source_material_only=discovered.source_material_only,
        has_existing_code=discovered.has_existing_code,
        core_doc_requirement_strength="strong" if canonical_count else "baseline",
        document_role_mapping=document_role_mapping,
    )


def _classify_size(
    inputs: ClassificationInputs,
    score: int,
) -> tuple[SizeClass, bool, str]:
    clear_small = (
        inputs.role_estimate <= 1
        and inputs.feature_estimate <= 3
        and inputs.integration_estimate <= 1
        and inputs.brownfield_change_impact == "low"
    )
    clear_large = (
        inputs.role_estimate >= 3
        or inputs.feature_estimate >= 5
        or inputs.integration_estimate >= 3
        or inputs.brownfield_change_impact == "high"
    )
    borderline_medium_large = (
        not clear_large
        and inputs.role_estimate >= 2
        and inputs.feature_estimate >= 3
        and inputs.integration_estimate >= 1
        and inputs.brownfield_change_impact == "medium"
    )

    if clear_large:
        return (SizeClass.LARGE, False, "high")
    if borderline_medium_large:
        return (SizeClass.MEDIUM, True, "medium")
    if clear_small:
        confidence = "low" if score == 0 else "high"
        return (SizeClass.SMALL, False, confidence)
    return (SizeClass.MEDIUM, False, "medium")


def _estimate_score(inputs: ClassificationInputs) -> int:
    return (
        inputs.feature_estimate
        + inputs.role_estimate
        + inputs.flow_estimate
        + (inputs.integration_estimate * 2)
        + _brownfield_impact_bonus(inputs.brownfield_change_impact)
        + (2 if inputs.has_existing_code else 0)
        + (1 if inputs.source_material_only else 0)
        + (1 if len(inputs.canonical_spec_paths) >= 3 else 0)
    )


def _brownfield_impact_bonus(impact: str) -> int:
    if impact == "high":
        return 4
    if impact == "medium":
        return 2
    return 0


def _infer_product_type(inputs: ClassificationInputs) -> str:
    if inputs.project_mode is ProjectMode.BROWNFIELD:
        return "brownfield-service"
    if inputs.source_material_only or inputs.canonical_spec_paths:
        return "spec-driven-product"
    return "greenfield-app"


_SIZE_ORDER = {
    SizeClass.SMALL: 0,
    SizeClass.MEDIUM: 1,
    SizeClass.LARGE: 2,
}


def parse_classification_report(path: Path) -> ClassificationSnapshot:
    """Parse an AI-generated classification-report.md into a ClassificationSnapshot."""
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block found in {path}")
    return ClassificationSnapshot(
        project_mode=ProjectMode(data["project_mode"]),
        size_class=SizeClass(data["size_class"]),
        product_type=str(data["product_type"]),
        confidence="medium",
        borderline=False,
        axis_observations={
            "core_user_flows": data.get("core_user_flows", []),
            "primary_entities": data.get("primary_entities", []),
            "risks": data.get("risks", []),
        },
        rationale=("parsed from AI classification-report.md",),
        brownfield_uncertainty=(
            "medium" if data["project_mode"] == "brownfield" else None
        ),
        requires_observation_reclassification=(
            data["project_mode"] == "brownfield"
        ),
    )
