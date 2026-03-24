"""End-to-end integration tests for the harness orchestrator.

Uses sample_exec_plan.md fixture with mocked AppleScript + CLI to verify
the full pipeline: parsing → session open → idle detect → verify → checkbox update → next chunk.
"""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.completion_detector import (
    build_feedback_text,
    build_verification_prompt,
    is_idle_trigger,
    parse_verification_result,
)
from cowork_pilot.config import HarnessConfig as ConfigHarnessConfig, load_harness_config, Config
from cowork_pilot.plan_parser import ExecPlan, parse_exec_plan, update_checkboxes
from cowork_pilot.session_manager import (
    ChunkRetryState,
    HarnessConfig,
    find_next_incomplete_chunk,
    move_to_completed,
    open_chunk_session,
    process_chunk,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PLAN = FIXTURE_DIR / "sample_exec_plan.md"


# ── Full pipeline integration: parse → verify → update → next chunk ──

class TestFullPipeline:
    """Integration test: walk through multiple chunks with mock verification."""

    def test_complete_all_chunks(self, tmp_path):
        """Simulate completing all chunks in sequence."""
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)

        config = HarnessConfig()

        # Track which chunks were processed
        processed_chunks = []

        def mock_verify(chunk, cfg, pd, plan_path=None):
            processed_chunks.append(chunk.number)
            return ("COMPLETED", "")

        # Chunk 1 (pending)
        plan = parse_exec_plan(plan_file)
        chunk = find_next_incomplete_chunk(plan)
        assert chunk.number == 1
        retry = ChunkRetryState()
        result = process_chunk(plan_file, chunk, config, "/tmp", retry,
                              verify_fn=mock_verify, feedback_fn=lambda t: True)
        assert result == "COMPLETED"

        # Chunk 2 is already completed in fixture, skip to Chunk 3
        plan = parse_exec_plan(plan_file)
        chunk = find_next_incomplete_chunk(plan)
        assert chunk.number == 3  # Chunk 2 was already [x]
        retry = ChunkRetryState()
        result = process_chunk(plan_file, chunk, config, "/tmp", retry,
                              verify_fn=mock_verify, feedback_fn=lambda t: True)
        assert result == "COMPLETED"

        # All done
        plan = parse_exec_plan(plan_file)
        assert find_next_incomplete_chunk(plan) is None
        assert plan.status == "completed"
        assert processed_chunks == [1, 3]

    def test_incomplete_feedback_then_complete(self, tmp_path):
        """Simulate: first verify = INCOMPLETE, second = COMPLETED."""
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)

        config = HarnessConfig()
        retry = ChunkRetryState()

        call_count = [0]

        def mock_verify(chunk, cfg, pd, plan_path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("INCOMPLETE", "pytest failed")
            return ("COMPLETED", "")

        feedback_calls = []

        plan = parse_exec_plan(plan_file)
        chunk = find_next_incomplete_chunk(plan)

        # First try: INCOMPLETE
        result = process_chunk(plan_file, chunk, config, "/tmp", retry,
                              verify_fn=mock_verify,
                              feedback_fn=lambda t: feedback_calls.append(t) or True)
        assert result == "INCOMPLETE"
        assert retry.incomplete_feedback_count == 1
        assert len(feedback_calls) == 1
        assert "pytest failed" in feedback_calls[0]

        # Second try: COMPLETED
        result = process_chunk(plan_file, chunk, config, "/tmp", retry,
                              verify_fn=mock_verify,
                              feedback_fn=lambda t: feedback_calls.append(t) or True)
        assert result == "COMPLETED"

    def test_move_to_completed_after_all_done(self, tmp_path):
        """Verify file moves from active/ to completed/."""
        active_dir = tmp_path / "active"
        active_dir.mkdir()
        plan_file = active_dir / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)

        # Complete all chunks
        update_checkboxes(plan_file, chunk_number=1)
        update_checkboxes(plan_file, chunk_number=3)

        plan = parse_exec_plan(plan_file)
        assert plan.status == "completed"

        dest = move_to_completed(plan_file)
        assert dest.exists()
        assert not plan_file.exists()
        assert dest.parent.name == "completed"


# ── Edge cases ───────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_exec_plan_dir(self, tmp_path):
        """No .md files in active/ → nothing to process."""
        active_dir = tmp_path / "docs" / "exec-plans" / "active"
        active_dir.mkdir(parents=True)
        plans = list(active_dir.glob("*.md"))
        assert len(plans) == 0

    def test_all_chunks_already_completed(self, tmp_path):
        """All checkboxes already [x] → find_next returns None immediately."""
        plan_file = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, plan_file)
        update_checkboxes(plan_file, chunk_number=1)
        update_checkboxes(plan_file, chunk_number=3)

        plan = parse_exec_plan(plan_file)
        assert find_next_incomplete_chunk(plan) is None

    def test_parse_error_raises(self, tmp_path):
        """Malformed exec-plan → ValueError."""
        bad = tmp_path / "bad.md"
        bad.write_text(textwrap.dedent("""\
        # Bad Plan

        ## Metadata
        - project_dir: /tmp
        - status: pending

        ---

        ## Chunk 1: Broken

        ### Completion Criteria
        - [ ] something

        ### Tasks
        - Task 1: Do it

        ### Session Prompt

        ---
        """))
        with pytest.raises(ValueError, match="empty Session Prompt"):
            parse_exec_plan(bad)


# ── Config loading ───────────────────────────────────────────────────

