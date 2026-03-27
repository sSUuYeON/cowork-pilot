"""Tests for session_manager — Chunk lifecycle control."""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.config import ReviewConfig
from cowork_pilot.plan_parser import Chunk, CompletionCriterion, ExecPlan, parse_exec_plan
from cowork_pilot.session_manager import (
    ChunkRetryState,
    HarnessConfig,
    _get_jsonl_snapshot,
    build_session_prompt,
    detect_new_jsonl,
    find_next_incomplete_chunk,
    handle_chunk_completion,
    move_to_completed,
    notify_escalate,
    open_chunk_session,
    process_chunk,
    run_chunk_verification,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PLAN = FIXTURE_DIR / "sample_exec_plan.md"


# ── find_next_incomplete_chunk ───────────────────────────────────────

class TestFindNextIncompleteChunk:
    def test_finds_first_pending(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        chunk = find_next_incomplete_chunk(plan)
        assert chunk is not None
        assert chunk.number == 1

    def test_skips_completed_chunks(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        # Chunk 2 is already completed in fixture; Chunk 1 is pending
        assert plan.chunks[1].status == "completed"
        chunk = find_next_incomplete_chunk(plan)
        assert chunk.number == 1  # first incomplete

    def test_returns_none_when_all_completed(self):
        plan = ExecPlan(
            title="Test",
            chunks=[
                Chunk(name="A", number=1, status="completed",
                      completion_criteria=[CompletionCriterion("x", True)]),
                Chunk(name="B", number=2, status="completed",
                      completion_criteria=[CompletionCriterion("y", True)]),
            ],
        )
        assert find_next_incomplete_chunk(plan) is None


# ── JSONL snapshot + detection ───────────────────────────────────────

class TestJsonlDetection:
    def test_snapshot_finds_jsonl_files(self, tmp_path):
        (tmp_path / "a.jsonl").write_text("{}")
        (tmp_path / "b.jsonl").write_text("{}")
        snap = _get_jsonl_snapshot(tmp_path)
        assert len(snap) == 2

    def test_detect_new_jsonl(self, tmp_path):
        (tmp_path / "old.jsonl").write_text("{}")
        snap = _get_jsonl_snapshot(tmp_path)

        # Simulate new file appearing
        new_file = tmp_path / "new.jsonl"
        new_file.write_text("{}")

        result = detect_new_jsonl(tmp_path, snap, timeout=2.0, poll_interval=0.1)
        assert result is not None
        assert result.name == "new.jsonl"

    def test_snapshot_ignores_audit_jsonl(self, tmp_path):
        (tmp_path / "session.jsonl").write_text("{}")
        (tmp_path / "audit.jsonl").write_text("{}")
        snap = _get_jsonl_snapshot(tmp_path)
        assert len(snap) == 1
        assert any("session.jsonl" in s for s in snap)
        assert not any("audit.jsonl" in s for s in snap)

    def test_detect_ignores_audit_jsonl(self, tmp_path):
        snap = _get_jsonl_snapshot(tmp_path)
        # Only audit.jsonl appears — should NOT be detected
        (tmp_path / "audit.jsonl").write_text("{}")
        result = detect_new_jsonl(tmp_path, snap, timeout=0.5, poll_interval=0.1)
        assert result is None

    def test_detect_timeout(self, tmp_path):
        snap = _get_jsonl_snapshot(tmp_path)
        result = detect_new_jsonl(tmp_path, snap, timeout=0.3, poll_interval=0.1)
        assert result is None


# ── open_chunk_session ───────────────────────────────────────────────

class TestOpenChunkSession:
    @patch("cowork_pilot.session_manager.detect_new_jsonl")
    @patch("cowork_pilot.session_opener.open_new_session")
    def test_success(self, mock_open, mock_detect, tmp_path):
        mock_open.return_value = True
        mock_detect.return_value = tmp_path / "new.jsonl"

        chunk = Chunk(name="Test", number=1, session_prompt="test prompt")
        config = HarnessConfig()

        result = open_chunk_session(chunk, config, tmp_path)
        assert result is not None
        mock_open.assert_called_once()

    @patch("cowork_pilot.session_manager.detect_new_jsonl")
    @patch("cowork_pilot.session_opener.open_new_session")
    def test_open_failure_retries(self, mock_open, mock_detect, tmp_path):
        mock_open.return_value = False
        mock_detect.return_value = None

        chunk = Chunk(name="Test", number=1, session_prompt="test prompt")
        config = HarnessConfig()

        result = open_chunk_session(chunk, config, tmp_path, max_retries=2)
        assert result is None
        assert mock_open.call_count == 2

    @patch("cowork_pilot.session_manager.detect_new_jsonl")
    @patch("cowork_pilot.session_opener.open_new_session")
    def test_review_config_wraps_prompt(self, mock_open, mock_detect, tmp_path):
        mock_open.return_value = True
        mock_detect.return_value = tmp_path / "new.jsonl"

        chunk = Chunk(name="Test", number=1, session_prompt="test prompt")
        config = HarnessConfig()
        rc = ReviewConfig(enabled=True)

        open_chunk_session(chunk, config, tmp_path, review_config=rc)
        # The prompt passed to open_new_session should include review instructions
        call_kwargs = mock_open.call_args
        actual_prompt = call_kwargs.kwargs.get("initial_prompt") or call_kwargs[1].get("initial_prompt")
        if actual_prompt is None:
            actual_prompt = call_kwargs[0][0] if call_kwargs[0] else ""
        assert "/engineering:code-review" in actual_prompt

    @patch("cowork_pilot.session_manager.detect_new_jsonl")
    @patch("cowork_pilot.session_opener.open_new_session")
    def test_detect_failure_retries(self, mock_open, mock_detect, tmp_path):
        mock_open.return_value = True
        mock_detect.return_value = None  # Can't find new JSONL

        chunk = Chunk(name="Test", number=1, session_prompt="test prompt")
        config = HarnessConfig()

        result = open_chunk_session(chunk, config, tmp_path, max_retries=2)
        assert result is None
        assert mock_open.call_count == 2


# ── move_to_completed ────────────────────────────────────────────────

class TestMoveToCompleted:
    def test_moves_file(self, tmp_path):
        active = tmp_path / "active"
        active.mkdir()
        plan_file = active / "plan.md"
        plan_file.write_text("# Test")

        completed_dir = tmp_path / "completed"
        # move_to_completed expects parent.parent / "completed"
        # so we need active's parent = tmp_path, and completed = tmp_path/completed
        dest = move_to_completed(plan_file)
        assert dest.exists()
        assert not plan_file.exists()
        assert dest.parent.name == "completed"


# ── Retry counters ───────────────────────────────────────────────────

class TestChunkRetryState:
    def test_initial_values(self):
        state = ChunkRetryState()
        assert state.cli_failure_count == 0
        assert state.incomplete_feedback_count == 0


# ── process_chunk ────────────────────────────────────────────────────

class TestProcessChunk:
    def _make_chunk(self):
        return Chunk(
            name="Test",
            number=1,
            completion_criteria=[
                CompletionCriterion("pytest passes", False),
                CompletionCriterion("file exists", False),
            ],
            session_prompt="test prompt",
        )

    def test_completed(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        chunk = self._make_chunk()
        config = HarnessConfig()
        retry = ChunkRetryState()

        def mock_verify(c, cfg, pd, plan_path=None):
            return ("COMPLETED", "")

        result = process_chunk(
            plan_file, chunk, config, "/tmp",
            retry, verify_fn=mock_verify,
        )
        assert result == "COMPLETED"

    def test_incomplete_sends_feedback(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        chunk = self._make_chunk()
        config = HarnessConfig()
        retry = ChunkRetryState()

        def mock_verify(c, cfg, pd, plan_path=None):
            return ("INCOMPLETE", "pytest failed")

        feedback_sent = []
        def mock_feedback(text):
            feedback_sent.append(text)
            return True

        result = process_chunk(
            plan_file, chunk, config, "/tmp",
            retry, verify_fn=mock_verify, feedback_fn=mock_feedback,
        )
        assert result == "INCOMPLETE"
        assert len(feedback_sent) == 1
        assert "pytest failed" in feedback_sent[0]
        assert retry.incomplete_feedback_count == 1

    def test_incomplete_escalates_after_max_retries(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        chunk = self._make_chunk()
        config = HarnessConfig(incomplete_retry_max=2)
        retry = ChunkRetryState(incomplete_feedback_count=2)

        def mock_verify(c, cfg, pd, plan_path=None):
            return ("INCOMPLETE", "still failing")

        result = process_chunk(
            plan_file, chunk, config, "/tmp",
            retry, verify_fn=mock_verify, feedback_fn=lambda t: True,
        )
        assert result == "ESCALATE"

    def test_error_increments_cli_counter(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        chunk = self._make_chunk()
        config = HarnessConfig()
        retry = ChunkRetryState()

        def mock_verify(c, cfg, pd, plan_path=None):
            return ("ERROR", "timeout")

        result = process_chunk(
            plan_file, chunk, config, "/tmp",
            retry, verify_fn=mock_verify,
        )
        assert result == "ERROR"
        assert retry.cli_failure_count == 1

    def test_error_escalates_after_max_retries(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        chunk = self._make_chunk()
        config = HarnessConfig(completion_check_max_retries=2)
        retry = ChunkRetryState(cli_failure_count=2)

        def mock_verify(c, cfg, pd, plan_path=None):
            return ("ERROR", "timeout")

        result = process_chunk(
            plan_file, chunk, config, "/tmp",
            retry, verify_fn=mock_verify,
        )
        assert result == "ESCALATE"


# ── File-based verification ──────────────────────────────────────────

class TestRunChunkVerification:
    """run_chunk_verification re-parses the plan file on disk."""

    def test_all_checked_returns_completed(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(
            "# Test Plan\n\n"
            "## Chunk 1: Setup\n\n"
            "### Completion Criteria\n"
            "- [x] file exists\n"
            "- [x] build passes\n\n"
            "### Session Prompt\n```\ndo stuff\n```\n",
            encoding="utf-8",
        )
        chunk = Chunk(name="Setup", number=1, session_prompt="do stuff")
        config = HarnessConfig()
        status, detail = run_chunk_verification(chunk, config, "/tmp", plan_path=plan_file)
        assert status == "COMPLETED"

    def test_unchecked_returns_incomplete(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(
            "# Test Plan\n\n"
            "## Chunk 1: Setup\n\n"
            "### Completion Criteria\n"
            "- [x] file exists\n"
            "- [ ] build passes\n\n"
            "### Session Prompt\n```\ndo stuff\n```\n",
            encoding="utf-8",
        )
        chunk = Chunk(name="Setup", number=1, session_prompt="do stuff")
        config = HarnessConfig()
        status, detail = run_chunk_verification(chunk, config, "/tmp", plan_path=plan_file)
        assert status == "INCOMPLETE"
        assert "build passes" in detail

    def test_missing_plan_returns_error(self):
        chunk = Chunk(name="Setup", number=1, session_prompt="do stuff")
        config = HarnessConfig()
        status, _ = run_chunk_verification(chunk, config, "/tmp", plan_path=Path("/nonexistent"))
        assert status == "ERROR"

    def test_no_plan_path_returns_error(self):
        chunk = Chunk(name="Setup", number=1, session_prompt="do stuff")
        config = HarnessConfig()
        status, _ = run_chunk_verification(chunk, config, "/tmp", plan_path=None)
        assert status == "ERROR"


# ── notify_escalate ──────────────────────────────────────────────────

class TestNotifyEscalate:
    @patch("cowork_pilot.responder.subprocess.run")
    def test_does_not_raise(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        notify_escalate("test message")  # should not raise

    @patch("cowork_pilot.responder.subprocess.run")
    def test_handles_oserror(self, mock_run):
        mock_run.side_effect = OSError("no osascript")
        notify_escalate("test message")  # should not raise


# ── build_session_prompt ─────────────────────────────────────────────

class TestBuildSessionPrompt:
    def _make_chunk(self, number=1, prompt="do stuff"):
        return Chunk(name="Test", number=number, session_prompt=prompt)

    def test_no_review_config_returns_original(self):
        chunk = self._make_chunk()
        assert build_session_prompt(chunk) == "do stuff"

    def test_review_disabled_returns_original(self):
        chunk = self._make_chunk()
        rc = ReviewConfig(enabled=False)
        assert build_session_prompt(chunk, rc) == "do stuff"

    def test_review_enabled_appends_instructions(self):
        chunk = self._make_chunk()
        rc = ReviewConfig(enabled=True)
        result = build_session_prompt(chunk, rc)
        assert result.startswith("do stuff")
        assert "/engineering:code-review" in result
        assert "implementation-map" in result
        assert "/chunk-complete:chunk-complete" in result
        assert "DESIGN_GUIDE.md" in result

    def test_skip_chunk_returns_original(self):
        chunk = self._make_chunk(number=1)
        rc = ReviewConfig(enabled=True, skip_chunks=[1, 3])
        assert build_session_prompt(chunk, rc) == "do stuff"

    def test_non_skipped_chunk_gets_instructions(self):
        chunk = self._make_chunk(number=2)
        rc = ReviewConfig(enabled=True, skip_chunks=[1, 3])
        result = build_session_prompt(chunk, rc)
        assert "/engineering:code-review" in result

    def test_prompt_preserves_original_content(self):
        original = "exec-plan을 읽고 Chunk 3을 진행해.\n빌드 후 테스트 실행."
        chunk = self._make_chunk(prompt=original)
        rc = ReviewConfig(enabled=True)
        result = build_session_prompt(chunk, rc)
        assert result.startswith(original)


class TestPromoteNextPlan:
    """planning/ → active/ plan 이동."""

    def test_promotes_first_by_filename_sort(self, tmp_path):
        """파일명 정렬 순으로 첫 번째를 promote."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)
        (planning / "02-implementation.md").write_text("# Plan 2")
        (planning / "01-docs-setup.md").write_text("# Plan 1")

        from cowork_pilot.session_manager import promote_next_plan
        promoted = promote_next_plan(tmp_path / "docs" / "exec-plans")
        assert promoted is not None
        assert promoted.name == "01-docs-setup.md"
        assert (active / "01-docs-setup.md").exists()
        assert not (planning / "01-docs-setup.md").exists()

    def test_returns_none_when_planning_empty(self, tmp_path):
        """planning/이 비어있으면 None."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None

    def test_returns_none_when_active_not_empty(self, tmp_path):
        """active/에 이미 plan이 있으면 promote하지 않음."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)
        (planning / "02-implementation.md").write_text("# Plan 2")
        (active / "01-docs-setup.md").write_text("# Plan 1")

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None

    def test_planning_dir_missing(self, tmp_path):
        """planning/ 디렉토리가 없으면 None."""
        active = tmp_path / "docs" / "exec-plans" / "active"
        active.mkdir(parents=True)

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None
