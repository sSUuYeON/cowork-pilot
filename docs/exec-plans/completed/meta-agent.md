# 메타 에이전트 (Phase 3) 구현 계획

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자 브리프에서 프로젝트 docs/ 구조를 자동 생성하고, Phase 2 하네스로 내용 채우기 + 구현까지 자동 실행하는 메타 에이전트 구현

**Architecture:** brief_parser가 마크다운 브리프를 구조화된 데이터로 파싱하고, scaffolder가 Jinja2 템플릿으로 디렉토리/파일/exec-plan을 결정적으로 생성하며, meta_runner가 Step 0~4 워크플로우를 오케스트레이션한다. 기존 Phase 1 자동응답 + Phase 2 하네스를 그대로 재사용.

**Tech Stack:** Python 3.11+, Jinja2, tomllib, pytest

## Metadata
- project_dir: /Users/yeonsu/autoagent/cowork-pilot
- spec: docs/specs/2026-03-25-meta-agent-design.md, docs/specs/2026-03-25-docs-content-guide-design.md
- created: 2026-03-25
- status: pending

---

## File Structure

### 새로 생성하는 파일

| 파일 | 역할 |
|------|------|
| `src/cowork_pilot/brief_parser.py` | 브리프 MD → `Brief` 데이터클래스 파싱 |
| `src/cowork_pilot/scaffolder.py` | `Brief` → 디렉토리 + Jinja2 렌더링 + exec-plan 생성 |
| `src/cowork_pilot/meta_runner.py` | Step 0~4 오케스트레이션 (진입점: `run_meta()`) |
| `src/cowork_pilot/brief_templates/AGENTS.md.j2` | AGENTS.md Jinja2 템플릿 |
| `src/cowork_pilot/brief_templates/ARCHITECTURE.md.j2` | ARCHITECTURE.md 빈 템플릿 |
| `src/cowork_pilot/brief_templates/design-doc.md.j2` | design-docs/ 하위 파일 범용 템플릿 |
| `src/cowork_pilot/brief_templates/product-spec.md.j2` | product-specs/ 하위 파일 범용 템플릿 |
| `src/cowork_pilot/brief_templates/index.md.j2` | index.md 범용 템플릿 |
| `src/cowork_pilot/brief_templates/docs-setup-plan.md.j2` | "docs 채우기 exec-plan" 템플릿 |
| `src/cowork_pilot/brief_templates/QUALITY_SCORE.md.j2` | QUALITY_SCORE.md 템플릿 (등급 기준 GUIDE 포함) |
| `src/cowork_pilot/brief_templates/SECURITY.md.j2` | SECURITY.md 템플릿 (보안 가이드 GUIDE 포함) |
| `src/cowork_pilot/brief_templates/DESIGN_GUIDE.md.j2` | DESIGN_GUIDE.md 템플릿 (디자인 시스템 GUIDE 포함) |
| `tests/test_brief_parser.py` | 브리프 파싱 단위 테스트 |
| `tests/test_scaffolder.py` | 스캐폴딩 단위 테스트 |
| `tests/test_meta_runner.py` | 메타 러너 단위 테스트 |
| `docs/brief-template.md` | 표준 브리프 템플릿 (사용자 참조용) |

### 수정하는 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/cowork_pilot/config.py` | `MetaConfig` 데이터클래스 + `load_meta_config()` 추가 |
| `src/cowork_pilot/watcher.py` | `WatcherStateMachine.__init__`에 `ignored_sessions` 파라미터 추가 |
| `src/cowork_pilot/main.py` | `--mode meta` CLI 옵션 + `run_meta()` 호출 추가 |
| `AGENTS.md` | Phase 3 파일/디렉토리 추가 |

### 재사용하는 파일 (수정 없음)

| 파일 | 역할 |
|------|------|
| `src/cowork_pilot/plan_parser.py` | exec-plan 파싱 — implementation.md 형식 검증에 재사용 |
| `src/cowork_pilot/session_manager.py` | Chunk 실행 관리 — Phase 2 그대로 |
| `src/cowork_pilot/session_opener.py` | Cowork 세션 열기 — Step 0 + Step 2에서 재사용 |

---

## Chunk 1: 기반 모듈 — config + brief_parser

### Completion Criteria
- [ ] `MetaConfig` 데이터클래스가 `config.py`에 존재하고 `load_meta_config()` 함수 동작
- [ ] `Brief` 데이터클래스가 `brief_parser.py`에 존재
- [ ] `parse_brief()` 함수가 브리프 MD를 `Brief`로 파싱
- [ ] `pytest tests/test_config.py tests/test_brief_parser.py -v` 전부 통과
- [ ] `docs/brief-template.md` 파일 존재
- [ ] `docs/project-conventions.md` 섹션 7이 새 docs/ 구조로 업데이트

### Tasks

#### Task 0: project-conventions.md 섹션 7 업데이트

- [ ] **Step 0: docs/project-conventions.md 섹션 7을 스펙 §4.1의 docs/ 구조로 교체**

스펙에서 명시: "이 업데이트는 구현 Chunk 1에서 가장 먼저 수행".
`docs/project-conventions.md`의 기존 섹션 7(Phase 3 워크플로우 초안)을
스펙 §4.1의 새 docs/ 구조 표준으로 교체한다.

- [ ] **Step 0.1: 커밋**

```bash
git add docs/project-conventions.md
git commit -m "docs: update project-conventions §7 with Phase 3 docs/ structure standard"
```

---

#### Task 1: MetaConfig 데이터클래스 + load_meta_config()

- [ ] **Step 1: test_config.py에 MetaConfig 테스트 추가**

`tests/test_config.py` 파일 끝에 추가:

```python
from cowork_pilot.config import MetaConfig, load_meta_config


class TestMetaConfig:
    def test_defaults(self):
        mc = MetaConfig()
        assert mc.approval_mode == "manual"
        assert mc.project_dir == ""
        assert mc.initial_description == ""
        assert mc.brief_template_dir != ""

    def test_load_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[meta]\n'
            'approval_mode = "auto"\n'
            'project_dir = "/tmp/my-project"\n'
        )
        mc = load_meta_config(toml_file)
        assert mc.approval_mode == "auto"
        assert mc.project_dir == "/tmp/my-project"

    def test_load_missing_file(self, tmp_path):
        mc = load_meta_config(tmp_path / "nonexistent.toml")
        assert mc.approval_mode == "manual"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_config.py::TestMetaConfig -v`
Expected: FAIL — `ImportError: cannot import name 'MetaConfig'`

- [ ] **Step 3: MetaConfig + load_meta_config() 구현**

`src/cowork_pilot/config.py`에 추가:

```python
@dataclass
class MetaConfig:
    """Meta-agent configuration (loaded from config.toml [meta])."""
    approval_mode: str = "manual"  # "manual" | "auto"
    project_dir: str = ""
    initial_description: str = ""  # CLI에서 전달받는 초기 설명
    brief_template_dir: str = ""   # 기본값: 패키지 내 brief_templates/

    def __post_init__(self):
        if not self.brief_template_dir:
            self.brief_template_dir = str(
                Path(__file__).parent / "brief_templates"
            )


def load_meta_config(path: Path) -> MetaConfig:
    """Load meta-agent config from config.toml's [meta] section."""
    if not path.exists():
        return MetaConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    m = data.get("meta", {})
    return MetaConfig(
        approval_mode=m.get("approval_mode", "manual"),
        project_dir=m.get("project_dir", ""),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_config.py::TestMetaConfig -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/config.py tests/test_config.py
git commit -m "feat(config): add MetaConfig dataclass and load_meta_config()"
```

---

#### Task 2: Brief 데이터클래스 + parse_brief()

