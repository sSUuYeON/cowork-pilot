from __future__ import annotations

import re

from cowork_pilot.models import EventType, Response


def validate_response(
    raw: str,
    event_type: EventType,
    num_options: int = 0,
) -> Response | None:
    """Validate CLI response format. Returns Response or None if invalid.

    No intelligence — just format checking.
    ESCALATE is valid for any event type — means CLI agent defers to human.
    """
    raw = raw.strip()

    if raw == "ESCALATE":
        return Response(action="escalate")

    if event_type == EventType.QUESTION:
        return _validate_question(raw, num_options)
    elif event_type == EventType.PERMISSION:
        return _validate_permission(raw)
    elif event_type == EventType.FREE_TEXT:
        return _validate_free_text(raw)
    return None


def _validate_question(raw: str, num_options: int) -> Response | None:
    # Check for "Other: text" pattern
    other_match = re.match(r"^Other:\s*(.+)$", raw, re.IGNORECASE)
    if other_match:
        text = other_match.group(1).strip()
        if text:
            return Response(action="other", value=text)
        return None

    # Check for plain number
    if re.match(r"^\d+$", raw):
        num = int(raw)
        if 1 <= num <= num_options:
            return Response(action="select", value=num)
    return None


def _validate_permission(raw: str) -> Response | None:
    lower = raw.lower()
    if lower == "allow":
        return Response(action="allow")
    if lower == "deny":
        return Response(action="deny")
    return None


def _validate_free_text(raw: str) -> Response | None:
    if not raw:
        return None
    return Response(action="text", value=raw)
