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


def _write_contradictions_index(
    project_dir: Path,
    *,
    contradiction_id: str = "entry--join-code--edit_window",
) -> None:
    root = project_dir / "docs" / "generated" / "contradictions"
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "contradiction_id": contradiction_id,
        "domain": "entry",
        "feature": "join-code",
        "facet": "edit_window",
        "severity": "blocking",
        "question": "How should edit timing be resolved?",
        "options": [
            "오타 수정형 (Recommended): draft에서만 허용",
            "운영 조정형: closed 전까지 허용",
            "혼합형: 직접 제한",
        ],
        "recommended": "오타 수정형 (Recommended): draft에서만 허용",
        "claims": [
            {
                "source_file": "shared.md",
                "source_section": "6.2",
                "excerpt": "잠금 전까지 편집",
                "facet": "edit_window",
                "normalized_value": "before_closed",
            },
            {
                "source_file": "join-code.md",
                "source_section": "8.1",
                "excerpt": "draft 1회 편집 허용",
                "facet": "edit_window",
                "normalized_value": "draft_once",
            },
        ],
    }
    (root / "index.json").write_text(
        json.dumps({"blocking": [item], "warnings": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / f"{contradiction_id}.json").write_text(
        json.dumps(item, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_prior_ai_decision_gap_report(
    project_dir: Path,
    *,
    domain: str = "entry",
    feature: str = "share-link-qr",
) -> Path:
    path = project_dir / "docs" / "generated" / "gap-reports" / f"{domain}--{feature}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# prior\n[AI_DECISION] 기존 계약 유지\n<!-- ORCHESTRATOR:DONE -->\n",
        encoding="utf-8",
    )
    return path


def _append_optional_inputs(
    project_dir: Path,
    payload: dict[str, object],
    *paths: Path,
) -> None:
    seed = dict(payload["question_context_seed"])  # type: ignore[index]
    optional_inputs = list(seed.get("optional_inputs", []))
    optional_inputs.extend(str(path) for path in paths)
    seed["optional_inputs"] = optional_inputs
    payload["question_context_seed"] = seed
    write_runtime(project_dir, payload)


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


def test_build_packet_accepts_phase2_conflict_and_escalation(tmp_path: Path) -> None:
    payload, _ = _write_waiting_runtime(
        tmp_path,
        step="phase_2_conflict:entry--join-code--edit_window",
    )
    payload["pending_question"]["escalation"] = {  # type: ignore[index]
        "reason": "source 충돌",
        "mode": "auto",
    }
    write_runtime(tmp_path, payload)

    runtime = load_runtime(tmp_path)
    assert runtime is not None
    packet = _build_packet_from_runtime(runtime)

    assert packet is not None
    assert packet.step == "phase_2_conflict:entry--join-code--edit_window"
    assert packet.escalation_context == {"reason": "source 충돌", "mode": "auto"}


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


def test_escalate_returns_needs_input_and_persists_nested_context(tmp_path: Path) -> None:
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
    assert result.status == "needs_input"
    assert runtime is not None
    assert runtime["auto_answer_state"]["status"] == "needs_input"  # type: ignore[index]
    pending_question = runtime["pending_question"]  # type: ignore[index]
    assert pending_question["escalation"]["reason"] == "The docs are insufficient."
    assert pending_question["question"].startswith("[자동 판단 중단]")
    assert pending_question["escalation"]["resolver_reason"] == "insufficient_evidence"


def test_escalate_with_contradiction_rewrites_runtime_to_handoff_question(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    _write_contradictions_index(tmp_path)

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "The docs conflict on edit timing.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Still unsafe to choose automatically.",
                },
                ensure_ascii=False,
            ),
        ],
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "needs_input"
    runtime = load_runtime(tmp_path)
    assert runtime is not None
    pending_question = runtime["pending_question"]  # type: ignore[index]
    assert pending_question["question"].startswith("[충돌 해소 필요]")
    assert pending_question["options"][0].startswith("오타 수정형")  # type: ignore[index]
    assert pending_question["escalation"]["original_question"] == "Which v1 scope should we choose?"  # type: ignore[index]
    assert pending_question["escalation"]["resolver_reason"] == "conflict"  # type: ignore[index]


def test_handoff_rewrite_refreshes_question_context_seed_fingerprint(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    original_fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    _write_contradictions_index(tmp_path)

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": original_fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "The docs conflict on edit timing.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": original_fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Still unsafe to choose automatically.",
                },
                ensure_ascii=False,
            ),
        ],
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "needs_input"
    runtime = load_runtime(tmp_path)
    assert runtime is not None
    pending_question = runtime["pending_question"]  # type: ignore[index]
    new_fingerprint = runtime["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    assert new_fingerprint != original_fingerprint
    assert new_fingerprint == PendingQuestionPacket.compute_fingerprint(
        str(runtime["step"]),  # type: ignore[index]
        str(runtime["pending_event_id"]),  # type: ignore[index]
        str(pending_question["question"]),
        [str(option) for option in pending_question["options"]],
    )

    packet = _build_packet_from_runtime(runtime)
    assert packet is not None
    assert packet.question_text == str(pending_question["question"])


def test_conflict_with_existing_contract_uses_existing_contract_first(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, output_files = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    step = str(payload["step"])
    prior_report = _write_prior_ai_decision_gap_report(tmp_path)
    _append_optional_inputs(tmp_path, payload, prior_report)

    prompts: list[str] = []

    def _run_upper(prompt: str, *_args) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "The docs conflict with prior decisions.",
                },
                ensure_ascii=False,
            )
        assert "You are the decision_resolver" in prompt
        assert "Existing contract detected: yes" in prompt
        return json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": "A. Keep v1 minimal",
                "selected_option": "A",
                "confidence": "medium",
                "rationale": "기존 계약을 우선합니다.",
                "resolver_reason": "conflict",
                "applied_policy": "existing_contract_first",
                "ai_decision_note": "이전 AI_DECISION과 맞는 범위만 유지합니다.",
            },
            ensure_ascii=False,
        )

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=_run_upper,
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
    assert "applied_policy: existing_contract_first" in kwargs["response_text"]
    assert "selected_option: A. Keep v1 minimal" in kwargs["response_text"]