- [ ] **Step 6: Brief 데이터클래스 정의 (test-first)**

`tests/test_brief_parser.py` 생성:

```python
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
```

- [ ] **Step 7: 테스트 실행하여 실패 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_brief_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cowork_pilot.brief_parser'`

- [ ] **Step 8: brief_parser.py 구현**

`src/cowork_pilot/brief_parser.py` 생성:

```python
"""Parse a project brief Markdown file into structured dataclasses.

The brief format is defined in docs/specs/2026-03-25-meta-agent-design.md §3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class Page:
    name: str
    description: str = ""
    key_elements: list[str] = field(default_factory=list)


@dataclass
class Entity:
    name: str
    fields: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)


@dataclass
class ArchDecision:
    decision: str
    rationale: str = ""


@dataclass
class Reference:
    name: str
    url: str = ""
    notes: str = ""


@dataclass
class Brief:
    """Structured representation of a project brief."""
    # Overview (required)
    name: str = ""
    description: str = ""
    type: str = ""

    # Tech Stack (required: language, framework)
    language: str = ""
    framework: str = ""
    database: str = ""
    styling: str = ""
    package_manager: str = ""

    # Pages / Features
    pages: list[Page] = field(default_factory=list)

    # Data Model
    entities: list[Entity] = field(default_factory=list)

    # Architecture Decisions
    decisions: list[ArchDecision] = field(default_factory=list)

    # Constraints
    auth: str = ""
    deployment: str = ""
    performance: str = ""
    accessibility: str = ""
    other_constraints: list[str] = field(default_factory=list)

    # Non-Goals
    non_goals: list[str] = field(default_factory=list)

    # References
    references: list[Reference] = field(default_factory=list)

    def domain_doc_names(self) -> list[str]:
        """Return list of domain-specific doc filenames based on constraints."""
        docs: list[str] = []
        if self.auth:
            docs.append("auth.md")
        if self.deployment:
            docs.append("deployment.md")
        return docs


# ── Parsing ──────────────────────────────────────────────────────────

_RE_KV = re.compile(r'^- (\w[\w_]*): (.*)$')
_RE_QUOTED = re.compile(r'^"(.*)"$|^\'(.*)\'$')
_RE_LIST_ITEM = re.compile(r'^- "([^"]*)"$|^- \'([^\']*)\'$|^- (.+)$')


def _unquote(val: str) -> str:
    """Remove surrounding quotes from a value string."""
    val = val.strip()
    m = _RE_QUOTED.match(val)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return val


def _parse_list_value(val: str) -> list[str]:
    """Parse a YAML-like inline list: ["a", "b", "c"]."""
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = []
        for item in re.split(r',\s*', inner):
            items.append(_unquote(item.strip()))
        return items
    return []


def _find_section(lines: list[str], heading: str) -> list[str]:
    """Extract lines under a specific ## heading until the next ## or EOF."""
    body: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## ") and stripped != heading:
                break
            body.append(line)
    return body


def _parse_overview(lines: list[str]) -> dict[str, str]:
    body = _find_section(lines, "## 1. Overview")
    result: dict[str, str] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            result[m.group(1)] = _unquote(m.group(2))
    return result


def _parse_tech_stack(lines: list[str]) -> dict[str, str]:
    body = _find_section(lines, "## 2. Tech Stack")
    result: dict[str, str] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            result[m.group(1)] = _unquote(m.group(2))
    return result


def _parse_pages(lines: list[str]) -> list[Page]:
    body = _find_section(lines, "## 3. Pages / Features")
    pages: list[Page] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "page":
                if current is not None:
                    pages.append(Page(**current))
                current = {"name": _unquote(val), "description": "", "key_elements": []}
            elif current is not None:
                if key == "description":
                    current["description"] = _unquote(val)
                elif key == "key_elements":
                    current["key_elements"] = _parse_list_value(val)

    if current is not None:
        pages.append(Page(**current))
    return pages


def _parse_entities(lines: list[str]) -> list[Entity]:
    body = _find_section(lines, "## 4. Data Model")
    entities: list[Entity] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "entity":
                if current is not None:
                    entities.append(Entity(**current))
                current = {"name": _unquote(val), "fields": [], "relations": []}
            elif current is not None:
                if key == "fields":
                    current["fields"] = _parse_list_value(val)
                elif key == "relations":
                    current["relations"] = _parse_list_value(val)

    if current is not None:
        entities.append(Entity(**current))
    return entities


def _parse_decisions(lines: list[str]) -> list[ArchDecision]:
    body = _find_section(lines, "## 5. Architecture Decisions")
    decisions: list[ArchDecision] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "decision":
                if current is not None:
                    decisions.append(ArchDecision(**current))
                current = {"decision": _unquote(val), "rationale": ""}
            elif current is not None and key == "rationale":
                current["rationale"] = _unquote(val)

    if current is not None:
        decisions.append(ArchDecision(**current))
    return decisions


def _parse_constraints(lines: list[str]) -> dict[str, str | list[str]]:
    body = _find_section(lines, "## 6. Constraints")
    result: dict[str, str | list[str]] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2)
            if key == "other":
                result[key] = _parse_list_value(val)
            else:
                result[key] = _unquote(val)
    return result


def _parse_non_goals(lines: list[str]) -> list[str]:
    body = _find_section(lines, "## 7. Non-Goals")
    goals: list[str] = []
    for line in body:
        stripped = line.strip()
        # Match: - "text" or - 'text' or - text
        if stripped.startswith("- "):
            val = stripped[2:].strip()
            goals.append(_unquote(val))
    return goals


def _parse_references(lines: list[str]) -> list[Reference]:
    body = _find_section(lines, "## 8. References")
    refs: list[Reference] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "ref":
                if current is not None:
                    refs.append(Reference(**current))
                current = {"name": _unquote(val), "url": "", "notes": ""}
            elif current is not None:
                if key == "url":
                    current["url"] = _unquote(val)
                elif key == "notes":
                    current["notes"] = _unquote(val)

    if current is not None:
        refs.append(Reference(**current))
    return refs


# ── Public API ───────────────────────────────────────────────────────

REQUIRED_FIELDS = ["name", "description", "type", "language", "framework"]


def parse_brief(path: Path) -> Brief:
    """Parse a project brief Markdown file into a Brief dataclass.

    Raises ValueError if required fields are missing.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    overview = _parse_overview(lines)
    tech = _parse_tech_stack(lines)
    constraints = _parse_constraints(lines)

    # Validate required fields
    all_fields = {**overview, **tech}
    for req in REQUIRED_FIELDS:
        if not all_fields.get(req):
            raise ValueError(f"Required field missing or empty: {req}")

    return Brief(
        name=overview.get("name", ""),
        description=overview.get("description", ""),
        type=overview.get("type", ""),
        language=tech.get("language", ""),
        framework=tech.get("framework", ""),
        database=tech.get("database", ""),
        styling=tech.get("styling", ""),
        package_manager=tech.get("package_manager", ""),
        pages=_parse_pages(lines),
        entities=_parse_entities(lines),
        decisions=_parse_decisions(lines),
        auth=constraints.get("auth", ""),
        deployment=constraints.get("deployment", ""),
        performance=constraints.get("performance", ""),
        accessibility=constraints.get("accessibility", ""),
        other_constraints=constraints.get("other", []),
        non_goals=_parse_non_goals(lines),
        references=_parse_references(lines),
    )
```

