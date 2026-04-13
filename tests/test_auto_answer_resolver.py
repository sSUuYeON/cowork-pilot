from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_models import PendingQuestionPacket, Phase2StepInputs
from cowork_pilot.auto_answer_resolver import _build_packet_from_runtime, try_auto_answer
from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator import _save_codex_waiting_runtime
from cowork_pilot.docs_orchestrator_codex import CodexStepResult
from cowork_pilot.docs_orchestrator_resume import (
    DocsResumeOutcome,
    _docs_resume_expected_files,
    resume_waiting_docs_step,
)
from cowork_pilot.docs_orchestrator_runtime import load_runtime, write_runtime
from cowork_pilot.orchestrator_state import OrchestratorState, StepStatus, save_state


def _make_configs(project_dir: Path) -> tuple[Config, DocsOrchestratorConfig, AutoAnswerConfig]:
    return (
        Config(project_dir=str(project_dir), engine="codex"),
        DocsOrchestratorConfig(engine="codex"),
        AutoAnswerConfig(enabled=True, engine="codex"),
    )


def _seed_state_file(project_dir: Path, step: str = "phase_2:entry:join-code") -> None:
    state = OrchestratorState(
        current={"phase": "phase_2", "step": step, "status": "running"},
        project_summary={},
        completed=[],
        pending=[],
        errors=[],
        project_dir=str(project_dir),
    )
    save_state(state, project_dir / "docs" / "generated" / "orchestrator-state.json")


def _write_waiting_runtime(
    project_dir: Path,
    *,
    step: str = "phase_2:entry:join-code",
    question: str = "Which v1 scope should we choose?",
    options: list[str] | None = None,
    recommended: str | None = None,
    runtime_state: str = "waiting_for_input",
    auto_answer_state: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[Path]]:
    generated = project_dir / "docs" / "generated"
    required = [
        generated / "references" / "checklists.md",
        generated / "analysis-report.md",
        generated / "domain-extracts" / "shared.md",
        generated / "domain-extracts" / "entry" / "join-code.md",
    ]
    optional = [generated / "domain-extracts" / "entry" / "_overview.md"]
    output_files = [generated / "gap-reports" / "entry--join-code.md"]

    for path in required + optional:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    output_files[0].parent.mkdir(parents=True, exist_ok=True)

    if options is None:
        options = ["A. Keep v1 minimal", "B. Add export workflow"]
    if recommended is None and options:
        recommended = options[0]

    event_id = "q1"
    fingerprint = PendingQuestionPacket.compute_fingerprint(
        step,
        event_id,
        question,
        options,
    )
    payload: dict[str, object] = {
        "backend": "codex",
        "step": step,
        "runtime_state": runtime_state,
        "resume_handle": "tid-001",
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": event_id,
        "pending_question": {
            "question": question,
            "options": options,
            "recommended": recommended or "",
            "blocking": True,
        },
        "pending_approval": None,
        "question_context_seed": {
            "phase": "phase_2",
            "phase_template": "phase2_manual",
            "required_inputs": [str(path) for path in required],
            "optional_inputs": [str(path) for path in optional],
            "output_files": [str(path) for path in output_files],
            "question_fingerprint": fingerprint,
        },
    }
    if auto_answer_state is not None:
        payload["auto_answer_state"] = auto_answer_state
    write_runtime(project_dir, payload)
    return payload, output_files


def _make_completed_state(project_dir: Path, step: str) -> OrchestratorState:
    return OrchestratorState(
        current={"phase": "phase_2", "step": step, "status": "idle"},
        project_summary={},
        completed=[StepStatus(step=step, status="completed")],
        pending=[],
        errors=[],
        project_dir=str(project_dir),
    )


def test_codex_waiting_to_applied(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, output_files = _write_waiting_runtime(tmp_path)
    step = str(payload["step"])
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        return_value=json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": "A. Keep v1 minimal",
                "selected_option": "A",
                "confidence": "high",
                "rationale": "Matches the current docs.",
            },
            ensure_ascii=False,
        ),
    ), patch(
        "cowork_pilot.auto_answer_resolver.resume_waiting_docs_step",
        return_value=DocsResumeOutcome(
            status="completed",
            state=_make_completed_state(tmp_path, step),
            step=step,
        ),
    ) as mock_resume:
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "applied"
    assert result.outcome is not None
    assert result.outcome.status == "completed"
    kwargs = mock_resume.call_args.kwargs
    assert kwargs["expected_files_override"] == output_files
    assert kwargs["response_text"] == "A. Keep v1 minimal"


