from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_engines import (
    ClaudeInlineDecisionMaterializer,
    ClaudeInlineMaterializer,
    CodexDecisionMaterializer,
    CodexPathMaterializer,
    run_upper_agent,
)
from cowork_pilot.auto_answer_models import (
    AutoAnswerState,
    PendingQuestionPacket,
    UpperAgentAnswer,
)
from cowork_pilot.auto_answer_validator import validate_upper_answer
from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator_resume import (
    DocsResumeOutcome,
    resume_waiting_docs_step,
)
from cowork_pilot.docs_orchestrator_runtime import load_runtime, write_runtime
from cowork_pilot.source_contradictions import (
    DetectedContradiction,
    load_contradiction_report,
)

logger = logging.getLogger(__name__)

_REASON_PRIORITY = [
    "conflict",
    "consistency_gap",
    "insufficient_evidence",
    "policy_uncertain",
]


@dataclass
class AutoAnswerResult:
    """Result of one auto-answer attempt."""

    status: str
    outcome: DocsResumeOutcome | None = None
    reason: str = ""


def _coerce_path_list(value: object) -> list[Path]:
    if not isinstance(value, (list, tuple)):
        return []
    return [Path(str(item)) for item in value]


def _build_packet_from_runtime(
    runtime: dict[str, object],
) -> PendingQuestionPacket | None:
    """Build an eligible phase2 packet from the runtime payload."""

    step = str(runtime.get("step", ""))
    if not (
        step.startswith("phase_2:")
        or step.startswith("phase_2_conflict:")
    ):
        return None

    runtime_state = str(runtime.get("runtime_state", ""))
    if runtime_state != "waiting_for_input":
        return None

    pending_question = runtime.get("pending_question")
    if not isinstance(pending_question, dict):
        return None
    if not pending_question.get("blocking"):
        return None

    question_text = str(pending_question.get("question", "")).strip()
    raw_options = pending_question.get("options", [])
    if not question_text or not isinstance(raw_options, (list, tuple)):
        return None
    options = [str(option) for option in raw_options]

    recommended = str(pending_question.get("recommended", "")).strip() or None
    if len(options) < 2 or not recommended:
        return None

    event_id = str(runtime.get("pending_event_id", "")).strip()
    if not event_id:
        return None

    seed = runtime.get("question_context_seed", {})
    if not isinstance(seed, dict):
        return None
    if str(seed.get("phase", "")) != "phase_2":
        return None

    required = _coerce_path_list(seed.get("required_inputs", []))
    optional = _coerce_path_list(seed.get("optional_inputs", []))
    output_files = _coerce_path_list(seed.get("output_files", []))
    seed_fingerprint = str(seed.get("question_fingerprint", "")).strip()

    fingerprint = PendingQuestionPacket.compute_fingerprint(
        step,
        event_id,
        question_text,
        options,
    )
    if seed_fingerprint and seed_fingerprint != fingerprint:
        return None

    escalation_context = pending_question.get("escalation")
    if not isinstance(escalation_context, dict):
        escalation_context = None

    return PendingQuestionPacket(
        event_id=event_id,
        step=step,
        question_text=question_text,
        options=options,
        recommended=recommended,
        seed_required_inputs=required,
        seed_optional_inputs=optional,
        seed_output_files=output_files,
        question_fingerprint=fingerprint,
        escalation_context=escalation_context,
    )


def _check_loop_guard(
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    response_hash: str,
) -> str | None:
    aas = runtime.get("auto_answer_state", {})
    if not isinstance(aas, dict):
        return None

    previous = AutoAnswerState.from_dict(aas)
    if (
        previous.event_id == packet.event_id
        and previous.question_fingerprint == packet.question_fingerprint
        and previous.last_response_hash == response_hash
        and previous.status == "applied"
    ):
        return "loop detected: same event_id + fingerprint + response"

    if (
        previous.event_id == packet.event_id
        and previous.question_fingerprint == packet.question_fingerprint
        and previous.attempt_count >= 2
    ):
        return f"max attempts reached for event {packet.event_id}"

    return None


