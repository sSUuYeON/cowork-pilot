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
