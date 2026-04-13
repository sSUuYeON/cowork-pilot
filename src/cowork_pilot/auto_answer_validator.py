from __future__ import annotations

import json
from dataclasses import dataclass

from cowork_pilot.auto_answer_models import PendingQuestionPacket, UpperAgentAnswer


@dataclass
class ValidationResult:
    ok: bool
    error: str = ""
    answer: UpperAgentAnswer | None = None


def validate_upper_answer(
    raw_json: str,
    packet: PendingQuestionPacket,
) -> ValidationResult:
    """Validate the upper-agent JSON output against the current packet."""

    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        return ValidationResult(ok=False, error=f"JSON 파싱 실패: {exc}")

    if not isinstance(data, dict):
        return ValidationResult(ok=False, error="응답이 JSON object가 아님")

    if data.get("event_id") != packet.event_id:
        return ValidationResult(
            ok=False,
            error=(
                f"event_id 불일치: expected={packet.event_id}, "
                f"got={data.get('event_id')}"
            ),
        )

    if data.get("question_fingerprint") != packet.question_fingerprint:
        return ValidationResult(
            ok=False,
            error=(
                "question_fingerprint 불일치: "
                f"expected={packet.question_fingerprint}, "
                f"got={data.get('question_fingerprint')}"
            ),
        )

    decision = data.get("decision", "")
    if decision not in ("answer", "escalate"):
        return ValidationResult(ok=False, error=f"잘못된 decision: {decision}")

    response_text = str(data.get("response_text", "")).strip()
    if decision == "answer" and not response_text:
        return ValidationResult(
            ok=False,
            error="decision=answer인데 response_text가 비어있음",
        )

    selected_raw = data.get("selected_option")
    selected = str(selected_raw).strip() if selected_raw is not None else None
    resolved_option: str | None = None

    if decision == "answer":
        resolved_option = _resolve_canonical_option(
            selected,
            response_text,
            packet.options,
        )
        if resolved_option is None:
            option_prefixes = _extract_option_prefixes(packet.options)
            return ValidationResult(
                ok=False,
                error=(
                    f"selected_option '{selected}'가 옵션 집합에 없음. "
                    f"유효: {sorted(option_prefixes)}"
                ),
            )
        response_text = resolved_option

    confidence = data.get("confidence", "medium")
    if confidence not in ("low", "medium", "high"):
        confidence = "medium"

    answer = UpperAgentAnswer(
        event_id=str(data["event_id"]),
        question_fingerprint=str(data["question_fingerprint"]),
        decision=decision,
        response_text=response_text,
        selected_option=resolved_option,
        confidence=confidence,
        rationale=str(data.get("rationale", "")),
    )
    return ValidationResult(ok=True, answer=answer)


def _extract_option_prefixes(options: list[str]) -> set[str]:
    prefixes: set[str] = set()
    for index, option in enumerate(options, start=1):
        stripped = option.strip()
        prefixes.add(str(index))
        if len(stripped) >= 2 and stripped[1] in (".", ")"):
            prefixes.add(stripped[0])
            prefixes.add(stripped[:2])
        if stripped:
            prefixes.add(stripped)
    return prefixes


def _find_matching_option(selected: str, options: list[str]) -> str | None:
    selected_clean = selected.strip()
    if not selected_clean:
        return None

    if selected_clean.isdigit():
        index = int(selected_clean) - 1
        if 0 <= index < len(options):
            return options[index].strip()

    if len(selected_clean) == 1 and selected_clean.isalpha():
        index = ord(selected_clean.upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index].strip()

    for option in options:
        stripped = option.strip()
        if stripped == selected_clean:
            return stripped
        if stripped.startswith(selected_clean):
            return stripped
    return None


def _response_matches_option(response_text: str, option_text: str) -> bool:
    response_clean = response_text.strip()
    option_clean = option_text.strip()
    if response_clean == option_clean:
        return True

    if response_clean.startswith(option_clean):
        return True

    option_body = option_clean[3:].strip() if len(option_clean) > 3 else option_clean
    if option_body and option_body[:20] in response_clean:
        return True
    return False


def _resolve_canonical_option(
    selected: str | None,
    response_text: str,
    options: list[str],
) -> str | None:
    if selected:
        matched = _find_matching_option(selected, options)
        if matched is not None:
            return matched

    response_clean = response_text.strip()
    if response_clean.isdigit():
        matched = _find_matching_option(response_clean, options)
        if matched is not None:
            return matched

    if len(response_clean) == 1 and response_clean.isalpha():
        matched = _find_matching_option(response_clean, options)
        if matched is not None:
            return matched

    for option in options:
        stripped = option.strip()
        if _response_matches_option(response_clean, stripped):
            return stripped
    return None