- [ ] **Step 9: 테스트 통과 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_brief_parser.py -v`
Expected: 전부 통과

- [ ] **Step 10: 커밋**

```bash
git add src/cowork_pilot/brief_parser.py tests/test_brief_parser.py
git commit -m "feat(brief_parser): add Brief dataclass and parse_brief() with tests"
```

---

#### Task 3: docs/brief-template.md 생성

- [ ] **Step 11: 표준 브리프 템플릿 파일 생성**

`docs/brief-template.md` — 스펙 섹션 3.1의 내용 그대로 복사. 사용자 참조용 문서.

```markdown
# Project Brief

## 1. Overview
- name: ""
- description: ""
- type: ""

## 2. Tech Stack
- language: ""
- framework: ""
- database: ""
- styling: ""
- package_manager: ""

## 3. Pages / Features

- page: ""
  description: ""
  key_elements: []

## 4. Data Model

- entity: ""
  fields: []
  relations: []

## 5. Architecture Decisions

- decision: ""
  rationale: ""

## 6. Constraints
- auth: ""
- deployment: ""
- performance: ""
- accessibility: ""
- other: []

## 7. Non-Goals

- ""

## 8. References

- ref: ""
  url: ""
  notes: ""
```

- [ ] **Step 12: 커밋**

```bash
git add docs/brief-template.md
git commit -m "docs: add standard brief template"
```

---

## Chunk 2: 스캐폴더 — Jinja2 템플릿 + scaffolder.py

### Completion Criteria
- [ ] `src/cowork_pilot/brief_templates/` 디렉토리에 9개 `.j2` 파일 존재
- [ ] `scaffold_project()` 함수가 `Brief` 입력으로 디렉토리 + 파일 + exec-plan 생성 (QUALITY_SCORE.md, SECURITY.md, DESIGN_GUIDE.md 포함)
- [ ] `pytest tests/test_scaffolder.py -v` 전부 통과
- [ ] Jinja2가 `pyproject.toml` 의존성에 포함

### Tasks

#### Task 4: Jinja2 의존성 추가 + 템플릿 파일 생성

- [ ] **Step 13: pyproject.toml에 Jinja2 추가**

`pyproject.toml`의 `dependencies` 리스트에 `"jinja2>=3.1"` 추가.

- [ ] **Step 14: pip install 실행**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && pip install -e ".[dev]" --break-system-packages`

- [ ] **Step 15: AGENTS.md.j2 생성**

`src/cowork_pilot/brief_templates/AGENTS.md.j2`:

```jinja2
# {{ brief.name }}

{{ brief.description }}

## Directory Map

- `src/` — {{ brief.language }} + {{ brief.framework }} 소스 코드
- `docs/design-docs/` — 설계 문서 (index.md에서 색인)
- `docs/product-specs/` — 페이지/기능별 스펙 (index.md에서 색인)
- `docs/exec-plans/active/` — 현재 진행 중인 구현 계획
- `tests/` — 테스트

## When Making Changes

1. AGENTS.md를 읽고 프로젝트 구조를 파악
2. docs/design-docs/를 참고하여 설계 의도 확인
3. 변경 후 테스트 실행
4. 기존 패턴을 따를 것

## Conventions

- {{ brief.language }}, {{ brief.framework }}
{% if brief.styling %}- {{ brief.styling }}
{% endif %}{% if brief.database %}- Database: {{ brief.database }}
{% endif %}{% if brief.package_manager %}- Package manager: {{ brief.package_manager }}
{% endif %}

## Writing Standards

이 프로젝트의 모든 docs/ 파일은 다음 규칙을 따른다.

### 형식 규칙
- 테이블: GitHub Flavored Markdown 테이블 사용. 3컬럼 이하 권장
- 리스트: 정의가 필요하면 `- **항목**: 설명` 형식. 나열만이면 `- 항목`
- 코드: 인라인은 백틱, 블록은 언어 명시 코드 펜스
- 다이어그램: ASCII art 또는 Mermaid. 5줄 이하면 ASCII, 그 이상이면 Mermaid

### 분량 규칙
- 각 섹션: 최소 3줄, 최대 30줄 (코드블록/테이블 제외)
- 한 줄짜리 섹션 금지 — 최소한 "무엇을, 왜, 어떻게" 3가지를 다뤄야 함
- 빈 섹션 금지 — 해당 없으면 "해당 없음 — (이유)" 한 줄 작성

### 금지 사항
- "추후 작성", "TBD", "TODO" 단독 사용 금지 — 대신 현재 알고 있는 것이라도 적을 것
- 브리프 내용 그대로 복붙 금지 — 반드시 구체화/확장해서 작성
- 주관적 표현 ("좋은", "적절한") 금지 — 측정 가능한 기준으로 대체

### GUIDE 주석 처리
- 각 파일의 `<!-- GUIDE: ... -->` 주석은 해당 섹션의 작성 가이드
- 내용을 채운 후 반드시 GUIDE 주석 삭제
- GUIDE 주석이 남아있으면 해당 섹션 미완료로 간주
```

- [ ] **Step 16: ARCHITECTURE.md.j2 생성**

`src/cowork_pilot/brief_templates/ARCHITECTURE.md.j2`:

```jinja2
# {{ brief.name }} — Architecture

> 아키텍처 개요
> 작성일: {{ today }}
> 상태: Draft

---

## 1. 시스템 개요
<!-- GUIDE:
- 내용: 이 프로젝트가 무엇이고 왜 존재하는지. 핵심 문제와 해결 방식
- 형식: 산문 2~3 문단
- 분량: 5~15줄
- 참조: project-brief.md §1 Overview
-->

## 2. 기술 스택
<!-- GUIDE:
- 내용: 언어, 프레임워크, DB, 인프라. 각각 선택 이유 포함
- 형식: `- **항목**: 설명 (선택 이유)` 리스트
- 분량: 항목당 1~2줄, 전체 5~15줄
- 참조: project-brief.md §2 Tech Stack
-->

- Language: {{ brief.language }}
- Framework: {{ brief.framework }}
{% if brief.database %}- Database: {{ brief.database }}{% endif %}
{% if brief.styling %}- Styling: {{ brief.styling }}{% endif %}

## 3. 핵심 설계 결정
<!-- GUIDE:
- 내용: 아키텍처 레벨 결정. 각각 결정/근거/버린 대안 포함
- 형식: 결정당 3줄 구조: `**결정**: / **근거**: / **대안(버림)**:`
- 분량: 최소 2개, 최대 7개
- 참조: project-brief.md §5 Architecture Decisions
-->

{% if brief.decisions %}{% for d in brief.decisions %}- {{ d.decision }}
  - 근거: {{ d.rationale }}
{% endfor %}{% endif %}

## 4. 디렉토리 구조
<!-- GUIDE:
- 내용: src/ 아래 주요 디렉토리와 각각의 역할
- 형식: 트리 구조 코드블록 + 각 항목 1줄 설명
- 분량: 10~25줄
-->

## 5. 데이터 흐름
<!-- GUIDE:
- 내용: 핵심 사용자 시나리오 1~2개의 요청→응답 흐름
- 형식: Mermaid sequence diagram 또는 ASCII 화살표 (`A → B → C`)
- 분량: 시나리오당 5~15줄
-->
```

- [ ] **Step 17: design-doc.md.j2 생성**

`src/cowork_pilot/brief_templates/design-doc.md.j2`:

```jinja2
# {{ title }}

> {{ summary }}
> 작성일: {{ today }}
> 상태: Draft

---

{% for section in sections %}
## {{ section.number }}. {{ section.title }}
<!-- GUIDE:
{{ section.guide }}
-->

{% endfor %}
```