def test_conflict_with_no_contract_uses_conservative_scope(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, output_files = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    step = str(payload["step"])

    prompts: list[str] = []

    def _run_upper(prompt: str, *_args) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "The docs conflict on scope expansion.",
                },
                ensure_ascii=False,
            )
        assert "Existing contract detected: no" in prompt
        return json.dumps(
            {
                "event_id": "q1",
                "question_fingerprint": fingerprint,
                "decision": "answer",
                "response_text": "A. Keep v1 minimal",
                "selected_option": "A",
                "confidence": "medium",
                "rationale": "권한 확대를 피합니다.",
                "resolver_reason": "conflict",
                "applied_policy": "conservative_scope",
                "ai_decision_note": "기존 계약이 없어 보수적인 범위를 채택합니다.",
            },
            ensure_ascii=False,
        )

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=_run_upper,
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
    assert "applied_policy: conservative_scope" in kwargs["response_text"]


def test_insufficient_evidence_uses_recommended_plus_consistency(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    step = str(payload["step"])

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "The docs are too thin.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "answer",
                    "response_text": "A. Keep v1 minimal",
                    "selected_option": "A",
                    "confidence": "medium",
                    "rationale": "추천안과 기존 패턴이 가장 일관적입니다.",
                    "resolver_reason": "insufficient_evidence",
                    "applied_policy": "recommended_plus_consistency",
                    "ai_decision_note": "문서 근거는 제한적이지만 recommended 옵션이 가장 일관적입니다.",
                },
                ensure_ascii=False,
            ),
        ],
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
    assert "applied_policy: recommended_plus_consistency" in mock_resume.call_args.kwargs["response_text"]


def test_policy_uncertain_irreversible_escalates_to_direct_check(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "This looks irreversible.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Irreversible launch policy needs a human.",
                    "resolver_reason": "policy_uncertain",
                    "applied_policy": None,
                    "ai_decision_note": "배포 이후 되돌리기 어려운 정책 결정이라 사람이 직접 확인해야 합니다.",
                },
                ensure_ascii=False,
            ),
        ],
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "needs_input"
    runtime = load_runtime(tmp_path)
    assert runtime is not None
    pending_question = runtime["pending_question"]  # type: ignore[index]
    assert pending_question["question"].startswith("[직접 확인 필요]")
    assert pending_question["escalation"]["resolver_reason"] == "policy_uncertain"  # type: ignore[index]


def test_decision_resolver_answer_uses_ai_decision_envelope(tmp_path: Path) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, output_files = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    step = str(payload["step"])

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Need resolver review.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "answer",
                    "response_text": "A. Keep v1 minimal",
                    "selected_option": "A",
                    "confidence": "medium",
                    "rationale": "resolver answered",
                    "resolver_reason": "insufficient_evidence",
                    "applied_policy": "recommended_plus_consistency",
                    "ai_decision_note": "recommended option과 기존 패턴이 가장 일관적입니다.",
                },
                ensure_ascii=False,
            ),
        ],
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
    assert kwargs["response_text"].startswith("[AI_DECISION]")
    assert "selected_option: A. Keep v1 minimal" in kwargs["response_text"]
    assert "resolver_reason: insufficient_evidence" in kwargs["response_text"]
    assert "최종 확정 답변:\nA. Keep v1 minimal" in kwargs["response_text"]


def test_decision_resolver_escalate_rewrites_consistency_gap_handoff(
    tmp_path: Path,
) -> None:
    config, orch_config, aa_config = _make_configs(tmp_path)
    payload, _ = _write_waiting_runtime(tmp_path)
    fingerprint = payload["question_context_seed"]["question_fingerprint"]  # type: ignore[index]
    prior_report = _write_prior_ai_decision_gap_report(tmp_path)
    _append_optional_inputs(tmp_path, payload, prior_report)

    with patch(
        "cowork_pilot.auto_answer_resolver.run_upper_agent",
        side_effect=[
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Potential mismatch with prior gap reports.",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event_id": "q1",
                    "question_fingerprint": fingerprint,
                    "decision": "escalate",
                    "response_text": "",
                    "selected_option": None,
                    "confidence": "low",
                    "rationale": "Existing AI decision conflicts with this new choice.",
                    "resolver_reason": "consistency_gap",
                    "applied_policy": "existing_contract_first",
                    "ai_decision_note": "기존 AI_DECISION과 충돌 가능성이 있어 사람이 확인해야 합니다.",
                },
                ensure_ascii=False,
            ),
        ],
    ):
        result = try_auto_answer(config, orch_config, aa_config, tmp_path)

    assert result.status == "needs_input"
    runtime = load_runtime(tmp_path)
    assert runtime is not None
    pending_question = runtime["pending_question"]  # type: ignore[index]
    assert pending_question["question"].startswith("[일관성 충돌]")
    assert pending_question["escalation"]["related_ai_decision_files"] == [str(prior_report)]  # type: ignore[index]


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
