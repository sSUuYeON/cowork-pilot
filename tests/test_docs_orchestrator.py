"""Tests for docs_orchestrator — Phase 0 → 1 → 1.5 → 2 → 3 state transitions.

All external calls (session_opener, subprocess, AppleScript) are mocked.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator import (
    _build_feature_bundles,
    _check_output_files,
    _check_output_files_fallback,
    _determine_next_step,
    _determine_watch_mode,
    _grep_forbidden_expressions,
    _resolve_separator_fallback,
    _is_feature_in_completed_bundle,
    _notify_completion,
    _parse_expected_files,
    _parse_outline_plans,
    _resolve_bundles,
    _run_final_completion,
    _run_phase_0,
    _run_phase_1,
    _run_phase_1_5,
    _run_phase_2,
    _run_phase_3,
    _run_phase_4,
    _run_phase_5_detail,
    _run_phase_5_outline,
    _rollback_phase_1,
    _update_state_completed,
    _update_state_error,
    _update_state_running,
    check_bundle_quality_degradation,
    run_docs_orchestrator,
)
from cowork_pilot.orchestrator_prompts import build_session_prompt
from cowork_pilot.orchestrator_state import (
    OrchestratorState,
    StepStatus,
    generate_gap_summary,
    load_state,
    recover_running_step,
    save_state,
)
from cowork_pilot.orchestrator.quality_gate import Phase1Result
from cowork_pilot.quality_gate import GateResult


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def base_config(tmp_path: Path) -> Config:
    """Create a minimal Config for testing."""
    return Config(
        project_dir=str(tmp_path),
        session_base_path=str(tmp_path / "sessions"),
        log_path=str(tmp_path / "logs" / "test.jsonl"),
    )


@pytest.fixture
def orch_config() -> DocsOrchestratorConfig:
    """Create a minimal DocsOrchestratorConfig."""
    return DocsOrchestratorConfig(
        idle_timeout_seconds=5.0,
        completion_poll_interval=0.1,
        idle_grace_seconds=1.0,
        docs_mode="auto",
    )


@pytest.fixture
def project_with_sources(tmp_path: Path) -> Path:
    """Create a project directory with source files."""
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    (source_dir / "planning.md").write_text(
        "# 프로젝트 기획서\n\n"
        "## 인증\n로그인, 회원가입\n\n"
        "## 결제\n결제 수단, 환불\n\n"
        "## 예약\n예약 관리\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def empty_state() -> OrchestratorState:
    """A fresh initial state."""
    return OrchestratorState()


@pytest.fixture
def phase0_completed_state(tmp_path: Path) -> OrchestratorState:
    """State after Phase 0 is completed."""
    return OrchestratorState(
        current={"phase": "phase_1", "step": "phase_1", "status": "idle"},
        project_summary={
            "type": "unknown",
            "source_docs": ["planning.md"],
            "domains": ["planning"],
            "features": {"planning": ["인증", "결제", "예약"]},
            "estimated_sessions": 15,
            "source_line_count": 100,
        },
        completed=[
            StepStatus(
                step="phase_0",
                status="completed",
                completed_at="2026-04-01T10:00:00",
                result="success",
            )
        ],
        pending=[],
        errors=[],
        updated_at="2026-04-01T10:00:00",
        mode="auto",
        project_dir=str(tmp_path),
    )


@pytest.fixture
def phase1_completed_state(tmp_path: Path) -> OrchestratorState:
    """State after Phase 1 is completed."""
    return OrchestratorState(
        current={"phase": "phase_1_5", "step": "phase_1_5", "status": "idle"},
        project_summary={
            "type": "unknown",
            "source_docs": ["planning.md"],
            "domains": ["planning"],
            "features": {"planning": ["인증", "결제", "예약"]},
            "estimated_sessions": 15,
            "source_line_count": 100,
        },
        completed=[
            StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
            StepStatus(step="phase_1", status="completed", completed_at="2026-04-01T10:30:00", result="success"),
        ],
        pending=[],
        errors=[],
        updated_at="2026-04-01T10:30:00",
        mode="auto",
        project_dir=str(tmp_path),
    )


# ── _determine_next_step tests ──────────────────────────────────────


class TestDetermineNextStep:
    def test_empty_state_returns_phase_0(self, empty_state: OrchestratorState):
        assert _determine_next_step(empty_state) == "phase_0"

    def test_phase0_done_returns_phase_1(self, phase0_completed_state: OrchestratorState):
        assert _determine_next_step(phase0_completed_state) == "phase_1"

    def test_phase1_done_returns_phase_1_5(self, phase1_completed_state: OrchestratorState):
        assert _determine_next_step(phase1_completed_state) == "phase_1_5"

    def test_all_early_phases_done_returns_phase_2(self, phase1_completed_state: OrchestratorState):
        """Phase 0 + 1 + 1.5 completed → Phase 2 (gap analysis)."""
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=list(phase1_completed_state.completed) + [
                StepStatus(step="phase_1_5", status="completed", completed_at="2026-04-01T11:00:00", result="success"),
            ],
            pending=[],
            errors=[],
            updated_at="2026-04-01T11:00:00",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_2"

    def test_phase_1_5_escalate_allows_retry(self, phase1_completed_state: OrchestratorState):
        """Phase 1.5 ESCALATE error → returns 'phase_1_5' for retry."""
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=phase1_completed_state.completed,
            pending=[],
            errors=[{
                "at": "2026-04-01T10:45:00",
                "step": "phase_1_5",
                "error": "ESCALATE: 커버리지 0.50 < 0.8",
                "action": "재시도 필요",
            }],
            updated_at="2026-04-01T10:45:00",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_1_5"

    def test_phase_1_5_non_escalate_error_allows_retry(self, phase1_completed_state: OrchestratorState):
        """Phase 1.5 non-ESCALATE error → can retry."""
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=phase1_completed_state.completed,
            pending=[],
            errors=[{
                "at": "2026-04-01T10:45:00",
                "step": "phase_1_5",
                "error": "누락 기능 보충 필요: planning/결제",
                "action": "재시도 필요",
            }],
            updated_at="2026-04-01T10:45:00",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_1_5"

    def test_phase_1_5_max_retries_returns_none(self, phase1_completed_state: OrchestratorState):
        """Phase 1.5 errors >= max retries → returns None to stop loop."""
        errors = [
            {
                "at": f"2026-04-01T10:{45+i}:00",
                "step": "phase_1_5",
                "error": f"ESCALATE: 실패 {i+1}",
                "action": "재시도 필요",
            }
            for i in range(3)  # _PHASE_1_5_MAX_RETRIES = 3
        ]
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=phase1_completed_state.completed,
            pending=[],
            errors=errors,
            updated_at="2026-04-01T10:48:00",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )
        assert _determine_next_step(state) is None

    def test_phase_1_5_rollback_then_phase_1_retry(self, phase1_completed_state: OrchestratorState):
        """After Phase 1 rollback (removed from completed), returns 'phase_1'."""
        # Simulate state after rollback: phase_0 completed, phase_1 NOT completed
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=[s for s in phase1_completed_state.completed if s.step != "phase_1"],
            pending=[],
            errors=[{
                "at": "2026-04-01T10:45:00",
                "step": "phase_1_5",
                "error": "ESCALATE: 커버리지 부족",
                "action": "재시도 필요",
            }],
            updated_at="2026-04-01T10:45:00",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_1"


# ── _determine_watch_mode tests ─────────────────────────────────────


class TestDetermineWatchMode:
    def test_auto_mode_returns_true(self, orch_config: DocsOrchestratorConfig):
        orch_config.docs_mode = "auto"
        assert _determine_watch_mode("phase_1", orch_config) is True

    def test_manual_mode_returns_false(self, orch_config: DocsOrchestratorConfig):
        orch_config.docs_mode = "manual"
        assert _determine_watch_mode("phase_1", orch_config) is False

    def test_hybrid_mode_override_domain_returns_false(self, orch_config: DocsOrchestratorConfig):
        orch_config.docs_mode = "hybrid"
        orch_config.manual_override = ["payment", "auth"]
        assert _determine_watch_mode("phase_2:payment:refund", orch_config) is False

    def test_hybrid_mode_non_override_domain_returns_true(self, orch_config: DocsOrchestratorConfig):
        orch_config.docs_mode = "hybrid"
        orch_config.manual_override = ["payment"]
        assert _determine_watch_mode("phase_2:booking:reservation", orch_config) is True

    def test_hybrid_mode_no_domain_in_step_returns_true(self, orch_config: DocsOrchestratorConfig):
        orch_config.docs_mode = "hybrid"
        orch_config.manual_override = ["payment"]
        assert _determine_watch_mode("phase_1", orch_config) is True


# ── State transition helper tests ───────────────────────────────────


class TestStateTransitions:
    def test_update_state_running(self, phase0_completed_state: OrchestratorState):
        new_state = _update_state_running(phase0_completed_state, "phase_1")
        assert new_state.current["status"] == "running"
        assert new_state.current["step"] == "phase_1"
        assert new_state.current["phase"] == "phase_1"

    def test_update_state_completed(self, phase0_completed_state: OrchestratorState):
        running = _update_state_running(phase0_completed_state, "phase_1")
        completed = _update_state_completed(running, "phase_1", "테스트 완료")
        assert completed.current["status"] == "idle"
        assert len(completed.completed) == len(phase0_completed_state.completed) + 1
        assert completed.completed[-1].step == "phase_1"
        assert completed.completed[-1].result == "success"

    def test_update_state_error(self, phase0_completed_state: OrchestratorState):
        running = _update_state_running(phase0_completed_state, "phase_1")
        errored = _update_state_error(running, "phase_1", "세션 실패")
        assert errored.current["status"] == "idle"
        assert len(errored.errors) == 1
        assert errored.errors[0]["step"] == "phase_1"
        assert errored.errors[0]["error"] == "세션 실패"

    def test_rollback_phase_1(self, phase1_completed_state: OrchestratorState):
        """Rollback removes phase_1 and phase_1:* from completed."""
        # Add a domain sub-step to verify it's also removed
        extra_completed = list(phase1_completed_state.completed) + [
            StepStatus(step="phase_1:기획서", status="completed"),
        ]
        state = OrchestratorState(
            current=phase1_completed_state.current,
            project_summary=phase1_completed_state.project_summary,
            completed=extra_completed,
            pending=[],
            errors=[],
            updated_at="2026-04-01",
            mode="auto",
            project_dir=phase1_completed_state.project_dir,
        )

        rolled_back = _rollback_phase_1(state)
        completed_steps = {s.step for s in rolled_back.completed}
        assert "phase_0" in completed_steps  # phase_0 preserved
        assert "phase_1" not in completed_steps  # phase_1 removed
        assert "phase_1:기획서" not in completed_steps  # domain sub-step removed


# ── Phase 0 → 1 → 1.5 integration test ─────────────────────────────


class TestPhaseTransitionIntegration:
    """Simulate the Phase 0 → 1 → 1.5 flow with mocked sessions."""

    @patch("cowork_pilot.docs_orchestrator._confirm_proceed", return_value=True)
    @patch("cowork_pilot.docs_orchestrator._copy_references")
    def test_phase_0_creates_state(
        self,
        mock_copy: MagicMock,
        mock_confirm: MagicMock,
        project_with_sources: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        base_config.project_dir = str(project_with_sources)
        generated_dir = project_with_sources / "docs" / "generated"
        state_path = generated_dir / "orchestrator-state.json"

        state = OrchestratorState()
        result = _run_phase_0(
            state, base_config, orch_config, project_with_sources, generated_dir, state_path,
        )

        assert generated_dir.exists()
        assert state_path.exists()
        completed_steps = {s.step for s in result.completed}
        assert "phase_0" in completed_steps
        assert result.current["phase"] == "phase_1"
        assert result.project_summary.get("domains")
        assert int(result.project_summary.get("source_line_count", 0)) > 0

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_1_single_session(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase0_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 1 with source <= 3000 lines → single session."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)
        generated_dir = tmp_path / "docs" / "generated"
        generated_dir.mkdir(parents=True)
        state_path = generated_dir / "orchestrator-state.json"

        result = _run_phase_1(
            phase0_completed_state, base_config, orch_config,
            tmp_path, generated_dir, tmp_path / "sessions", state_path,
        )

        mock_open.assert_called_once()
        mock_wait.assert_called_once()
        completed_steps = {s.step for s in result.completed}
        assert "phase_1" in completed_steps

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_1_multi_session(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """Phase 1 with source > 3000 lines → multiple sessions."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)
        generated_dir = tmp_path / "docs" / "generated"
        generated_dir.mkdir(parents=True)
        state_path = generated_dir / "orchestrator-state.json"

        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "idle"},
            project_summary={
                "source_docs": ["big.md"],
                "domains": ["auth", "payment"],
                "features": {"auth": ["login"], "payment": ["pay"]},
                "source_line_count": 5000,  # > 3000
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        result = _run_phase_1(
            state, base_config, orch_config,
            tmp_path, generated_dir, tmp_path / "sessions", state_path,
        )

        # 1 (overall analysis) + 2 (auth, payment domains) = 3 sessions
        assert mock_open.call_count == 3
        completed_steps = {s.step for s in result.completed}
        assert "phase_1" in completed_steps
        assert "phase_1:auth" in completed_steps
        assert "phase_1:payment" in completed_steps

    def test_phase_1_5_pass(
        self,
        phase1_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 1.5 passes → step completed.

        Both gates must report success: legacy coverage OK AND new gate ok=True.
        """
        base_config.project_dir = str(tmp_path)
        state_path = tmp_path / "docs" / "generated" / "orchestrator-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        gate_result = GateResult(
            passed=True,
            coverage_ratio=0.95,
            uncovered_sections=[],
            missing_features=[],
        )
        new_ok = Phase1Result(ok=True, hard_failures=[], warnings=[])

        with patch(
            "cowork_pilot.docs_orchestrator.check_phase1_quality",
            return_value=gate_result,
        ), patch(
            "cowork_pilot.docs_orchestrator.evaluate_phase1",
            return_value=new_ok,
        ):
            result = _run_phase_1_5(
                phase1_completed_state, base_config, orch_config, tmp_path, state_path,
            )

        completed_steps = {s.step for s in result.completed}
        assert "phase_1_5" in completed_steps
        assert len(result.errors) == 0

    @patch("cowork_pilot.docs_orchestrator._notify_escalate")
    def test_phase_1_5_fail_coverage_escalates(
        self,
        mock_notify: MagicMock,
        phase1_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 1.5 coverage failure → ESCALATE, doesn't advance to Phase 2."""
        base_config.project_dir = str(tmp_path)
        state_path = tmp_path / "docs" / "generated" / "orchestrator-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        gate_result = GateResult(
            passed=False,
            coverage_ratio=0.5,
            uncovered_sections=["인증"],
            missing_features=[],
        )

        with patch("cowork_pilot.docs_orchestrator.check_phase1_quality", return_value=gate_result):
            result = _run_phase_1_5(
                phase1_completed_state, base_config, orch_config, tmp_path, state_path,
            )

        completed_steps = {s.step for s in result.completed}
        assert "phase_1_5" not in completed_steps
        # Phase 1 should be rolled back so it can re-run
        assert "phase_1" not in completed_steps
        assert len(result.errors) > 0
        assert "ESCALATE" in result.errors[-1]["error"]
        mock_notify.assert_called_once()

    @patch("cowork_pilot.docs_orchestrator._notify_escalate")
    def test_phase_1_5_halts_when_new_gate_hard_fails_even_if_legacy_passes(
        self,
        mock_notify: MagicMock,
        phase1_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Single-gate rewiring: new gate's hard_failures must halt the pipeline.

        The legacy gate reports passed=True (coverage OK, no missing_features)
        while the new gate reports ok=False with a hard_failure (e.g., the
        analysis-report.md is missing or shared.md is missing). Before the
        Chunk 3 single-gate rewiring, the orchestrator consulted only the
        legacy gate's ``passed`` field and advanced to Phase 2 even though
        the new gate had flagged a hard failure. This test pins the correct
        behavior: phase_1_5 must NOT complete, the pipeline must report the
        new gate's hard failure, and Phase 1 must be rolled back so the
        extraction can re-run.
        """
        base_config.project_dir = str(tmp_path)
        state_path = tmp_path / "docs" / "generated" / "orchestrator-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        legacy_ok = GateResult(
            passed=True,
            coverage_ratio=0.95,
            uncovered_sections=[],
            missing_features=[],
        )
        new_fail = Phase1Result(
            ok=False,
            hard_failures=["domain-extracts/shared.md is missing (hard fail)"],
            warnings=[],
        )

        with patch(
            "cowork_pilot.docs_orchestrator.check_phase1_quality",
            return_value=legacy_ok,
        ), patch(
            "cowork_pilot.docs_orchestrator.evaluate_phase1",
            return_value=new_fail,
        ):
            result = _run_phase_1_5(
                phase1_completed_state, base_config, orch_config, tmp_path, state_path,
            )

        completed_steps = {s.step for s in result.completed}
        assert "phase_1_5" not in completed_steps, (
            "phase_1_5 must not complete when the new gate reports a hard failure"
        )
        # Phase 1 must be rolled back so the extraction can re-run.
        assert "phase_1" not in completed_steps
        assert len(result.errors) > 0
        # The new gate's hard_failure message must surface in the error.
        assert any(
            "shared.md" in err.get("error", "") for err in result.errors
        ), f"expected 'shared.md' in errors, got: {result.errors}"

    def test_phase_1_5_fail_missing_features_only(
        self,
        phase1_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 1.5 new-gate hard failure (missing features) → rollback, not ESCALATE.

        After the Chunk 3 single-gate rewiring, the new gate (``evaluate_phase1``)
        owns feature / shared / overview presence checks. When the legacy
        coverage gate is OK but the new gate reports hard_failures for missing
        feature files, the pipeline must roll back Phase 1 without triggering
        the ESCALATE path (which is reserved for coverage failures).
        """
        base_config.project_dir = str(tmp_path)
        state_path = tmp_path / "docs" / "generated" / "orchestrator-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        legacy_ok = GateResult(
            passed=True,
            coverage_ratio=0.9,
            uncovered_sections=[],
            missing_features=[],
        )
        new_fail = Phase1Result(
            ok=False,
            hard_failures=["no feature files were produced under domain-extracts/"],
            warnings=[],
        )

        with patch(
            "cowork_pilot.docs_orchestrator.check_phase1_quality",
            return_value=legacy_ok,
        ), patch(
            "cowork_pilot.docs_orchestrator.evaluate_phase1",
            return_value=new_fail,
        ):
            result = _run_phase_1_5(
                phase1_completed_state, base_config, orch_config, tmp_path, state_path,
            )

        completed_steps = {s.step for s in result.completed}
        assert "phase_1_5" not in completed_steps
        # Phase 1 should be rolled back so it can re-run
        assert "phase_1" not in completed_steps
        assert len(result.errors) > 0
        assert "ESCALATE" not in result.errors[-1]["error"]
        assert "Phase 1 필수 산출물 누락" in result.errors[-1]["error"]
        assert "feature files" in result.errors[-1]["error"]

    @patch("cowork_pilot.docs_orchestrator._confirm_proceed", return_value=True)
    @patch("cowork_pilot.docs_orchestrator._copy_references")
    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_full_phase_0_1_1_5_flow(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        mock_copy: MagicMock,
        mock_confirm: MagicMock,
        project_with_sources: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """Full integration: Phase 0 → 1 → 1.5 with all steps passing."""
        mock_open.return_value = project_with_sources / "session.jsonl"
        base_config.project_dir = str(project_with_sources)

        gate_result = GateResult(
            passed=True,
            coverage_ratio=0.95,
            uncovered_sections=[],
            missing_features=[],
        )
        new_ok = Phase1Result(ok=True, hard_failures=[], warnings=[])

        with patch(
            "cowork_pilot.docs_orchestrator.check_phase1_quality",
            return_value=gate_result,
        ), patch(
            "cowork_pilot.docs_orchestrator.evaluate_phase1",
            return_value=new_ok,
        ):
            run_docs_orchestrator(base_config, orch_config)

        # Verify state file
        state_path = project_with_sources / "docs" / "generated" / "orchestrator-state.json"
        assert state_path.exists()
        final_state = load_state(state_path)

        completed_steps = {s.step for s in final_state.completed}
        assert "phase_0" in completed_steps
        assert "phase_1" in completed_steps
        assert "phase_1_5" in completed_steps

    @patch("cowork_pilot.docs_orchestrator._confirm_proceed", return_value=True)
    @patch("cowork_pilot.docs_orchestrator._copy_references")
    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    @patch("cowork_pilot.docs_orchestrator._notify_escalate")
    def test_phase_1_5_failure_blocks_phase_2(
        self,
        mock_notify: MagicMock,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        mock_copy: MagicMock,
        mock_confirm: MagicMock,
        project_with_sources: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """Phase 1.5 ESCALATE failure → retries Phase 1 + 1.5 up to max,
        then orchestrator stops. Phase 2 never reached."""
        mock_open.return_value = project_with_sources / "session.jsonl"
        base_config.project_dir = str(project_with_sources)

        gate_result = GateResult(
            passed=False,
            coverage_ratio=0.3,
            uncovered_sections=["인증", "결제"],
            missing_features=[],
        )

        with patch("cowork_pilot.docs_orchestrator.check_phase1_quality", return_value=gate_result):
            run_docs_orchestrator(base_config, orch_config)

        state_path = project_with_sources / "docs" / "generated" / "orchestrator-state.json"
        final_state = load_state(state_path)

        completed_steps = {s.step for s in final_state.completed}
        assert "phase_0" in completed_steps
        assert "phase_1_5" not in completed_steps  # NOT completed — never passed
        # Phase 1 may or may not be in completed (last retry re-adds it before
        # max retries check stops the loop), but Phase 2 must NOT be reached
        assert "phase_2" not in completed_steps
        # Should have multiple phase_1_5 errors (Phase 1→1.5 retry cycle)
        phase_1_5_errors = [e for e in final_state.errors if e.get("step") == "phase_1_5"]
        assert len(phase_1_5_errors) == 3  # exactly _PHASE_1_5_MAX_RETRIES


# ── recover_running_step tests ──────────────────────────────────────


class TestRecoverRunningStep:
    def test_running_with_marker_recovers_to_completed(self, tmp_path: Path):
        """running + output file with marker → completed."""
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        report = generated / "analysis-report.md"
        report.write_text("# Report\nContent\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")

        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )

        recovered = recover_running_step(state, tmp_path)
        assert recovered.current["status"] == "idle"
        assert any(s.step == "phase_1" and s.status == "completed" for s in recovered.completed)

    def test_running_without_marker_reverts_to_pending(self, tmp_path: Path):
        """running + output file without marker → pending (file deleted)."""
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        report = generated / "analysis-report.md"
        report.write_text("# Report\nIncomplete content", encoding="utf-8")

        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )

        recovered = recover_running_step(state, tmp_path)
        assert recovered.current["status"] == "idle"
        assert not report.exists()  # File should be deleted
        assert any(p.get("step") == "phase_1" for p in recovered.pending)

    def test_running_no_output_reverts_to_pending(self, tmp_path: Path):
        """running + no output file → pending."""
        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )

        recovered = recover_running_step(state, tmp_path)
        assert recovered.current["status"] == "idle"
        assert any(p.get("step") == "phase_1" for p in recovered.pending)

    def test_non_running_state_unchanged(self, tmp_path: Path):
        """Non-running state → unchanged."""
        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "idle"},
            project_dir=str(tmp_path),
        )

        recovered = recover_running_step(state, tmp_path)
        assert recovered.current["status"] == "idle"
        assert recovered is state  # Same object, no change


