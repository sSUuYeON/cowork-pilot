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


# ── GUIDE sections for design-doc.md.j2 ─────────────────────────────

CORE_BELIEFS_SECTIONS = [
    {
        "number": 1,
        "title": "목표",
        "guide": (
            "- 내용: 이 프로젝트에서 에이전트/개발자가 따라야 할 핵심 철학\n"
            "- 형식: 원칙당 `### 원칙 이름` + 산문 2~3줄\n"
            "- 분량: 3~5개 원칙, 전체 15~30줄\n"
            '- 예시 원칙: "사용자 경험 우선", "단순함 > 완벽함", "테스트 없는 코드는 없다"'
        ),
    },
    {
        "number": 2,
        "title": "설계",
        "guide": (
            "- 내용: 원칙이 실제 코드에 어떻게 반영되는지. 금지 패턴 포함\n"
            "- 형식: 원칙별 `**DO**: ... / **DON'T**: ...` 쌍\n"
            "- 분량: 원칙당 2~4줄"
        ),
    },
]

DATA_MODEL_SECTIONS = [
    {
        "number": 1,
        "title": "목표",
        "guide": (
            "- 내용: 데이터 모델의 전체 설계 방향. 정규화 수준, 확장 방향\n"
            "- 형식: 산문 1~2 문단\n"
            "- 분량: 3~8줄"
        ),
    },
    {
        "number": 2,
        "title": "설계",
        "guide": (
            "- 내용: 엔티티별 필드 정의\n"
            "- 형식: 엔티티당 GFM 테이블: | 필드명 | 타입 | 필수 | 설명 |\n"
            "- 분량: 엔티티당 테이블 1개 + 관계 설명 1~3줄\n"
            "- 참조: project-brief.md §4 Data Model"
        ),
    },
    {
        "number": 3,
        "title": "구현 세부사항",
        "guide": (
            "- 내용: 엔티티 간 관계 (1:N, N:M 등). ERD 다이어그램\n"
            "- 형식: Mermaid erDiagram 또는 ASCII 관계도\n"
            "- 분량: 5~20줄"
        ),
    },
]

DOMAIN_DOC_SECTIONS = [
    {
        "number": 1,
        "title": "목표",
        "guide": (
            "- 내용: 이 도메인에서 달성하려는 것과 제약 조건\n"
            "- 형식: 산문 1~2 문단\n"
            "- 분량: 3~8줄\n"
            "- 참조: project-brief.md §6 Constraints"
        ),
    },
    {
        "number": 2,
        "title": "설계",
        "guide": (
            "- 내용: 선택한 방식의 구체적 설계. 플로우, 컴포넌트, 설정값\n"
            "- 형식: 플로우는 Mermaid/ASCII, 설정은 코드블록, 컴포넌트는 리스트\n"
            "- 분량: 10~25줄"
        ),
    },
    {
        "number": 3,
        "title": "구현 세부사항",
        "guide": (
            "- 내용: 구현에 필요한 라이브러리, API 키, 환경변수, 설정 파일 경로\n"
            "- 형식: `- **항목**: 값/설명` 리스트 + 필요시 코드블록\n"
            "- 분량: 5~15줄"
        ),
    },
]


# ── Helpers ──────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to a URL/filename-safe slug.

    Preserves non-ASCII (Korean etc.) but lowercases ASCII,
    replaces spaces/special chars with hyphens, strips edges.
    """
    # Replace whitespace and common separators with hyphens
    text = re.sub(r'[\s_/\\()\[\]{}]+', '-', text)
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
        "docs/exec-plans/planning",
        "docs/exec-plans/completed",
        "docs/references",
        "docs/generated",
        "docs/implementation-map",
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

    # ── 2a. docs/ root files (QUALITY_SCORE, SECURITY, DESIGN_GUIDE) ──
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

    # Core docs with type-specific GUIDE sections
    core_docs_with_sections = [
        ("core-beliefs.md", "에이전트 운영 원칙 및 기술 철학", CORE_BELIEFS_SECTIONS),
        ("data-model.md", "데이터 모델 — 엔티티, 관계, 스키마", DATA_MODEL_SECTIONS),
    ]

    # Domain docs based on constraints
    for doc_name in brief.domain_doc_names():
        label = doc_name.replace(".md", "")
        core_docs_with_sections.append((doc_name, f"{label} 설계", DOMAIN_DOC_SECTIONS))

    all_design_docs = []
    for filename, summary, sections in core_docs_with_sections:
        title = summary.split(" — ")[0] if " — " in summary else summary
        content = design_doc_tpl.render(
            title=title, summary=summary, today=today, sections=sections
        )
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
    plan_filename = "01-docs-setup.md"
    completed_path = project_dir / "docs" / "exec-plans" / "completed" / plan_filename
    if not completed_path.exists():
        _write_if_not_exists(
            project_dir / "docs" / "exec-plans" / "active" / plan_filename,
            plan_content,
        )