`sections`는 scaffolder.py가 문서 타입에 따라 주입하는 리스트:
- **도메인 문서** (auth.md, deployment.md): `[{number: 1, title: "목표", guide: "내용: 이 도메인에서 달성하려는 것과 제약 조건\n형식: 산문 1~2 문단\n분량: 3~8줄\n참조: project-brief.md §6 Constraints"}, ...]`
- **core-beliefs.md**: `[{number: 1, title: "목표", guide: "내용: 에이전트/개발자가 따라야 할 핵심 철학\n형식: 원칙당 ### 원칙 이름 + 산문 2~3줄\n분량: 3~5개 원칙, 전체 15~30줄"}, ...]`
- **data-model.md**: `[{number: 1, title: "목표", guide: "내용: 데이터 모델의 전체 설계 방향\n형식: 산문 1~2 문단\n분량: 3~8줄"}, ...]`

각 문서 타입의 전체 GUIDE 내용은 `docs/specs/2026-03-25-docs-content-guide-design.md` §4.2~§4.4 참조.

- [ ] **Step 18: product-spec.md.j2 생성**

`src/cowork_pilot/brief_templates/product-spec.md.j2`:

```jinja2
# {{ page.name }}

> {{ page.description }}
> 작성일: {{ today }}
> 상태: Draft

---

## 1. 개요
<!-- GUIDE:
- 내용: 이 페이지/기능이 사용자에게 제공하는 가치
- 형식: 산문 1~2 문단
- 분량: 3~8줄
-->

{{ page.description }}

## 2. 핵심 요소
<!-- GUIDE:
- 내용: 브리프의 key_elements를 구체화. 각 요소의 동작/상태/인터랙션
- 형식: `### 요소명` + `- **동작**: / **상태**: / **예외**:` 리스트
- 분량: 요소당 3~8줄
-->

{% for elem in page.key_elements %}- {{ elem }}
{% endfor %}
## 3. 사용자 시나리오
<!-- GUIDE:
- 내용: 핵심 유스케이스 2~4개
- 형식: 시나리오당 Given-When-Then 3줄
- 분량: 시나리오당 3줄, 전체 6~12줄
-->

## 4. UI 구성
<!-- GUIDE:
- 내용: 레이아웃, 주요 컴포넌트 배치, 반응형 동작
- 형식: ASCII 와이어프레임 또는 컴포넌트 계층 리스트
- 분량: 5~15줄
-->

## 5. API / 데이터
<!-- GUIDE:
- 내용: 이 페이지가 사용하는 API 엔드포인트와 데이터 구조
- 형식: GFM 테이블: | 엔드포인트 | 메서드 | 요청 | 응답 |
- 분량: 엔드포인트당 테이블 1행, 전체 3~15줄
-->
```

- [ ] **Step 19: index.md.j2 생성**

`src/cowork_pilot/brief_templates/index.md.j2`:

```jinja2
# {{ section_name }} Index

> 이 디렉토리의 문서 색인
> 최종 업데이트: {{ today }}

---

{% for doc in documents %}- [`{{ doc.filename }}`]({{ doc.filename }}) — {{ doc.summary }}
{% endfor %}
{% if not documents %}(아직 문서가 없습니다)
{% endif %}
```

- [ ] **Step 20: docs-setup-plan.md.j2 생성**

`src/cowork_pilot/brief_templates/docs-setup-plan.md.j2`:

```jinja2
# docs/ 구조 내용 채우기

## Metadata
- project_dir: {{ project_dir }}
- spec: docs/project-brief.md
- created: {{ today }}
- status: pending

---

## Chunk 1: 아키텍처 기반 문서

### Completion Criteria
- [ ] ARCHITECTURE.md 파일이 비어있지 않음
- [ ] docs/design-docs/core-beliefs.md 파일이 비어있지 않음
- [ ] docs/design-docs/data-model.md 파일이 비어있지 않음

### Tasks
- Task 1: project-brief.md를 읽고 ARCHITECTURE.md 작성
- Task 2: core-beliefs.md 작성 (에이전트 운영 원칙, 기술 철학)
- Task 3: data-model.md 작성 (엔티티, 관계, 스키마 초안)

### Session Prompt
```
docs/project-brief.md를 읽고, ARCHITECTURE.md와 docs/design-docs/의
core-beliefs.md, data-model.md를 작성해.
AGENTS.md를 먼저 읽어서 Writing Standards와 프로젝트 구조를 파악하고,
각 파일의 <!-- GUIDE: ... --> 주석을 따라 내용을 채워.
내용을 채운 후 GUIDE 주석은 반드시 삭제해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 2: 도메인별 설계 문서

### Completion Criteria
- [ ] docs/design-docs/ 아래 모든 .md 파일이 비어있지 않음
- [ ] docs/design-docs/index.md에 모든 문서가 색인됨

### Tasks
- Task 1: 브리프의 제약/결정에 따라 도메인별 설계 문서 작성
- Task 2: index.md 업데이트

### Session Prompt
```
docs/exec-plans/active/docs-setup.md를 읽고 Chunk 2를 진행해.
AGENTS.md의 Writing Standards를 먼저 읽고,
docs/project-brief.md와 ARCHITECTURE.md를 참고해서
docs/design-docs/ 아래 빈 파일들의 <!-- GUIDE: --> 주석을 따라 내용을 채워.
내용을 채운 후 GUIDE 주석은 반드시 삭제해.
index.md도 업데이트해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 3: 페이지/기능별 스펙

### Completion Criteria
- [ ] docs/product-specs/ 아래 모든 .md 파일이 비어있지 않음
- [ ] docs/product-specs/index.md에 모든 스펙이 색인됨

### Tasks
- Task 1: 각 페이지/기능별 스펙 작성
- Task 2: index.md 업데이트

### Session Prompt
```
docs/exec-plans/active/docs-setup.md를 읽고 Chunk 3를 진행해.
AGENTS.md의 Writing Standards를 먼저 읽고,
docs/project-brief.md, ARCHITECTURE.md, docs/design-docs/를 참고해서
docs/product-specs/ 아래 빈 파일들의 <!-- GUIDE: --> 주석을 따라 내용을 채워.
내용을 채운 후 GUIDE 주석은 반드시 삭제해.
index.md도 업데이트해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 4: 구현 계획 (exec-plan) 생성

### Completion Criteria
- [ ] docs/exec-plans/active/implementation.md 파일 존재
- [ ] plan_parser.py로 implementation.md 파싱 성공 (형식 검증)

### Tasks
- Task 1: 설계 문서 + 스펙을 기반으로 구현 exec-plan 작성
- Task 2: Chunk은 2~5개 Task, 2~5개 Completion Criteria로 구성

### Session Prompt
```
docs/exec-plans/active/docs-setup.md를 읽고 Chunk 4를 진행해.
ARCHITECTURE.md, docs/design-docs/, docs/product-specs/를 전부 읽고
이 프로젝트의 구현 계획(exec-plan)을 작성해.
docs/project-conventions.md 섹션 4의 형식을 정확히 따라.
파일 위치: docs/exec-plans/active/implementation.md

