from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlanningRuntimeState(str, Enum):
    PENDING = "pending"
    RUNNING_EXEC = "running_exec"
    RUNNING_CLI = "running_cli"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class QuestionStrategy(str, Enum):
    FRONT_LOADED = "front_loaded"
    BALANCED = "balanced"
    MINIMAL = "minimal"


class AssumptionScope(str, Enum):
    CONSERVATIVE = "conservative"
    BROAD_PRODUCT_DESIGN = "broad_product_design"


class ApprovalPolicy(str, Enum):
    FINAL_DRAFT_ONLY = "final_draft_only"
    SECTION_APPROVAL = "section_approval"


class PhaseStrategy(str, Enum):
    QUESTION_HEAVY_THEN_AUTO = "question_heavy_then_auto"
    EVENLY_DISTRIBUTED = "evenly_distributed"


@dataclass(frozen=True)
class ResumeHandleRef:
    surface: str
    resume_handle_kind: str
    resume_handle: str
    stage: str
    substage: str
