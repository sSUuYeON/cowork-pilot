from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Phase2StepInputs:
    """All inputs and owned outputs for one phase2 step."""

    step_name: str
    phase_template: str
    render_kwargs: dict[str, object]
    required_inputs: list[Path]
    optional_inputs: list[Path]
    output_files: list[Path]

    @property
    def all_existing_inputs(self) -> list[Path]:
        result = [p for p in self.required_inputs if p.exists()]
        result.extend(p for p in self.optional_inputs if p.exists())
        return result


@dataclass(frozen=True)
class PendingQuestionPacket:
    """Structured payload sent to the upper auto-answer agent."""

    event_id: str
    step: str
    question_text: str
    options: list[str]
    recommended: str | None
    seed_required_inputs: list[Path]
    seed_optional_inputs: list[Path]
    seed_output_files: list[Path]
    question_fingerprint: str

    @staticmethod
    def compute_fingerprint(
        step: str,
        event_id: str,
        question: str,
        options: list[str],
    ) -> str:
        blob = json.dumps(
            {
                "step": step,
                "event_id": event_id,
                "question": question,
                "options": options,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class UpperAgentAnswer:
    """Validated upper-agent answer."""

    event_id: str
    question_fingerprint: str
    decision: Literal["answer", "escalate"]
    response_text: str
    selected_option: str | None
    confidence: Literal["low", "medium", "high"]
    rationale: str


@dataclass
class AutoAnswerState:
    """Loop-guard state persisted in the runtime sidecar."""

    event_id: str = ""
    question_fingerprint: str = ""
    attempt_count: int = 0
    last_response_hash: str = ""
    last_selected_option: str = ""
    status: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "question_fingerprint": self.question_fingerprint,
            "attempt_count": self.attempt_count,
            "last_response_hash": self.last_response_hash,
            "last_selected_option": self.last_selected_option,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AutoAnswerState:
        return cls(
            event_id=str(data.get("event_id", "")),
            question_fingerprint=str(data.get("question_fingerprint", "")),
            attempt_count=int(data.get("attempt_count", 0)),
            last_response_hash=str(data.get("last_response_hash", "")),
            last_selected_option=str(data.get("last_selected_option", "")),
            status=str(data.get("status", "")),
        )