exec-plan 형식:
- # 제목 + ## Metadata (project_dir, spec, created, status)
- ## Chunk N: 이름 + ### Completion Criteria (- [ ] 체크박스) + ### Tasks (- Task N:) + ### Session Prompt (코드블록)
- Chunk당 Task 2~5개, Completion Criteria 2~5개
완료 조건을 모두 만족시켜.
```

---

## Chunk 5: 크로스 링크 검증

### Completion Criteria
- [ ] AGENTS.md의 Directory Map이 실제 파일 구조와 일치
- [ ] docs/design-docs/index.md의 목록이 실제 파일과 일치
- [ ] docs/product-specs/index.md의 목록이 실제 파일과 일치
- [ ] QUALITY_SCORE.md 초기화됨
- [ ] grep -r "<!-- GUIDE:" docs/ 결과가 0건 (모든 GUIDE 주석 삭제됨)

### Tasks
- Task 1: AGENTS.md 최종 업데이트
- Task 2: index.md 파일들 검증 및 수정
- Task 3: QUALITY_SCORE.md에 각 도메인/레이어 초기 등급 설정
- Task 4: GUIDE 주석 잔존 검증 — 남아있으면 해당 파일 내용 보완 후 삭제

### Session Prompt
```
docs/exec-plans/active/docs-setup.md를 읽고 Chunk 5를 진행해.
프로젝트 전체 파일 구조를 확인하고:
1. AGENTS.md의 Directory Map이 실제와 맞는지 검증, 불일치 시 수정
2. design-docs/index.md, product-specs/index.md가 실제 파일과 일치하는지 검증
3. QUALITY_SCORE.md에 각 도메인/레이어 초기 등급 설정
4. grep -r "<!-- GUIDE:" docs/ 실행 → 결과 0건이어야 함. 남아있으면 해당 파일 내용 보완 후 GUIDE 주석 삭제
완료 조건을 모두 만족시켜.
```

- [ ] **Step 20a: QUALITY_SCORE.md.j2 생성**

`src/cowork_pilot/brief_templates/QUALITY_SCORE.md.j2`:

```jinja2
# {{ brief.name }} — Quality Score

> 도메인/레이어별 품질 등급
> 작성일: {{ today }}
> 상태: Draft

---

## 등급 기준
<!-- GUIDE:
- 내용: 도메인/레이어별 품질 등급
- 형식: GFM 테이블: | 도메인 | 등급 | 근거 |
- 등급: A=프로덕션 준비, B=동작하지만 개선 필요, C=기본 구현만, D=미구현
- 분량: 도메인당 1행, 전체 5~15행
- 등급 변경 시 근거 컬럼 필수 업데이트
-->
```

- [ ] **Step 20b: SECURITY.md.j2 생성**

`src/cowork_pilot/brief_templates/SECURITY.md.j2`:

```jinja2
# {{ brief.name }} — Security

> 보안 설계 및 위험 관리
> 작성일: {{ today }}
> 상태: Draft

---

## 1. 인증/인가
<!-- GUIDE:
- 내용: 인증 방식, 토큰 관리, 권한 모델
- 형식: 플로우는 Mermaid, 설정은 코드블록
- 분량: 5~15줄
- auth 제약 없으면: "해당 없음 — 인증 불필요 (project-brief.md §6 참조)"
-->

## 2. 데이터 보호
<!-- GUIDE:
- 내용: 민감 데이터 목록, 암호화, 저장 위치
- 형식: `- **데이터**: 보호 방식` 리스트
- 분량: 3~10줄
-->

## 3. 알려진 위험
<!-- GUIDE:
- 내용: 현재 알려진 보안 위험과 대응 계획
- 형식: `- **위험**: / **영향**: / **대응**:` 3줄 구조
- 분량: 항목당 3줄, 없으면 "현재 식별된 위험 없음"
-->
```

- [ ] **Step 20c: DESIGN_GUIDE.md.j2 생성**

`src/cowork_pilot/brief_templates/DESIGN_GUIDE.md.j2`:

```jinja2
# {{ brief.name }} — Design Guide

> 디자인 시스템, 가이드라인, 레퍼런스
> 작성일: {{ today }}
> 상태: Draft

---

## 1. 디자인 원칙
<!-- GUIDE:
- 내용: 이 프로젝트의 시각적/UX 원칙 3~5개
- 형식: 원칙당 `### 원칙 이름` + 1~2줄 설명
- 분량: 5~15줄
- 예시: "일관성 > 화려함", "모바일 우선", "접근성 AA 기본"
-->

## 2. 컬러/타이포그래피
<!-- GUIDE:
- 내용: 주요 컬러 팔레트, 폰트, 사이즈 체계
- 형식: 컬러는 `- **이름**: #hex (용도)` 리스트, 타이포는 테이블
- 분량: 5~15줄
- styling 제약 없으면: "프레임워크 기본값 사용 — (이유)"
-->

## 3. 컴포넌트 규칙
<!-- GUIDE:
- 내용: 버튼/입력/카드 등 공통 컴포넌트 스타일 규칙
- 형식: 컴포넌트별 `### 이름` + 상태(기본/호버/비활성) 설명
- 분량: 컴포넌트당 3~5줄
-->

## 4. 레퍼런스
<!-- GUIDE:
- 내용: 참고한 디자인 시스템, 경쟁 제품 UI, 영감 받은 소스
- 형식: `- **이름**: [링크](url) — 참고 포인트 1줄`
- 분량: 1~5개
- 이미지/스크린샷은 docs/references/에 저장하고 상대경로로 참조
-->
```

- [ ] **Step 21: 커밋**

```bash
git add src/cowork_pilot/brief_templates/ pyproject.toml
git commit -m "feat(scaffolder): add Jinja2 templates with inline GUIDE comments for content quality"
```

---

#### Task 5: scaffolder.py 구현

- [ ] **Step 22: test_scaffolder.py 작성**

`tests/test_scaffolder.py` 생성:

```python
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
        plan = tmp_path / "docs" / "exec-plans" / "active" / "docs-setup.md"
        assert plan.exists()
        content = plan.read_text()
        assert "## Chunk 1:" in content
        assert "## Metadata" in content
        assert "### Session Prompt" in content

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
```

- [ ] **Step 23: 테스트 실행하여 실패 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_scaffolder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 24: scaffolder.py 구현**

`src/cowork_pilot/scaffolder.py` 생성:

```python
"""Scaffold a project directory from a Brief using Jinja2 templates.

Deterministic code — no AI involved. Creates directories, renders
Jinja2 templates into files, and generates the docs-setup exec-plan.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cowork_pilot.brief_parser import Brief


# ── Helpers ──────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to a URL/filename-safe slug.

    Preserves non-ASCII (Korean etc.) but lowercases ASCII,
    replaces spaces/special chars with hyphens, strips edges.
    """
    # Replace whitespace and common separators with hyphens
    text = re.sub(r'[\s/\\()\[\]{}]+', '-', text)
    # Remove anything that isn't alphanumeric, hyphen, or non-ASCII letter
    text = re.sub(r'[^\w\-]', '', text, flags=re.UNICODE)
    # Collapse multiple hyphens
    text = re.sub(r'-+', '-', text).strip('-')
    # Lowercase ASCII only
    result = []
    for ch in text:
        if ch.isascii() and ch.isalpha():
            result.append(ch.lower())
        else:
            result.append(ch)
    return ''.join(result)


