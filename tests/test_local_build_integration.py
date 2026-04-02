"""Integration tests for local build runner feature in exec-plan processing."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cowork_pilot.completion_detector import run_build_criteria
from cowork_pilot.config import HarnessConfig, ReviewConfig
from cowork_pilot.plan_parser import parse_exec_plan, update_checkboxes
from cowork_pilot.session_manager import (
    ChunkRetryState,
    build_session_prompt,
    process_chunk,
)


class TestLocalBuildIntegration:
    """End-to-end tests for local build execution in chunks."""

    def test_full_roundtrip(self, tmp_path: Path) -> None:
        """Test parsing, building, and checkpoint update cycle.

        1. Write an exec-plan with [BUILD] criteria to tmp_path
        2. Parse it with parse_exec_plan()
        3. Run run_build_criteria() with simple `true` command
        4. Verify checkboxes are updated to [x]
        5. Re-parse and confirm chunk status is "completed"
        """
        # Create sample exec-plan with [BUILD] criteria
        plan_file = tmp_path / "test_plan.md"
        plan_content = textwrap.dedent("""\
            # Test Build Plan

            ## Metadata
            - project_dir: {project_dir}
            - spec: docs/specs/test.md
            - created: 2026-04-02
            - status: pending

            ---

            ## Chunk 1: Build Test

            ### Completion Criteria
            - [ ] [BUILD] true
            - [ ] [BUILD] echo ok

            ### Tasks
            - Task 1: Run builds

            ### Session Prompt
            ```
            Complete the build tasks.
            ```
            """).format(project_dir=str(tmp_path))

        plan_file.write_text(plan_content)

        # Step 1: Parse the plan
        plan = parse_exec_plan(plan_file)
        assert len(plan.chunks) == 1
        chunk = plan.chunks[0]
        assert chunk.number == 1
        assert len(chunk.completion_criteria) == 2
        assert chunk.completion_criteria[0].build_command == "true"
        assert chunk.completion_criteria[1].build_command == "echo ok"
        assert chunk.status == "pending"
        assert not chunk.completion_criteria[0].checked
        assert not chunk.completion_criteria[1].checked

        # Step 2: Run build criteria
        status, detail = run_build_criteria(
            chunk,
            project_dir=str(tmp_path),
            plan_path=plan_file,
            timeout=30.0,
        )
        assert status == "PASSED"
        assert detail == ""

        # Step 3: Re-parse and verify checkboxes are updated
        plan_after = parse_exec_plan(plan_file)
        chunk_after = plan_after.chunks[0]
        assert chunk_after.completion_criteria[0].checked
        assert chunk_after.completion_criteria[1].checked
        assert chunk_after.status == "completed"

    def test_build_session_prompt_integration(self, tmp_path: Path) -> None:
        """Test that build_session_prompt injects VM notice and review instructions.

        1. Write exec-plan with [BUILD] criteria to tmp_path
        2. Parse it and get chunk with [BUILD] items
        3. Call build_session_prompt() with review_config enabled
        4. Verify prompt contains VM build notice ("VM에서 실행하지 마라")
        5. Verify prompt contains review instructions
        """
        # Create sample exec-plan with [BUILD] criteria
        plan_file = tmp_path / "test_plan.md"
        plan_content = textwrap.dedent("""\
            # Test Build Plan

            ## Metadata
            - project_dir: {project_dir}
            - spec: docs/specs/test.md
            - created: 2026-04-02
            - status: pending

            ---

            ## Chunk 1: Build with Review

            ### Completion Criteria
            - [ ] [BUILD] true
            - [ ] Code passes review

            ### Tasks
            - Task 1: Write code

            ### Session Prompt
            ```
            Implement the feature.
            ```
            """).format(project_dir=str(tmp_path))

        plan_file.write_text(plan_content)

        # Parse and get chunk
        plan = parse_exec_plan(plan_file)
        chunk = plan.chunks[0]

        # Build session prompt with review enabled
        review_config = ReviewConfig(enabled=True, skip_chunks=[])
        prompt = build_session_prompt(chunk, review_config=review_config)

        # Verify VM build notice is present
        assert "VM에서 실행하지 마라" in prompt
        assert "[BUILD]" in prompt or "Completion Criteria" in prompt

        # Verify review instructions are present
        assert "code-review" in prompt
        assert "chunk-complete" in prompt
        assert "리뷰" in prompt or "review" in prompt

    def test_process_chunk_build_then_verify(self, tmp_path: Path) -> None:
        """Test process_chunk workflow: build pass then verify/review cycle.

        1. Write exec-plan with mixed criteria: one [BUILD] and one regular
        2. First process_chunk call:
           - build_fn returns ("PASSED", "")
           - verify_fn mocked to simulate review/incomplete
           - Should return "INCOMPLETE"
        3. Manually mark all checkboxes as [x]
        4. Second process_chunk call:
           - verify_fn returns ("COMPLETED", "")
           - Should return "COMPLETED"
        """
        # Create sample exec-plan with mixed criteria
        plan_file = tmp_path / "test_plan.md"
        plan_content = textwrap.dedent("""\
            # Test Build Plan

            ## Metadata
            - project_dir: {project_dir}
            - spec: docs/specs/test.md
            - created: 2026-04-02
            - status: pending

            ---

            ## Chunk 1: Mixed Criteria

            ### Completion Criteria
            - [ ] [BUILD] true
            - [ ] Code review passed

            ### Tasks
            - Task 1: Implement

            ### Session Prompt
            ```
            Do the work.
            ```
            """).format(project_dir=str(tmp_path))

        plan_file.write_text(plan_content)

        # Parse the plan
        plan = parse_exec_plan(plan_file)
        chunk = plan.chunks[0]
        harness_config = HarnessConfig(build_timeout_seconds=30.0)
        retry_state = ChunkRetryState()

        # ── First process_chunk: build passes, but review needed ──
        def mock_build_fn(chunk_arg, project_dir, plan_path, timeout):
            """Mock build that succeeds."""
            return ("PASSED", "")

        def mock_verify_fn_incomplete(chunk_arg, harness_cfg, project_dir, plan_path=None):
            """Mock verify that indicates incomplete (needs review)."""
            return ("INCOMPLETE", "Code review pending")

        def mock_feedback_fn(feedback_text):
            """Mock feedback sender (no-op for test)."""
            pass

        # Re-parse fresh chunk for each call
        fresh_plan = parse_exec_plan(plan_file)
        fresh_chunk = fresh_plan.chunks[0]

        result1 = process_chunk(
            plan_file,
            fresh_chunk,
            harness_config,
            str(tmp_path),
            retry_state,
            verify_fn=mock_verify_fn_incomplete,
            feedback_fn=mock_feedback_fn,
            build_fn=mock_build_fn,
        )

        # After build pass, if build criteria exist, we expect INCOMPLETE
        # (asking for code-review/chunk-complete)
        assert result1 == "INCOMPLETE"

        # ── Manually mark all checkboxes as complete ──
        update_checkboxes(plan_file, chunk.number)

        # ── Second process_chunk: everything checked, verify returns COMPLETED ──
        def mock_verify_fn_completed(chunk_arg, harness_cfg, project_dir, plan_path=None):
            """Mock verify that indicates completed."""
            return ("COMPLETED", "")

        fresh_plan2 = parse_exec_plan(plan_file)
        fresh_chunk2 = fresh_plan2.chunks[0]

        result2 = process_chunk(
            plan_file,
            fresh_chunk2,
            harness_config,
            str(tmp_path),
            retry_state,
            verify_fn=mock_verify_fn_completed,
            feedback_fn=mock_feedback_fn,
            build_fn=mock_build_fn,
        )

        # Now everything is checked, verify returns COMPLETED → process_chunk returns COMPLETED
        assert result2 == "COMPLETED"

        # Verify the plan file has all checkboxes marked
        final_plan = parse_exec_plan(plan_file)
        final_chunk = final_plan.chunks[0]
        assert all(c.checked for c in final_chunk.completion_criteria)
        assert final_chunk.status == "completed"
