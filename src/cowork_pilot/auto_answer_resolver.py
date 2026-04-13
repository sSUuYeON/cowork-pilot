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
    ClaudeInlineMaterializer,
    CodexPathMaterializer,
    run_upper_agent,
)
from cowork_pilot.auto_answer_models import (
    AutoAnswerState,
    PendingQuestionPacket,
)
from cowork_pilot.auto_answer_validator import validate_upper_answer
from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator_resume import (
    DocsResumeOutcome,
    resume_waiting_docs_step,
)
from cowork_pilot.docs_orchestrator_runtime import load_runtime, write_runtime

logger = logging.getLogger(__name__)


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
    if not step.startswith("phase_2:"):
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
        _write_log(
            project_dir,
            {
                "step": packet.step,
                "event_id": packet.event_id,
                "upper_engine": aa_config.engine,
                "decision": "escalate",
                "rationale": answer.rationale,
                "result": "escalated",
            },
        )
        _update_auto_answer_state(
            project_dir,
            runtime,
            packet,
            response_hash="",
            status="escalated",
            selected_option="",
        )
        return AutoAnswerResult(status="escalated", reason=answer.rationale)

    response_hash = hashlib.sha256(
        answer.response_text.encode("utf-8"),
    ).hexdigest()
    selected = answer.selected_option or answer.response_text
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
            response_text=answer.response_text,
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
            "upper_engine": aa_config.engine,
            "read_files": [
                str(path)
                for path in packet.seed_required_inputs + packet.seed_optional_inputs
            ],
            "decision": answer.decision,
            "selected_option": answer.selected_option,
            "response_text": answer.response_text[:200],
            "confidence": answer.confidence,
            "rationale": answer.rationale,
            "applied_via": "docs_resume",
            "result": outcome.status,
        },
    )

    _print_status(f"applied: lower session is now {outcome.status}")

    return AutoAnswerResult(status="applied", outcome=outcome)


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