def _write_log(project_dir: Path, entry: dict[str, object]) -> None:
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "auto-answer.jsonl"
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _clip_text(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _print_packet(packet: PendingQuestionPacket, engine: str) -> None:
    print(
        f"[auto-answer] pending question: {packet.step} ({packet.event_id})",
        file=sys.stderr,
    )
    print(f"  Q: {_clip_text(packet.question_text)}", file=sys.stderr)
    for index, option in enumerate(packet.options, start=1):
        print(f"  {index}. {_clip_text(option)}", file=sys.stderr)
    if packet.recommended:
        print(
            f"  Recommended: {_clip_text(packet.recommended)}",
            file=sys.stderr,
        )
    print(
        f"[auto-answer] asking upper agent via {engine}...",
        file=sys.stderr,
    )


def _print_status(message: str) -> None:
    print(f"[auto-answer] {message}", file=sys.stderr)


def _file_contains(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _phase2_step_pairs(step: str) -> list[tuple[str, str]]:
    if step.startswith("phase_2_conflict:"):
        contradiction_id = step[len("phase_2_conflict:"):]
        parts = contradiction_id.split("--")
        if len(parts) >= 3:
            return [(parts[0], parts[1])]
        return []

    if not step.startswith("phase_2:"):
        return []

    pairs: list[tuple[str, str]] = []
    rest = step[len("phase_2:"):]
    for item in rest.split("+"):
        parts = item.split(":", 1)
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    return pairs


def _relevant_contradictions(
    packet: PendingQuestionPacket,
    project_dir: Path,
) -> list[DetectedContradiction]:
    generated_dir = project_dir / "docs" / "generated"
    report = load_contradiction_report(generated_dir)

    if packet.step.startswith("phase_2_conflict:"):
        contradiction_id = packet.step[len("phase_2_conflict:"):]
        return [
            item
            for item in report.blocking
            if item.contradiction_id == contradiction_id
        ]

    pairs = set(_phase2_step_pairs(packet.step))
    if not pairs:
        return []
    return [
        item
        for item in report.blocking
        if (item.domain, item.feature) in pairs
    ]


def _serialize_contradictions(
    contradictions: list[DetectedContradiction],
) -> list[dict[str, object]]:
    return [
        {
            "contradiction_id": item.contradiction_id,
            "domain": item.domain,
            "feature": item.feature,
            "facet": item.facet,
            "claims": [
                {
                    "source_file": claim.source_file,
                    "source_section": claim.source_section,
                    "excerpt": claim.excerpt,
                }
                for claim in item.claims[:3]
            ],
        }
        for item in contradictions
    ]


def _relevant_ai_decision_files(
    packet: PendingQuestionPacket,
    project_dir: Path,
) -> list[Path]:
    _ = project_dir
    results: list[Path] = []
    for path in packet.seed_optional_inputs:
        if not path.exists():
            continue
        path_str = str(path)
        if "contradiction-resolutions" in path_str and path not in results:
            results.append(path)
            continue
        if "gap-reports" in path_str and _file_contains(path, "[AI_DECISION]"):
            results.append(path)
    return results


def _existing_contract_exists(
    packet: PendingQuestionPacket,
    project_dir: Path,
) -> bool:
    return bool(_relevant_ai_decision_files(packet, project_dir))


def _policy_for_reason(reason: str, *, existing_contract_exists: bool) -> str:
    if reason == "conflict":
        return (
            "existing_contract_first"
            if existing_contract_exists
            else "conservative_scope"
        )
    if reason == "consistency_gap":
        return "existing_contract_first"
    if reason == "insufficient_evidence":
        return "recommended_plus_consistency"
    return "irreversible_guard"


def _fallback_resolver_reason(
    *,
    packet: PendingQuestionPacket,
    project_dir: Path,
    first_pass_rationale: str,
) -> str:
    contradictions = _relevant_contradictions(packet, project_dir)
    if contradictions:
        return "conflict"
    relevant_contracts = _relevant_ai_decision_files(packet, project_dir)
    if relevant_contracts:
        return "consistency_gap"

    rationale_lower = first_pass_rationale.lower()
    if any(
        token in rationale_lower
        for token in ("irreversible", "cannot undo", "unsafe", "policy")
    ):
        return "policy_uncertain"
    return "insufficient_evidence"


def _build_escalation_context(
    *,
    packet: PendingQuestionPacket,
    project_dir: Path,
    first_pass_rationale: str,
    resolver_answer: UpperAgentAnswer | None,
) -> dict[str, object]:
    pending_question = (
        dict(packet.escalation_context)
        if isinstance(packet.escalation_context, dict)
        else {}
    )
    existing_contract_exists = _existing_contract_exists(packet, project_dir)
    resolver_reason = (
        resolver_answer.resolver_reason
        if resolver_answer and resolver_answer.resolver_reason
        else _fallback_resolver_reason(
            packet=packet,
            project_dir=project_dir,
            first_pass_rationale=first_pass_rationale,
        )
    )
    original_question = str(
        pending_question.get("original_question", packet.question_text),
    ).strip() or packet.question_text
    original_options = [
        str(option)
        for option in pending_question.get("original_options", packet.options)
    ]
    original_recommended = (
        str(
            pending_question.get(
                "original_recommended",
                packet.recommended or "",
            ),
        ).strip()
        or packet.recommended
        or ""
    )

    return {
        "reason": first_pass_rationale,
        "resolver_reason": resolver_reason,
        "applied_policy": (
            resolver_answer.applied_policy
            if resolver_answer and resolver_answer.applied_policy
            else (
                None
                if resolver_reason == "policy_uncertain"
                else _policy_for_reason(
                    resolver_reason,
                    existing_contract_exists=existing_contract_exists,
                )
            )
        ),
        "ai_decision_note": (
            resolver_answer.ai_decision_note if resolver_answer else None
        ),
        "original_question": original_question,
        "original_options": original_options,
        "original_recommended": original_recommended,
        "related_contradictions": _serialize_contradictions(
            _relevant_contradictions(packet, project_dir),
        ),
        "related_ai_decision_files": [
            str(path) for path in _relevant_ai_decision_files(packet, project_dir)
        ],
    }


def _refresh_question_context_seed(
    runtime: dict[str, object],
    *,
    step: str,
    event_id: str,
    question: str,
    options: list[str],
) -> None:
    seed_raw = runtime.get("question_context_seed")
    if not isinstance(seed_raw, dict):
        return

    seed = dict(seed_raw)
    seed["question_fingerprint"] = PendingQuestionPacket.compute_fingerprint(
        step=step,
        event_id=event_id,
        question=question,
        options=options,
    )
    runtime["question_context_seed"] = seed


def _rewrite_runtime_for_handoff(
    *,
    project_dir: Path,
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    first_pass_rationale: str,
    resolver_answer: UpperAgentAnswer | None,
) -> dict[str, object]:
    updated_runtime = dict(runtime)
    pending_question = updated_runtime.get("pending_question", {})
    pending = dict(pending_question) if isinstance(pending_question, dict) else {}
    contradictions = _relevant_contradictions(packet, project_dir)
    escalation_payload = _build_escalation_context(
        packet=packet,
        project_dir=project_dir,
        first_pass_rationale=first_pass_rationale,
        resolver_answer=resolver_answer,
    )

    resolver_reason = str(escalation_payload.get("resolver_reason", "")).strip()
    original_question = str(escalation_payload.get("original_question", "")).strip()
    original_options = [
        str(option) for option in escalation_payload.get("original_options", [])
    ]
    original_recommended = str(
        escalation_payload.get("original_recommended", ""),
    ).strip()
    ai_decision_note = str(
        escalation_payload.get("ai_decision_note", ""),
    ).strip()

    if resolver_reason == "conflict" and contradictions:
        primary = contradictions[0]
        escalation_payload["handoff_contradiction_id"] = primary.contradiction_id
        pending["question"] = (
            "[충돌 해소 필요]\n"
            "기존 문서 또는 이전 결정 간 충돌이 있어, 아래 계약을 먼저 사람이 확정해야 합니다.\n\n"
            f"{primary.question}"
        )
        pending["options"] = list(primary.options)
        pending["recommended"] = primary.recommended or ""
    elif resolver_reason == "consistency_gap":
        pending["question"] = (
            "[일관성 충돌]\n"
            "기존 AI_DECISION 또는 이미 확정된 계약과 이번 선택이 충돌할 수 있어 사람이 정해야 합니다.\n"
            f"{ai_decision_note or first_pass_rationale}\n\n"
            f"원래 질문:\n{original_question}"
        )
        pending["options"] = original_options
        pending["recommended"] = original_recommended
    elif resolver_reason == "policy_uncertain":
        pending["question"] = (
            "[직접 확인 필요]\n"
            "되돌리기 어려운 결정이라 자동 확정을 중단했습니다.\n"
            f"{ai_decision_note or first_pass_rationale}\n\n"
            f"원래 질문:\n{original_question}"
        )
        pending["options"] = original_options
        pending["recommended"] = original_recommended
    else:
        pending["question"] = (
            "[자동 판단 중단]\n"
            "근거가 부족해 자동으로 확정하지 않았습니다.\n"
            f"{ai_decision_note or first_pass_rationale}\n\n"
            f"원래 질문:\n{original_question}"
        )
        pending["options"] = original_options
        pending["recommended"] = original_recommended

    pending["blocking"] = True
    pending["escalation"] = escalation_payload
    updated_runtime["pending_question"] = pending
    _refresh_question_context_seed(
        updated_runtime,
        step=packet.step,
        event_id=packet.event_id,
        question=str(pending.get("question", "")).strip(),
        options=[str(option) for option in pending.get("options", [])],
    )
    write_runtime(project_dir, updated_runtime)
    return updated_runtime


def _try_decision_resolver(
    *,
    packet: PendingQuestionPacket,
    aa_config: AutoAnswerConfig,
    project_dir: Path,
    previous_rationale: str,
) -> UpperAgentAnswer | None:
    current_rationale = previous_rationale
    attempts = max(1, aa_config.max_conflict_resolver_attempts)
    existing_contract_exists = _existing_contract_exists(packet, project_dir)

    for attempt in range(attempts):
        if aa_config.engine == "codex":
            prompt = CodexDecisionMaterializer().build_prompt(
                packet,
                previous_rationale=current_rationale,
                existing_contract_exists=existing_contract_exists,
            )
        elif aa_config.engine == "claude":
            prompt = ClaudeInlineDecisionMaterializer(
                max_chars=aa_config.claude_max_chars,
            ).build_prompt(
                packet,
                previous_rationale=current_rationale,
                existing_contract_exists=existing_contract_exists,
            )
        else:
            return None

        if prompt is None:
            _print_status(
                "decision_resolver unsupported: prompt materialization exceeded limits",
            )
            return None

        _print_status(f"asking decision_resolver via {aa_config.engine}...")
        try:
            raw_output = run_upper_agent(prompt, aa_config, project_dir)
        except Exception as exc:
            _print_status(f"decision_resolver failed: upper agent error: {exc}")
            return None

        validation = validate_upper_answer(raw_output, packet)
        if not validation.ok:
            _print_status(
                f"decision_resolver failed: validation error: {validation.error}",
            )
            return None

        answer = validation.answer
        assert answer is not None
        if answer.decision == "answer":
            return answer
        current_rationale = answer.rationale or current_rationale
        if attempt == attempts - 1:
            _print_status(
                "decision_resolver escalated: "
                f"{_clip_text(current_rationale or 'unsafe to answer')}",
            )
            return answer

    return None


def _build_ai_decision_resume_text(answer: UpperAgentAnswer) -> str:
    selected = answer.selected_option or answer.response_text
    resolver_reason = answer.resolver_reason or "insufficient_evidence"
    applied_policy = answer.applied_policy or _policy_for_reason(
        resolver_reason,
        existing_contract_exists=False,
    )
    note = answer.ai_decision_note or answer.rationale or "자동 결정 근거를 기록합니다."
    return "\n".join(
        [
            "[AI_DECISION]",
            f"selected_option: {selected}",
            f"resolver_reason: {resolver_reason}",
            f"applied_policy: {applied_policy}",
            f"note: {note}",
            "[/AI_DECISION]",
            "",
            "최종 확정 답변:",
            selected,
        ]
    )


def _apply_answer(
    *,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    answer: UpperAgentAnswer,
    applied_via: str,
    upper_engine: str,
) -> AutoAnswerResult:
    response_hash = hashlib.sha256(
        answer.response_text.encode("utf-8"),
    ).hexdigest()
    selected = answer.selected_option or answer.response_text
    resume_text = (
        _build_ai_decision_resume_text(answer)
        if applied_via == "decision_resolver"
        else answer.response_text
    )
    _print_status(
        "selected: "
        f"{_clip_text(selected)} "
        f"(confidence={answer.confidence})",
    )
    if answer.rationale:
        _print_status(f"rationale: {_clip_text(answer.rationale)}")
    loop_error = _check_loop_guard(runtime, packet, response_hash)
    if loop_error:
        _print_status(f"failed: {loop_error}")
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "loop_error": loop_error,
                "result": "failed",
            },
        )
        return AutoAnswerResult(status="failed", reason=loop_error)

    try:
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text=resume_text,
            response_kind="answer",
            expected_files_override=list(packet.seed_output_files),
        )
    except RuntimeError as exc:
        _print_status(f"failed: resume error: {exc}")
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "resume_error": str(exc),
                "result": "failed",
            },
        )
        return AutoAnswerResult(
            status="failed",
            reason=f"resume failed: {exc}",
        )

    _update_auto_answer_state(
        project_dir,
        load_runtime(project_dir) or {},
        packet,
        response_hash=response_hash,
        status="applied",
        selected_option=answer.selected_option or "",
    )

    _write_log(
        project_dir,
        {
            "step": packet.step,
            "event_id": packet.event_id,
            "source": "docs_runtime",
            "upper_engine": upper_engine,
            "read_files": [
                str(path)
                for path in packet.seed_required_inputs + packet.seed_optional_inputs
            ],
            "decision": answer.decision,
            "selected_option": answer.selected_option,
            "response_text": resume_text[:200],
            "confidence": answer.confidence,
            "rationale": answer.rationale,
            "resolver_reason": answer.resolver_reason,
            "applied_policy": answer.applied_policy,
            "ai_decision_note": answer.ai_decision_note,
            "applied_via": applied_via,
            "result": outcome.status,
        },
    )

    _print_status(f"applied: lower session is now {outcome.status}")
    return AutoAnswerResult(status="applied", outcome=outcome)


