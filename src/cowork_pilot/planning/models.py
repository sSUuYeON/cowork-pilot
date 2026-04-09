from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


class ProjectMode(str, Enum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class SizeClass(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class PlanningStage(str, Enum):
    CLASSIFICATION = "classification"
    BROWNFIELD_CODE_OBSERVATION_EXTRACTION = "brownfield_code_observation_extraction"
    BROWNFIELD_OBSERVATION_SYNTHESIS = "brownfield_observation_synthesis"
    BROWNFIELD_GAP_SYNTHESIS = "brownfield_gap_synthesis"
    CORE_DOCS_CHECK = "core_docs_check"
    ADAPTIVE_DOCS_SELECTION = "adaptive_docs_selection"
    CORE_DOCS_PRESENCE_REVIEW = "core_docs_presence_review"
    PRODUCT_COMPLETENESS_REVIEW = "product_completeness_review"
    SCOPE_STRUCTURING = "scope_structuring"
    WORK_SIZING = "work_sizing"
    PLAN_PACKING = "plan_packing"
    PLAN_REVIEW = "plan_review"
    EXEC_PLAN_AUTHORING = "exec_plan_authoring"
    EXEC_PLAN_SKELETON = "exec_plan_skeleton"
    EXEC_PLAN_FEATURE_OUTLINE = "exec_plan_feature_outline"
    EXEC_PLAN_DETAIL = "exec_plan_detail"


class ProjectConventionProfile(str, Enum):
    SPECS_CENTERED = "specs_centered"
    PRODUCT_SPECS_CENTERED = "product_specs_centered"


StageExecutionKind = Literal["local", "ai"]


@dataclass(frozen=True)
class ClassificationSnapshot:
    project_mode: ProjectMode
    size_class: SizeClass
    product_type: str
    confidence: str
    borderline: bool
    axis_observations: dict[str, object] = field(default_factory=dict)
    rationale: tuple[str, ...] = ()
    classification_snapshot_kind: str = "initial"
    initial_size_class: SizeClass | None = None
    confirmed_size_class: SizeClass | None = None
    initial_borderline: bool | None = None
    confirmed_borderline: bool | None = None
    confirmed_change_impact: str | None = None
    brownfield_uncertainty: str | None = None
    requires_observation_reclassification: bool = False


@dataclass(frozen=True)
class PlanningContext:
    run_dir: Path | None = None
    project_dir: Path | None = None
    target_version: str = ""
    mode: ProjectMode | None = None
    explicit_mode: bool = False
    request_text: str = ""
    request_source: str = ""
    change_request_text: str = ""
    change_request_source: str = ""


@dataclass(frozen=True)
class StageDispatch:
    stage: PlanningStage
    execution_kind: StageExecutionKind
    order: int
    substage: str = ""
    slice_name: str = ""


@dataclass(frozen=True)
class PlanningPipelineResult:
    context: PlanningContext
    snapshot: ClassificationSnapshot
    core_docs: list[str]
    adaptive_docs: list[str]
    scope_map: dict[str, list[str]]
    work_items: list[str]
    packed_plans: list[str]
    review_notes: list[str]
    stage_prompt: str
    exec_plan_path: Path | None = None
    exec_plan_paths: tuple[Path, ...] = ()
    runtime_state: str = "completed"
    stopped_stage: str = ""


@dataclass(frozen=True)
class OutlinePlan:
    number: str
    name: str
    filename: str
    feature_scope: tuple[str, ...] = ()
