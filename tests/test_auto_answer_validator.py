from __future__ import annotations

import json
from pathlib import Path

from cowork_pilot.auto_answer_models import PendingQuestionPacket
from cowork_pilot.auto_answer_validator import validate_upper_answer


def _make_packet() -> PendingQuestionPacket:
    options = [
        "A. Keep v1 minimal",
        "B. Add export workflow",
    ]
    return PendingQuestionPacket(
        event_id="q1",
        step="phase_2:entry:share-link-qr",
        question_text="Which scope should we lock for v1?",
        options=options,
        recommended=options[0],
        seed_required_inputs=[Path("/tmp/checklists.md")],
        seed_optional_inputs=[],
        seed_output_files=[Path("/tmp/out.md")],
        question_fingerprint=PendingQuestionPacket.compute_fingerprint(
            "phase_2:entry:share-link-qr",
            "q1",
            "Which scope should we lock for v1?",
            options,
        ),
    )


def test_valid_answer_passes() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "A. Keep v1 minimal",
            "selected_option": "A",
            "confidence": "high",
            "rationale": "Matches the current docs.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is True
    assert result.answer is not None
    assert result.answer.selected_option == "A. Keep v1 minimal"
    assert result.answer.response_text == "A. Keep v1 minimal"


def test_wrong_event_id_fails() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": "other",
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "A. Keep v1 minimal",
            "selected_option": "A",
            "confidence": "high",
            "rationale": "Mismatch.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is False
    assert "event_id 불일치" in result.error


def test_invalid_json_fails() -> None:
    result = validate_upper_answer("{not json", _make_packet())
    assert result.ok is False
    assert "JSON 파싱 실패" in result.error


def test_option_mismatch_fails() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "Z. Unknown option",
            "selected_option": "Z",
            "confidence": "high",
            "rationale": "Invalid option.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is False
    assert "selected_option" in result.error


def test_empty_response_text_fails() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "",
            "selected_option": "A",
            "confidence": "high",
            "rationale": "Missing response.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is False
    assert "response_text가 비어있음" in result.error


def test_escalate_passes() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "escalate",
            "response_text": "",
            "selected_option": None,
            "confidence": "low",
            "rationale": "Docs are insufficient.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is True
    assert result.answer is not None
    assert result.answer.decision == "escalate"


def test_response_text_option_prefix_mismatch() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "B. Add export workflow",
            "selected_option": "A",
            "confidence": "medium",
            "rationale": "Prefix mismatch.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is True
    assert result.answer is not None
    assert result.answer.selected_option == "A. Keep v1 minimal"
    assert result.answer.response_text == "A. Keep v1 minimal"


def test_question_fingerprint_mismatch_fails() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": "wrong",
            "decision": "answer",
            "response_text": "A. Keep v1 minimal",
            "selected_option": "A",
            "confidence": "high",
            "rationale": "Mismatch.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is False
    assert "question_fingerprint 불일치" in result.error


def test_numeric_selected_option_maps_to_canonical_option() -> None:
    packet = _make_packet()
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "1",
            "selected_option": "1",
            "confidence": "medium",
            "rationale": "Choose first option.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is True
    assert result.answer is not None
    assert result.answer.selected_option == "A. Keep v1 minimal"
    assert result.answer.response_text == "A. Keep v1 minimal"


def test_unlabeled_options_accept_letter_selection_by_position() -> None:
    options = [
        "운영형 표준 (Recommended): 화면 유지",
        "최소형 표준: 전체 스피너",
        "직접 정의: 직접 작성",
    ]
    packet = PendingQuestionPacket(
        event_id="q2",
        step="phase_2:host:_overview",
        question_text="호스트 공통 UI 상태는 어떤 세트로 정의할까요?",
        options=options,
        recommended=options[0],
        seed_required_inputs=[Path("/tmp/checklists.md")],
        seed_optional_inputs=[],
        seed_output_files=[Path("/tmp/out.md")],
        question_fingerprint=PendingQuestionPacket.compute_fingerprint(
            "phase_2:host:_overview",
            "q2",
            "호스트 공통 UI 상태는 어떤 세트로 정의할까요?",
            options,
        ),
    )
    raw = json.dumps(
        {
            "event_id": packet.event_id,
            "question_fingerprint": packet.question_fingerprint,
            "decision": "answer",
            "response_text": "운영형 표준으로 정의합니다.",
            "selected_option": "A",
            "confidence": "medium",
            "rationale": "첫 번째 옵션이 가장 적합합니다.",
        },
        ensure_ascii=False,
    )

    result = validate_upper_answer(raw, packet)

    assert result.ok is True
    assert result.answer is not None
    assert result.answer.selected_option == options[0]
    assert result.answer.response_text == options[0]
