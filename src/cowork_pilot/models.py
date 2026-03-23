from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    QUESTION = "question"
    PERMISSION = "permission"
    FREE_TEXT = "free_text"


class WatcherState(Enum):
    IDLE = "idle"
    TOOL_USE_DETECTED = "tool_use_detected"
    DEBOUNCE_WAIT = "debounce_wait"
    PENDING_RESPONSE = "pending_response"
    RESPONDED = "responded"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    tool_use_id: str
    tool_name: str
    questions: list[dict[str, Any]] = field(default_factory=list)
    tool_input: dict[str, Any] = field(default_factory=dict)
    context_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Response:
    action: str  # "select", "other", "allow", "deny", "text"
    value: Any = None  # option number, text string, or None