# ── Output file check tests ────────────────────────────────────────


class TestOutputFileChecks:
    def test_check_output_files_with_marker(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("Content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")
        assert _check_output_files([f]) is True

    def test_check_output_files_without_marker(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("Content without marker", encoding="utf-8")
        assert _check_output_files([f]) is False

    def test_check_output_files_missing_file(self, tmp_path: Path):
        f = tmp_path / "nonexistent.md"
        assert _check_output_files([f]) is False

    def test_check_output_files_directory(self, tmp_path: Path):
        d = tmp_path / "extracts"
        d.mkdir()
        (d / "feature.md").write_text("Content\n<!-- ORCHESTRATOR:DONE -->", encoding="utf-8")
        assert _check_output_files([d]) is True

    def test_check_output_files_fallback_sufficient_lines(self, tmp_path: Path):
        f = tmp_path / "analysis-report.md"
        f.write_text("\n".join([f"line {i}" for i in range(50)]), encoding="utf-8")
        assert _check_output_files_fallback([f]) is True

    def test_check_output_files_fallback_insufficient_lines(self, tmp_path: Path):
        f = tmp_path / "analysis-report.md"
        f.write_text("short", encoding="utf-8")
        assert _check_output_files_fallback([f]) is False

    def test_empty_expected_files(self):
        assert _check_output_files([]) is False
        assert _check_output_files_fallback([]) is False


class TestParseExpectedFiles:
    def test_strips_legacy_directory_annotation_suffix(self):
        prompt = """
출력 파일:
- /tmp/project/docs/generated/analysis-report.md
- /tmp/project/docs/generated/domain-extracts/ (도메인별/기능별 파일)
- /tmp/project/docs/generated/domain-extracts/shared.md
"""

        paths = _parse_expected_files(prompt)

        assert paths == [
            Path("/tmp/project/docs/generated/analysis-report.md"),
            Path("/tmp/project/docs/generated/domain-extracts/"),
            Path("/tmp/project/docs/generated/domain-extracts/shared.md"),
        ]

    def test_phase1_single_prompt_yields_machine_readable_paths(self):
        prompt = build_session_prompt(
            "phase1_single",
            project_dir="/tmp/project",
            source_docs=["기획서.md"],
            domains=["poll"],
            features={"poll": ["vote"]},
        )

        paths = _parse_expected_files(prompt)

        assert paths == [
            Path("/tmp/project/docs/generated/analysis-report.md"),
            Path("/tmp/project/docs/generated/domain-extracts/"),
            Path("/tmp/project/docs/generated/domain-extracts/shared.md"),
        ]

    def test_phase1_domain_prompt_yields_machine_readable_paths(self):
        """phase1_domain expected files must contain only the domain directory.

        The Chunk 2 phase1_domain template intentionally keeps
        ``_overview.md`` out of the machine-readable bullet list because it
        is a conditional artefact (generated only when
        ``overview_needed == yes``). The template also lists a
        ``<feature>.md (feature 개수만큼)`` placeholder bullet — a human /
        AI-facing instruction, not a real output path — which the parser
        must skip. The only thing the runtime can assert ahead of time is
        that the domain directory should contain *some* .md output.
        """
        prompt = build_session_prompt(
            "phase1_domain",
            project_dir="/tmp/project",
            domain="poll-voting",
            source_docs=["기획서.md"],
        )

        paths = _parse_expected_files(prompt)

        assert paths == [
            Path("/tmp/project/docs/generated/domain-extracts/poll-voting/"),
        ]

    def test_skips_angle_bracket_placeholder_paths(self):
        """Bullets containing ``<placeholder>`` tokens must be skipped.

        The phase1_domain template uses ``<feature>.md`` as a symbolic
        stand-in telling the AI "one file per feature". These strings
        must never reach ``_check_output_files`` — if they did, the
        orchestrator would wait forever for a literal file named
        ``<feature>.md``.
        """
        prompt = (
            "출력 파일:\n"
            "- /tmp/project/docs/generated/domain-extracts/poll/\n"
            "- /tmp/project/docs/generated/domain-extracts/poll/<feature>.md (feature 개수만큼)\n"
        )

        paths = _parse_expected_files(prompt)

        assert paths == [
            Path("/tmp/project/docs/generated/domain-extracts/poll/"),
        ]


# ── Phase 1.5 completed fixture ──────────────────────────────────────


@pytest.fixture
def phase1_5_completed_state(tmp_path: Path) -> OrchestratorState:
    """State after Phase 0 + 1 + 1.5 are completed — ready for Phase 2."""
    return OrchestratorState(
        current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
        project_summary={
            "type": "unknown",
            "source_docs": ["planning.md"],
            "domains": ["payment", "booking"],
            "features": {
                "payment": ["refund", "checkout"],
                "booking": ["reservation", "cancel"],
            },
            "estimated_sessions": 20,
            "source_line_count": 5000,
        },
        completed=[
            StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
            StepStatus(step="phase_1", status="completed", completed_at="2026-04-01T10:30:00", result="success"),
            StepStatus(step="phase_1_5", status="completed", completed_at="2026-04-01T11:00:00", result="success"),
        ],
        pending=[],
        errors=[],
        updated_at="2026-04-01T11:00:00",
        mode="auto",
        project_dir=str(tmp_path),
    )


# ── _build_feature_bundles tests ──────────────────────────────────────


class TestBuildFeatureBundles:
    def test_basic_bundling(self):
        """Lines [150, 180, 250, 100] → [[150,180], [250], [100]] (250 is standalone)."""
        config = DocsOrchestratorConfig(
            feature_bundle_threshold_lines=200,
            max_bundle_size=2,
        )
        features_with_lines = [
            ("auth", "login", 150),
            ("auth", "signup", 180),
            ("payment", "refund", 250),
            ("booking", "cancel", 100),
        ]

        bundles = _build_feature_bundles(features_with_lines, config)

        assert len(bundles) == 3
        assert bundles[0] == [("auth", "login"), ("auth", "signup")]
        assert bundles[1] == [("payment", "refund")]
        assert bundles[2] == [("booking", "cancel")]

    def test_all_large_features_standalone(self):
        """All features > threshold → each gets its own bundle."""
        config = DocsOrchestratorConfig(
            feature_bundle_threshold_lines=200,
            max_bundle_size=2,
        )
        features = [
            ("a", "f1", 300),
            ("b", "f2", 250),
        ]

        bundles = _build_feature_bundles(features, config)
        assert len(bundles) == 2
        assert all(len(b) == 1 for b in bundles)

    def test_all_small_features_bundle_by_max_size(self):
        """All small features — bundled up to max_bundle_size."""
        config = DocsOrchestratorConfig(
            feature_bundle_threshold_lines=200,
            max_bundle_size=2,
        )
        features = [
            ("a", "f1", 50),
            ("a", "f2", 60),
            ("b", "f3", 70),
        ]

        bundles = _build_feature_bundles(features, config)
        assert len(bundles) == 2
        assert bundles[0] == [("a", "f1"), ("a", "f2")]
        assert bundles[1] == [("b", "f3")]

    def test_empty_features(self):
        config = DocsOrchestratorConfig()
        assert _build_feature_bundles([], config) == []

    def test_bundle_disabled_returns_singletons(self):
        """When bundle_disabled=True, _resolve_bundles returns all singletons."""
        config = DocsOrchestratorConfig(
            feature_bundle_threshold_lines=200,
            max_bundle_size=2,
        )
        features_with_lines = [
            ("auth", "login", 50),
            ("auth", "signup", 60),
            ("payment", "refund", 70),
        ]

        # State with bundle_disabled=True
        state = OrchestratorState(
            project_summary={"bundle_disabled": True},
        )

        bundles = _resolve_bundles(features_with_lines, config, state)
        assert len(bundles) == 3
        assert all(len(b) == 1 for b in bundles)

    def test_bundle_not_disabled_uses_bundling(self):
        """When bundle_disabled=False, _resolve_bundles uses normal bundling."""
        config = DocsOrchestratorConfig(
            feature_bundle_threshold_lines=200,
            max_bundle_size=2,
        )
        features_with_lines = [
            ("auth", "login", 50),
            ("auth", "signup", 60),
        ]

        state = OrchestratorState(
            project_summary={},
        )

        bundles = _resolve_bundles(features_with_lines, config, state)
        assert len(bundles) == 1
        assert bundles[0] == [("auth", "login"), ("auth", "signup")]


# ── _determine_next_step Phase 2/3 tests ─────────────────────────────


class TestDetermineNextStepPhase2And3:
    def test_phase_1_5_done_returns_phase_2(self, phase1_5_completed_state: OrchestratorState):
        """After Phase 1.5 → Phase 2."""
        assert _determine_next_step(phase1_5_completed_state) == "phase_2"

    def test_phase_2_all_done_but_no_summary_returns_phase_2(
        self, phase1_5_completed_state: OrchestratorState,
    ):
        """All Phase 2 features done but no summary → still phase_2."""
        features = phase1_5_completed_state.project_summary.get("features", {})
        feature_steps = []
        for domain, flist in features.items():
            for f in flist:
                feature_steps.append(
                    StepStatus(step=f"phase_2:{domain}:{f}", status="completed",
                               completed_at="2026-04-01T12:00:00", result="success")
                )

        state = OrchestratorState(
            current=phase1_5_completed_state.current,
            project_summary=phase1_5_completed_state.project_summary,
            completed=list(phase1_5_completed_state.completed) + feature_steps,
            pending=[],
            errors=[],
            updated_at="2026-04-01T12:00:00",
            mode="auto",
            project_dir=phase1_5_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_2"

    def test_phase_2_complete_with_summary_returns_phase_3_A(
        self, phase1_5_completed_state: OrchestratorState,
    ):
        """Phase 2 fully done (features + summary) → Phase 3-A."""
        features = phase1_5_completed_state.project_summary.get("features", {})
        feature_steps = []
        for domain, flist in features.items():
            for f in flist:
                feature_steps.append(
                    StepStatus(step=f"phase_2:{domain}:{f}", status="completed",
                               completed_at="2026-04-01T12:00:00", result="success")
                )
        feature_steps.append(
            StepStatus(step="phase_2_summary", status="completed",
                       completed_at="2026-04-01T12:10:00", result="success")
        )

        state = OrchestratorState(
            current=phase1_5_completed_state.current,
            project_summary=phase1_5_completed_state.project_summary,
            completed=list(phase1_5_completed_state.completed) + feature_steps,
            pending=[],
            errors=[],
            updated_at="2026-04-01T12:10:00",
            mode="auto",
            project_dir=phase1_5_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_3_A"

    def test_phase_3_group_order_a_b_c_d(
        self, phase1_5_completed_state: OrchestratorState,
    ):
        """Phase 3 group order: A → B → C → D."""
        features = phase1_5_completed_state.project_summary.get("features", {})
        base_steps = []
        for domain, flist in features.items():
            for f in flist:
                base_steps.append(
                    StepStatus(step=f"phase_2:{domain}:{f}", status="completed",
                               completed_at="2026-04-01T12:00:00", result="success")
                )
        base_steps.append(
            StepStatus(step="phase_2_summary", status="completed",
                       completed_at="2026-04-01T12:10:00", result="success")
        )
        all_completed = list(phase1_5_completed_state.completed) + base_steps

        def make_state(extra_steps: list[StepStatus]) -> OrchestratorState:
            return OrchestratorState(
                current=phase1_5_completed_state.current,
                project_summary=phase1_5_completed_state.project_summary,
                completed=all_completed + extra_steps,
                pending=[],
                errors=[],
                updated_at="2026-04-01T13:00:00",
                mode="auto",
                project_dir=phase1_5_completed_state.project_dir,
            )

        # Without A → should return phase_3_A
        assert _determine_next_step(make_state([])) == "phase_3_A"

        # With A done → should return phase_3_B
        step_a = StepStatus(step="phase_3_A", status="completed",
                            completed_at="2026-04-01T13:00:00", result="success")
        assert _determine_next_step(make_state([step_a])) == "phase_3_B"

        # With A + all B done → should return phase_3_C
        b_steps = [step_a]
        for domain, flist in features.items():
            for f in flist:
                b_steps.append(
                    StepStatus(step=f"phase_3_B:{domain}:{f}", status="completed",
                               completed_at="2026-04-01T13:30:00", result="success")
                )
        assert _determine_next_step(make_state(b_steps)) == "phase_3_C"

        # With A + B + C done → should return phase_3_D
        step_c = StepStatus(step="phase_3_C", status="completed",
                            completed_at="2026-04-01T14:00:00", result="success")
        assert _determine_next_step(make_state(b_steps + [step_c])) == "phase_3_D"

        # With A + B + C + D done → Phase 4-1
        step_d = StepStatus(step="phase_3_D", status="completed",
                            completed_at="2026-04-01T14:30:00", result="success")
        assert _determine_next_step(make_state(b_steps + [step_c, step_d])) == "phase_4_1"

    def test_bundled_features_recognized_as_completed(
        self, phase1_5_completed_state: OrchestratorState,
    ):
        """Bundle step like 'phase_2:payment:refund+payment:checkout' marks both features done."""
        # Only one bundled step for two features
        bundle_step = StepStatus(
            step="phase_2:payment:refund+payment:checkout",
            status="completed",
            completed_at="2026-04-01T12:00:00",
            result="success",
        )

        assert _is_feature_in_completed_bundle(
            "payment", "refund", "phase_2",
            {"phase_2:payment:refund+payment:checkout"},
        )
        assert _is_feature_in_completed_bundle(
            "payment", "checkout", "phase_2",
            {"phase_2:payment:refund+payment:checkout"},
        )
        assert not _is_feature_in_completed_bundle(
            "booking", "reservation", "phase_2",
            {"phase_2:payment:refund+payment:checkout"},
        )


# ── Phase 2 integration tests ─────────────────────────────────────────


class TestPhase2Integration:
    def test_phase_2_waiting_uses_orch_config_auto_answer(
        self,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ) -> None:
        from cowork_pilot.docs_orchestrator import StepExecutionOutcome
        from cowork_pilot.orchestrator_state import OrchestratorState, StepStatus

        base_config.project_dir = str(tmp_path)
        orch_config.engine = "codex"
        orch_config.auto_answer.enabled = True
        orch_config.auto_answer.max_rounds_per_run = 300

        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary={
                "domains": ["auth"],
                "features": {"auth": ["login"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        (generated / "references").mkdir(parents=True, exist_ok=True)
        (generated / "gap-reports").mkdir(parents=True, exist_ok=True)
        auth_dir = generated / "domain-extracts" / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (generated / "references" / "checklists.md").write_text("checklist\n", encoding="utf-8")
        (generated / "analysis-report.md").write_text("report\n", encoding="utf-8")
        (generated / "domain-extracts" / "shared.md").write_text("shared\n", encoding="utf-8")
        (auth_dir / "login.md").write_text("line\n" * 50, encoding="utf-8")

        state_path = generated / "orchestrator-state.json"

        completed_state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_2:auth:login", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step",
            return_value=StepExecutionOutcome(kind="waiting"),
        ), patch(
            "cowork_pilot.auto_answer_resolver.try_auto_answer",
            return_value=type(
                "AutoAnswerResult",
                (),
                {
                    "status": "applied",
                    "outcome": type(
                        "Outcome",
                        (),
                        {
                            "status": "completed",
                            "state": completed_state,
                        },
                    )(),
                },
            )(),
        ) as mock_try_auto_answer:
            result = _run_phase_2(
                state,
                base_config,
                orch_config,
                tmp_path,
                tmp_path / "sessions",
                state_path,
            )

        mock_try_auto_answer.assert_called_once()
        assert any(step.step == "phase_2:auth:login" for step in result.completed)

    def test_phase_2_waiting_can_continue_past_ten_auto_answer_rounds(
        self,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ) -> None:
        from cowork_pilot.docs_orchestrator import StepExecutionOutcome
        from cowork_pilot.orchestrator_state import OrchestratorState, StepStatus

        base_config.project_dir = str(tmp_path)
        orch_config.engine = "codex"
        orch_config.auto_answer.enabled = True

        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary={
                "domains": ["auth"],
                "features": {"auth": ["login"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        (generated / "references").mkdir(parents=True, exist_ok=True)
        (generated / "gap-reports").mkdir(parents=True, exist_ok=True)
        auth_dir = generated / "domain-extracts" / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (generated / "references" / "checklists.md").write_text("checklist\n", encoding="utf-8")
        (generated / "analysis-report.md").write_text("report\n", encoding="utf-8")
        (generated / "domain-extracts" / "shared.md").write_text("shared\n", encoding="utf-8")
        (auth_dir / "login.md").write_text("line\n" * 50, encoding="utf-8")

        state_path = generated / "orchestrator-state.json"

        completed_state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_2:auth:login", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        def _auto_answer_result(*, outcome_status: str, outcome_state: OrchestratorState):
            return type(
                "AutoAnswerResult",
                (),
                {
                    "status": "applied",
                    "outcome": type(
                        "Outcome",
                        (),
                        {
                            "status": outcome_status,
                            "state": outcome_state,
                        },
                    )(),
                },
            )()

        waiting_results = [
            _auto_answer_result(outcome_status="waiting", outcome_state=state)
            for _ in range(10)
        ]
        final_result = _auto_answer_result(
            outcome_status="completed",
            outcome_state=completed_state,
        )

        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step",
            return_value=StepExecutionOutcome(kind="waiting"),
        ), patch(
            "cowork_pilot.auto_answer_resolver.try_auto_answer",
            side_effect=waiting_results + [final_result],
        ) as mock_try_auto_answer:
            result = _run_phase_2(
                state,
                base_config,
                orch_config,
                tmp_path,
                tmp_path / "sessions",
                state_path,
            )

        assert mock_try_auto_answer.call_count == 11
        assert any(step.step == "phase_2:auth:login" for step in result.completed)

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_2_creates_gap_reports_and_summary(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase1_5_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 2 runs sessions for each feature and generates _summary.md."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        # Create domain-extracts so line counting works
        generated_dir = tmp_path / "docs" / "generated"
        gap_dir = generated_dir / "gap-reports"
        gap_dir.mkdir(parents=True)

        for domain in ["payment", "booking"]:
            domain_dir = generated_dir / "domain-extracts" / domain
            domain_dir.mkdir(parents=True)
            for feature in phase1_5_completed_state.project_summary["features"][domain]:
                (domain_dir / f"{feature}.md").write_text(
                    "\n".join([f"line {i}" for i in range(100)]),
                    encoding="utf-8",
                )

        state_path = generated_dir / "orchestrator-state.json"

        # Simulate gap-report file creation (would normally be done by AI session)
        def create_gap_report(*args, **kwargs):
            # Create gap reports that the AI session would produce
            for domain in ["payment", "booking"]:
                for feature in phase1_5_completed_state.project_summary["features"][domain]:
                    report = gap_dir / f"{domain}--{feature}.md"
                    if not report.exists():
                        report.write_text(
                            f"# {domain}/{feature}\n종합 점수: 8/10\n[AI_DECISION] test\n"
                            "<!-- ORCHESTRATOR:DONE -->",
                            encoding="utf-8",
                        )
            return True

        mock_wait.side_effect = create_gap_report

        result = _run_phase_2(
            phase1_5_completed_state, base_config, orch_config,
            tmp_path, tmp_path / "sessions", state_path,
        )

        completed_steps = {s.step for s in result.completed}
        assert "phase_2_summary" in completed_steps

        # _summary.md should exist
        summary_path = gap_dir / "_summary.md"
        assert summary_path.exists()
        summary_content = summary_path.read_text(encoding="utf-8")
        assert "갭 분석 요약" in summary_content
        assert "ORCHESTRATOR:DONE" in summary_content

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_2_uses_bundles_for_small_features(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """Phase 2 bundles small features together."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)
        orch_config.feature_bundle_threshold_lines = 200
        orch_config.max_bundle_size = 2

        # Two small features (< 200 lines each) → should be bundled
        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary={
                "domains": ["auth"],
                "features": {"auth": ["login", "signup"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        # Create small domain-extracts
        generated = tmp_path / "docs" / "generated"
        gap_dir = generated / "gap-reports"
        gap_dir.mkdir(parents=True)
        auth_dir = generated / "domain-extracts" / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "login.md").write_text("\n".join([f"l{i}" for i in range(50)]), encoding="utf-8")
        (auth_dir / "signup.md").write_text("\n".join([f"l{i}" for i in range(60)]), encoding="utf-8")

        state_path = generated / "orchestrator-state.json"

        result = _run_phase_2(
            state, base_config, orch_config, tmp_path, tmp_path / "sessions", state_path,
        )

        # Should open only 1 session (bundled) instead of 2
        assert mock_open.call_count == 1


# ── Phase 3 integration tests ─────────────────────────────────────────


class TestPhase3Integration:
    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_3_group_order_enforced(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """Phase 3 runs groups in order A → B → C → D."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        state = OrchestratorState(
            current={"phase": "phase_3", "step": "phase_3", "status": "idle"},
            project_summary={
                "domains": ["auth"],
                "features": {"auth": ["login"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
                StepStatus(step="phase_2:auth:login", status="completed"),
                StepStatus(step="phase_2_summary", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        # Create domain-extracts for feature line counting
        generated = tmp_path / "docs" / "generated"
        auth_dir = generated / "domain-extracts" / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "login.md").write_text("\n".join([f"l{i}" for i in range(50)]), encoding="utf-8")

        state_path = generated / "orchestrator-state.json"

        result = _run_phase_3(
            state, base_config, orch_config, tmp_path, tmp_path / "sessions", state_path,
        )

        completed_steps = [s.step for s in result.completed if s.step.startswith("phase_3")]
        # Verify order: A before B before C before D
        step_order = {step: i for i, step in enumerate(completed_steps)}
        assert step_order.get("phase_3_A", -1) < step_order.get("phase_3_C", 999)
        assert step_order.get("phase_3_C", -1) < step_order.get("phase_3_D", 999)

        # All 4 groups should be completed
        step_set = set(completed_steps)
        assert "phase_3_A" in step_set
        assert "phase_3_C" in step_set
        assert "phase_3_D" in step_set
        # At least one phase_3_B step
        assert any(s.startswith("phase_3_B") for s in step_set)

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_3_group_a_failure_blocks_b(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ):
        """If Phase 3-A fails, B/C/D should not run."""
        mock_open.return_value = None  # Simulate session open failure
        base_config.project_dir = str(tmp_path)

        state = OrchestratorState(
            current={"phase": "phase_3", "step": "phase_3", "status": "idle"},
            project_summary={
                "domains": ["auth"],
                "features": {"auth": ["login"]},
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
                StepStatus(step="phase_2:auth:login", status="completed"),
                StepStatus(step="phase_2_summary", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        state_path = generated / "orchestrator-state.json"

        result = _run_phase_3(
            state, base_config, orch_config, tmp_path, tmp_path / "sessions", state_path,
        )

        completed_steps = {s.step for s in result.completed}
        assert "phase_3_A" not in completed_steps
        assert "phase_3_D" not in completed_steps
        assert len(result.errors) > 0


# ── Bundle quality degradation tests ─────────────────────────────────


class TestBundleQualityDegradation:
    def test_degradation_count_below_threshold(self, tmp_path: Path):
        """Less than 3 degradation mentions → bundle stays enabled."""
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        rescore = generated / "phase4-rescore.md"
        rescore.write_text("품질 저하 1건\n품질 저하 2건\n", encoding="utf-8")

        state = OrchestratorState(
            project_summary={},
            project_dir=str(tmp_path),
        )

        result = check_bundle_quality_degradation(state, tmp_path)
        assert result.project_summary.get("bundle_disabled") is not True

    def test_degradation_count_at_threshold_disables_bundles(self, tmp_path: Path):
        """3+ degradation mentions → bundle_disabled=True."""
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        rescore = generated / "phase4-rescore.md"
        rescore.write_text(
            "품질 저하 1건\n품질 저하 2건\n품질 저하 3건\n",
            encoding="utf-8",
        )

        state = OrchestratorState(
            project_summary={},
            project_dir=str(tmp_path),
        )

        result = check_bundle_quality_degradation(state, tmp_path)
        assert result.project_summary.get("bundle_disabled") is True

    def test_no_rescore_file_no_change(self, tmp_path: Path):
        """No rescore file → state unchanged."""
        state = OrchestratorState(
            project_summary={},
            project_dir=str(tmp_path),
        )

        result = check_bundle_quality_degradation(state, tmp_path)
        assert result is state


# ── Gap summary fixture test ──────────────────────────────────────────


class TestGapSummaryWithFixture:
    def test_generate_gap_summary_from_fixture(self, tmp_path: Path):
        """generate_gap_summary parses scores and [AI_DECISION] tags from fixture."""
        import shutil
        fixture = Path(__file__).parent / "fixtures" / "sample_gap_report.md"
        gap_dir = tmp_path / "gap-reports"
        gap_dir.mkdir()
        shutil.copy(fixture, gap_dir / "payment--refund.md")

        summary = generate_gap_summary(gap_dir)

        assert "갭 분석 요약" in summary
        assert "payment" in summary
        assert "refund" in summary
        assert "10/15" in summary  # Score from fixture
        assert "3" in summary  # 3 [AI_DECISION] tags in fixture
        assert "ORCHESTRATOR:DONE" in summary


# ── Fixtures for Phase 4/5 tests ─────────────────────────────────────


def _make_all_phase3_completed_state(tmp_path: Path) -> OrchestratorState:
    """State after Phase 0 + 1 + 1.5 + 2 + 3 are fully completed."""
    return OrchestratorState(
        current={"phase": "phase_4", "step": "phase_4_1", "status": "idle"},
        project_summary={
            "type": "unknown",
            "source_docs": ["planning.md"],
            "domains": ["payment", "booking"],
            "features": {
                "payment": ["refund", "checkout"],
                "booking": ["reservation"],
            },
            "estimated_sessions": 25,
            "source_line_count": 5000,
        },
        completed=[
            StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
            StepStatus(step="phase_1", status="completed", completed_at="2026-04-01T10:30:00", result="success"),
            StepStatus(step="phase_1_5", status="completed", completed_at="2026-04-01T11:00:00", result="success"),
            StepStatus(step="phase_2:payment:refund", status="completed", completed_at="2026-04-01T11:30:00", result="success"),
            StepStatus(step="phase_2:payment:checkout", status="completed", completed_at="2026-04-01T11:40:00", result="success"),
            StepStatus(step="phase_2:booking:reservation", status="completed", completed_at="2026-04-01T11:50:00", result="success"),
            StepStatus(step="phase_2_summary", status="completed", completed_at="2026-04-01T12:00:00", result="success"),
            StepStatus(step="phase_3_A", status="completed", completed_at="2026-04-01T12:30:00", result="success"),
            StepStatus(step="phase_3_B:payment:refund", status="completed", completed_at="2026-04-01T13:00:00", result="success"),
            StepStatus(step="phase_3_B:payment:checkout", status="completed", completed_at="2026-04-01T13:10:00", result="success"),
            StepStatus(step="phase_3_B:booking:reservation", status="completed", completed_at="2026-04-01T13:20:00", result="success"),
            StepStatus(step="phase_3_C", status="completed", completed_at="2026-04-01T13:30:00", result="success"),
            StepStatus(step="phase_3_D", status="completed", completed_at="2026-04-01T14:00:00", result="success"),
        ],
        pending=[],
        errors=[],
        updated_at="2026-04-01T14:00:00",
        mode="auto",
        project_dir=str(tmp_path),
    )


@pytest.fixture
def phase3_completed_state(tmp_path: Path) -> OrchestratorState:
    return _make_all_phase3_completed_state(tmp_path)


# ── _determine_next_step full Phase flow tests ────────────────────────


class TestDetermineNextStepFullFlow:
    """Test _determine_next_step() across the complete Phase 0 → 5 → done flow."""

    def test_after_phase_3_d_returns_phase_4_1(self, phase3_completed_state: OrchestratorState):
        """Phase 3-D done → Phase 4-1."""
        assert _determine_next_step(phase3_completed_state) == "phase_4_1"

    def test_phase_4_1_done_returns_phase_4_2(self, phase3_completed_state: OrchestratorState):
        state = OrchestratorState(
            current=phase3_completed_state.current,
            project_summary=phase3_completed_state.project_summary,
            completed=list(phase3_completed_state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=phase3_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_4_2"

    def test_phase_4_2_done_returns_phase_4_3(self, phase3_completed_state: OrchestratorState):
        state = OrchestratorState(
            current=phase3_completed_state.current,
            project_summary=phase3_completed_state.project_summary,
            completed=list(phase3_completed_state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=phase3_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_4_3"

    def test_phase_4_3_done_returns_phase_5_outline(self, phase3_completed_state: OrchestratorState):
        state = OrchestratorState(
            current=phase3_completed_state.current,
            project_summary=phase3_completed_state.project_summary,
            completed=list(phase3_completed_state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
                StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=phase3_completed_state.project_dir,
        )
        assert _determine_next_step(state) == "phase_5_outline"

    def test_phase_5_outline_done_returns_phase_5_detail(self, tmp_path: Path):
        """Phase 5-outline done + outline file exists → phase_5_detail:{first_plan}."""
        state = _make_all_phase3_completed_state(tmp_path)
        state = OrchestratorState(
            current=state.current,
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
                StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
                StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=str(tmp_path),
        )

        # Create outline file
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        outline = generated / "exec-plan-outline.md"
        outline.write_text(
            "## exec-plan 개요\n\n"
            "| # | 파일명 | 범위 | Chunk 수 | 의존성 |\n"
            "|---|--------|------|---------|--------|\n"
            "| 1 | 01-project-setup.md | 초기화 | 5 | 없음 |\n"
            "| 2 | 02-data-layer.md | 데이터 | 8 | 01 |\n\n"
            "## 01-project-setup.md 상세\n...\n## 02-data-layer.md 상세\n...\n"
            "<!-- ORCHESTRATOR:DONE -->\n",
            encoding="utf-8",
        )

        result = _determine_next_step(state)
        assert result == "phase_5_detail:01-project-setup"

    def test_phase_5_outline_done_with_no_parseable_plans_returns_done(self, tmp_path: Path):
        """Outline complete but no parseable plan rows/headers -> done."""
        state = _make_all_phase3_completed_state(tmp_path)
        state = OrchestratorState(
            current={
                **state.current,
                "phase": "phase_5",
                "step": "phase_5_outline",
                "status": "idle",
            },
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
                StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
                StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        outline = generated / "exec-plan-outline.md"
        outline.write_text(
            "# Outline\n<!-- ORCHESTRATOR:DONE -->\n",
            encoding="utf-8",
        )

        assert _determine_next_step(state) == "done"

    def test_phase_5_first_detail_done_returns_second(self, tmp_path: Path):
        """First detail done → next detail."""
        state = _make_all_phase3_completed_state(tmp_path)
        state = OrchestratorState(
            current=state.current,
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
                StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
                StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
                StepStatus(step="phase_5_detail:01-project-setup", status="completed", completed_at="2026-04-01T16:30:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        outline = generated / "exec-plan-outline.md"
        outline.write_text(
            "| 1 | 01-project-setup.md | 초기화 | 5 | 없음 |\n"
            "| 2 | 02-data-layer.md | 데이터 | 8 | 01 |\n",
            encoding="utf-8",
        )

        assert _determine_next_step(state) == "phase_5_detail:02-data-layer"

    def test_all_details_done_returns_done(self, tmp_path: Path):
        """All phase_5_detail steps done → 'done'."""
        state = _make_all_phase3_completed_state(tmp_path)
        state = OrchestratorState(
            current=state.current,
            project_summary=state.project_summary,
            completed=list(state.completed) + [
                StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
                StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
                StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
                StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
                StepStatus(step="phase_5_detail:01-project-setup", status="completed", completed_at="2026-04-01T16:30:00", result="success"),
                StepStatus(step="phase_5_detail:02-data-layer", status="completed", completed_at="2026-04-01T17:00:00", result="success"),
            ],
            pending=[], errors=[], mode="auto",
            project_dir=str(tmp_path),
        )

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        outline = generated / "exec-plan-outline.md"
        outline.write_text(
            "| 1 | 01-project-setup.md | 초기화 | 5 | 없음 |\n"
            "| 2 | 02-data-layer.md | 데이터 | 8 | 01 |\n",
            encoding="utf-8",
        )

        assert _determine_next_step(state) == "done"


# ── _parse_outline_plans tests ────────────────────────────────────────


class TestParseOutlinePlans:
    def test_table_pattern(self, tmp_path: Path):
        """Parse exec-plan names from table rows."""
        outline = tmp_path / "outline.md"
        outline.write_text(
            "## exec-plan 개요\n\n"
            "| # | 파일명 | 범위 | Chunk 수 | 의존성 |\n"
            "|---|--------|------|---------|--------|\n"
            "| 1 | 01-project-setup.md | 초기화, 설정 | 5 | 없음 |\n"
            "| 2 | 02-data-layer.md | 데이터 모델, DB | 8 | 01 |\n"
            "| 3 | 03-api-server.md | API | 6 | 01, 02 |\n",
            encoding="utf-8",
        )

        plans = _parse_outline_plans(outline)
        assert len(plans) == 3
        assert plans[0]["name"] == "01-project-setup"
        assert plans[0]["filename"] == "01-project-setup.md"
        assert plans[1]["name"] == "02-data-layer"
        assert plans[2]["name"] == "03-api-server"

    def test_header_pattern(self, tmp_path: Path):
        """Parse exec-plan names from section headers."""
        outline = tmp_path / "outline.md"
        outline.write_text(
            "## 01-project-setup.md 상세\n...\n"
            "## 02-data-layer.md 상세\n...\n",
            encoding="utf-8",
        )

        plans = _parse_outline_plans(outline)
        assert len(plans) == 2
        assert plans[0]["name"] == "01-project-setup"
        assert plans[1]["name"] == "02-data-layer"

    def test_empty_file(self, tmp_path: Path):
        outline = tmp_path / "outline.md"
        outline.write_text("No plans here\n", encoding="utf-8")
        assert _parse_outline_plans(outline) == []

    def test_nonexistent_file(self, tmp_path: Path):
        assert _parse_outline_plans(tmp_path / "missing.md") == []

    def test_deduplication(self, tmp_path: Path):
        """Same plan in table and header is not duplicated."""
        outline = tmp_path / "outline.md"
        outline.write_text(
            "| 1 | 01-project-setup.md | 초기화 | 5 | 없음 |\n"
            "## 01-project-setup.md 상세\n",
            encoding="utf-8",
        )

        plans = _parse_outline_plans(outline)
        assert len(plans) == 1

    def test_determines_detail_session_count(self, tmp_path: Path):
        """Number of parsed plans determines how many detail sessions to run."""
        outline = tmp_path / "outline.md"
        outline.write_text(
            "| 1 | 01-setup.md | Setup | 3 | - |\n"
            "| 2 | 02-core.md | Core | 5 | 01 |\n"
            "| 3 | 03-api.md | API | 4 | 01,02 |\n"
            "| 4 | 04-frontend.md | UI | 6 | 03 |\n",
            encoding="utf-8",
        )

        plans = _parse_outline_plans(outline)
        assert len(plans) == 4  # 4 detail sessions needed


# ── Phase 4 integration tests ────────────────────────────────────────


class TestPhase4Integration:
    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_4_1_injects_section_keywords(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase3_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 4-1 calls build_session_prompt with section_keywords."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        state_path = generated / "orchestrator-state.json"

        # Create phase4-consistency.md (expected output)
        (generated / "phase4-consistency.md").write_text(
            "# Consistency\n<!-- ORCHESTRATOR:DONE -->",
            encoding="utf-8",
        )

        with patch("cowork_pilot.docs_orchestrator.get_section_keywords", return_value=["데이터", "API"]) as mock_kw:
            result = _run_phase_4(
                phase3_completed_state, base_config, orch_config,
                tmp_path, tmp_path / "sessions", state_path, "phase_4_1",
            )

        mock_kw.assert_called_once()
        completed_steps = {s.step for s in result.completed}
        assert "phase_4_1" in completed_steps

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_4_2_checks_bundle_degradation(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase3_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 4-2 checks bundle quality degradation after completion."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        state_path = generated / "orchestrator-state.json"

        # Create rescore with 3+ degradation markers
        (generated / "phase4-rescore.md").write_text(
            "품질 저하 1\n품질 저하 2\n품질 저하 3\n<!-- ORCHESTRATOR:DONE -->",
            encoding="utf-8",
        )

        result = _run_phase_4(
            phase3_completed_state, base_config, orch_config,
            tmp_path, tmp_path / "sessions", state_path, "phase_4_2",
        )

        completed_steps = {s.step for s in result.completed}
        assert "phase_4_2" in completed_steps
        assert result.project_summary.get("bundle_disabled") is True

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_4_3_grep_forbidden_expressions(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase3_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 4-3 runs grep for forbidden expressions."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        state_path = generated / "orchestrator-state.json"

        # Create a doc with forbidden expressions
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "test-spec.md").write_text(
            "# Spec\n적절한 방식으로 처리\nTBD\n",
            encoding="utf-8",
        )
        (docs_dir / "QUALITY_SCORE.md").write_text(
            "# Quality\n<!-- ORCHESTRATOR:DONE -->",
            encoding="utf-8",
        )

        result = _run_phase_4(
            phase3_completed_state, base_config, orch_config,
            tmp_path, tmp_path / "sessions", state_path, "phase_4_3",
        )

        completed_steps = {s.step for s in result.completed}
        assert "phase_4_3" in completed_steps


class TestGrepForbiddenExpressions:
    def test_finds_forbidden_expressions(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "spec.md").write_text("적절한 방식\nTBD 항목\n정상 내용\n", encoding="utf-8")

        hits = _grep_forbidden_expressions(tmp_path)
        assert len(hits) == 2
        exprs = {h["expression"] for h in hits}
        assert "적절한" in exprs
        assert "TBD" in exprs

    def test_no_docs_dir(self, tmp_path: Path):
        assert _grep_forbidden_expressions(tmp_path) == []

    def test_clean_docs(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "clean.md").write_text("깨끗한 문서\n", encoding="utf-8")
        assert _grep_forbidden_expressions(tmp_path) == []


# ── Phase 4 → 5 transition test ────────────────────────────────────────


class TestPhase4To5Transition:
    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_4_to_5_transition(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase3_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 4 completes all 3 sub-steps → Phase 5 outline."""
        # Start with Phase 3 completed
        state = phase3_completed_state

        # After 4-1, 4-2, 4-3 are completed
        all_phase4 = [
            StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
            StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
            StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
        ]

        state = OrchestratorState(
            current=state.current,
            project_summary=state.project_summary,
            completed=list(state.completed) + all_phase4,
            pending=[], errors=[], mode="auto",
            project_dir=state.project_dir,
        )

        assert _determine_next_step(state) == "phase_5_outline"


# ── Phase 5 integration tests ────────────────────────────────────────

@patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
@patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
def test_phase_5_outline_uses_outline_session(
    mock_wait: MagicMock,
    mock_open: MagicMock,
    phase3_completed_state: OrchestratorState,
    base_config: Config,
    orch_config: DocsOrchestratorConfig,
    tmp_path: Path,
):
    """Phase 5-outline opens an orchestrator session and completes from outline output."""
    mock_open.return_value = tmp_path / "session.jsonl"
    base_config.project_dir = str(tmp_path)

    generated = tmp_path / "docs" / "generated"
    generated.mkdir(parents=True)
    outline = generated / "exec-plan-outline.md"
    outline.write_text(
        "## exec-plan 개요\n\n"
        "| # | 파일명 | 범위 | Chunk 수 | 의존성 |\n"
        "|---|--------|------|---------|--------|\n"
        "| 1 | 01-project-setup.md | 초기화 | 5 | 없음 |\n"
        "<!-- ORCHESTRATOR:DONE -->\n",
        encoding="utf-8",
    )
    state_path = generated / "orchestrator-state.json"

    result = _run_phase_5_outline(
        phase3_completed_state, base_config, orch_config,
        tmp_path, tmp_path / "sessions", state_path,
    )

    completed_steps = {s.step for s in result.completed}
    assert "phase_5_outline" in completed_steps
    assert result.current["status"] == "idle"
    mock_open.assert_called_once()
    mock_wait.assert_called_once()


@patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
def test_phase_5_outline_fails_when_session_open_fails(
    mock_open: MagicMock,
    phase3_completed_state: OrchestratorState,
    base_config: Config,
    orch_config: DocsOrchestratorConfig,
    tmp_path: Path,
):
    """Phase 5-outline records an error if session open fails."""
    mock_open.return_value = None
    base_config.project_dir = str(tmp_path)

    generated = tmp_path / "docs" / "generated"
    generated.mkdir(parents=True)
    state_path = generated / "orchestrator-state.json"

    result = _run_phase_5_outline(
        phase3_completed_state, base_config, orch_config,
        tmp_path, tmp_path / "sessions", state_path,
    )

    completed_steps = {s.step for s in result.completed}
    assert "phase_5_outline" not in completed_steps
    assert result.errors
    assert "세션 열기 실패" in result.errors[-1]["error"]


class TestPhase5Integration:

    @patch("cowork_pilot.docs_orchestrator._open_orchestrator_session")
    @patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", return_value=True)
    def test_phase_5_detail_creates_plan_file(
        self,
        mock_wait: MagicMock,
        mock_open: MagicMock,
        phase3_completed_state: OrchestratorState,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
        tmp_path: Path,
    ):
        """Phase 5-detail creates exec-plan file in planning/."""
        mock_open.return_value = tmp_path / "session.jsonl"
        base_config.project_dir = str(tmp_path)

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        state_path = generated / "orchestrator-state.json"

        # Create planning dir and simulate AI output
        planning_dir = tmp_path / "docs" / "exec-plans" / "planning"
        planning_dir.mkdir(parents=True)
        (planning_dir / "01-project-setup.md").write_text(
            "# Plan\n<!-- ORCHESTRATOR:DONE -->",
            encoding="utf-8",
        )

        result = _run_phase_5_detail(
            phase3_completed_state, base_config, orch_config,
            tmp_path, tmp_path / "sessions", state_path,
            "phase_5_detail:01-project-setup",
        )

        completed_steps = {s.step for s in result.completed}
        assert "phase_5_detail:01-project-setup" in completed_steps

    def test_outline_parsing_determines_detail_sessions(self, tmp_path: Path):
        """Number of plans in outline determines number of detail sessions."""
        outline = tmp_path / "outline.md"
        outline.write_text(
            "| 1 | 01-setup.md | Setup | 3 | - |\n"
            "| 2 | 02-core.md | Core | 5 | 01 |\n"
            "| 3 | 03-api.md | API | 4 | 01,02 |\n",
            encoding="utf-8",
        )

        plans = _parse_outline_plans(outline)
        assert len(plans) == 3  # 3 detail sessions


# ── Final completion tests ───────────────────────────────────────────


class TestFinalCompletion:
    def test_final_completion_prints_summary(self, tmp_path: Path, capsys):
        """_run_final_completion prints summary to stderr."""
        planning_dir = tmp_path / "docs" / "exec-plans" / "planning"
        planning_dir.mkdir(parents=True)
        (planning_dir / "01-setup.md").write_text("# Plan 1\n", encoding="utf-8")
        (planning_dir / "02-core.md").write_text("# Plan 2\n", encoding="utf-8")

        state = OrchestratorState(
            completed=[
                StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
                StepStatus(step="phase_1", status="completed", completed_at="2026-04-01T10:30:00", result="success"),
                StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
            ],
            errors=[{"at": "2026-04-01T11:00:00", "step": "phase_1_5", "error": "test"}],
            project_dir=str(tmp_path),
        )

        with patch("cowork_pilot.docs_orchestrator._notify_completion"):
            _run_final_completion(state, tmp_path)

        captured = capsys.readouterr()
        assert "Total sessions completed: 3" in captured.err
        assert "Errors: 1" in captured.err
        assert "Exec-plan files: 2" in captured.err

    def test_final_completion_with_no_planning_files(self, tmp_path: Path, capsys):
        """Warning when no exec-plan files found."""
        state = OrchestratorState(
            completed=[
                StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
            ],
            errors=[],
            project_dir=str(tmp_path),
        )

        with patch("cowork_pilot.docs_orchestrator._notify_completion"):
            _run_final_completion(state, tmp_path)

        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_final_completion_calls_notify(self, tmp_path: Path):
        """Final completion sends macOS notification."""
        state = OrchestratorState(
            completed=[
                StepStatus(step="phase_0", status="completed", completed_at="2026-04-01T10:00:00", result="success"),
            ],
            errors=[],
            project_dir=str(tmp_path),
        )

        with patch("cowork_pilot.docs_orchestrator._notify_completion") as mock_notify:
            _run_final_completion(state, tmp_path)
            mock_notify.assert_called_once_with(1, 0, 0)

    def test_final_completion_reports_planning_runtime_state(self, tmp_path: Path, capsys):
        planning_dir = tmp_path / "docs" / "exec-plans" / "planning"
        planning_dir.mkdir(parents=True)
        (planning_dir / "01-setup.md").write_text("# Plan 1\n", encoding="utf-8")

        run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "greenfield-cli-planning"
        run_dir.mkdir(parents=True)
        (run_dir / "run-state.json").write_text(
            '{"state": "waiting_for_input"}\n',
            encoding="utf-8",
        )

        state = OrchestratorState(
            completed=[StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success")],
            errors=[],
            project_dir=str(tmp_path),
        )

        with patch("cowork_pilot.docs_orchestrator._notify_completion"):
            _run_final_completion(state, tmp_path)

        captured = capsys.readouterr()
        assert "Planning runtime state: waiting_for_input" in captured.err

    def test_all_completed_state_returns_done(self, tmp_path: Path):
        """Verify that a fully completed state returns 'done'."""
        state = _make_all_phase3_completed_state(tmp_path)

        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        outline = generated / "exec-plan-outline.md"
        outline.write_text(
            "| 1 | 01-setup.md | Setup | 3 | - |\n",
            encoding="utf-8",
        )

        all_remaining = [
            StepStatus(step="phase_4_1", status="completed", completed_at="2026-04-01T14:30:00", result="success"),
            StepStatus(step="phase_4_2", status="completed", completed_at="2026-04-01T15:00:00", result="success"),
            StepStatus(step="phase_4_3", status="completed", completed_at="2026-04-01T15:30:00", result="success"),
            StepStatus(step="phase_5_outline", status="completed", completed_at="2026-04-01T16:00:00", result="success"),
            StepStatus(step="phase_5_detail:01-setup", status="completed", completed_at="2026-04-01T16:30:00", result="success"),
        ]

        state = OrchestratorState(
            current=state.current,
            project_summary=state.project_summary,
            completed=list(state.completed) + all_remaining,
            pending=[], errors=[], mode="auto",
            project_dir=str(tmp_path),
        )

        assert _determine_next_step(state) == "done"


# ── Separator fallback tests ─────────────────────────────────────────


class TestResolveSeparatorFallback:
    """_resolve_separator_fallback renames single-hyphen files to double-hyphen."""

    def test_canonical_file_exists(self, tmp_path: Path) -> None:
        """When canonical '--' file exists, return it unchanged."""
        f = tmp_path / "ai-agent--nl-parser.md"
        f.write_text("content")
        result = _resolve_separator_fallback(f)
        assert result == f
        assert f.exists()

    def test_single_hyphen_renamed(self, tmp_path: Path) -> None:
        """When only single-hyphen variant exists, rename it to canonical form."""
        alt = tmp_path / "ai-agent-nl-parser.md"
        alt.write_text("content\n<!-- ORCHESTRATOR:DONE -->")
        canonical = tmp_path / "ai-agent--nl-parser.md"

        result = _resolve_separator_fallback(canonical)
        assert result == canonical
        assert canonical.exists()
        assert not alt.exists()

    def test_neither_exists(self, tmp_path: Path) -> None:
        """When neither variant exists, return canonical path unchanged."""
        canonical = tmp_path / "ai-agent--nl-parser.md"
        result = _resolve_separator_fallback(canonical)
        assert result == canonical
        assert not canonical.exists()

    def test_no_double_hyphen_in_name(self, tmp_path: Path) -> None:
        """When filename has no '--', return path unchanged."""
        f = tmp_path / "simple-file.md"
        result = _resolve_separator_fallback(f)
        assert result == f


class TestCheckOutputFilesWithFallback:
    """_check_output_files uses separator fallback to find single-hyphen files."""

    def test_finds_single_hyphen_files(self, tmp_path: Path) -> None:
        """_check_output_files succeeds when AI session used single hyphen."""
        # AI session creates files with single hyphen
        (tmp_path / "ai-agent-nl-parser.md").write_text(
            "# NL Parser\ncontent\n<!-- ORCHESTRATOR:DONE -->"
        )
        (tmp_path / "ai-agent-query-planner.md").write_text(
            "# Query Planner\ncontent\n<!-- ORCHESTRATOR:DONE -->"
        )

        # Orchestrator expects double hyphen
        expected = [
            tmp_path / "ai-agent--nl-parser.md",
            tmp_path / "ai-agent--query-planner.md",
        ]

        assert _check_output_files(expected) is True
        # Files should now be renamed to canonical form
        assert (tmp_path / "ai-agent--nl-parser.md").exists()
        assert (tmp_path / "ai-agent--query-planner.md").exists()
        assert not (tmp_path / "ai-agent-nl-parser.md").exists()
        assert not (tmp_path / "ai-agent-query-planner.md").exists()


# ── Chunk 4: _execute_orchestrator_step() ───────────────────────────


class TestExecuteOrchestratorStep:
    """Tests for the backend-dispatch helper used by phase functions."""

    def test_claude_path_calls_open_orchestrator_session(self, tmp_path: Path) -> None:
        """engine=claude → _open_orchestrator_session() 반드시 호출."""
        from cowork_pilot.docs_orchestrator import (
            _execute_orchestrator_step,
            StepExecutionOutcome,
        )

        orch_config = DocsOrchestratorConfig(engine="claude")

        opened: list[bool] = []
        waited: list[bool] = []

        def fake_open(prompt, config, orch_config, base_path):
            opened.append(True)
            return tmp_path / "fake.jsonl"

        def fake_wait(jsonl_path, expected_files, config, orch_config, watch_mode):
            waited.append(True)
            return True

        with patch(
            "cowork_pilot.docs_orchestrator._open_orchestrator_session",
            side_effect=fake_open,
        ), patch(
            "cowork_pilot.docs_orchestrator._wait_for_session_completion",
            side_effect=fake_wait,
        ):
            outcome = _execute_orchestrator_step(
                step_name="phase_1",
                prompt="test prompt",
                expected_files=[],
                watch_mode=False,
                config=Config(project_dir=str(tmp_path)),
                orch_config=orch_config,
                project_dir=tmp_path,
                base_path=tmp_path,
            )

        assert len(opened) == 1, (
            "Claude 경로에서 _open_orchestrator_session이 호출되어야 함"
        )
        assert len(waited) == 1, (
            "Claude 경로에서 _wait_for_session_completion이 호출되어야 함"
        )
        assert outcome.kind == "completed"

    def test_codex_path_does_not_call_session_opener(self, tmp_path: Path) -> None:
        """engine=codex → session_opener와 JSONL helper가 호출되지 않아야 함."""
        from cowork_pilot.docs_orchestrator import _execute_orchestrator_step
        from cowork_pilot.docs_orchestrator_codex import CodexStepResult

        orch_config = DocsOrchestratorConfig(engine="codex")

        mock_run_codex = MagicMock(
            return_value=CodexStepResult(
                status="completed",
                event_lines=[],
                assistant_message="",
                exit_code=0,
                resume_handle="tid-001",
                waiting_kind=None,
                pending_event_id=None,
                pending_question=None,
                pending_approval=None,
                error="",
            )
        )

        with patch(
            "cowork_pilot.docs_orchestrator._open_orchestrator_session"
        ) as mock_open, patch(
            "cowork_pilot.docs_orchestrator._wait_for_session_completion"
        ) as mock_wait, patch(
            "cowork_pilot.docs_orchestrator.run_codex_step",
            mock_run_codex,
        ):
            _execute_orchestrator_step(
                step_name="phase_1",
                prompt="test prompt",
                expected_files=[],
                watch_mode=False,
                config=Config(project_dir=str(tmp_path)),
                orch_config=orch_config,
                project_dir=tmp_path,
                base_path=tmp_path,
            )

        mock_open.assert_not_called()
        mock_wait.assert_not_called()
        mock_run_codex.assert_called_once()

    def test_codex_waiting_writes_runtime_sidecar(self, tmp_path: Path) -> None:
        """Codex waiting → orchestrator-runtime.json sidecar 기록."""
        from cowork_pilot.docs_orchestrator import _execute_orchestrator_step
        from cowork_pilot.docs_orchestrator_codex import CodexStepResult
        from cowork_pilot.docs_orchestrator_runtime import (
            load_runtime,
            runtime_is_waiting,
        )

        orch_config = DocsOrchestratorConfig(engine="codex")

        waiting_result = CodexStepResult(
            status="waiting",
            event_lines=[],
            assistant_message="",
            exit_code=0,
            resume_handle="tid-002",
            waiting_kind="input",
            pending_event_id="q1",
            pending_question={"question": "continue?"},
            pending_approval=None,
            error="",
        )

        with patch(
            "cowork_pilot.docs_orchestrator.run_codex_step",
            return_value=waiting_result,
        ):
            outcome = _execute_orchestrator_step(
                step_name="phase_2:x:y",
                prompt="prompt",
                expected_files=[],
                watch_mode=False,
                config=Config(project_dir=str(tmp_path)),
                orch_config=orch_config,
                project_dir=tmp_path,
                base_path=tmp_path,
            )

        assert outcome.kind == "waiting"
        assert runtime_is_waiting(tmp_path)
        payload = load_runtime(tmp_path)
        assert payload is not None
        assert payload["backend"] == "codex"
        assert payload["step"] == "phase_2:x:y"
        assert payload["runtime_state"] == "waiting_for_input"
        assert payload["resume_handle"] == "tid-002"
        assert payload["pending_event_id"] == "q1"

    def test_codex_path_uses_wrapper_prompt(self, tmp_path: Path) -> None:
        """engine=codex에서 build_codex_session_prompt()가 호출되어야 함."""
        from cowork_pilot.docs_orchestrator import _execute_orchestrator_step
        from cowork_pilot.docs_orchestrator_codex import CodexStepResult

        orch_config = DocsOrchestratorConfig(engine="codex")

        mock_result = CodexStepResult(
            status="completed",
            event_lines=[],
            assistant_message="",
            exit_code=0,
            resume_handle="t",
            waiting_kind=None,
            pending_event_id=None,
            pending_question=None,
            pending_approval=None,
            error="",
        )

        with patch(
            "cowork_pilot.docs_orchestrator.build_codex_session_prompt"
        ) as mock_build, patch(
            "cowork_pilot.docs_orchestrator.run_codex_step",
            return_value=mock_result,
        ) as mock_run_codex:
            mock_build.return_value = "CODEX_PROMPT"

            _execute_orchestrator_step(
                step_name="phase_1",
                prompt="CLAUDE_PROMPT",
                prompt_phase="phase1_single",
                prompt_kwargs={"project_dir": "/p"},
                expected_files=[],
                watch_mode=False,
                config=Config(project_dir=str(tmp_path)),
                orch_config=orch_config,
                project_dir=tmp_path,
                base_path=tmp_path,
            )

        mock_build.assert_called_once_with("phase1_single", project_dir="/p")
        # run_codex_step must receive the wrapper prompt, not the Claude prompt
        call_kwargs = mock_run_codex.call_args.kwargs
        assert call_kwargs["prompt"] == "CODEX_PROMPT"


class TestRunLoopCodexPauseRecovery:
    """Startup cleanup + waiting pause behaviour for the Codex backend."""

    def _write_state(self, tmp_path: Path, current_step: str) -> Path:
        gen_dir = tmp_path / "docs" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        state_data = {
            "current": {"step": current_step, "status": "running"},
            "completed": [],
            "pending": [],
            "errors": [],
            "project_summary": {
                "domains": [],
                "features": {},
                "source_docs": [],
                "source_line_count": 0,
            },
            "updated_at": "",
            "mode": "auto",
            "manual_override": [],
            "project_dir": str(tmp_path),
        }
        (gen_dir / "orchestrator-state.json").write_text(json.dumps(state_data))
        return gen_dir

    def test_run_loop_pauses_when_codex_waiting(self, tmp_path: Path) -> None:
        """Codex waiting runtime → run loop exits immediately without executing phases."""
        gen_dir = self._write_state(tmp_path, "phase_2:x:y")
        (gen_dir / "orchestrator-runtime.json").write_text(
            json.dumps({
                "backend": "codex",
                "step": "phase_2:x:y",
                "runtime_state": "waiting_for_input",
                "resume_handle": "tid-001",
            })
        )

        orch_config = DocsOrchestratorConfig(engine="codex")
        config = Config(project_dir=str(tmp_path))

        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step"
        ) as mock_exec, patch(
            "cowork_pilot.docs_orchestrator._determine_next_step",
            return_value="phase_2",
        ):
            run_docs_orchestrator(config, orch_config)

        # Phase execution must NOT have been called (loop paused on waiting)
        mock_exec.assert_not_called()

    def test_run_loop_auto_answers_existing_waiting_runtime_when_enabled(
        self, tmp_path: Path,
    ) -> None:
        """Existing startup waiting runtime should try auto-answer before pausing."""
        gen_dir = self._write_state(tmp_path, "phase_2:x:y")
        (gen_dir / "orchestrator-runtime.json").write_text(
            json.dumps({
                "backend": "codex",
                "step": "phase_2:x:y",
                "runtime_state": "waiting_for_input",
                "resume_handle": "tid-001",
                "pending_event_id": "q1",
                "pending_question": {
                    "question": "Q?",
                    "options": ["A", "B"],
                    "recommended": "A",
                    "blocking": True,
                },
                "question_context_seed": {
                    "phase": "phase_2",
                    "phase_template": "phase2_manual",
                    "required_inputs": [],
                    "optional_inputs": [],
                    "output_files": [],
                    "question_fingerprint": "fp",
                },
            })
        )

        orch_config = DocsOrchestratorConfig(engine="codex")
        orch_config.auto_answer.enabled = True
        orch_config.auto_answer.max_rounds_per_run = 300
        config = Config(project_dir=str(tmp_path))

        updated_state = OrchestratorState(
            current={"step": "phase_2", "status": "idle"},
            completed=[StepStatus(step="phase_2:x:y", status="completed")],
            pending=[],
            errors=[],
            project_summary={
                "domains": [],
                "features": {},
                "source_docs": [],
                "source_line_count": 0,
            },
            updated_at="",
            mode="auto",
            manual_override=[],
            project_dir=str(tmp_path),
        )

        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step"
        ) as mock_exec, patch(
            "cowork_pilot.docs_orchestrator._determine_next_step",
            return_value=None,
        ), patch(
            "cowork_pilot.docs_orchestrator.runtime_is_waiting",
            side_effect=[True, False],
        ), patch(
            "cowork_pilot.auto_answer_resolver.try_auto_answer",
            return_value=type(
                "AutoAnswerResult",
                (),
                {
                    "status": "applied",
                    "outcome": type(
                        "Outcome",
                        (),
                        {
                            "status": "completed",
                            "state": updated_state,
                        },
                    )(),
                },
            )(),
        ) as mock_try_auto_answer:
            run_docs_orchestrator(config, orch_config)

        mock_try_auto_answer.assert_called_once()
        mock_exec.assert_not_called()

    def test_run_loop_existing_waiting_can_continue_past_ten_auto_answer_rounds(
        self, tmp_path: Path,
    ) -> None:
        """Startup waiting runtime should keep auto-answering beyond 10 rounds."""
        gen_dir = self._write_state(tmp_path, "phase_2:x:y")
        (gen_dir / "orchestrator-runtime.json").write_text(
            json.dumps({
                "backend": "codex",
                "step": "phase_2:x:y",
                "runtime_state": "waiting_for_input",
                "resume_handle": "tid-001",
                "pending_event_id": "q1",
                "pending_question": {
                    "question": "Q?",
                    "options": ["A", "B"],
                    "recommended": "A",
                    "blocking": True,
                },
                "question_context_seed": {
                    "phase": "phase_2",
                    "phase_template": "phase2_manual",
                    "required_inputs": [],
                    "optional_inputs": [],
                    "output_files": [],
                    "question_fingerprint": "fp",
                },
            })
        )

        orch_config = DocsOrchestratorConfig(engine="codex")
        orch_config.auto_answer.enabled = True
        config = Config(project_dir=str(tmp_path))

        updated_state = OrchestratorState(
            current={"step": "phase_2", "status": "idle"},
            completed=[StepStatus(step="phase_2:x:y", status="completed")],
            pending=[],
            errors=[],
            project_summary={
                "domains": [],
                "features": {},
                "source_docs": [],
                "source_line_count": 0,
            },
            updated_at="",
            mode="auto",
            manual_override=[],
            project_dir=str(tmp_path),
        )

        def _auto_answer_result(*, outcome_status: str, outcome_state: OrchestratorState):
            return type(
                "AutoAnswerResult",
                (),
                {
                    "status": "applied",
                    "outcome": type(
                        "Outcome",
                        (),
                        {
                            "status": outcome_status,
                            "state": outcome_state,
                        },
                    )(),
                },
            )()

        waiting_results = [
            _auto_answer_result(outcome_status="waiting", outcome_state=updated_state)
            for _ in range(10)
        ]
        final_result = _auto_answer_result(
            outcome_status="completed",
            outcome_state=updated_state,
        )

        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step"
        ) as mock_exec, patch(
            "cowork_pilot.docs_orchestrator._determine_next_step",
            return_value=None,
        ), patch(
            "cowork_pilot.docs_orchestrator.runtime_is_waiting",
            side_effect=[True, False],
        ), patch(
            "cowork_pilot.auto_answer_resolver.try_auto_answer",
            side_effect=waiting_results + [final_result],
        ) as mock_try_auto_answer:
            run_docs_orchestrator(config, orch_config)

        assert mock_try_auto_answer.call_count == 11
        mock_exec.assert_not_called()

    def test_run_loop_clears_stale_runtime_on_startup(self, tmp_path: Path) -> None:
        """Runtime file with a step already completed → stale, auto-cleaned at startup."""
        from cowork_pilot.docs_orchestrator_runtime import load_runtime

        gen_dir = tmp_path / "docs" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        state_data = {
            "current": {"step": "phase_1", "status": "completed"},
            "completed": [
                {
                    "step": "phase_1",
                    "status": "completed",
                    "message": "ok",
                    "completed_at": "",
                    "marker_missing": False,
                }
            ],
            "pending": [],
            "errors": [],
            "project_summary": {
                "domains": [],
                "features": {},
                "source_docs": [],
                "source_line_count": 0,
            },
            "updated_at": "",
            "mode": "auto",
            "manual_override": [],
            "project_dir": str(tmp_path),
        }
        (gen_dir / "orchestrator-state.json").write_text(json.dumps(state_data))
        (gen_dir / "orchestrator-runtime.json").write_text(
            json.dumps({
                "backend": "codex",
                "step": "phase_1",
                "runtime_state": "waiting_for_input",
                "resume_handle": "tid-001",
            })
        )

        orch_config = DocsOrchestratorConfig(engine="codex")
        config = Config(project_dir=str(tmp_path))

        # Stop the loop immediately after cleanup
        with patch(
            "cowork_pilot.docs_orchestrator._determine_next_step",
            return_value=None,
        ):
            run_docs_orchestrator(config, orch_config)

        # Runtime should have been cleaned up
        assert load_runtime(tmp_path) is None


# ── Step 5 / Chunk 4: explicit overview-context injection at render sites ─


class TestPhase2And3PassOverviewContextExplicitly:
    """Step 5 / Chunk 4 strict alignment.

    The renderer (``orchestrator_prompts.build_session_prompt``) no longer
    auto-injects ``extracts`` and ``overview_reasons`` via a central hook.
    Every phase2 / phase3 render call site in ``docs_orchestrator`` must
    therefore pass both kwargs **explicitly**, and must also include them
    in ``prompt_kwargs`` for runtime resume.
    """

    def _fake_execute_captured(self, captured: list):
        """Return an ``_execute_orchestrator_step`` stub that records prompt_kwargs."""
        from cowork_pilot.docs_orchestrator import StepExecutionOutcome

        def fake_execute(**kwargs):
            captured.append(kwargs)
            return StepExecutionOutcome(kind="completed")

        return fake_execute

    def _project_with_extracts(self, tmp_path: Path) -> Path:
        generated = tmp_path / "docs" / "generated"
        host_dir = generated / "domain-extracts" / "host"
        host_dir.mkdir(parents=True)
        (host_dir / "create-poll.md").write_text(
            "\n".join(f"line {i}" for i in range(50)), encoding="utf-8"
        )
        (host_dir / "_overview.md").write_text(
            "\n".join(f"line {i}" for i in range(50)), encoding="utf-8"
        )
        (generated / "domain-extracts" / "shared.md").write_text("shared\n", encoding="utf-8")
        (generated / "gap-reports").mkdir(exist_ok=True)
        (generated / "analysis-report.md").write_text(
            "# Report\n\n"
            "## Domain Overview Decisions\n\n"
            "| domain | overview_needed | reason |\n"
            "|---|---|---|\n"
            "| host | yes | lifecycle shared |\n",
            encoding="utf-8",
        )
        return generated

    def test_phase_2_render_passes_extracts_and_overview_reasons_explicitly(
        self,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ) -> None:
        base_config.project_dir = str(tmp_path)

        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2", "status": "idle"},
            project_summary={
                "domains": ["host"],
                "features": {"host": ["create-poll"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        generated = self._project_with_extracts(tmp_path)
        state_path = generated / "orchestrator-state.json"

        captured: list[dict] = []
        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step",
            side_effect=self._fake_execute_captured(captured),
        ):
            _run_phase_2(
                state,
                base_config,
                orch_config,
                tmp_path,
                tmp_path / "sessions",
                state_path,
            )

        phase2_calls = [
            c for c in captured
            if c.get("prompt_phase") in ("phase2_auto", "phase2_manual")
        ]
        assert phase2_calls, f"expected phase2 execute call, got {captured!r}"
        pk = phase2_calls[0]["prompt_kwargs"]
        assert "extracts" in pk, (
            "phase2 render must pass `extracts` explicitly in prompt_kwargs "
            "after the central auto-inject hook is removed"
        )
        assert "overview_reasons" in pk, (
            "phase2 render must pass `overview_reasons` explicitly in prompt_kwargs"
        )
        assert pk["overview_reasons"].get("host") == "lifecycle shared"
        # `extracts` must be an AvailableExtracts-shaped object reporting
        # host/_overview.md as present.
        assert pk["extracts"].overviews.get("host") is True
        assert pk["extracts"].shared is True

    def test_phase_3_architecture_render_passes_extracts_and_overview_reasons_explicitly(
        self,
        tmp_path: Path,
        base_config: Config,
        orch_config: DocsOrchestratorConfig,
    ) -> None:
        from cowork_pilot.docs_orchestrator import _run_phase_3_group_c

        base_config.project_dir = str(tmp_path)

        state = OrchestratorState(
            current={"phase": "phase_3", "step": "phase_3_C", "status": "idle"},
            project_summary={
                "domains": ["host"],
                "features": {"host": ["create-poll"]},
                "source_line_count": 100,
            },
            completed=[
                StepStatus(step="phase_0", status="completed"),
                StepStatus(step="phase_1", status="completed"),
                StepStatus(step="phase_1_5", status="completed"),
                StepStatus(step="phase_2:host:create-poll", status="completed"),
                StepStatus(step="phase_2_summary", status="completed"),
                StepStatus(step="phase_3_A", status="completed"),
                StepStatus(step="phase_3_B:host", status="completed"),
            ],
            project_dir=str(tmp_path),
        )

        generated = self._project_with_extracts(tmp_path)
        state_path = generated / "orchestrator-state.json"

        captured: list[dict] = []
        with patch(
            "cowork_pilot.docs_orchestrator._execute_orchestrator_step",
            side_effect=self._fake_execute_captured(captured),
        ):
            _run_phase_3_group_c(
                state,
                base_config,
                orch_config,
                tmp_path,
                tmp_path / "sessions",
                state_path,
            )

        arch_calls = [
            c for c in captured
            if c.get("prompt_phase") == "phase3_architecture"
        ]
        assert arch_calls, f"expected phase3_architecture execute call, got {captured!r}"
        pk = arch_calls[0]["prompt_kwargs"]
        assert "extracts" in pk, (
            "phase3_architecture render must pass `extracts` explicitly in prompt_kwargs"
        )
        assert "overview_reasons" in pk, (
            "phase3_architecture render must pass `overview_reasons` explicitly in prompt_kwargs"
        )
        assert pk["overview_reasons"].get("host") == "lifecycle shared"
        assert pk["extracts"].overviews.get("host") is True

    def test_inject_overview_context_hook_is_removed(self) -> None:
        """The central auto-inject hook must no longer exist on orchestrator_prompts."""
        from cowork_pilot import orchestrator_prompts

        assert not hasattr(orchestrator_prompts, "_inject_overview_context"), (
            "_inject_overview_context must be removed as part of the single-source "
            "refactor; call sites now pass extracts/overview_reasons explicitly"
        )