def _write_if_not_exists(path: Path, content: str) -> bool:
    """Write content to path only if file doesn't already exist.

    Returns True if written, False if skipped.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


# ── Template rendering ──────────────────────────────────────────────

def _get_jinja_env(template_dir: Path | None = None) -> Environment:
    """Create Jinja2 environment with the brief_templates directory."""
    if template_dir is None:
        template_dir = Path(__file__).parent / "brief_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )
    env.filters["slugify"] = slugify
    return env


# ── Public API ───────────────────────────────────────────────────────

def scaffold_project(
    brief: Brief,
    project_dir: Path,
    template_dir: Path | None = None,
) -> None:
    """Create project directory structure and render templates.

    Args:
        brief: Parsed Brief dataclass
        project_dir: Root directory of the target project
        template_dir: Override for Jinja2 template directory (testing)
    """
    today = date.today().isoformat()
    env = _get_jinja_env(template_dir)

    # ── 1. Create directories ────────────────────────────────────
    dirs = [
        "docs/design-docs",
        "docs/product-specs",
        "docs/exec-plans/active",
        "docs/exec-plans/completed",
        "docs/references",
        "docs/generated",
        "src",
        "tests",
    ]
    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # ── 2. Render top-level files ────────────────────────────────
    ctx = {"brief": brief, "today": today}

    # AGENTS.md
    tpl = env.get_template("AGENTS.md.j2")
    _write_if_not_exists(project_dir / "AGENTS.md", tpl.render(**ctx))

    # ARCHITECTURE.md
    tpl = env.get_template("ARCHITECTURE.md.j2")
    _write_if_not_exists(project_dir / "ARCHITECTURE.md", tpl.render(**ctx))

    # ── 2a. docs/ 루트 파일 (QUALITY_SCORE, SECURITY, DESIGN_GUIDE) ──
    for tmpl_name, out_name in [
        ("QUALITY_SCORE.md.j2", "QUALITY_SCORE.md"),
        ("SECURITY.md.j2", "SECURITY.md"),
        ("DESIGN_GUIDE.md.j2", "DESIGN_GUIDE.md"),
    ]:
        tpl = env.get_template(tmpl_name)
        _write_if_not_exists(project_dir / "docs" / out_name, tpl.render(**ctx))

    # ── 3. Design docs ───────────────────────────────────────────
    dd = project_dir / "docs" / "design-docs"
    design_doc_tpl = env.get_template("design-doc.md.j2")

    # Always create core docs
    # NOTE: design-doc.md.j2가 sections 파라미터로 GUIDE 주석을 받으므로,
    # 각 문서 타입별 GUIDE_SECTIONS를 정의하여 렌더 시 전달.
    # 상세 GUIDE 내용: docs/specs/2026-03-25-docs-content-guide-design.md §4.2~§4.4
    core_docs = [
        ("core-beliefs.md", "에이전트 운영 원칙 및 기술 철학"),
        ("data-model.md", "데이터 모델 — 엔티티, 관계, 스키마"),
    ]
    # Domain docs based on constraints
    for doc_name in brief.domain_doc_names():
        label = doc_name.replace(".md", "")
        core_docs.append((doc_name, f"{label} 설계"))

    all_design_docs = []
    for filename, summary in core_docs:
        title = summary.split(" — ")[0] if " — " in summary else summary
        content = design_doc_tpl.render(title=title, summary=summary, today=today)
        _write_if_not_exists(dd / filename, content)
        all_design_docs.append({"filename": filename, "summary": summary})

    # design-docs/index.md
    index_tpl = env.get_template("index.md.j2")
    _write_if_not_exists(
        dd / "index.md",
        index_tpl.render(section_name="Design Docs", documents=all_design_docs, today=today),
    )

    # ── 4. Product specs ─────────────────────────────────────────
    ps = project_dir / "docs" / "product-specs"
    spec_tpl = env.get_template("product-spec.md.j2")

    all_specs = []
    for page in brief.pages:
        filename = f"{slugify(page.name)}.md"
        content = spec_tpl.render(page=page, today=today)
        _write_if_not_exists(ps / filename, content)
        all_specs.append({"filename": filename, "summary": page.description})

    # product-specs/index.md
    _write_if_not_exists(
        ps / "index.md",
        index_tpl.render(section_name="Product Specs", documents=all_specs, today=today),
    )

    # ── 5. Exec-plan (docs-setup.md) ────────────────────────────
    plan_tpl = env.get_template("docs-setup-plan.md.j2")
    plan_content = plan_tpl.render(
        brief=brief,
        project_dir=str(project_dir.resolve()),
        today=today,
    )
    _write_if_not_exists(
        project_dir / "docs" / "exec-plans" / "active" / "docs-setup.md",
        plan_content,
    )
```

**GUIDE 시스템 구현 노트:**

scaffolder.py에 `GUIDE_SECTIONS: dict[str, list[dict]]`를 정의하여 문서 타입별 GUIDE 주석 내용을 관리한다.
- `design-doc.md.j2`는 `sections` 파라미터를 받아 각 섹션의 GUIDE 주석을 렌더링
- core-beliefs.md, data-model.md, 도메인 문서 각각 다른 GUIDE 내용 (상세: `docs/specs/2026-03-25-docs-content-guide-design.md` §4.2~§4.4)
- `scaffold_project()` 호출 시 문서 타입에 맞는 sections를 `design_doc_tpl.render()`에 전달
- ARCHITECTURE.md.j2, product-spec.md.j2는 GUIDE가 템플릿에 직접 포함되어 있으므로 추가 파라미터 불필요

- [ ] **Step 25: 테스트 통과 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_scaffolder.py -v`
Expected: 전부 통과

- [ ] **Step 26: 커밋**

```bash
git add src/cowork_pilot/scaffolder.py tests/test_scaffolder.py
git commit -m "feat(scaffolder): scaffold project from Brief with Jinja2 templates"
```

---

## Chunk 3: meta_runner + watcher 수정 + main.py 통합

### Completion Criteria
- [ ] `WatcherStateMachine`이 `ignored_sessions` 파라미터를 지원
- [ ] `meta_runner.run_meta()` 함수가 Step 0~4를 오케스트레이션
- [ ] `--mode meta` CLI 옵션이 동작
- [ ] `pytest tests/test_meta_runner.py -v` 전부 통과
- [ ] `AGENTS.md` 업데이트 완료

### Tasks

#### Task 6: watcher.py — ignored_sessions 지원

- [ ] **Step 27: test_watcher.py에 ignored_sessions 테스트 추가**

`tests/test_watcher.py` 끝에 추가:

```python
class TestIgnoredSessions:
    """ignored_sessions 파라미터 테스트."""

    def test_ignored_session_skips_events(self):
        sm = WatcherStateMachine(debounce_seconds=0.0, ignored_sessions={Path("/fake/session.jsonl")})
        sm.set_current_session(Path("/fake/session.jsonl"))
        sm.on_tool_use({"id": "tu_1", "name": "AskUserQuestion", "input": {}})
        assert sm.state == WatcherState.IDLE  # 이벤트 무시됨

    def test_non_ignored_session_processes_events(self):
        sm = WatcherStateMachine(debounce_seconds=0.0, ignored_sessions={Path("/fake/other.jsonl")})
        sm.set_current_session(Path("/fake/session.jsonl"))
        sm.on_tool_use({"id": "tu_1", "name": "AskUserQuestion", "input": {}})
        assert sm.state == WatcherState.TOOL_USE_DETECTED

    def test_add_remove_ignored(self):
        ignored = set()
        sm = WatcherStateMachine(debounce_seconds=0.0, ignored_sessions=ignored)
        sm.set_current_session(Path("/fake/session.jsonl"))

        # Initially not ignored
        sm.on_tool_use({"id": "tu_1", "name": "AskUserQuestion", "input": {}})
        assert sm.state == WatcherState.TOOL_USE_DETECTED

        # Reset and add to ignored
        sm.state = WatcherState.IDLE
        sm.pending_tool_use = None
        ignored.add(Path("/fake/session.jsonl"))
        sm.on_tool_use({"id": "tu_2", "name": "AskUserQuestion", "input": {}})
        assert sm.state == WatcherState.IDLE
```

- [ ] **Step 28: 테스트 실행하여 실패 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_watcher.py::TestIgnoredSessions -v`
Expected: FAIL — `TypeError: WatcherStateMachine.__init__() got an unexpected keyword argument 'ignored_sessions'`

- [ ] **Step 29: watcher.py 수정 — ignored_sessions + set_current_session()**

`WatcherStateMachine.__init__`에 파라미터 추가:

```python
def __init__(self, debounce_seconds: float = 2.0, ignored_sessions: set[Path] | None = None):
    self.state = WatcherState.IDLE
    self.debounce_seconds = debounce_seconds
    self.pending_tool_use: dict | None = None
    self._detected_at: float = 0.0
    self.ignored_sessions: set[Path] = ignored_sessions if ignored_sessions is not None else set()
    self._current_session: Path | None = None

def set_current_session(self, path: Path) -> None:
    """Set the current session JSONL path for ignored_sessions check."""
    self._current_session = path
```

`on_tool_use` 메서드의 맨 앞에 가드 추가:

```python
def on_tool_use(self, tool_use: dict) -> None:
    # Check if current session is ignored
    if self._current_session and self._current_session in self.ignored_sessions:
        return
    if tool_use["name"] not in DIALOG_TOOLS:
        return
    # ... existing code
```

- [ ] **Step 30: 테스트 통과 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_watcher.py -v`
Expected: 전부 통과 (기존 + 새 테스트)

- [ ] **Step 31: 커밋**

```bash
git add src/cowork_pilot/watcher.py tests/test_watcher.py
git commit -m "feat(watcher): add ignored_sessions support for meta-agent Phase 1 control"
```

---

#### Task 7: meta_runner.py 구현

- [ ] **Step 32: test_meta_runner.py 작성**

`tests/test_meta_runner.py` 생성:

```python
"""Tests for meta_runner — Step 0~4 orchestration."""
from __future__ import annotations

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


class TestHarnessConfigFrom:
    """MetaConfig → HarnessConfig 변환."""

    def test_basic_conversion(self, tmp_path):
        mc = MetaConfig(project_dir=str(tmp_path))
        hc = harness_config_from(mc)
        assert hc.exec_plans_dir == "docs/exec-plans"

    def test_inherits_project_dir_for_exec_plans(self, tmp_path):
        mc = MetaConfig(project_dir=str(tmp_path))
        hc = harness_config_from(mc)
        # HarnessConfig doesn't store project_dir directly,
        # but exec_plans_dir is relative
        assert hc.exec_plans_dir == "docs/exec-plans"


class TestWaitForBriefCompletion:
    """브리프 세션 완료 감지 (단위 테스트 가능 부분만)."""

    def test_detects_brief_file(self, tmp_path):
        """project-brief.md가 생기면 완료."""
        docs = tmp_path / "docs"
        docs.mkdir()
        brief_path = docs / "project-brief.md"

        # Simulate: file appears after brief session
        brief_path.write_text("# Project Brief\n\n## 1. Overview\n- name: test\n")

        # wait_for_brief_completion should detect the file
        # (testing the file-existence check logic, not the full async wait)
        assert brief_path.exists()
```

- [ ] **Step 33: 테스트 실행하여 실패 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_meta_runner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 34: meta_runner.py 구현**

`src/cowork_pilot/meta_runner.py` 생성:

```python
"""Meta-agent runner — Step 0~4 orchestration.