def test_auto_answer_prints_question_and_selected_result(
    tmp_path: Path,
    capsys,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    step = str(payload["step"])
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        return_value=json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": "A. Keep v1 minimal",
                "selected_option": "A",
                "confidence": "high",
                "rationale": "Matches the current docs.",
            },
            ensure_ascii=False,
        ),
    ), patch(
        "cowork_pilot.auto_answer_resolver.resume_waiting_docs_step",
        return_value=DocsResumeOutcome(
            status="completed",
            state=_make_completed_state(tmp_path, step),
            step=step,
        ),
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "applied"
    captured = capsys.readouterr()
    assert "[auto-answer] pending question:" in captured.err
    assert "Q: Which v1 scope should we choose?" in captured.err
    assert "[auto-answer] selected:" in captured.err
    assert "[auto-answer] applied: lower session is now completed" in captured.err


def test_unlabeled_option_answer_maps_letter_to_full_option(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    options = [
        "운영형 표준 (Recommended): 화면 유지",
        "최소형 표준: 전체 스피너",
        "직접 정의: 직접 작성",
    ]
    payload, output_files = _write_waiting_runtime(
        tmp_path,
        step="phase_2:host:_overview",
        question="호스트 공통 UI 상태는 어떤 세트로 정의할까요?",
        options=options,
        recommended=options[0],
    )
    step = str(payload["step"])
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        return_value=json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": "운영형 표준으로 정의합니다.",
                "selected_option": "A",
                "confidence": "medium",
                "rationale": "첫 번째 옵션이 가장 적합합니다.",
            },
            ensure_ascii=False,
        ),
    ), patch(
        "cowork_pilot.auto_answer_resolver.resume_waiting_docs_step",
        return_value=DocsResumeOutcome(
            status="completed",
            state=_make_completed_state(tmp_path, step),
            step=step,
        ),
    ) as mock_resume:
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "applied"
    kwargs = mock_resume.call_args.kwargs
    assert kwargs["expected_files_override"] == output_files
    assert kwargs["response_text"] == options[0]


def test_unsupported_non_phase2(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path, step="phase_1")
    payload["question_context_seed"]["phase"] = "phase_1"  # type: ignore[index]
    write_runtime(tmp_path, payload)

    result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "unsupported"


def test_unsupported_free_text(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    _write_waiting_runtime(
        tmp_path,
        options=[],
        recommended="",
    )

    result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "unsupported"


def test_loop_guard_blocks_repeat(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    response_text = "A. Keep v1 minimal"
    response_hash = __import__("hashlib").sha256(response_text.encode("utf-8")).hexdigest()
    payload["auto_answer_state"] = {
        "event_id": "q1",
        "question_fingerprint": fingerprint,
        "attempt_count": 1,
        "last_response_hash": response_hash,
        "last_selected_option": "A",
        "status": "applied",
    }
    write_runtime(tmp_path, payload)

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        return_value=json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": response_text,
                "selected_option": "A",
                "confidence": "high",
                "rationale": "Same as before.",
            },
            ensure_ascii=False,
        ),
    ), patch(
        "cowork_pilot.auto_answer_resolver.resume_waiting_docs_step",
    ) as mock_resume:
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "failed"
    assert "loop detected" in result.reason
    mock_resume.assert_not_called()


def test_max_attempts_blocks(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    payload["auto_answer_state"] = {
        "event_id": "q1",
        "question_fingerprint": fingerprint,
        "attempt_count": 2,
        "last_response_hash": "",
        "last_selected_option": "",
        "status": "failed",
    }
    write_runtime(tmp_path, payload)

    with patch("cowork_pilot.auto_answer_resolver.run_upper_agent") as mock_run:
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "failed"
    assert "max attempts" in result.reason
    mock_run.assert_not_called()


def test_escalate_returns_escalated(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        return_value=json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "escalate",
                "response_text": "",
                "selected_option": None,
                "confidence": "low",
                "rationale": "The docs are insufficient.",
            },
            ensure_ascii=False,
        ),
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    runtime = load_runtime(tmp_path)
    assert result.status == "escalated"
    assert runtime is not None
    assert runtime["auto_answer_state"]["status"] == "escalated"  # type: ignore[index]