class TestHarnessConfigLoading:
    def test_load_harness_config_defaults(self, tmp_path):
        """No config file → defaults."""
        cfg = load_harness_config(tmp_path / "nonexistent.toml")
        assert cfg.idle_timeout_seconds == 120.0
        assert cfg.completion_check_max_retries == 3

    def test_load_harness_config_from_toml(self, tmp_path):
        """Config file with [harness] section."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(textwrap.dedent("""\
        [harness]
        idle_timeout_seconds = 60
        completion_check_max_retries = 5

        [harness.session]
        open_delay_seconds = 5.0
        detect_timeout_seconds = 15.0
        """))
        cfg = load_harness_config(toml_file)
        assert cfg.idle_timeout_seconds == 60.0
        assert cfg.completion_check_max_retries == 5
        assert cfg.session_open_delay == 5.0
        assert cfg.session_detect_timeout == 15.0

    def test_load_harness_config_inherits_engine(self, tmp_path):
        """Engine settings inherited from base Config."""
        base = Config(engine="codex", codex_command="/usr/local/bin/codex", codex_args=["-q"])
        cfg = load_harness_config(tmp_path / "nonexistent.toml", base_config=base)
        assert cfg.engine == "codex"
        assert cfg.engine_command == "/usr/local/bin/codex"
        assert cfg.engine_args == ["-q"]


# ── Idle detection integration ───────────────────────────────────────

class TestIdleDetectionIntegration:
    """Verify idle detection works with realistic JSONL record shapes."""

    def test_summary_after_long_idle(self):
        record = {"type": "summary", "message": {"content": "turn summary"}}
        assert is_idle_trigger(record, 0.0, 130.0) is True

    def test_assistant_done_after_long_idle(self):
        record = {
            "type": "assistant",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": "All tasks completed."},
                ],
            },
        }
        assert is_idle_trigger(record, 0.0, 130.0) is True

    def test_parsed_record_never_triggers(self):
        """Bug repro: if last_record is a parsed dict from parse_jsonl_line
        (type="user" with tool_results key), idle trigger never fires because
        is_idle_trigger expects raw JSONL records (type="assistant"/"summary").
        This was the root cause of harness not transitioning between chunks."""
        # This is what parse_jsonl_line returns — a processed dict
        parsed_record = {
            "type": "user",
            "tool_results": ["toolu_abc"],
            "raw": {"type": "user", "message": {"content": []}},
        }
        # Even after long timeout, this should NOT trigger (user type)
        assert is_idle_trigger(parsed_record, 0.0, 999.0) is False

    def test_raw_assistant_end_turn_triggers(self):
        """Fix verification: raw JSONL assistant record with end_turn and no
        tool_use triggers idle correctly — this is what the harness loop
        should store in last_record."""
        raw_record = {
            "type": "assistant",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": "Chunk 1 구현이 완료되었습니다."},
                ],
            },
        }
        assert is_idle_trigger(raw_record, 0.0, 130.0) is True

    def test_no_trigger_during_active_work(self):
        """Tool use in progress → no trigger even after timeout."""
        record = {
            "type": "assistant",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "Bash"},
                ],
            },
        }
        assert is_idle_trigger(record, 0.0, 130.0) is False

    def test_last_prompt_overwrites_and_triggers(self):
        """Real scenario: assistant final record has stop_reason: null
        (streaming artifact), followed by last-prompt.  The harness stores
        all records in last_record, so last-prompt ends up as last_record.
        is_idle_trigger treats last-prompt as a session-end signal."""
        import json as _json

        lines = [
            _json.dumps({"type": "assistant", "message": {
                "stop_reason": None,
                "content": [{"type": "text", "text": "Done."}],
            }}),
            _json.dumps({"type": "last-prompt", "lastPrompt": "..."}),
        ]

        # Replicate the harness loop's raw-record storage logic (no filter)
        last_record = None
        for line in lines:
            try:
                raw = _json.loads(line.strip())
                if isinstance(raw, dict):
                    last_record = raw
            except (ValueError, _json.JSONDecodeError):
                pass

        # last_record IS last-prompt now — and idle trigger handles it
        assert last_record is not None
        assert last_record["type"] == "last-prompt"
        assert is_idle_trigger(last_record, 0.0, 130.0) is True

    def test_last_prompt_direct_idle_trigger(self):
        """is_idle_trigger recognizes last-prompt as session-end signal."""
        record = {"type": "last-prompt"}
        assert is_idle_trigger(record, 0.0, 130.0) is True

    def test_assistant_end_turn_still_triggers(self):
        """Normal case: assistant with stop_reason end_turn still works."""
        record = {"type": "assistant", "message": {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done."}],
        }}
        assert is_idle_trigger(record, 0.0, 130.0) is True


# ── Verification prompt → parse roundtrip ────────────────────────────

class TestVerificationRoundtrip:
    def test_prompt_to_completed(self):
        from cowork_pilot.plan_parser import Chunk, CompletionCriterion
        chunk = Chunk(
            name="Test", number=1,
            completion_criteria=[
                CompletionCriterion("pytest passes", False),
                CompletionCriterion("file exists", False),
            ],
        )
        prompt = build_verification_prompt(chunk)
        assert "Chunk 1" in prompt

        # Simulate CLI returning COMPLETED
        status, _ = parse_verification_result("All checks passed.\nCOMPLETED")
        assert status == "COMPLETED"

    def test_prompt_to_incomplete(self):
        status, detail = parse_verification_result(
            "INCOMPLETE: pytest tests/test_x.py failed with exit code 1"
        )
        assert status == "INCOMPLETE"
        assert "pytest" in detail