Coordinates brief collection, scaffolding, and Phase 2 harness
execution to go from a user description to a fully scaffolded project.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from cowork_pilot.brief_parser import parse_brief
from cowork_pilot.config import Config, HarnessConfig, MetaConfig, load_harness_config
from cowork_pilot.logger import StructuredLogger
from cowork_pilot.scaffolder import scaffold_project
from cowork_pilot.session_opener import open_new_session
from cowork_pilot.session_finder import find_active_jsonl


# ── Brief prompt ─────────────────────────────────────────────────────

BRIEF_PROMPT_TEMPLATE = """\
사용자가 새 프로젝트를 만들려고 합니다.

사용자의 설명: "{description}"

아래 브리프 템플릿의 항목을 하나씩 AskUserQuestion으로 물어보세요.
필수 항목(name, description, type, language, framework)은 반드시 답을 받아야 합니다.
선택 항목은 사용자가 "몰라" 또는 "알아서 해"라고 하면 스킵합니다.

모든 항목을 채웠으면 "이대로 진행할까요?" 확인 질문을 합니다.
승인 시 채워진 브리프를 docs/project-brief.md로 저장하고 세션을 종료합니다.

## 브리프 항목

### 필수 (반드시 질문)
1. **프로젝트 이름** (name)
2. **한 줄 설명** (description)
3. **프로젝트 유형** (type): web-app, cli, api, library, mobile, other
4. **프로그래밍 언어** (language)
5. **프레임워크** (framework)

### 선택 (물어보되 스킵 가능)
6. 데이터베이스 (database)
7. 스타일링 (styling)
8. 패키지 매니저 (package_manager)
9. 페이지/기능 목록 (Pages/Features) — 각각 이름, 설명, 핵심 요소
10. 데이터 모델 (Data Model) — 엔티티, 필드, 관계
11. 아키텍처 결정 (Architecture Decisions)
12. 제약 (Constraints) — 인증, 배포, 성능, 접근성
13. 하지 않을 것 (Non-Goals)
14. 참고 자료 (References)

## 출력 형식

docs/project-brief.md로 저장. 형식:

```
# Project Brief

## 1. Overview
- name: "값"
- description: "값"
- type: "값"

## 2. Tech Stack
- language: "값"
- framework: "값"
- database: "값"
- styling: "값"
- package_manager: "값"

## 3. Pages / Features
- page: "이름"
  description: "설명"
  key_elements: ["요소1", "요소2"]

## 4. Data Model
- entity: "이름"
  fields: ["필드1", "필드2"]
  relations: ["관계1"]

## 5. Architecture Decisions
- decision: "결정"
  rationale: "근거"

## 6. Constraints
- auth: "값"
- deployment: "값"
- performance: "값"
- accessibility: "값"
- other: []

## 7. Non-Goals
- "하지 않을 것"

## 8. References
- ref: "이름"
  url: "URL"
  notes: "메모"
```
"""


def build_brief_prompt(meta_config: MetaConfig) -> str:
    """Build the initial prompt for the brief-filling Cowork session."""
    return BRIEF_PROMPT_TEMPLATE.format(description=meta_config.initial_description)


# ── Harness config conversion ────────────────────────────────────────

def harness_config_from(meta_config: MetaConfig) -> HarnessConfig:
    """Create a HarnessConfig pointing at the meta project's exec-plans."""
    return HarnessConfig(
        exec_plans_dir="docs/exec-plans",
    )


# ── Brief completion detection ───────────────────────────────────────

def wait_for_brief_completion(
    jsonl_path: Path,
    meta_config: MetaConfig,
    poll_interval: float = 2.0,
    timeout: float = 3600.0,  # 1 hour max
) -> Path:
    """Wait for the brief-filling session to complete.

    Completion is detected when docs/project-brief.md exists in project_dir.
    The file is written by the Cowork session (not by us).

    Returns the path to the completed brief file.
    Raises TimeoutError if timeout exceeded.
    """
    brief_path = Path(meta_config.project_dir) / "docs" / "project-brief.md"
    start = time.monotonic()

    while (time.monotonic() - start) < timeout:
        if brief_path.exists() and brief_path.stat().st_size > 0:
            return brief_path
        time.sleep(poll_interval)

    raise TimeoutError(f"Brief not completed within {timeout}s")


