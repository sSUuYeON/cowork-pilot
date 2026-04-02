"""Tests for orchestrator_state module (§12.4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cowork_pilot.config import DocsOrchestratorConfig
from cowork_pilot.orchestrator_state import (
    OrchestratorState,
    StepStatus,
    compute_adaptive_timeout,
    estimate_sessions,
    generate_gap_summary,
    load_state,
    recover_running_step,
    save_state,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_orchestrator_state.json"


# ── Serialization round-trip ─────────────────────────────────────────


class TestSerializationRoundTrip:
    """직렬화 → JSON → 역직렬화 라운드트립."""

    def test_roundtrip_default_state(self, tmp_path: Path) -> None:
        state = OrchestratorState()
        path = tmp_path / "state.json"
        save_state(state, path)
        loaded = load_state(path)

        assert loaded.current == state.current
        assert loaded.completed == []
        assert loaded.pending == []
        assert loaded.errors == []

    def test_roundtrip_with_completed_steps(self, tmp_path: Path) -> None:
        steps = [
            StepStatus(step="phase_0", status="completed", completed_at="2026-01-01T00:00:00", result="success"),
            StepStatus(step="phase_1", status="completed", completed_at="2026-01-01T01:00:00", result="success", actual_idle_seconds=85.0),
        ]
        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2:payment:refund", "status": "idle"},
            project_summary={"type": "web-app", "domains": ["payment"]},
            completed=steps,
            pending=[{"step": "phase_2:booking:calendar"}],
            errors=[],
            updated_at="2026-01-01T02:00:00",
            mode="auto",
            manual_override=["payment"],
            project_dir="/tmp/test",
        )
        path = tmp_path / "state.json"
        save_state(state, path)
        loaded = load_state(path)

        assert loaded.mode == "auto"
        assert loaded.manual_override == ["payment"]
        assert loaded.project_dir == "/tmp/test"
        assert len(loaded.completed) == 2
        assert loaded.completed[0].step == "phase_0"
        assert loaded.completed[1].actual_idle_seconds == 85.0
        assert loaded.current["phase"] == "phase_2"

    def test_load_fixture_file(self) -> None:
        state = load_state(FIXTURE_PATH)
        assert state.mode == "auto"
        assert state.manual_override == ["payment"]
        assert state.current["phase"] == "phase_2"
        assert len(state.completed) == 5
        assert len(state.pending) == 3
        assert len(state.errors) == 1

    def test_load_nonexistent_returns_default(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "nonexistent.json")
        assert state.current["phase"] == "phase_0"
        assert state.completed == []

    def test_step_status_marker_missing_roundtrip(self, tmp_path: Path) -> None:
        steps = [
            StepStatus(step="phase_1", status="completed", marker_missing=True, actual_idle_seconds=120.0),
        ]
        state = OrchestratorState(completed=steps)
        path = tmp_path / "state.json"
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.completed[0].marker_missing is True
        assert loaded.completed[0].actual_idle_seconds == 120.0


# ── estimate_sessions ────────────────────────────────────────────────


class TestEstimateSessions:
    """도메인 3개/기능 10개 → 예상 세션 수."""

    def test_small_project(self) -> None:
        """Source <= 3000 lines, 3 domains, 10 features."""
        domains = ["payment", "booking", "user"]
        features = {
            "payment": ["payment-methods", "refund", "settlement"],
            "booking": ["reservation", "calendar"],
            "user": ["auth", "profile", "settings", "notification", "history"],
        }
        result = estimate_sessions(domains, features, source_line_count=2500)

        # Phase 1: 1 (source <= 3000)
        # Phase 2: 10 features
        # Phase 3: 3 + 10 = 13
        # Phase 4: 3
        # Phase 5: 1 + ceil(10/3)=4 = 5
        # Total: 1 + 10 + 13 + 3 + 5 = 32
        assert result == 32

    def test_large_project(self) -> None:
        """Source > 3000 lines."""
        domains = ["payment", "booking", "user"]
        features = {
            "payment": ["payment-methods", "refund", "settlement"],
            "booking": ["reservation", "calendar"],
            "user": ["auth", "profile", "settings", "notification", "history"],
        }
        result = estimate_sessions(domains, features, source_line_count=5000)

        # Phase 1: 1 + 3 = 4
        # Phase 2: 10
        # Phase 3: 3 + 10 = 13
        # Phase 4: 3
        # Phase 5: 1 + 4 = 5
        # Total: 4 + 10 + 13 + 3 + 5 = 35
        assert result == 35

    def test_minimal_project(self) -> None:
        """1 domain, 1 feature."""
        result = estimate_sessions(["core"], {"core": ["main"]}, source_line_count=500)
        # Phase 1: 1, Phase 2: 1, Phase 3: 3+1=4, Phase 4: 3, Phase 5: 1+1=2
        # Total: 1 + 1 + 4 + 3 + 2 = 11
        assert result == 11


# ── Adaptive timeout ─────────────────────────────────────────────────


class TestAdaptiveTimeout:
    """적응형 타임아웃: 실측 [80, 90, 100] → 평균 90 × 1.5 = 135초 (60~300 클램핑)."""

    def test_basic_calculation(self) -> None:
        config = DocsOrchestratorConfig()
        steps = [
            StepStatus(step="s1", status="completed", actual_idle_seconds=80.0),
            StepStatus(step="s2", status="completed", actual_idle_seconds=90.0),
            StepStatus(step="s3", status="completed", actual_idle_seconds=100.0),
        ]
        result = compute_adaptive_timeout(steps, config)
        # avg=90, 90*1.5=135, clamped to [60, 300] → 135
        assert result == 135.0

    def test_fewer_than_three_returns_initial(self) -> None:
        config = DocsOrchestratorConfig()
        steps = [
            StepStatus(step="s1", status="completed", actual_idle_seconds=80.0),
            StepStatus(step="s2", status="completed", actual_idle_seconds=90.0),
        ]
        result = compute_adaptive_timeout(steps, config)
        assert result == config.idle_timeout_seconds  # 120.0

    def test_clamp_minimum(self) -> None:
        config = DocsOrchestratorConfig()
        steps = [
            StepStatus(step="s1", status="completed", actual_idle_seconds=10.0),
            StepStatus(step="s2", status="completed", actual_idle_seconds=15.0),
            StepStatus(step="s3", status="completed", actual_idle_seconds=20.0),
        ]
        result = compute_adaptive_timeout(steps, config)
        # avg=15, 15*1.5=22.5 → clamped to min=60
        assert result == 60.0

    def test_clamp_maximum(self) -> None:
        config = DocsOrchestratorConfig()
        steps = [
            StepStatus(step="s1", status="completed", actual_idle_seconds=250.0),
            StepStatus(step="s2", status="completed", actual_idle_seconds=280.0),
            StepStatus(step="s3", status="completed", actual_idle_seconds=300.0),
        ]
        result = compute_adaptive_timeout(steps, config)
        # avg=276.67, 276.67*1.5=415 → clamped to max=300
        assert result == 300.0

    def test_zero_idle_seconds_ignored(self) -> None:
        config = DocsOrchestratorConfig()
        steps = [
            StepStatus(step="s1", status="completed", actual_idle_seconds=0.0),  # ignored
            StepStatus(step="s2", status="completed", actual_idle_seconds=80.0),
            StepStatus(step="s3", status="completed", actual_idle_seconds=90.0),
            StepStatus(step="s4", status="completed", actual_idle_seconds=100.0),
        ]
        result = compute_adaptive_timeout(steps, config)
        assert result == 135.0

    def test_empty_steps(self) -> None:
        config = DocsOrchestratorConfig()
        result = compute_adaptive_timeout([], config)
        assert result == config.idle_timeout_seconds


# ── Running step recovery ────────────────────────────────────────────


class TestRecoverRunningStep:
    """running 복구: 마커 있음 → completed, 마커 없음+파일 있음 → pending."""

    def test_not_running_returns_unchanged(self) -> None:
        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "idle"},
        )
        result = recover_running_step(state, Path("/tmp"))
        assert result.current["status"] == "idle"

    def test_marker_present_transitions_to_completed(self, tmp_path: Path) -> None:
        # Set up output file with marker
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        report = generated / "analysis-report.md"
        report.write_text("# Analysis\nContent here\n<!-- ORCHESTRATOR:DONE -->")

        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )
        result = recover_running_step(state, tmp_path)

        assert result.current["status"] == "idle"
        assert len(result.completed) == 1
        assert result.completed[0].step == "phase_1"
        assert result.completed[0].result == "recovered"

    def test_file_without_marker_reverts_to_pending(self, tmp_path: Path) -> None:
        # Set up output file WITHOUT marker
        generated = tmp_path / "docs" / "generated"
        generated.mkdir(parents=True)
        report = generated / "analysis-report.md"
        report.write_text("# Incomplete report\nSome content")

        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )
        result = recover_running_step(state, tmp_path)

        assert result.current["status"] == "idle"
        assert len(result.completed) == 0
        assert any(p["step"] == "phase_1" for p in result.pending)
        # File should be deleted
        assert not report.exists()

    def test_no_output_files_reverts_to_pending(self, tmp_path: Path) -> None:
        state = OrchestratorState(
            current={"phase": "phase_1", "step": "phase_1", "status": "running"},
            project_dir=str(tmp_path),
        )
        result = recover_running_step(state, tmp_path)

        assert result.current["status"] == "idle"
        assert any(p["step"] == "phase_1" for p in result.pending)

    def test_gap_report_recovery_with_marker(self, tmp_path: Path) -> None:
        """Phase 2 step recovery with domain--feature pattern."""
        generated = tmp_path / "docs" / "generated" / "gap-reports"
        generated.mkdir(parents=True)
        gap_file = generated / "payment--refund.md"
        gap_file.write_text("## Refund Gap\nContent\n<!-- ORCHESTRATOR:DONE -->")

        state = OrchestratorState(
            current={"phase": "phase_2", "step": "phase_2:payment:refund", "status": "running"},
            project_dir=str(tmp_path),
        )
        result = recover_running_step(state, tmp_path)

        assert result.current["status"] == "idle"
        assert len(result.completed) == 1
        assert result.completed[0].step == "phase_2:payment:refund"


# ── generate_gap_summary ─────────────────────────────────────────────


class TestGenerateGapSummary:
    """점수 행 + [AI_DECISION] 파싱 검증 (tmp_path 사용)."""

    def test_basic_summary(self, tmp_path: Path) -> None:
        # Create gap-report files
        (tmp_path / "payment--payment-methods.md").write_text(
            "## 결제 수단 갭 분석\n\n"
            "종합: 2.7/3.0\n\n"
            "- [AI_DECISION] 에러 처리 방식: 토스트 알림\n"
            "- [AI_DECISION] 환불 정책: 3영업일\n"
        )
        (tmp_path / "payment--refund.md").write_text(
            "## 환불 갭 분석\n\n"
            "점수: 2.3/3.0\n\n"
            "- [AI_DECISION] 환불 처리 시간\n"
        )
        (tmp_path / "booking--reservation.md").write_text(
            "## 예약 갭 분석\n\n"
            "종합: 3.0/3.0\n"
        )

        result = generate_gap_summary(tmp_path)

        assert "# 갭 분석 요약" in result
        assert "payment" in result
        assert "payment-methods" in result
        assert "2.7/3.0" in result
        assert "2.3/3.0" in result
        assert "3.0/3.0" in result
        assert "<!-- ORCHESTRATOR:DONE -->" in result

        # AI_DECISION counts
        assert "| 2 |" in result  # payment-methods has 2
        assert "| 1 |" in result  # refund has 1
        assert "| 0 |" in result  # reservation has 0

        # Total
        assert "총 AI 결정 수**: 3건" in result

    def test_skips_summary_file(self, tmp_path: Path) -> None:
        (tmp_path / "_summary.md").write_text("existing summary")
        (tmp_path / "payment--refund.md").write_text("종합: 2.0/3.0\n")

        result = generate_gap_summary(tmp_path)
        assert "refund" in result
        # _summary.md should not be parsed as a gap-report
        lines = [l for l in result.split("\n") if "| " in l and "payment" in l]
        assert len(lines) == 1

    def test_no_score_found(self, tmp_path: Path) -> None:
        (tmp_path / "misc--feature.md").write_text("Some content without score\n")
        result = generate_gap_summary(tmp_path)
        assert "| - |" in result  # score is "-"

    def test_empty_dir(self, tmp_path: Path) -> None:
        result = generate_gap_summary(tmp_path)
        assert "# 갭 분석 요약" in result
        assert "전체 평균**: -" in result
        assert "총 AI 결정 수**: 0건" in result