def test_runtime_question_context_seed_saved(tmp_path: Path) -> None:
    generated = tmp_path / "docs" / "generated"
    inputs = Phase2StepInputs(
        step_name="phase_2:entry:join-code",
        phase_template="phase2_manual",
        render_kwargs={},
        required_inputs=[
            generated / "references" / "checklists.md",
            generated / "analysis-report.md",
        ],
        optional_inputs=[generated / "domain-extracts" / "entry" / "_overview.md"],
        output_files=[generated / "gap-reports" / "entry--join-code.md"],
    )
    result = CodexStepResult(
        status="waiting",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-002",
        waiting_kind="input",
        pending_event_id="q1",
        pending_question={
            "question": "Which v1 scope should we choose?",
            "options": ["A. Keep v1 minimal", "B. Add export workflow"],
            "recommended": "A. Keep v1 minimal",
            "blocking": True,
        },
        pending_approval=None,
        error="",
    )

    _save_codex_waiting_runtime(
        project_dir=tmp_path,
        step_name=inputs.step_name,
        result=result,
        phase2_inputs=inputs,
    )

    runtime = load_runtime(tmp_path)
    assert runtime is not None
    assert runtime["question_context_seed"]["phase"] == "phase_2"  # type: ignore[index]
    assert runtime["question_context_seed"]["required_inputs"] == [  # type: ignore[index]
        str(path) for path in inputs.required_inputs
    ]
    assert runtime["question_context_seed"]["output_files"] == [  # type: ignore[index]
        str(path) for path in inputs.output_files
    ]
    assert runtime["question_context_seed"]["question_fingerprint"]  # type: ignore[index]


def test_resume_waiting_carries_forward_question_context_seed(tmp_path: Path) -> None:
    _seed_state_file(tmp_path)
    config, orch_config, _ = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    payload["auto_answer_state"] = {
        "event_id": "q1",
        "question_fingerprint": payload["question_context_seed"]["question_fingerprint"],  # type: ignore[index]
        "attempt_count": 1,
        "last_response_hash": "abc",
        "last_selected_option": "A",
        "status": "applied",
    }
    write_runtime(tmp_path, payload)

    waiting_result = CodexStepResult(
        status="waiting",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-003",
        waiting_kind="input",
        pending_event_id="q2",
        pending_question={
            "question": "Next?",
            "options": ["A. First", "B. Second"],
            "recommended": "A. First",
            "blocking": True,
        },
        pending_approval=None,
        error="",
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=waiting_result,
    ):
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text="A. Keep v1 minimal",
            response_kind="answer",
        )

    runtime = load_runtime(tmp_path)
    assert outcome.status == "waiting"
    assert runtime is not None
    assert runtime["question_context_seed"]["phase"] == payload["question_context_seed"]["phase"]  # type: ignore[index]
    assert runtime["question_context_seed"]["phase_template"] == payload["question_context_seed"]["phase_template"]  # type: ignore[index]
    assert runtime["question_context_seed"]["required_inputs"] == payload["question_context_seed"]["required_inputs"]  # type: ignore[index]
    assert runtime["question_context_seed"]["optional_inputs"] == payload["question_context_seed"]["optional_inputs"]  # type: ignore[index]
    assert runtime["question_context_seed"]["output_files"] == payload["question_context_seed"]["output_files"]  # type: ignore[index]
    assert runtime["question_context_seed"]["question_fingerprint"] != payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    assert runtime["auto_answer_state"] == payload["auto_answer_state"]  # type: ignore[index]
    packet = _build_packet_from_runtime(runtime)
    assert packet is not None
    assert packet.event_id == "q2"
    assert packet.question_text == "Next?"


def test_docs_resume_expected_files_bundle(tmp_path: Path) -> None:
    assert _docs_resume_expected_files(
        "phase_2:entry:join-code+entry:share-link-qr",
        tmp_path,
    ) == [
        tmp_path / "docs" / "generated" / "gap-reports" / "entry--join-code.md",
        tmp_path / "docs" / "generated" / "gap-reports" / "entry--share-link-qr.md",
    ]