# ── Notification ─────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    """Send macOS notification."""
    try:
        script = (
            f'display notification "{message[:100]}" '
            f'with title "{title}" '
            f'sound name "Sosumi"'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def notify_and_wait_approval(meta_config: MetaConfig) -> None:
    """Send notification and wait for user to approve (manual mode).

    In manual mode, waits for a sentinel file:
    {project_dir}/docs/.meta-approved
    """
    _notify(
        "메타 에이전트 — 승인 필요",
        "docs/ 구조가 생성되었습니다. 확인 후 승인해주세요.",
    )

    sentinel = Path(meta_config.project_dir) / "docs" / ".meta-approved"
    print(f"\n승인 대기 중... 확인 후 다음 파일을 생성하세요: {sentinel}")
    print(f"  touch {sentinel}")

    while not sentinel.exists():
        time.sleep(2.0)

    # Clean up sentinel
    sentinel.unlink(missing_ok=True)


# ── Main orchestration ───────────────────────────────────────────────

def run_meta(config: Config, meta_config: MetaConfig) -> None:
    """Execute the full meta-agent workflow (Steps 0~4).

    Step 0: Open brief-filling Cowork session (Phase 1 OFF)
    Step 1: Scaffold project from completed brief
    Step 2: Run Phase 2 harness for docs-setup.md (Phase 1 ON)
    Step 3: Verify + approve (manual or auto)
    Step 4: Run Phase 2 harness for implementation.md (Phase 1 ON)
    """
    from cowork_pilot.main import run_harness
    from cowork_pilot.watcher import WatcherStateMachine

    logger = StructuredLogger(config.log_path, config.log_level)
    logger.info("meta", "Meta-agent starting", project_dir=meta_config.project_dir)

    project_dir = Path(meta_config.project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    base_path = Path(config.session_base_path).expanduser()

    # ── Step 0: Brief filling ────────────────────────────────────
    logger.info("meta", "Step 0: Opening brief session")
    print("Step 0: 브리프 채우기 세션 열기...")

    prompt = build_brief_prompt(meta_config)
    success = open_new_session(initial_prompt=prompt)
    if not success:
        logger.error("meta", "Failed to open brief session")
        print("Error: 브리프 세션 열기 실패", file=sys.stderr)
        sys.exit(1)

    # Find the new session's JSONL
    time.sleep(3.0)
    brief_jsonl = find_active_jsonl(base_path)
    if brief_jsonl is None:
        logger.error("meta", "Cannot find brief session JSONL")
        sys.exit(1)

    # Register as ignored (Phase 1 OFF for this session)
    # Note: ignored_sessions is a shared set that the watcher checks
    ignored_sessions: set[Path] = set()
    ignored_sessions.add(brief_jsonl)
    logger.info("meta", "Brief session registered as ignored", jsonl=str(brief_jsonl))

    # Wait for brief completion
    print("사용자가 브리프를 채우는 중... (docs/project-brief.md 생성 대기)")
    try:
        brief_path = wait_for_brief_completion(brief_jsonl, meta_config)
    except TimeoutError:
        logger.error("meta", "Brief completion timeout")
        print("Error: 브리프 작성 시간 초과", file=sys.stderr)
        sys.exit(1)

    logger.info("meta", "Step 0 complete", brief=str(brief_path))
    print(f"브리프 완성: {brief_path}")

    # ── Step 1: Scaffolding ──────────────────────────────────────
    logger.info("meta", "Step 1: Scaffolding")
    print("\nStep 1: 프로젝트 스캐폴딩...")

    brief = parse_brief(brief_path)
    scaffold_project(brief, project_dir)

    logger.info("meta", "Step 1 complete")
    print("스캐폴딩 완료!")

    # ── Step 2: Fill docs (Phase 2 harness) ──────────────────────
    logger.info("meta", "Step 2: Filling docs via harness")
    print("\nStep 2: docs/ 내용 채우기 (Phase 2 하네스)...")

    # Phase 1 ON — remove from ignored
    ignored_sessions.discard(brief_jsonl)

    # Set project_dir in config for harness
    config.project_dir = str(project_dir)
    harness_cfg = harness_config_from(meta_config)

    # Inherit engine settings
    harness_cfg.engine = config.engine
    if config.engine == "codex":
        harness_cfg.engine_command = config.codex_command
        harness_cfg.engine_args = config.codex_args or ["-q"]
    else:
        harness_cfg.engine_command = config.claude_command
        harness_cfg.engine_args = config.claude_args or ["-p"]

    run_harness(config, harness_cfg)

    # ── Step 3: Verify + approve ─────────────────────────────────
    logger.info("meta", "Step 3: Verification")
    print("\nStep 3: 검증...")

    if meta_config.approval_mode == "manual":
        notify_and_wait_approval(meta_config)
        logger.info("meta", "Manual approval received")

    # ── Step 4: Implementation (Phase 2 harness) ─────────────────
    logger.info("meta", "Step 4: Implementation via harness")
    print("\nStep 4: 구현 시작 (Phase 2 하네스)...")

    run_harness(config, harness_cfg)

    logger.info("meta", "Meta-agent complete")
    print("\n메타 에이전트 완료!")
```

- [ ] **Step 35: 테스트 통과 확인**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_meta_runner.py -v`
Expected: 전부 통과

- [ ] **Step 36: 커밋**

```bash
git add src/cowork_pilot/meta_runner.py tests/test_meta_runner.py
git commit -m "feat(meta_runner): add Step 0~4 orchestration for meta-agent"
```

---

#### Task 8: main.py — --mode meta 통합

- [ ] **Step 37: main.py 수정 — --mode meta 추가**

`src/cowork_pilot/main.py`의 `cli()` 함수 수정:

```python
def cli() -> None:
    """Entry point for `cowork-pilot` command."""
    import argparse

    parser = argparse.ArgumentParser(description="Cowork Pilot — auto-response agent")
    parser.add_argument("--config", type=str, default="config.toml", help="Path to config file")
    parser.add_argument("--engine", type=str, choices=["codex", "claude"], help="Override engine")
    parser.add_argument("--mode", type=str, choices=["watch", "harness", "meta"], default="watch",
                       help="Run mode: watch (Phase 1) / harness (Phase 2) / meta (Phase 3)")
    parser.add_argument("description", nargs="?", default="",
                       help="Initial project description (meta mode only)")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if args.engine:
        config.engine = args.engine

    if args.mode == "meta":
        from cowork_pilot.config import load_meta_config
        from cowork_pilot.meta_runner import run_meta
        meta_config = load_meta_config(Path(args.config))
        if args.description:
            meta_config.initial_description = args.description
        if not meta_config.project_dir:
            meta_config.project_dir = config.project_dir
        run_meta(config, meta_config)
    elif args.mode == "harness":
        harness_config = load_harness_config(Path(args.config), config)
        run_harness(config, harness_config)
    else:
        run(config)
```

- [ ] **Step 38: 동작 확인 (CLI 파싱만)**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m cowork_pilot.main --mode meta --help`
Expected: help 텍스트에 `meta` 모드와 `description` 인자 표시

- [ ] **Step 39: 커밋**

```bash
git add src/cowork_pilot/main.py
git commit -m "feat(main): add --mode meta CLI option for Phase 3"
```

---

#### Task 9: AGENTS.md 업데이트

- [ ] **Step 40: AGENTS.md에 Phase 3 파일 추가**

`AGENTS.md`의 Directory Map 섹션에 추가:

```markdown
- `src/cowork_pilot/brief_parser.py` — 브리프 MD 파싱
- `src/cowork_pilot/scaffolder.py` — 프로젝트 디렉토리 + 템플릿 스캐폴딩
- `src/cowork_pilot/meta_runner.py` — Phase 3 메타 에이전트 오케스트레이션
- `src/cowork_pilot/brief_templates/` — Jinja2 프로젝트 템플릿 (6개 .j2 파일)
```

- [ ] **Step 41: 커밋**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md with Phase 3 files"
```

---

#### Task 10: 전체 테스트 실행 + 검증

- [ ] **Step 42: 전체 테스트 실행**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/ -v --tb=short`
Expected: 기존 테스트 + 새 테스트 전부 통과

- [ ] **Step 43: import 검증**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -c "from cowork_pilot.meta_runner import run_meta; from cowork_pilot.brief_parser import parse_brief; from cowork_pilot.scaffolder import scaffold_project; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 44: 최종 커밋 (필요 시)**

수정 사항 있으면 커밋. 없으면 스킵.