def try_auto_answer(
    config: Config,
    orch_config: DocsOrchestratorConfig,
    aa_config: AutoAnswerConfig,
    project_dir: Path,
) -> AutoAnswerResult:
    """Try to answer the current waiting phase2 question automatically."""

    if not aa_config.enabled:
        return AutoAnswerResult(
            status="unsupported",
            reason="auto-answer disabled",
        )

    runtime = load_runtime(project_dir)
    if runtime is None:
        return AutoAnswerResult(status="failed", reason="no runtime found")

    packet = _build_packet_from_runtime(runtime)
    if packet is None:
        _print_status("unsupported: question not eligible for auto-answer")
        return AutoAnswerResult(
            status="unsupported",
            reason="question not eligible for auto-answer",
        )

    if aa_config.engine == "codex":
        materializer = CodexPathMaterializer()
    elif aa_config.engine == "claude":
        materializer = ClaudeInlineMaterializer(
            max_chars=aa_config.claude_max_chars,
        )
    else:
        return AutoAnswerResult(
            status="failed",
            reason=f"unknown engine: {aa_config.engine}",
        )

    prompt = materializer.build_prompt(packet)
    if prompt is None:
        _print_status("unsupported: prompt materialization exceeded limits")
        return AutoAnswerResult(
            status="unsupported",
            reason="claude mode: input files exceed token budget",
        )

    _print_packet(packet, aa_config.engine)

    aas = runtime.get("auto_answer_state", {})
    if isinstance(aas, dict):
        previous = AutoAnswerState.from_dict(aas)
        if (
            previous.event_id == packet.event_id
            and previous.question_fingerprint == packet.question_fingerprint
            and previous.attempt_count >= aa_config.max_attempts_per_event
        ):
            return AutoAnswerResult(
                status="failed",
                reason=(
                    f"max attempts ({aa_config.max_attempts_per_event}) reached"
                ),
            )

    try:
        raw_output = run_upper_agent(prompt, aa_config, project_dir)
    except Exception as exc:
        _print_status(f"failed: upper agent error: {exc}")
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "upper_engine": aa_config.engine,
                "error": str(exc),
                "result": "failed",
            },
        )
        return AutoAnswerResult(
            status="failed",
            reason=f"upper agent failed: {exc}",
        )

    validation = validate_upper_answer(raw_output, packet)
    if not validation.ok:
        _print_status(f"failed: validation error: {validation.error}")
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "upper_engine": aa_config.engine,
                "validation_error": validation.error,
                "raw_output": raw_output[:500],
                "result": "failed",
            },
        )
        _update_auto_answer_state(
            project_dir,
            runtime,
            packet,
            response_hash="",
            status="failed",
            selected_option="",
        )
        return AutoAnswerResult(
            status="failed",
            reason=f"validation failed: {validation.error}",
        )

    answer = validation.answer
    assert answer is not None

    if answer.decision == "escalate":
        _print_status(
            f"escalated: {_clip_text(answer.rationale or 'upper agent escalated')}",
        )
        resolver_answer: UpperAgentAnswer | None = None

        if (
            aa_config.escalate_mode == "auto"
            and aa_config.conflict_resolver_enabled
        ):
            resolver_answer = _try_decision_resolver(
                packet=packet,
                aa_config=aa_config,
                project_dir=project_dir,
                previous_rationale=answer.rationale,
            )
            if resolver_answer is not None and resolver_answer.decision == "answer":
                return _apply_answer(
                    config=config,
                    orch_config=orch_config,
                    project_dir=project_dir,
                    runtime=runtime,
                    packet=packet,
                    answer=resolver_answer,
                    applied_via="decision_resolver",
                    upper_engine=aa_config.engine,
                )

        runtime = _rewrite_runtime_for_handoff(
            project_dir=project_dir,
            runtime=runtime,
            packet=packet,
            first_pass_rationale=answer.rationale,
            resolver_answer=resolver_answer,
        )
        escalation_context = runtime.get("pending_question", {})
        pending = dict(escalation_context) if isinstance(escalation_context, dict) else {}
        escalation_data = pending.get("escalation", {})
        escalation_payload = (
            dict(escalation_data) if isinstance(escalation_data, dict) else {}
        )
        final_reason = str(
            escalation_payload.get("resolver_reason", answer.rationale),
        ).strip() or answer.rationale
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "upper_engine": aa_config.engine,
                "decision": "escalate",
                "rationale": answer.rationale,
                "resolver_reason": escalation_payload.get("resolver_reason"),
                "applied_policy": escalation_payload.get("applied_policy"),
                "ai_decision_note": escalation_payload.get("ai_decision_note"),
                "result": "escalated",
            },
        )

        next_status = (
            "escalated"
            if aa_config.escalate_mode == "never_human"
            else "needs_input"
        )
        _update_auto_answer_state(
            project_dir,
            runtime,
            packet,
            response_hash="",
            status=next_status,
            selected_option="",
        )
        if next_status == "escalated":
            return AutoAnswerResult(status="escalated", reason=final_reason)
        return AutoAnswerResult(status="needs_input", reason=final_reason)

    return _apply_answer(
        config=config,
        orch_config=orch_config,
        project_dir=project_dir,
        runtime=runtime,
        packet=packet,
        answer=answer,
        applied_via="docs_resume",
        upper_engine=aa_config.engine,
    )


def _update_auto_answer_state(
    project_dir: Path,
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    *,
    response_hash: str,
    status: str,
    selected_option: str,
) -> None:
    previous_data = runtime.get("auto_answer_state", {})
    if not isinstance(previous_data, dict):
        previous_data = {}
    previous = AutoAnswerState.from_dict(previous_data)

    if previous.question_fingerprint != packet.question_fingerprint:
        attempt_count = 1
    else:
        attempt_count = previous.attempt_count + 1

    new_state = AutoAnswerState(
        event_id=packet.event_id,
        question_fingerprint=packet.question_fingerprint,
        attempt_count=attempt_count,
        last_response_hash=response_hash,
        last_selected_option=selected_option,
        status=status,
    )

    current = load_runtime(project_dir)
    if current is not None:
        current["auto_answer_state"] = new_state.to_dict()
        write_runtime(project_dir, current)
