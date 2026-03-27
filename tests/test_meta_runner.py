"""Tests for meta_runner — Step 0~4 orchestration."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from cowork_pilot.config import Config, MetaConfig
from cowork_pilot.meta_runner import (
    build_brief_prompt,
    harness_config_from,
    run_meta,
    wait_for_brief_completion,
)


class TestBuildBriefPrompt:
    """브리프 채우기 프롬프트 생성."""

    def test_includes_description(self):
        mc = MetaConfig(initial_description="할 일 관리 앱 만들고 싶어")
        prompt = build_brief_prompt(mc)
        assert "할 일 관리 앱" in prompt

    def test_includes_template_sections(self):
        mc = MetaConfig(initial_description="test")
        prompt = build_brief_prompt(mc)
        assert "Overview" in prompt
        assert "Tech Stack" in prompt
        assert "필수" in prompt

    def test_resume_includes_existing_brief(self):
        mc = MetaConfig(initial_description="test")
        existing = "# Project Brief\n## 1. Overview\n- name: \"My App\"\n"
        prompt = build_brief_prompt(mc, existing_brief=existing)
        assert "이전에 부분적으로 채워진 브리프" in prompt
        assert "My App" in prompt
        assert "이어서 진행" in prompt

    def test_no_resume_without_existing_brief(self):
        mc = MetaConfig(initial_description="test")
        prompt = build_brief_prompt(mc)
        assert "이전에 부분적으로 채워진 브리프" not in prompt


class TestHarnessConfigFrom:
    """MetaConfig → HarnessConfig 변환."""

    def test_basic_conversion(self, tmp_path):
        mc = MetaConfig(project_dir=str(tmp_path))
        hc = harness_config_from(mc)
        assert hc.exec_plans_dir == "docs/exec-plans"

    def test_inherits_project_dir_for_exec_plans(self, tmp_path):
        mc = MetaConfig(project_dir=str(tmp_path))
        hc = harness_config_from(mc)
        assert hc.exec_plans_dir == "docs/exec-plans"


class TestWaitForBriefCompletion:
    """브리프 세션 완료 감지."""

    def test_returns_path_when_file_exists(self, tmp_path):
        """project-brief.md가 이미 존재하면 즉시 반환."""
        docs = tmp_path / "docs"
        docs.mkdir()
        brief_path = docs / "project-brief.md"
        brief_path.write_text("# Project Brief\n\n## 1. Overview\n- name: test\n")

        mc = MetaConfig(project_dir=str(tmp_path))
        jsonl_path = tmp_path / "fake.jsonl"
        jsonl_path.write_text("")

        result = wait_for_brief_completion(
            jsonl_path, mc, poll_interval=0.1, timeout=1.0,
        )
        assert result == brief_path

    def test_timeout_when_file_missing(self, tmp_path):
        """project-brief.md가 없으면 TimeoutError."""
        mc = MetaConfig(project_dir=str(tmp_path))
        jsonl_path = tmp_path / "fake.jsonl"
        jsonl_path.write_text("")

        (tmp_path / "docs").mkdir()

        with pytest.raises(TimeoutError):
            wait_for_brief_completion(
                jsonl_path, mc, poll_interval=0.1, timeout=0.3,
            )

    def test_detects_session_end_without_brief(self, tmp_path):
        """세션이 끝났는데 brief가 없으면 RuntimeError."""
        mc = MetaConfig(project_dir=str(tmp_path))
        (tmp_path / "docs").mkdir()

        jsonl_path = tmp_path / "session.jsonl"
        jsonl_path.write_text(json.dumps({"type": "summary"}) + "\n")

        with pytest.raises(RuntimeError, match="Brief session ended"):
            wait_for_brief_completion(
                jsonl_path, mc, poll_interval=0.1, timeout=1.0,
            )


class TestMetaResumeStep2:
    """Step 2 resume — skip when 01-docs-setup.md already in completed/."""

    def _make_project(self, tmp_path):
        """Create a project dir with complete brief + scaffolded structure."""
        project_dir = tmp_path / "project"
        docs = project_dir / "docs"
        docs.mkdir(parents=True)

        brief_path = docs / "project-brief.md"
        brief_path.write_text(textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "Test"
            - description: "Test project"
            - type: "cli"

            ## 2. Tech Stack
            - language: "python"
            - framework: "none"
        """))

        (project_dir / "AGENTS.md").write_text("# AGENTS\n")

        ep = docs / "exec-plans"
        (ep / "active").mkdir(parents=True)
        (ep / "completed").mkdir(parents=True)
        (ep / "planning").mkdir(parents=True)

        return project_dir, ep

    def test_step2_skip_when_completed(self, tmp_path):
        """completed/에 01-docs-setup.md가 있으면 run_harness 호출 안 됨."""
        project_dir, ep = self._make_project(tmp_path)
        (ep / "completed" / "01-docs-setup.md").write_text("# Done\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        with patch("cowork_pilot.main.run_harness") as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan", return_value=None), \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            run_meta(config, meta_config)
            mock_harness.assert_not_called()

    def test_step2_resume_when_active(self, tmp_path):
        """active/에 01-docs-setup.md가 있으면 run_harness 호출됨."""
        project_dir, ep = self._make_project(tmp_path)
        active_plan = ep / "active" / "01-docs-setup.md"
        active_plan.write_text("# In Progress\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        import shutil

        def fake_harness(*args, **kwargs):
            """Simulate run_harness completing: move active → completed."""
            if active_plan.exists():
                shutil.move(str(active_plan), str(ep / "completed" / active_plan.name))

        with patch("cowork_pilot.main.run_harness", side_effect=fake_harness) as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan", return_value=None), \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            run_meta(config, meta_config)
            mock_harness.assert_called()

    def test_harness_cfg_available_after_step2_skip(self, tmp_path):
        """Step 2 스킵 후에도 Step 4에서 harness_cfg 사용 가능 (NameError 없음)."""
        project_dir, ep = self._make_project(tmp_path)
        (ep / "completed" / "01-docs-setup.md").write_text("# Done\n")
        (ep / "planning" / "02-impl.md").write_text("# Plan\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        import shutil

        def fake_harness(*args, **kwargs):
            """Simulate run_harness: clear active/ plans."""
            for f in (ep / "active").glob("*.md"):
                shutil.move(str(f), str(ep / "completed" / f.name))

        with patch("cowork_pilot.main.run_harness", side_effect=fake_harness) as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan") as mock_promote, \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            promoted_path = ep / "active" / "02-impl.md"
            mock_promote.side_effect = [promoted_path, None]

            # This should NOT raise NameError for harness_cfg
            run_meta(config, meta_config)
            mock_harness.assert_called()
