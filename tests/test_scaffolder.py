"""Tests for scaffolder — Brief → project directory structure."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cowork_pilot.brief_parser import Brief, Page, Entity, ArchDecision, Reference
from cowork_pilot.scaffolder import scaffold_project, slugify


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def minimal_brief() -> Brief:
    return Brief(
        name="todo-app",
        description="할 일 관리 앱",
        type="web-app",
        language="TypeScript",
        framework="Next.js",
    )


@pytest.fixture
def full_brief() -> Brief:
    return Brief(
        name="hype-app",
        description="팀원에게 칭찬을 보내는 소셜 앱",
        type="web-app",
        language="TypeScript",
        framework="Next.js",
        database="PostgreSQL",
        styling="Tailwind",
        package_manager="pnpm",
        pages=[
            Page(name="홈 피드", description="최근 하이프 목록", key_elements=["하이프 카드", "무한 스크롤"]),
            Page(name="하이프 보내기", description="팀원에게 칭찬 작성", key_elements=["팀원 검색", "텍스트 입력"]),
        ],
        entities=[
            Entity(name="User", fields=["id", "name", "email"], relations=["has_many Hype"]),
            Entity(name="Hype", fields=["id", "sender_id", "message"], relations=["belongs_to User"]),
        ],
        decisions=[
            ArchDecision(decision="Server Components 기본", rationale="번들 사이즈 최소화"),
        ],
        auth="Google OAuth",
        deployment="Vercel",
        non_goals=["실시간 알림"],
        references=[Reference(name="Next.js Docs", url="https://nextjs.org/docs")],
    )


# ── Tests ───────────────────────────────────────────────────────────

class TestSlugify:
    def test_korean(self):
        assert slugify("홈 피드") == "홈-피드"

    def test_english(self):
        assert slugify("Home Feed") == "home-feed"

    def test_special_chars(self):
        assert slugify("auth/login (v2)") == "auth-login-v2"

    def test_underscore_to_hyphen(self):
        assert slugify("my_page name") == "my-page-name"

    def test_underscore_only(self):
        assert slugify("hello_world") == "hello-world"


class TestScaffoldDirectories:
    """생성되는 디렉토리 구조 검증."""

    def test_creates_docs_structure(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        assert (tmp_path / "docs").is_dir()
        assert (tmp_path / "docs" / "design-docs").is_dir()
        assert (tmp_path / "docs" / "product-specs").is_dir()
        assert (tmp_path / "docs" / "exec-plans" / "active").is_dir()
        assert (tmp_path / "docs" / "exec-plans" / "completed").is_dir()
        assert (tmp_path / "docs" / "references").is_dir()
        assert (tmp_path / "docs" / "generated").is_dir()

    def test_creates_implementation_map_dir(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        assert (tmp_path / "docs" / "implementation-map").is_dir()

    def test_creates_planning_dir(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        assert (tmp_path / "docs" / "exec-plans" / "planning").is_dir()

    def test_creates_src_and_tests(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "tests").is_dir()


class TestScaffoldFiles:
    """생성되는 파일 검증."""

    def test_agents_md(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "AGENTS.md").read_text()
        assert "hype-app" in content
        assert "TypeScript" in content
        assert "Next.js" in content

    def test_architecture_md(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "ARCHITECTURE.md").read_text()
        assert "hype-app" in content
        assert "TypeScript" in content
        assert "<!-- GUIDE:" in content  # GUIDE 주석 포함 확인

    def test_docs_root_files(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        assert (tmp_path / "docs" / "QUALITY_SCORE.md").exists()
        assert (tmp_path / "docs" / "SECURITY.md").exists()
        assert (tmp_path / "docs" / "DESIGN_GUIDE.md").exists()
        # GUIDE 주석 포함 확인
        for fname in ["QUALITY_SCORE.md", "SECURITY.md", "DESIGN_GUIDE.md"]:
            content = (tmp_path / "docs" / fname).read_text()
            assert "<!-- GUIDE:" in content

    def test_design_guide_has_all_sections(self, tmp_path, full_brief):
        """DESIGN_GUIDE.md에 섹션 1~7이 모두 포함되어야 한다."""
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "docs" / "DESIGN_GUIDE.md").read_text()
        assert "## 1. 디자인 원칙" in content
        assert "## 2. 컬러/타이포그래피" in content
        assert "## 3. 컴포넌트 규칙" in content
        assert "## 4. 레퍼런스" in content
        assert "## 5. 레이아웃 시스템" in content
        assert "## 6. 스페이싱 체계" in content
        assert "## 7. 반응형 규칙" in content

    def test_design_guide_layout_section_has_required_keywords(self, tmp_path, full_brief):
        """레이아웃/스페이싱/반응형 GUIDE에 구체적 수치 관련 키워드가 있어야 한다."""
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "docs" / "DESIGN_GUIDE.md").read_text()
        # 레이아웃 시스템 — 브레이크포인트, max-width 등 구체적 키워드
        assert "브레이크포인트" in content
        assert "max-width" in content
        # 스페이싱 체계 — px값 관련
        assert "xs" in content and "xl" in content
        # 반응형 규칙 — 주관적 표현 금지 안내
        assert "주관적 표현 금지" in content

    def test_agents_has_implementation_map_section(self, tmp_path, full_brief):
        """AGENTS.md에 Implementation Map 섹션과 절대규칙이 포함되어야 한다."""
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "AGENTS.md").read_text()
        assert "## Implementation Map" in content
        assert "implementation-map/index.md" in content
        assert "## 절대 규칙: 코드를 예측하지 마라" in content
        # Directory Map에도 implementation-map 경로가 있어야 함
        assert "docs/implementation-map/" in content

    def test_writing_standards_in_agents(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        content = (tmp_path / "AGENTS.md").read_text()
        assert "## Writing Standards" in content
        assert "GUIDE 주석" in content

    def test_project_brief_preserved(self, tmp_path, full_brief):
        """스캐폴딩 전에 project-brief.md가 있으면 보존."""
        docs = tmp_path / "docs"
        docs.mkdir(parents=True)
        brief_file = docs / "project-brief.md"
        brief_file.write_text("# Original Brief\n")
        scaffold_project(full_brief, tmp_path)
        assert brief_file.read_text() == "# Original Brief\n"

    def test_design_docs(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        dd = tmp_path / "docs" / "design-docs"
        assert (dd / "index.md").exists()
        assert (dd / "core-beliefs.md").exists()
        assert (dd / "data-model.md").exists()
        assert (dd / "auth.md").exists()
        assert (dd / "deployment.md").exists()

    def test_product_specs(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        ps = tmp_path / "docs" / "product-specs"
        assert (ps / "index.md").exists()
        assert (ps / "홈-피드.md").exists()
        assert (ps / "하이프-보내기.md").exists()

    def test_exec_plan_generated(self, tmp_path, full_brief):
        scaffold_project(full_brief, tmp_path)
        plan = tmp_path / "docs" / "exec-plans" / "active" / "01-docs-setup.md"
        assert plan.exists()
        content = plan.read_text()
        assert "## Chunk 1:" in content
        assert "## Metadata" in content
        assert "### Session Prompt" in content

    def test_exec_plan_chunk2_includes_design_guide(self, tmp_path, full_brief):
        """docs-setup exec-plan의 Chunk 2가 DESIGN_GUIDE.md 작성을 포함해야 한다."""
        scaffold_project(full_brief, tmp_path)
        plan = tmp_path / "docs" / "exec-plans" / "active" / "01-docs-setup.md"
        content = plan.read_text()
        assert "DESIGN_GUIDE.md" in content
        assert "구체적인 수치" in content or "구체적 수치" in content

    def test_no_domain_docs_when_no_constraints(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        dd = tmp_path / "docs" / "design-docs"
        assert not (dd / "auth.md").exists()
        assert not (dd / "deployment.md").exists()


class TestScaffoldIdempotent:
    """기존 파일 덮어쓰지 않기."""

    def test_does_not_overwrite_existing(self, tmp_path, minimal_brief):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Custom AGENTS\n")
        scaffold_project(minimal_brief, tmp_path)
        # AGENTS.md는 덮어쓰지 않음 (이미 존재)
        assert agents.read_text() == "# Custom AGENTS\n"
