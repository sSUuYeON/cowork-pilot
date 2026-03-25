"""Tests for brief_parser — Markdown brief → Brief dataclass."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cowork_pilot.brief_parser import Brief, Page, Entity, ArchDecision, Reference, parse_brief


# ── Fixtures ────────────────────────────────────────────────────────

MINIMAL_BRIEF = textwrap.dedent("""\
    # Project Brief

    ## 1. Overview
    - name: "todo-app"
    - description: "할 일 관리 앱"
    - type: "web-app"

    ## 2. Tech Stack
    - language: "TypeScript"
    - framework: "Next.js"
    - database: ""
    - styling: ""
    - package_manager: ""

    ## 3. Pages / Features

    ## 4. Data Model

    ## 5. Architecture Decisions

    ## 6. Constraints
    - auth: ""
    - deployment: ""
    - performance: ""
    - accessibility: ""
    - other: []

    ## 7. Non-Goals

    ## 8. References
""")

FULL_BRIEF = textwrap.dedent("""\
    # Project Brief

    ## 1. Overview
    - name: "hype-app"
    - description: "팀원에게 칭찬을 보내는 소셜 앱"
    - type: "web-app"

    ## 2. Tech Stack
    - language: "TypeScript"
    - framework: "Next.js"
    - database: "PostgreSQL"
    - styling: "Tailwind"
    - package_manager: "pnpm"

    ## 3. Pages / Features

    - page: "홈 피드"
      description: "최근 하이프 목록"
      key_elements: ["하이프 카드", "무한 스크롤"]

    - page: "하이프 보내기"
      description: "팀원에게 칭찬 작성"
      key_elements: ["팀원 검색", "텍스트 입력", "이모지 선택"]

    ## 4. Data Model

    - entity: "User"
      fields: ["id", "name", "email", "avatar_url"]
      relations: ["has_many Hype (sender)", "has_many Hype (receiver)"]

    - entity: "Hype"
      fields: ["id", "sender_id", "receiver_id", "message", "emoji", "created_at"]
      relations: ["belongs_to User (sender)", "belongs_to User (receiver)"]

    ## 5. Architecture Decisions

    - decision: "Server Components 기본, 인터랙션 필요한 곳만 Client Component"
      rationale: "번들 사이즈 최소화 + SEO"

    ## 6. Constraints
    - auth: "Google OAuth"
    - deployment: "Vercel"
    - performance: ""
    - accessibility: ""
    - other: []

    ## 7. Non-Goals

    - "실시간 알림 (v1에서는 제외)"
    - "모바일 네이티브 앱"

    ## 8. References

    - ref: "Next.js App Router Docs"
      url: "https://nextjs.org/docs/app"
      notes: "Server Components 참고"
""")


# ── Tests ───────────────────────────────────────────────────────────

class TestParseBriefMinimal:
    """최소 브리프 (필수 항목만) 파싱."""

    def test_overview_fields(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(MINIMAL_BRIEF)
        brief = parse_brief(p)
        assert brief.name == "todo-app"
        assert brief.description == "할 일 관리 앱"
        assert brief.type == "web-app"

    def test_tech_stack(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(MINIMAL_BRIEF)
        brief = parse_brief(p)
        assert brief.language == "TypeScript"
        assert brief.framework == "Next.js"
        assert brief.database == ""

    def test_empty_lists(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(MINIMAL_BRIEF)
        brief = parse_brief(p)
        assert brief.pages == []
        assert brief.entities == []
        assert brief.decisions == []
        assert brief.non_goals == []
        assert brief.references == []


class TestParseBriefFull:
    """완전한 브리프 파싱."""

    def test_pages(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert len(brief.pages) == 2
        assert brief.pages[0].name == "홈 피드"
        assert brief.pages[0].description == "최근 하이프 목록"
        assert "하이프 카드" in brief.pages[0].key_elements

    def test_entities(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert len(brief.entities) == 2
        assert brief.entities[0].name == "User"
        assert "id" in brief.entities[0].fields

    def test_decisions(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert len(brief.decisions) == 1
        assert "Server Components" in brief.decisions[0].decision

    def test_constraints(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert brief.auth == "Google OAuth"
        assert brief.deployment == "Vercel"

    def test_non_goals(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert len(brief.non_goals) == 2
        assert "실시간 알림" in brief.non_goals[0]

    def test_references(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        assert len(brief.references) == 1
        assert brief.references[0].name == "Next.js App Router Docs"
        assert "nextjs.org" in brief.references[0].url


class TestParseBriefEdgeCases:
    """엣지 케이스."""

    def test_missing_optional_sections(self, tmp_path):
        """선택 항목이 아예 없어도 파싱 성공."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "minimal"
            - description: "test"
            - type: "cli"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "Click"
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert brief.name == "minimal"
        assert brief.language == "Python"

    def test_missing_required_field_raises(self, tmp_path):
        """필수 항목 누락 시 ValueError."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - description: "test"
            - type: "cli"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "Click"
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        with pytest.raises(ValueError, match="name"):
            parse_brief(p)

    def test_tab_indented_children(self, tmp_path):
        """탭 들여쓰기도 child로 인식."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "tab-app"
            - description: "탭 테스트"
            - type: "web-app"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "FastAPI"

            ## 3. Pages / Features

            - page: "대시보드"
            \tdescription: "메인 대시보드"
            \tkey_elements: ["차트", "테이블"]
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert len(brief.pages) == 1
        assert brief.pages[0].description == "메인 대시보드"
        assert "차트" in brief.pages[0].key_elements

    def test_four_space_indented_children(self, tmp_path):
        """4칸 스페이스도 child로 인식."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "four-app"
            - description: "4칸 테스트"
            - type: "web-app"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "Django"

            ## 3. Pages / Features

            - page: "설정"
                description: "설정 페이지"
                key_elements: ["폼", "저장 버튼"]
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert len(brief.pages) == 1
        assert brief.pages[0].description == "설정 페이지"

    def test_quoted_and_unquoted_values(self, tmp_path):
        """따옴표 있든 없든 파싱."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: todo-app
            - description: "할 일 관리"
            - type: web-app

            ## 2. Tech Stack
            - language: Python
            - framework: "FastAPI"
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert brief.name == "todo-app"
        assert brief.description == "할 일 관리"
        assert brief.framework == "FastAPI"


class TestBriefDomainDocs:
    """auth/deployment 제약에 따른 도메인 문서 결정."""

    def test_domain_docs_with_auth(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        docs = brief.domain_doc_names()
        assert "auth.md" in docs

    def test_domain_docs_with_deployment(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(FULL_BRIEF)
        brief = parse_brief(p)
        docs = brief.domain_doc_names()
        assert "deployment.md" in docs

    def test_no_domain_docs_when_empty(self, tmp_path):
        p = tmp_path / "project-brief.md"
        p.write_text(MINIMAL_BRIEF)
        brief = parse_brief(p)
        docs = brief.domain_doc_names()
        assert docs == []
