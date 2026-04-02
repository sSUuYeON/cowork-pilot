"""Tests for plan_parser — exec-plan MD → dataclasses."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cowork_pilot.plan_parser import (
    CompletionCriterion,
    Chunk,
    ExecPlan,
    parse_exec_plan,
    update_checkboxes,
    update_checkboxes_by_description,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PLAN = FIXTURE_DIR / "sample_exec_plan.md"


# ── Metadata parsing ─────────────────────────────────────────────────

class TestParseMetadata:
    """Tests for metadata extraction (title, project_dir, status)."""

    def test_parse_metadata(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert plan.title == "Phase 2: Sample Implementation Plan"
        assert plan.project_dir == "/Users/test/sample-project"
        assert plan.spec == "docs/specs/2026-03-24-sample-design.md"
        assert plan.created == "2026-03-24"

    def test_plan_status_from_metadata(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        # Mix of completed/pending chunks → in_progress at plan level
        # Actually, chunk2 is completed and chunks 1,3 are pending
        # Since some are non-pending, plan is in_progress
        assert plan.status == "in_progress"


# ── Chunk parsing ────────────────────────────────────────────────────

class TestParseChunks:
    """Tests for chunk splitting and content extraction."""

    def test_parse_chunks_count(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert len(plan.chunks) == 3

    def test_chunk_numbers_and_names(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert plan.chunks[0].number == 1
        assert plan.chunks[0].name == "Foundation"
        assert plan.chunks[1].number == 2
        assert plan.chunks[1].name == "Watcher"
        assert plan.chunks[2].number == 3
        assert plan.chunks[2].name == "Integration"

    def test_chunk_tasks(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert plan.chunks[0].tasks == [
            "Task 1: Project Scaffold",
            "Task 2: Models",
            "Task 3: Config",
        ]
        assert plan.chunks[1].tasks == [
            "Task 4: JSONL Parser",
            "Task 5: State Machine",
        ]

    def test_completion_criteria_unchecked(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        c1 = plan.chunks[0].completion_criteria
        assert len(c1) == 3
        assert c1[0].description == "pytest tests/test_models.py 통과"
        assert c1[0].checked is False
        assert c1[1].checked is False
        assert c1[2].checked is False

    def test_completion_criteria_checked(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        c2 = plan.chunks[1].completion_criteria
        assert len(c2) == 2
        assert c2[0].checked is True
        assert c2[1].checked is True

    def test_chunk_status_completed(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert plan.chunks[1].status == "completed"

    def test_chunk_status_pending(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        assert plan.chunks[0].status == "pending"
        assert plan.chunks[2].status == "pending"

    def test_session_prompt_extraction(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        prompt1 = plan.chunks[0].session_prompt
        assert "Chunk 1을 진행해" in prompt1
        assert "AGENTS.md" in prompt1
        # Should not contain the code fence markers
        assert "```" not in prompt1

    def test_session_prompt_generic(self):
        plan = parse_exec_plan(SAMPLE_PLAN)
        prompt2 = plan.chunks[1].session_prompt
        assert "다음 미완료 Chunk를 진행해" in prompt2


# ── Session Prompt edge cases ────────────────────────────────────────

class TestSessionPromptEdgeCases:
    """Tests for prompt extraction: multiple code blocks, no code block, empty."""

    def test_multiple_code_blocks_uses_first(self, tmp_path):
        md = textwrap.dedent("""\
        # Test Plan

        ## Metadata
        - project_dir: /tmp/test
        - status: pending

        ---

        ## Chunk 1: Test

        ### Completion Criteria
        - [ ] something

        ### Tasks
        - Task 1: Do it

        ### Session Prompt
        ```
        First code block — use this one.
        ```

        Some comment text.

        ```
        Second code block — ignore this.
        ```
        """)
        p = tmp_path / "plan.md"
        p.write_text(md)
        plan = parse_exec_plan(p)
        assert plan.chunks[0].session_prompt == "First code block — use this one."

    def test_no_code_block_uses_plain_text(self, tmp_path):
        md = textwrap.dedent("""\
        # Test Plan

        ## Metadata
        - project_dir: /tmp/test
        - status: pending

        ---

        ## Chunk 1: Test

        ### Completion Criteria
        - [ ] something

        ### Tasks
        - Task 1: Do it

        ### Session Prompt
        Plain text prompt without code block.
        Second line of prompt.
        """)
        p = tmp_path / "plan.md"
        p.write_text(md)
        plan = parse_exec_plan(p)
        assert "Plain text prompt" in plan.chunks[0].session_prompt
        assert "Second line" in plan.chunks[0].session_prompt

    def test_empty_prompt_raises(self, tmp_path):
        md = textwrap.dedent("""\
        # Test Plan

        ## Metadata
        - project_dir: /tmp/test
        - status: pending

        ---

        ## Chunk 1: Test

        ### Completion Criteria
        - [ ] something

        ### Tasks
        - Task 1: Do it

        ### Session Prompt

        ---

        ## Chunk 2: Another

        ### Completion Criteria
        - [ ] other thing

        ### Tasks
        - Task 2: Do that

        ### Session Prompt
        ```
        Some prompt here.
        ```
        """)
        p = tmp_path / "plan.md"
        p.write_text(md)
        with pytest.raises(ValueError, match="empty Session Prompt"):
            parse_exec_plan(p)


# ── Checkbox update ──────────────────────────────────────────────────

class TestUpdateCheckboxes:
    """Tests for in-place checkbox update in exec-plan files."""

    def test_update_all_checkboxes(self, tmp_path):
        import shutil
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, dest)

        update_checkboxes(dest, chunk_number=1)
        plan = parse_exec_plan(dest)
        for c in plan.chunks[0].completion_criteria:
            assert c.checked is True

    def test_update_specific_indices(self, tmp_path):
        import shutil
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, dest)

        update_checkboxes(dest, chunk_number=1, criteria_indices=[0, 2])
        plan = parse_exec_plan(dest)
        assert plan.chunks[0].completion_criteria[0].checked is True
        assert plan.chunks[0].completion_criteria[1].checked is False  # not updated
        assert plan.chunks[0].completion_criteria[2].checked is True

    def test_update_does_not_affect_other_chunks(self, tmp_path):
        import shutil
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, dest)

        update_checkboxes(dest, chunk_number=1)
        plan = parse_exec_plan(dest)
        # Chunk 3 criteria should still be unchecked
        for c in plan.chunks[2].completion_criteria:
            assert c.checked is False

    def test_all_checked_sets_completed_status(self, tmp_path):
        import shutil
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, dest)

        # Check all chunks
        update_checkboxes(dest, chunk_number=1)
        update_checkboxes(dest, chunk_number=3)
        plan = parse_exec_plan(dest)
        assert plan.chunks[0].status == "completed"
        assert plan.chunks[1].status == "completed"  # already was
        assert plan.chunks[2].status == "completed"
        assert plan.status == "completed"


# ── parse_exec_plan full integration ─────────────────────────────────

class TestParseExecPlanIntegration:
    """Full integration: parse → verify structure → update → re-parse."""

    def test_roundtrip(self, tmp_path):
        import shutil
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_PLAN, dest)

        # Parse
        plan = parse_exec_plan(dest)
        assert len(plan.chunks) == 3
        assert plan.chunks[0].status == "pending"

        # Update
        update_checkboxes(dest, chunk_number=1)

        # Re-parse
        plan2 = parse_exec_plan(dest)
        assert plan2.chunks[0].status == "completed"
        # Other chunks unchanged
        assert plan2.chunks[2].status == "pending"


# ── BUILD tag parsing ────────────────────────────────────────────────

class TestBuildTagParsing:
    """Tests for [BUILD] tag parsing and build_command field."""

    FIXTURE_BUILD = FIXTURE_DIR / "sample_exec_plan_build.md"

    def test_build_command_parsed_from_tag(self):
        """Verify [BUILD] tag is extracted into build_command field."""
        plan = parse_exec_plan(self.FIXTURE_BUILD)
        chunk1 = plan.chunks[0]

        # Criterion 0: no [BUILD] tag
        assert chunk1.completion_criteria[0].build_command == ""
        assert chunk1.completion_criteria[0].description == "vercel.json 파일 존재"

        # Criterion 1: [BUILD] npm run lint
        assert chunk1.completion_criteria[1].build_command == "npm run lint"
        assert chunk1.completion_criteria[1].description == "npm run lint"

        # Criterion 2: [BUILD] npm run build
        assert chunk1.completion_criteria[2].build_command == "npm run build"
        assert chunk1.completion_criteria[2].description == "npm run build"

    def test_build_command_empty_for_non_build(self):
        """Verify non-[BUILD] criteria have empty build_command."""
        plan = parse_exec_plan(self.FIXTURE_BUILD)
        chunk2 = plan.chunks[1]

        # Criterion 0: no [BUILD] tag
        assert chunk2.completion_criteria[0].build_command == ""
        assert chunk2.completion_criteria[0].description == "README.md 파일 존재"

    def test_checked_build_preserves_command(self):
        """Verify [BUILD] tag is preserved even when checked."""
        plan = parse_exec_plan(self.FIXTURE_BUILD)
        chunk2 = plan.chunks[1]

        # Criterion 1 is checked and has [BUILD] tag
        assert chunk2.completion_criteria[1].checked is True
        assert chunk2.completion_criteria[1].build_command == "npm run test"
        assert chunk2.completion_criteria[1].description == "npm run test"

    def test_build_command_with_complex_command(self):
        """Verify complex build commands with arguments are captured correctly."""
        plan = parse_exec_plan(self.FIXTURE_BUILD)
        chunk1 = plan.chunks[0]

        # Complex commands should be fully captured
        assert chunk1.completion_criteria[1].build_command == "npm run lint"
        assert chunk1.completion_criteria[2].build_command == "npm run build"

    def test_existing_fixture_backward_compatible(self):
        """Verify existing sample_exec_plan.md (no [BUILD] tags) still works."""
        plan = parse_exec_plan(SAMPLE_PLAN)
        chunk1 = plan.chunks[0]

        # All criteria should have empty build_command
        for criterion in chunk1.completion_criteria:
            assert criterion.build_command == ""
            assert criterion.description != ""


# ── update_checkboxes_by_description ──────────────────────────────────

class TestUpdateCheckboxesByDescription:
    """Tests for update_checkboxes_by_description() helper function."""

    def test_updates_matching_description(self, tmp_path):
        """Verify checkbox is updated when description matches exactly."""
        import shutil
        FIXTURE_BUILD = FIXTURE_DIR / "sample_exec_plan_build.md"
        dest = tmp_path / "plan.md"
        shutil.copy(FIXTURE_BUILD, dest)

        # Update by description
        update_checkboxes_by_description(dest, chunk_number=1, description="npm run lint")

        # Re-parse and verify
        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]

        # Criterion 1 should now be checked
        assert chunk1.completion_criteria[1].checked is True
        # Others unchanged
        assert chunk1.completion_criteria[0].checked is False
        assert chunk1.completion_criteria[2].checked is False

    def test_no_match_does_nothing(self, tmp_path):
        """Verify no changes when description doesn't match."""
        import shutil
        FIXTURE_BUILD = FIXTURE_DIR / "sample_exec_plan_build.md"
        dest = tmp_path / "plan.md"
        shutil.copy(FIXTURE_BUILD, dest)

        # Try to update with non-matching description
        update_checkboxes_by_description(dest, chunk_number=1, description="nonexistent criterion")

        # Re-parse and verify nothing changed
        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]

        for criterion in chunk1.completion_criteria:
            assert criterion.checked is False
