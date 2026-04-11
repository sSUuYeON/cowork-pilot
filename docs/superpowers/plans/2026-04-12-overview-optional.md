# docs-orchestrator `_overview.md` Optional Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `domain/_overview.md` from an always-generated Phase 1 artifact into a conditional artifact governed by an explicit "Domain Overview Decisions" contract in `analysis-report.md`, and make every downstream phase template read overview files only when they physically exist on disk.

**Architecture:** The change has three pillars. (1) Phase 1 prompts are extended with an explicit boundary rule and are required to emit a structured `Domain Overview Decisions` table inside `analysis-report.md`; this table becomes the single source of truth for "does this domain need an overview?". (2) The Python quality gate splits what used to be a monolithic "missing files" check into three categories (`missing_shared` hard fail, `missing_features` hard fail, `missing_overviews` warning only), and the feature detector is tightened so it stops treating support files as features. (3) Downstream phase templates (Phase 2/3) stop unconditionally reading `_overview.md`; instead the prompt renderer computes an `available_extracts` structure from the filesystem and the templates only reference overview files that actually exist.

**Tech Stack:** Python 3.11+, Jinja2 templates (`cowork_pilot.orchestrator_templates`), pytest (unit + e2e), existing Cowork Pilot orchestrator code under `src/cowork_pilot/`.

---

## Invariants (do not violate during implementation)

These invariants must hold at every commit boundary. Review them before each step.

1. `shared.md` is always a Phase 1 required artifact. Its absence is a hard fail.
2. Every feature file identified in `analysis-report.md` is always a Phase 1 required artifact. Missing feature files are a hard fail.
3. `_overview.md` is never a required artifact. Its absence is at most a warning.
4. The machine-readable `출력 파일:` (output files) bullet list in `phase1_domain.j2` must not contain `_overview.md` as a required path. Any mention of `_overview.md` in the output section must be in natural-language prose *outside* the machine-readable block, marked as conditional.
5. `analysis-report.md` must contain the `Domain Overview Decisions` table whenever Phase 1 runs in domain mode. This table is the only authoritative "overview needed?" source for the quality gate.
6. Quality gate uses two independent inputs: the parsed decision table (for "was an overview needed?") and the filesystem (for "does the file exist?"). These inputs are never confused.
7. Phase 2/3 templates must not contain any unconditional reference to an `_overview.md` path. Every overview path must be gated behind a Jinja `{% if ... %}` block driven by render kwargs.
8. The `references/` directory, `shared.md`, and `_overview.md` must never be counted as "features" by the feature detector.
9. Backward compatibility: existing projects that already have `_overview.md` files but no decision table must not hard-fail on re-run.
10. TDD: every code change in this plan is driven by a failing test first.

## Contract: Domain Overview Decisions Table

Every `analysis-report.md` produced by Phase 1 (domain mode) must contain exactly one section with this heading and format:

```markdown
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | create-poll / share-access / live-results / close-poll share poll lifecycle state and host-only permission rules |
| voter | no | common context is already captured in shared.md and each voter feature is self-contained |
```

Rules:

- The heading text is exactly `## Domain Overview Decisions` (case-sensitive, one level two heading).
- Column order is fixed: `domain`, `overview_needed`, `reason`.
- `overview_needed` must be the literal string `yes` or `no`. Any other value is a parse error.
- `domain` values must match the domain directory names used elsewhere in the report.
- `reason` is free-form prose but must be non-empty.
- The table must appear after the domain list and before any appendix.
- In `single` Phase 1 mode (no domain decomposition), the table is also emitted; for single-domain projects it should contain exactly one row whose domain is either the project slug or the single domain name.

## Feature Flags / Configuration

No new feature flag is introduced. The behavior change is unconditional from the release on. Migration is handled by the tolerant branch in the quality gate (see Chunk 3, Task 3.4).

## Skills to reference during execution

- `@superpowers:test-driven-development` — every code task is test-first.
- `@superpowers:systematic-debugging` — if any step fails in an unexpected way.
- `@superpowers:verification-before-completion` — before marking any chunk complete, run the stated verification commands and confirm the expected output.
- `@superpowers:subagent-driven-development` — recommended execution mode.

## Assumed repository layout

The template files live under:

```
src/cowork_pilot/orchestrator_templates/
  phase1_single.j2
  phase1_domain.j2
  phase2_auto.j2
  phase2_manual.j2
  phase3_architecture.j2
```

The Python orchestrator code lives under `src/cowork_pilot/orchestrator/` (exact file names may differ slightly). During Task 0 below, the exact paths for `quality_gate.py`, `feature_detector.py`, and the prompt renderer will be discovered and pinned. All subsequent tasks use the pinned paths.

Tests live under `tests/unit/` and `tests/e2e/` (create `tests/e2e/` if it does not already exist).

## Pinned file paths (locked during Chunk 0)

These paths were discovered during Chunk 0 execution (2026-04-12) and are fixed for the remainder of this plan. Every task that references `<QG_legacy>`, `<QG_overview>`, `<FD>`, or `<PR>` means the corresponding file below.

| alias | path | role |
|---|---|---|
| `<QG_legacy>` | `src/cowork_pilot/quality_gate.py` | Legacy Phase 1 gate. Owns **coverage ratio** (`coverage_ratio`, `uncovered_sections`) and — under the dual-gate transition — still owns hard-fail on missing `shared.md` / missing feature files. Plan goal: narrow this module to coverage-only once `<QG_overview>` is authoritative for shared/features/overviews. |
| `<QG_overview>` | `src/cowork_pilot/orchestrator/quality_gate.py` | New overview-aware Phase 1 gate created by Chunk 3. Entry point `evaluate_phase1(generated_dir) -> Phase1Result` returning `{missing_shared, missing_features, missing_overviews (warning), warnings}`. This is the module all new overview-optional logic is built against. |
| `<FD>` | `src/cowork_pilot/orchestrator/feature_detector.py` | Feature detector created by Chunk 3 Task 3.1. Entry point `detect_features(extracts_root)`. Excludes `shared.md`, `_overview.md`, and `references/` from feature enumeration. |
| `<PR>` | `src/cowork_pilot/orchestrator_prompts.py` | Prompt renderer — top-level module, **not** inside the `orchestrator/` subpackage. Public API: `build_session_prompt(phase, **kwargs)`, `build_codex_session_prompt(phase, **kwargs)`. Chunk 4 Task 4.1 adds `AvailableExtracts`, `compute_available_extracts(extracts_root)`, and `_load_overview_reasons(project_dir)` here. Test imports must use `from cowork_pilot.orchestrator_prompts import ...`. |

Notes and known divergences from the prose above:

- **There are two `quality_gate.py` files.** Do not confuse `src/cowork_pilot/quality_gate.py` (legacy, coverage + shared/features hard-fail) with `src/cowork_pilot/orchestrator/quality_gate.py` (new, overview-aware). Chunk 3 as currently implemented **runs both gates in sequence** inside `docs_orchestrator.py::_run_phase_1_5` — legacy is consulted first for hard-fail categories, then `evaluate_phase1` is consulted for the overview warning track only. The new gate's own hard-fail categories are intentionally ignored in the current wiring because they are covered by the legacy gate. The original plan intent was for the new gate to take over those categories outright; closing that gap is the remaining work for Chunk 3 (see "Recovery" note at the bottom of this section).
- **`<PR>` is not in the `orchestrator` subpackage.** The `orchestrator/` subpackage was created by Chunk 3 and holds `analysis_report.py`, `feature_detector.py`, and the new `quality_gate.py`. The prompt renderer predates it and lives one level up. Any test fixture importing from `cowork_pilot.orchestrator.<PR_MODULE>` in the original plan body should read `cowork_pilot.orchestrator_prompts` instead.
- **Tests directory structure.** Unit tests for this plan live under `tests/unit/` (created by Chunk 1). E2E tests for Chunk 5 should be added under `tests/e2e/`. Legacy gate tests remain at `tests/test_quality_gate.py` (top-level, not under `tests/unit/`).

Recovery note: the dual-gate wiring above is a known deviation from the plan, not a bug. The agreed recovery path is to (a) verify functional equivalence between `<QG_legacy>`'s shared/features hard-fail logic and `<QG_overview>`'s equivalents, (b) migrate any missing logic into `<QG_overview>`, (c) narrow `<QG_legacy>` to coverage-only, and (d) re-wire `docs_orchestrator.py::_run_phase_1_5` so `<QG_overview>` is the sole source of truth for shared/features/overviews and `<QG_legacy>` is consulted only for coverage. Chunks 5 and 6 should not run before this recovery is complete.

---

## Chunk 0: Locate existing code and lock file paths

This chunk only gathers information. It produces no production code change. It exists because several Python module paths referenced below ("quality gate", "feature detector", "prompt renderer") are conceptual names; the implementer must pin them to real files before the TDD chunks start.

### Task 0.1: Inventory the template files

**Files:**
- Inspect: `src/cowork_pilot/orchestrator_templates/phase1_single.j2`
- Inspect: `src/cowork_pilot/orchestrator_templates/phase1_domain.j2`
- Inspect: `src/cowork_pilot/orchestrator_templates/phase2_auto.j2`
- Inspect: `src/cowork_pilot/orchestrator_templates/phase2_manual.j2`
- Inspect: `src/cowork_pilot/orchestrator_templates/phase3_architecture.j2`

- [ ] **Step 1: Read every template listed above in full.**

Record in a scratch note: (a) the exact line ranges that mention `_overview.md`, (b) the exact line ranges that list "expected output files" or "출력 파일", (c) the exact Jinja variable names already available in each template's render context.

- [ ] **Step 2: Grep for `_overview` across the whole repo.**

Run:
```bash
rg -n "_overview" src tests
```
Expected: matches in the five templates above, plus references in the quality gate / feature detector / tests. Record every hit with file and line.

- [ ] **Step 3: Locate the quality gate module.**

Run:
```bash
rg -n "quality_gate|missing_features|missing_shared|Phase ?1" src --glob '*.py'
```
Pin the file that contains the "phase 1 completion check" logic. Name it `<QG>` for the rest of this plan.

- [ ] **Step 4: Locate the feature detector module.**

Run:
```bash
rg -n "feature_detector|detect_features|features = " src --glob '*.py'
```
Pin the file that classifies markdown files under `domain-extracts/` into feature files. Name it `<FD>` for the rest of this plan.

- [ ] **Step 5: Locate the prompt renderer module.**

Run:
```bash
rg -n "render.*phase2|render.*phase3|Environment\(|Template\(" src --glob '*.py'
```
Pin the file where Jinja `render(**kwargs)` is called for phase 2 / phase 3 prompts. Name it `<PR>` for the rest of this plan.

- [ ] **Step 6: Record all pinned paths in the plan execution log.**

Write them into the commit message of Task 0.1. Do not edit the plan document.

- [ ] **Step 7: Commit (no code change).**

```bash
git add -A && git diff --cached --stat
# expect: empty
git commit --allow-empty -m "chore(plan): lock file paths for overview-optional refactor

QG = <path>
FD = <path>
PR = <path>"
```

---

## Chunk 1: Analysis-report parser and contract tests

This chunk introduces the single source of truth parser and its unit tests. It does not touch any template or existing Python logic. After this chunk, the parser exists and is fully tested, but nothing in the orchestrator uses it yet.

### Task 1.1: Create the parser module skeleton (TDD step 1 — failing test first)

**Files:**
- Create: `tests/unit/test_analysis_report_parser.py`
- Create: `src/cowork_pilot/orchestrator/analysis_report.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_analysis_report_parser.py
from cowork_pilot.orchestrator.analysis_report import (
    OverviewDecision,
    parse_overview_decisions,
    MissingDecisionTableError,
    MalformedDecisionTableError,
)


def test_parse_basic_table():
    report = """
# Analysis Report

## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | poll lifecycle shared |
| voter | no | self contained |
"""
    decisions = parse_overview_decisions(report)
    assert decisions == {
        "host": OverviewDecision(domain="host", overview_needed=True, reason="poll lifecycle shared"),
        "voter": OverviewDecision(domain="voter", overview_needed=False, reason="self contained"),
    }
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `pytest tests/unit/test_analysis_report_parser.py::test_parse_basic_table -xvs`
Expected: `ModuleNotFoundError: No module named 'cowork_pilot.orchestrator.analysis_report'`.

- [ ] **Step 3: Create the minimal module to make the import work (but still fail on behavior).**

```python
# src/cowork_pilot/orchestrator/analysis_report.py
from __future__ import annotations

from dataclasses import dataclass


class MissingDecisionTableError(ValueError):
    """Raised when analysis-report.md has no Domain Overview Decisions section."""


class MalformedDecisionTableError(ValueError):
    """Raised when the table exists but does not match the required format."""


@dataclass(frozen=True)
class OverviewDecision:
    domain: str
    overview_needed: bool
    reason: str


def parse_overview_decisions(report_text: str) -> dict[str, OverviewDecision]:
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it now fails on behavior (not import).**

Run: `pytest tests/unit/test_analysis_report_parser.py::test_parse_basic_table -xvs`
Expected: `NotImplementedError`.

- [ ] **Step 5: Implement the minimal parser.**

```python
import re

_HEADING_RE = re.compile(r"^##\s+Domain Overview Decisions\s*$", re.MULTILINE)


def parse_overview_decisions(report_text: str) -> dict[str, OverviewDecision]:
    match = _HEADING_RE.search(report_text)
    if not match:
        raise MissingDecisionTableError(
            "analysis-report.md is missing the '## Domain Overview Decisions' section"
        )

    # Grab everything after the heading until the next '## ' or end of file.
    tail = report_text[match.end():]
    next_section = re.search(r"^##\s+", tail, re.MULTILINE)
    body = tail[: next_section.start()] if next_section else tail

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Expect: header row, separator row, then data rows.
    table_rows = [ln for ln in lines if ln.startswith("|")]
    if len(table_rows) < 3:
        raise MalformedDecisionTableError(
            "Domain Overview Decisions table must have a header, separator, and at least one data row"
        )

    header_cells = [c.strip() for c in table_rows[0].strip("|").split("|")]
    if header_cells != ["domain", "overview_needed", "reason"]:
        raise MalformedDecisionTableError(
            f"unexpected column order: {header_cells!r}, must be ['domain', 'overview_needed', 'reason']"
        )

    decisions: dict[str, OverviewDecision] = {}
    for row in table_rows[2:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) != 3:
            raise MalformedDecisionTableError(f"row does not have 3 cells: {row!r}")
        domain, needed, reason = cells
        if needed not in ("yes", "no"):
            raise MalformedDecisionTableError(
                f"overview_needed must be 'yes' or 'no', got {needed!r} for domain {domain!r}"
            )
        if not reason:
            raise MalformedDecisionTableError(f"reason is empty for domain {domain!r}")
        decisions[domain] = OverviewDecision(
            domain=domain,
            overview_needed=(needed == "yes"),
            reason=reason,
        )
    return decisions
```

- [ ] **Step 6: Run the test.**

Run: `pytest tests/unit/test_analysis_report_parser.py::test_parse_basic_table -xvs`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add tests/unit/test_analysis_report_parser.py src/cowork_pilot/orchestrator/analysis_report.py
git commit -m "feat(orchestrator): add analysis-report Domain Overview Decisions parser"
```

### Task 1.2: Add error-case tests for the parser

**Files:**
- Modify: `tests/unit/test_analysis_report_parser.py`

- [ ] **Step 1: Append failing tests for the error cases.**

```python
import pytest


def test_missing_section_raises():
    report = "# Analysis Report\n\nNo table here.\n"
    with pytest.raises(MissingDecisionTableError):
        parse_overview_decisions(report)


def test_bad_column_order_raises():
    report = """
## Domain Overview Decisions

| overview_needed | domain | reason |
|---|---|---|
| yes | host | x |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_invalid_value_raises():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | maybe | x |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_empty_reason_raises():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes |   |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_section_stops_at_next_heading():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | a |

## Appendix

| ignored | ignored | ignored |
|---|---|---|
| foo | no | bar |
"""
    decisions = parse_overview_decisions(report)
    assert set(decisions) == {"host"}
```

- [ ] **Step 2: Run the new tests and confirm they pass (parser already handles them).**

Run: `pytest tests/unit/test_analysis_report_parser.py -xvs`
Expected: all 5 tests PASS. If any fails, fix the parser (not the test) before continuing.

- [ ] **Step 3: Commit.**

```bash
git add tests/unit/test_analysis_report_parser.py
git commit -m "test(orchestrator): cover analysis-report parser error cases"
```

### Task 1.3: Add a tolerant loader for migration

**Files:**
- Modify: `src/cowork_pilot/orchestrator/analysis_report.py`
- Modify: `tests/unit/test_analysis_report_parser.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_load_tolerant_returns_none_when_missing():
    from cowork_pilot.orchestrator.analysis_report import load_overview_decisions_tolerant

    report = "# Analysis Report\n\nNo table.\n"
    assert load_overview_decisions_tolerant(report) is None


def test_load_tolerant_returns_decisions_when_present():
    from cowork_pilot.orchestrator.analysis_report import load_overview_decisions_tolerant

    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | because |
"""
    result = load_overview_decisions_tolerant(report)
    assert result is not None
    assert result["host"].overview_needed is True
```

- [ ] **Step 2: Run tests and confirm they fail on import.**

Run: `pytest tests/unit/test_analysis_report_parser.py -xvs`
Expected: `ImportError: cannot import name 'load_overview_decisions_tolerant'`.

- [ ] **Step 3: Implement the tolerant loader.**

Append to `src/cowork_pilot/orchestrator/analysis_report.py`:

```python
def load_overview_decisions_tolerant(
    report_text: str,
) -> dict[str, OverviewDecision] | None:
    """Return decisions if the table exists and is valid; return None otherwise.

    Used by the quality gate in migration mode: legacy projects that predate
    the decision-table contract should not hard-fail.
    """
    try:
        return parse_overview_decisions(report_text)
    except (MissingDecisionTableError, MalformedDecisionTableError):
        return None
```

- [ ] **Step 4: Run tests and confirm PASS.**

Run: `pytest tests/unit/test_analysis_report_parser.py -xvs`
Expected: all tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(orchestrator): add tolerant analysis-report loader for legacy projects"
```

---

## Chunk 2: Phase 1 prompt template changes

This chunk rewrites the two Phase 1 templates so that (a) the boundary rule is visible to the LLM, (b) `analysis-report.md` must carry the decision table, (c) `_overview.md` is described as conditional, and (d) the machine-readable output bullets no longer include `_overview.md`.

### Task 2.1: Boundary-rule block (shared snippet)

**Files:**
- Create: `src/cowork_pilot/orchestrator_templates/_partials/overview_boundary_rules.md.j2`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_phase1_prompts_contain_rules.py
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path("src/cowork_pilot/orchestrator_templates")


@pytest.fixture
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )


BOUNDARY_PHRASES = [
    "shared.md",
    "2개 이상 도메인",
    "_overview.md",
    "한 도메인의 2개 이상 feature",
    "feature.md",
    "단일 feature",
]


def _render(env: Environment, name: str, **ctx) -> str:
    return env.get_template(name).render(**ctx)


def test_phase1_single_contains_boundary_rules(env):
    out = _render(env, "phase1_single.j2", project_slug="demo")
    for phrase in BOUNDARY_PHRASES:
        assert phrase in out, f"phase1_single.j2 missing boundary phrase: {phrase!r}"


def test_phase1_domain_contains_boundary_rules(env):
    out = _render(env, "phase1_domain.j2", domain="host", project_slug="demo")
    for phrase in BOUNDARY_PHRASES:
        assert phrase in out, f"phase1_domain.j2 missing boundary phrase: {phrase!r}"
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`
Expected: failing assertions because the phrases are not yet in the templates. (If the templates don't render at all because kwargs differ, widen the fixture's kwargs to match the real template contracts found in Task 0.1.)

- [ ] **Step 3: Create the partial.**

```jinja
{# src/cowork_pilot/orchestrator_templates/_partials/overview_boundary_rules.md.j2 #}
### 문서 경계 규칙 (반드시 준수)

아래 3층 분리 규칙을 반드시 지켜라. 판단이 애매하면 상위 레이어에 올리지 말고 기본값으로 `feature.md`에 남겨라.

1. **`shared.md`**: 2개 이상 도메인이 참조하는 전역 공통 정보만 담는다. 프로젝트 개요, 목표, 공통 데이터 구조, 기술 스택, 전역 규칙이 대표 예시다.
2. **`{domain}/_overview.md`**: 한 도메인의 2개 이상 feature가 실제로 공유하는 상태/용어/불변조건/권한 규칙/공통 워크플로/공통 데이터 모델이 있을 때만 생성한다. 공통 맥락이 없거나, 느낌만 있고 본문으로 쓰면 10줄 미만이거나, 사실상 한 feature 전용 내용이면 만들지 않는다.
3. **`{domain}/feature.md`**: 단일 feature 전용 정보만 담는다. 여러 feature에 걸쳐 공유되는 내용은 올려 보낸다.

**overview 생성 판정 체크리스트**

- yes 조건 (모두 충족해야 `_overview.md` 생성)
  - 해당 도메인에 feature가 2개 이상 존재한다.
  - 공통 상태 머신, 용어, 불변조건, 권한 규칙, 공통 워크플로, 공통 데이터 모델 중 하나 이상이 2개 이상 feature에 걸친다.
  - 그 공통 내용을 각 feature 파일에 복사했을 때 중복 source block이 2개 이상 생긴다.
- no 조건 (하나라도 해당하면 `_overview.md` 생성 금지)
  - 그 도메인의 feature가 0개 또는 1개다.
  - 내용이 사실상 전역 공통이라 `shared.md`에 들어가야 한다.
  - 내용이 사실상 단일 feature 전용이다.
  - 예상 본문이 10줄 미만 또는 2개 미만의 source block이어서 ceremonial overview가 된다.
```

- [ ] **Step 4: Include the partial from both Phase 1 templates.**

In `phase1_single.j2`, near the top (after the existing header but before the per-phase instructions), add:

```jinja
{% include "_partials/overview_boundary_rules.md.j2" %}
```

Do the same in `phase1_domain.j2`. Place the include at the same structural point — immediately after any existing "프로젝트 정보" block and before the "출력 파일" (output files) block.

- [ ] **Step 5: Run the test again.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add -A
git commit -m "feat(templates): embed document boundary rules in phase1 prompts"
```

### Task 2.2: Mandate the Domain Overview Decisions table in `analysis-report.md`

**Files:**
- Modify: `src/cowork_pilot/orchestrator_templates/phase1_single.j2`
- Modify: `src/cowork_pilot/orchestrator_templates/phase1_domain.j2`
- Modify: `tests/unit/test_phase1_prompts_contain_rules.py`

- [ ] **Step 1: Write the failing test.**

```python
DECISION_TABLE_REQUIRED_PHRASES = [
    "Domain Overview Decisions",
    "| domain | overview_needed | reason |",
    "overview_needed",
    "yes",
    "no",
]


def test_phase1_single_requires_decision_table(env):
    out = _render(env, "phase1_single.j2", project_slug="demo")
    for phrase in DECISION_TABLE_REQUIRED_PHRASES:
        assert phrase in out, f"phase1_single.j2 missing decision-table phrase: {phrase!r}"


def test_phase1_domain_requires_decision_table(env):
    out = _render(env, "phase1_domain.j2", domain="host", project_slug="demo")
    for phrase in DECISION_TABLE_REQUIRED_PHRASES:
        assert phrase in out, f"phase1_domain.j2 missing decision-table phrase: {phrase!r}"
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`

- [ ] **Step 3: Add the mandate block to both templates.**

Insert this block into both `phase1_single.j2` and `phase1_domain.j2`, in the section that describes what `analysis-report.md` must contain:

```markdown
### `analysis-report.md` 필수 섹션: Domain Overview Decisions

`analysis-report.md` 안에 아래 형식의 표를 반드시 포함하라. 이 표는 `_overview.md` 생성 여부의 유일한 기계 판독 계약이다.

```md
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| <도메인명> | yes | <overview가 필요한 이유, 1~2 문장> |
| <도메인명> | no | <overview가 불필요한 이유, 1~2 문장> |
```

규칙:
- 헤딩은 정확히 `## Domain Overview Decisions`.
- 컬럼 순서는 `domain | overview_needed | reason` 고정.
- `overview_needed`는 문자 그대로 `yes` 또는 `no`만 허용.
- `reason`은 비어 있을 수 없다.
- `domain` 값은 본 보고서의 다른 섹션에서 쓴 도메인 디렉토리 이름과 일치해야 한다.
- 단일 도메인 프로젝트라도 이 표는 한 행으로 반드시 작성한다.
```

(Note: the inner fenced block is intentionally shown as literal text. In the Jinja file, escape the inner triple backticks using Jinja `raw` blocks so they do not break rendering. Wrap the example in `{% raw %}{% endraw %}`.)

- [ ] **Step 4: Run the test again.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(templates): require Domain Overview Decisions table in analysis-report"
```

### Task 2.3: Make `_overview.md` conditional in `phase1_domain.j2`

**Files:**
- Modify: `src/cowork_pilot/orchestrator_templates/phase1_domain.j2`
- Modify: `tests/unit/test_phase1_prompts_contain_rules.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_phase1_domain_output_bullets_do_not_force_overview(env):
    out = _render(env, "phase1_domain.j2", domain="host", project_slug="demo")

    # Find the '출력 파일:' machine-readable block. Grab everything from that
    # line up to the next blank-line-separated section.
    import re
    m = re.search(r"출력 파일:\s*\n((?:- .*\n)+)", out)
    assert m is not None, "phase1_domain.j2 must have a '출력 파일:' bullet block"
    bullet_block = m.group(1)

    # The machine-readable block must NOT list _overview.md as a required path.
    assert "_overview.md" not in bullet_block, (
        "phase1_domain.j2 machine-readable 출력 파일 block must not force _overview.md; "
        "it must be described conditionally outside the bullet list"
    )

    # But the template must still mention _overview.md conditionally somewhere outside the block.
    prose = out.replace(bullet_block, "")
    assert "_overview.md" in prose
    assert "overview_needed" in prose
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py::test_phase1_domain_output_bullets_do_not_force_overview -xvs`

- [ ] **Step 3: Edit the `출력 파일:` block in `phase1_domain.j2`.**

Before:
```markdown
출력 파일:
- `domain-extracts/{{ domain }}/_overview.md`
- `domain-extracts/{{ domain }}/<feature>.md` (feature 개수만큼)
```

After:
```markdown
출력 파일:
- `domain-extracts/{{ domain }}/`
- `domain-extracts/{{ domain }}/<feature>.md` (feature 개수만큼)

위 bullet list에 `_overview.md`는 의도적으로 빠져 있다. `_overview.md`는 조건부 산출물이다. `analysis-report.md`의 `Domain Overview Decisions` 표에서 이 도메인 행의 `overview_needed` 값이 `yes`이면 추가로 `domain-extracts/{{ domain }}/_overview.md`를 생성하라. `no`이면 생성하지 마라. 판단은 위의 "문서 경계 규칙 > overview 생성 판정 체크리스트"를 기준으로 하라.
```

- [ ] **Step 4: Run the test again.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`
Expected: all phase1 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(templates): downgrade _overview.md to conditional output in phase1_domain"
```

### Task 2.4: Mirror the conditional message in `phase1_single.j2`

**Files:**
- Modify: `src/cowork_pilot/orchestrator_templates/phase1_single.j2`
- Modify: `tests/unit/test_phase1_prompts_contain_rules.py`

- [ ] **Step 1: Add a single-mode assertion.**

```python
def test_phase1_single_describes_conditional_overview(env):
    out = _render(env, "phase1_single.j2", project_slug="demo")
    assert "_overview.md" in out
    assert "조건부" in out or "overview_needed" in out
```

- [ ] **Step 2: Run and confirm failure (if `phase1_single.j2` does not already mention conditional overview).**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py::test_phase1_single_describes_conditional_overview -xvs`

- [ ] **Step 3: Add a conditional overview description to `phase1_single.j2`.**

Place this prose under the "출력 파일" section (outside any machine-readable bullet block):

```markdown
`_overview.md`는 각 도메인 디렉토리에서 조건부 산출물이다. 생성 여부는 `analysis-report.md`의 `Domain Overview Decisions` 표를 기준으로 판단하며, 판단 기준은 "문서 경계 규칙 > overview 생성 판정 체크리스트"를 따른다. `overview_needed=no`인 도메인에는 파일을 만들지 마라.
```

- [ ] **Step 4: Run the test and confirm PASS.**

Run: `pytest tests/unit/test_phase1_prompts_contain_rules.py -xvs`

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(templates): document conditional overview in phase1_single"
```

---

## Chunk 3: Quality gate and feature detector

This chunk updates the Python validation layer so that (a) `shared.md` and feature files remain hard-required, (b) `_overview.md` becomes warning-only, (c) the decision table drives the "should this overview exist?" question, and (d) the feature detector stops treating support files as features.

> Paths `<QG>`, `<FD>` below are the paths pinned in Task 0.1.

### Task 3.1: Feature detector excludes support files (TDD)

**Files:**
- Create: `tests/unit/test_feature_detector_filter.py`
- Modify: `<FD>`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_feature_detector_filter.py
from pathlib import Path

from cowork_pilot.orchestrator.<FD_MODULE> import detect_features  # replace <FD_MODULE>


def _touch(path: Path, body: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_feature_detector_excludes_support_files(tmp_path: Path) -> None:
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "shared.md")
    _touch(extracts / "host" / "_overview.md")
    _touch(extracts / "host" / "create-poll.md")
    _touch(extracts / "host" / "close-poll.md")
    _touch(extracts / "voter" / "cast-vote.md")
    _touch(extracts / "references" / "some-ref.md")

    features = detect_features(extracts)

    names = sorted(f.name for f in features)
    assert names == ["cast-vote.md", "close-poll.md", "create-poll.md"]

    joined = "\n".join(str(f) for f in features)
    assert "shared.md" not in joined
    assert "_overview.md" not in joined
    assert "references" not in joined
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_feature_detector_filter.py -xvs`
Expected: either an import error (rename `<FD_MODULE>` to the real module pinned in Task 0.1 and rerun) or a failure because the current detector includes `_overview.md` / `shared.md`.

- [ ] **Step 3: Update the detector to filter support files.**

Inside `<FD>`, find the function that walks `domain-extracts/` and returns feature paths. Add a filter:

```python
_SUPPORT_NAMES = {"shared.md", "_overview.md"}
_SUPPORT_DIRS = {"references"}


def _is_feature_path(path: Path, extracts_root: Path) -> bool:
    if path.suffix != ".md":
        return False
    if path.name in _SUPPORT_NAMES:
        return False
    try:
        rel_parts = path.relative_to(extracts_root).parts
    except ValueError:
        return False
    if rel_parts and rel_parts[0] in _SUPPORT_DIRS:
        return False
    # Features live inside a domain directory: domain/<feature>.md
    return len(rel_parts) == 2
```

Wire `_is_feature_path` into the existing `detect_features` call site.

- [ ] **Step 4: Run the test and confirm PASS.**

Run: `pytest tests/unit/test_feature_detector_filter.py -xvs`

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "fix(orchestrator): feature detector excludes shared/_overview/references"
```

### Task 3.2: Quality gate splits missing_shared / missing_features / missing_overviews (TDD)

**Files:**
- Create: `tests/unit/test_quality_gate_overview.py`
- Modify: `<QG>`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_quality_gate_overview.py
from pathlib import Path

from cowork_pilot.orchestrator.<QG_MODULE> import (  # replace <QG_MODULE>
    evaluate_phase1,
    Phase1Result,
)


def _write(path: Path, body: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


DECISION_TABLE = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | lifecycle shared |
| voter | no | self contained |
"""


def _setup_project(tmp_path: Path, *, include_shared=True, include_host_overview=True) -> Path:
    project = tmp_path / "proj"
    extracts = project / "domain-extracts"
    _write(project / "analysis-report.md", "# report\n" + DECISION_TABLE)
    if include_shared:
        _write(extracts / "shared.md")
    _write(extracts / "host" / "create-poll.md")
    _write(extracts / "host" / "close-poll.md")
    _write(extracts / "voter" / "cast-vote.md")
    if include_host_overview:
        _write(extracts / "host" / "_overview.md", "10 line body\n" * 12)
    return project


def test_happy_path_passes(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    result = evaluate_phase1(project)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_missing_shared_is_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_shared=False)
    result = evaluate_phase1(project)
    assert result.ok is False
    assert any("shared.md" in f for f in result.hard_failures)


def test_missing_overview_for_yes_domain_is_warning(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=False)
    result = evaluate_phase1(project)
    assert result.ok is True, "missing overview must not be a hard fail"
    assert any("host" in w and "_overview" in w for w in result.warnings)


def test_missing_overview_for_no_domain_is_silent(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    # voter has overview_needed=no and no overview file; no warning expected.
    assert not (project / "domain-extracts" / "voter" / "_overview.md").exists()
    result = evaluate_phase1(project)
    assert not any("voter" in w and "_overview" in w for w in result.warnings)


def test_ceremonial_overview_is_warning(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    # Overwrite host overview with a <10-line body.
    (project / "domain-extracts" / "host" / "_overview.md").write_text("one line only\n")
    result = evaluate_phase1(project)
    assert any("host" in w and "10" in w for w in result.warnings)


def test_missing_feature_file_is_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    (project / "domain-extracts" / "host" / "create-poll.md").unlink()
    result = evaluate_phase1(project)
    assert result.ok is False
    assert any("create-poll" in f for f in result.hard_failures)


def test_legacy_project_without_decision_table_does_not_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=False)
    # Strip the decision table.
    (project / "analysis-report.md").write_text("# report\nno table\n")
    result = evaluate_phase1(project)
    assert result.ok is True
    # In legacy mode overview checks are silenced or emitted as informational only.
    assert all("hard" not in w.lower() for w in result.warnings)
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_quality_gate_overview.py -xvs`

- [ ] **Step 3: Refactor `<QG>` to expose `evaluate_phase1`.**

Introduce (or rename to) a `Phase1Result` dataclass and an `evaluate_phase1(project_root: Path) -> Phase1Result` function:

```python
from dataclasses import dataclass, field
from pathlib import Path

from .analysis_report import load_overview_decisions_tolerant
from .<FD_MODULE> import detect_features  # replace with the real import


OVERVIEW_MIN_LINES = 10


@dataclass
class Phase1Result:
    ok: bool
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def evaluate_phase1(project_root: Path) -> Phase1Result:
    result = Phase1Result(ok=True)

    report_path = project_root / "analysis-report.md"
    extracts = project_root / "domain-extracts"

    if not report_path.exists():
        result.hard_failures.append("analysis-report.md is missing")
    shared = extracts / "shared.md"
    if not shared.exists():
        result.hard_failures.append("domain-extracts/shared.md is missing (hard fail)")

    features = detect_features(extracts) if extracts.exists() else []
    if not features:
        result.hard_failures.append("no feature files were produced under domain-extracts/")

    report_text = report_path.read_text() if report_path.exists() else ""
    decisions = load_overview_decisions_tolerant(report_text)

    if decisions is None:
        # Legacy / migration mode: do not hard-fail on overview at all.
        # Emit an informational warning only if the project is clearly post-contract.
        pass
    else:
        for domain, decision in decisions.items():
            overview_path = extracts / domain / "_overview.md"
            if decision.overview_needed:
                if not overview_path.exists():
                    result.warnings.append(
                        f"domain {domain!r} has overview_needed=yes but "
                        f"{overview_path.relative_to(project_root)} does not exist"
                    )
                else:
                    line_count = len(overview_path.read_text().splitlines())
                    if line_count < OVERVIEW_MIN_LINES:
                        result.warnings.append(
                            f"domain {domain!r} _overview.md has only {line_count} lines "
                            f"(< {OVERVIEW_MIN_LINES}); looks ceremonial"
                        )
            else:
                # overview_needed=no: silent; only warn if the file exists anyway
                # AND is short (ceremonial). Long files are left alone.
                if overview_path.exists():
                    line_count = len(overview_path.read_text().splitlines())
                    if line_count < OVERVIEW_MIN_LINES:
                        result.warnings.append(
                            f"domain {domain!r} has overview_needed=no but a short "
                            f"_overview.md exists ({line_count} lines); consider removing"
                        )

    result.ok = not result.hard_failures
    return result
```

If the existing module already has an `evaluate_phase1` function with a different signature, preserve backward compatibility by keeping the old name as a thin wrapper.

- [ ] **Step 4: Run the tests and iterate until all pass.**

Run: `pytest tests/unit/test_quality_gate_overview.py -xvs`
Expected: all 7 tests PASS. Fix the implementation (not the tests) until green.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(orchestrator): split phase1 validation into shared/features/overviews"
```

### Task 3.3: Wire the new quality gate result into the CLI / runner

**Files:**
- Modify: wherever the old phase-1 gate was called (grep for the old function name pinned in Task 0.1).

- [ ] **Step 1: Search call sites.**

```bash
rg -n "evaluate_phase1|missing_features|missing_shared" src
```

- [ ] **Step 2: Replace each call site to consume `Phase1Result`.**

Each call site must:
- Continue to halt the pipeline if `result.ok is False`.
- Print `result.hard_failures` to stderr with a clear "HARD FAIL" prefix.
- Print `result.warnings` to stderr with a clear "WARNING" prefix but not halt.

- [ ] **Step 3: Run the unit tests for the touched modules.**

Run: `pytest tests/unit -xvs`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add -A
git commit -m "refactor(orchestrator): call sites consume Phase1Result"
```

### Task 3.4: Migration safety test

**Files:**
- Modify: `tests/unit/test_quality_gate_overview.py` (already has one legacy test; this task adds one more explicit scenario).

- [ ] **Step 1: Add the test.**

```python
def test_legacy_project_with_existing_overview_passes(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=True)
    (project / "analysis-report.md").write_text("# legacy report without table\n")
    result = evaluate_phase1(project)
    assert result.ok is True
    # No overview-related warnings because we're in legacy mode.
    assert not any("_overview" in w for w in result.warnings)
```

- [ ] **Step 2: Run and confirm PASS (should already work given Task 3.2).**

Run: `pytest tests/unit/test_quality_gate_overview.py -xvs`

- [ ] **Step 3: Commit.**

```bash
git add -A
git commit -m "test(orchestrator): cover legacy project migration path"
```

---

## Chunk 4: Downstream phase templates become overview-aware

This chunk teaches `phase2_auto.j2`, `phase2_manual.j2`, and `phase3_architecture.j2` to reference `_overview.md` only when the file actually exists.

### Task 4.1: Add `available_extracts` to the render context

**Files:**
- Modify: `<PR>` (prompt renderer pinned in Task 0.1)
- Create: `tests/unit/test_available_extracts.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_available_extracts.py
from pathlib import Path

from cowork_pilot.orchestrator.<PR_MODULE> import compute_available_extracts  # replace


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_computes_presence_map(tmp_path: Path) -> None:
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "shared.md")
    _touch(extracts / "host" / "_overview.md")
    _touch(extracts / "host" / "create-poll.md")
    _touch(extracts / "voter" / "cast-vote.md")

    info = compute_available_extracts(extracts)

    assert info.shared is True
    assert info.overviews == {"host": True, "voter": False}
    assert sorted(info.features["host"]) == ["create-poll.md"]
    assert sorted(info.features["voter"]) == ["cast-vote.md"]
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_available_extracts.py -xvs`

- [ ] **Step 3: Implement `compute_available_extracts`.**

```python
# in <PR>
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AvailableExtracts:
    shared: bool = False
    overviews: dict[str, bool] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)


def compute_available_extracts(extracts_root: Path) -> AvailableExtracts:
    info = AvailableExtracts()
    info.shared = (extracts_root / "shared.md").exists()
    if not extracts_root.exists():
        return info
    for domain_dir in sorted(p for p in extracts_root.iterdir() if p.is_dir()):
        if domain_dir.name == "references":
            continue
        info.overviews[domain_dir.name] = (domain_dir / "_overview.md").exists()
        info.features[domain_dir.name] = sorted(
            f.name
            for f in domain_dir.iterdir()
            if f.is_file() and f.suffix == ".md" and f.name != "_overview.md"
        )
    return info
```

- [ ] **Step 4: Wire `compute_available_extracts` into every render call for phase 2 and phase 3.**

Wherever a `phase2_auto.j2`, `phase2_manual.j2`, or `phase3_architecture.j2` render happens, add:

```python
extracts = compute_available_extracts(project_root / "domain-extracts")
kwargs["extracts"] = extracts
```

- [ ] **Step 5: Run the test.**

Run: `pytest tests/unit/test_available_extracts.py -xvs`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add -A
git commit -m "feat(orchestrator): compute_available_extracts for downstream renders"
```

### Task 4.2: Gate `_overview.md` references in phase 2 and phase 3 templates

**Files:**
- Modify: `src/cowork_pilot/orchestrator_templates/phase2_auto.j2`
- Modify: `src/cowork_pilot/orchestrator_templates/phase2_manual.j2`
- Modify: `src/cowork_pilot/orchestrator_templates/phase3_architecture.j2`
- Create: `tests/unit/test_phase23_optional_overview.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/test_phase23_optional_overview.py
from pathlib import Path
from dataclasses import dataclass, field

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path("src/cowork_pilot/orchestrator_templates")


@dataclass
class FakeExtracts:
    shared: bool = True
    overviews: dict[str, bool] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)


@pytest.fixture
def env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), keep_trailing_newline=True)


TEMPLATES = ["phase2_auto.j2", "phase2_manual.j2", "phase3_architecture.j2"]


@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_absent_removes_path(env: Environment, name: str) -> None:
    extracts = FakeExtracts(
        overviews={"host": False, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    out = env.get_template(name).render(extracts=extracts, domain="host", project_slug="demo")
    assert "_overview.md" not in out


@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_present_includes_path(env: Environment, name: str) -> None:
    extracts = FakeExtracts(
        overviews={"host": True, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    out = env.get_template(name).render(extracts=extracts, domain="host", project_slug="demo")
    assert "host/_overview.md" in out
    # voter does not get an overview path even though we're rendering host.
    assert "voter/_overview.md" not in out
```

- [ ] **Step 2: Run and confirm failure.**

Run: `pytest tests/unit/test_phase23_optional_overview.py -xvs`

- [ ] **Step 3: Edit each template to gate `_overview.md` references.**

Find the line in each template that reads something like:

```markdown
- `domain-extracts/{{ domain }}/_overview.md`
```

Replace it with:

```jinja
{% if extracts.overviews.get(domain) %}
- `domain-extracts/{{ domain }}/_overview.md`
{% endif %}
```

If the template lists overview paths for *all* domains (not just `domain`), replace the loop with:

```jinja
{% for d, present in extracts.overviews.items() if present %}
- `domain-extracts/{{ d }}/_overview.md`
{% endfor %}
```

- [ ] **Step 4: Run the test and iterate.**

Run: `pytest tests/unit/test_phase23_optional_overview.py -xvs`
Expected: all 6 parametrized cases PASS.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "feat(templates): phase2/phase3 read _overview.md only when present"
```

### Task 4.3: Give phase 2/3 templates access to the decision rationale (optional context only)

**Files:**
- Modify: `src/cowork_pilot/orchestrator_templates/phase2_auto.j2`
- Modify: `src/cowork_pilot/orchestrator_templates/phase2_manual.j2`
- Modify: `src/cowork_pilot/orchestrator_templates/phase3_architecture.j2`
- Modify: `<PR>`
- Modify: `tests/unit/test_phase23_optional_overview.py`

- [ ] **Step 1: Add the test.**

```python
@pytest.mark.parametrize("name", TEMPLATES)
def test_overview_decision_reasons_are_passed_through(env: Environment, name: str) -> None:
    extracts = FakeExtracts(
        overviews={"host": True, "voter": False},
        features={"host": ["create-poll.md"], "voter": ["cast-vote.md"]},
    )
    overview_reasons = {
        "host": "poll lifecycle shared",
        "voter": "self contained",
    }
    out = env.get_template(name).render(
        extracts=extracts,
        overview_reasons=overview_reasons,
        domain="host",
        project_slug="demo",
    )
    assert "poll lifecycle shared" in out
    assert "self contained" in out
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Extend the renderer to pass `overview_reasons`.**

In `<PR>`, after computing `available_extracts`, also read `analysis-report.md` and call `load_overview_decisions_tolerant`. If a decision map is returned, flatten it into `{domain: reason}` and pass as `overview_reasons`. If it is `None`, pass `{}`.

- [ ] **Step 4: Extend each template with a short "Domain context" section.**

```jinja
{% if overview_reasons %}
### Domain Overview Decisions (컨텍스트)

{% for d, reason in overview_reasons.items() %}
- **{{ d }}**: {{ "overview 있음" if extracts.overviews.get(d) else "overview 없음" }} — {{ reason }}
{% endfor %}

이 목록은 참고용 컨텍스트다. 파일이 실제로 존재하는지 여부만 읽기 판단에 사용한다.
{% endif %}
```

- [ ] **Step 5: Run the test.**

Run: `pytest tests/unit/test_phase23_optional_overview.py -xvs`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add -A
git commit -m "feat(templates): surface overview decision reasons as phase2/3 context"
```

---

## Chunk 5: End-to-end tests and release verification

This chunk adds E2E tests that exercise the full flow, then runs the complete test suite.

### Task 5.1: Create fixture factory for projects

**Files:**
- Create: `tests/e2e/conftest.py`

- [ ] **Step 1: Create the conftest.**

```python
# tests/e2e/conftest.py
from pathlib import Path

import pytest


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _decision_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "## Domain Overview Decisions",
        "",
        "| domain | overview_needed | reason |",
        "|---|---|---|",
    ]
    for d, needed, reason in rows:
        lines.append(f"| {d} | {needed} | {reason} |")
    return "\n".join(lines) + "\n"


@pytest.fixture
def mixed_project(tmp_path: Path) -> Path:
    project = tmp_path / "mixed"
    extracts = project / "domain-extracts"
    _write(
        project / "analysis-report.md",
        "# Analysis Report\n\n"
        + _decision_table([
            ("host", "yes", "poll lifecycle shared"),
            ("voter", "no", "self contained"),
        ]),
    )
    _write(extracts / "shared.md", "# shared\n")
    _write(extracts / "host" / "_overview.md", "# host overview\n" + "line\n" * 15)
    _write(extracts / "host" / "create-poll.md", "# create poll\n")
    _write(extracts / "host" / "close-poll.md", "# close poll\n")
    _write(extracts / "voter" / "cast-vote.md", "# cast vote\n")
    return project


@pytest.fixture
def small_project(tmp_path: Path) -> Path:
    project = tmp_path / "small"
    extracts = project / "domain-extracts"
    _write(
        project / "analysis-report.md",
        "# Analysis Report\n\n"
        + _decision_table([
            ("core", "no", "single feature domain"),
        ]),
    )
    _write(extracts / "shared.md", "# shared\n")
    _write(extracts / "core" / "do-the-thing.md", "# do it\n")
    return project
```

- [ ] **Step 2: Commit (no test yet; conftest only).**

```bash
git add -A
git commit -m "test(e2e): add project fixture factories"
```

### Task 5.2: E2E: quality gate + renderer on mixed project

**Files:**
- Create: `tests/e2e/test_mixed_project.py`

- [ ] **Step 1: Write the test.**

```python
from pathlib import Path

from cowork_pilot.orchestrator.<QG_MODULE> import evaluate_phase1
from cowork_pilot.orchestrator.<PR_MODULE> import compute_available_extracts


def test_mixed_project_phase1_passes(mixed_project: Path) -> None:
    result = evaluate_phase1(mixed_project)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_mixed_project_extracts_reflect_disk(mixed_project: Path) -> None:
    info = compute_available_extracts(mixed_project / "domain-extracts")
    assert info.shared is True
    assert info.overviews == {"host": True, "voter": False}
    assert sorted(info.features["host"]) == ["close-poll.md", "create-poll.md"]
    assert sorted(info.features["voter"]) == ["cast-vote.md"]


def test_mixed_project_phase2_auto_prompt_has_host_overview(mixed_project: Path) -> None:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("src/cowork_pilot/orchestrator_templates"))
    info = compute_available_extracts(mixed_project / "domain-extracts")
    out = env.get_template("phase2_auto.j2").render(
        extracts=info,
        overview_reasons={"host": "poll lifecycle shared", "voter": "self contained"},
        domain="host",
        project_slug="mixed",
    )
    assert "host/_overview.md" in out
    assert "voter/_overview.md" not in out
```

- [ ] **Step 2: Run and iterate.**

Run: `pytest tests/e2e/test_mixed_project.py -xvs`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add -A
git commit -m "test(e2e): mixed project with one overview-needed and one not"
```

### Task 5.3: E2E: small project that produces no overview at all

**Files:**
- Create: `tests/e2e/test_small_project_no_overview.py`

- [ ] **Step 1: Write the test.**

```python
from pathlib import Path

from cowork_pilot.orchestrator.<QG_MODULE> import evaluate_phase1
from cowork_pilot.orchestrator.<PR_MODULE> import compute_available_extracts


def test_small_project_passes_without_overview(small_project: Path) -> None:
    result = evaluate_phase1(small_project)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_small_project_phase3_prompt_has_no_overview_path(small_project: Path) -> None:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("src/cowork_pilot/orchestrator_templates"))
    info = compute_available_extracts(small_project / "domain-extracts")
    out = env.get_template("phase3_architecture.j2").render(
        extracts=info,
        overview_reasons={"core": "single feature domain"},
        domain="core",
        project_slug="small",
    )
    assert "_overview.md" not in out
```

- [ ] **Step 2: Run and iterate.**

Run: `pytest tests/e2e/test_small_project_no_overview.py -xvs`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add -A
git commit -m "test(e2e): small project with no overviews"
```

### Task 5.4: Full suite verification

- [ ] **Step 1: Run the full test suite.**

Run: `pytest -x`
Expected: all tests PASS.

- [ ] **Step 2: Run ruff / mypy if the project uses them.**

```bash
ruff check src tests
mypy src
```
Expected: no new errors. If the project does not use these, skip.

- [ ] **Step 3: Smoke-render every template one last time.**

```bash
python -c "
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('src/cowork_pilot/orchestrator_templates'))
for name in ['phase1_single.j2','phase1_domain.j2','phase2_auto.j2','phase2_manual.j2','phase3_architecture.j2']:
    print('---', name)
    print(env.get_template(name).render(
        project_slug='demo', domain='host',
        extracts=type('E',(),{'shared':True,'overviews':{'host':True},'features':{'host':['create-poll.md']}})(),
        overview_reasons={'host':'shared lifecycle'},
    )[:200])
"
```
Expected: each template renders without raising.

- [ ] **Step 4: Commit (empty commit as a release marker).**

```bash
git commit --allow-empty -m "chore: overview-optional refactor complete"
```

---

## Chunk 6: Documentation and release notes

### Task 6.1: Update the docs-orchestrator user-facing doc

**Files:**
- Modify: the docs-orchestrator user guide / README (exact path to be discovered; grep for `_overview.md` in `docs/`).

- [x] **Step 1: Grep.**

```bash
rg -n "_overview.md" docs
```

- [x] **Step 2: For each hit, rewrite the surrounding paragraph.**

Key points the doc must now state:

- The three-layer rule (shared / overview / feature) with concrete yes/no criteria.
- `_overview.md` is optional and governed by the `Domain Overview Decisions` table in `analysis-report.md`.
- Missing `_overview.md` is not a hard fail; it is a warning.
- Existing projects continue to work without the decision table (legacy mode).
- Downstream phases automatically skip overview files that do not exist on disk.

- [ ] **Step 3: Commit.** (deferred — user requested no commit for this execution)

```bash
git add -A
git commit -m "docs: document overview-optional contract and migration notes"
```

### Task 6.2: Release note

**Files:**
- Create or modify: `CHANGELOG.md` (or wherever the project records release notes).

- [x] **Step 1: Add an entry.**

```markdown
## Unreleased

### Changed
- `domain/_overview.md` is now a conditional Phase 1 artifact. Whether it is generated is
  governed by a new `Domain Overview Decisions` table that every `analysis-report.md` must
  contain. Phase 2 and Phase 3 templates now read `_overview.md` only when the file exists
  on disk.

### Migration
- Existing projects that predate the decision table continue to run without hard failures.
  New Phase 1 runs populate the decision table automatically.

### Rules
- `shared.md`: 2개 이상 도메인이 참조하는 전역 공통 정보.
- `domain/_overview.md`: 한 도메인의 2개 이상 feature가 실제로 공유하는 맥락이 있을 때만 생성.
- `domain/feature.md`: 단일 feature 전용 정보.
```

- [ ] **Step 2: Commit.** (deferred — user requested no commit for this execution)

```bash
git add -A
git commit -m "docs: changelog entry for overview-optional refactor"
```

---

## Final verification checklist

Before declaring the plan complete, confirm each of these by running the stated command and reading the output.

- [ ] `pytest -x` — all unit and e2e tests pass.
- [ ] `rg -n "_overview.md" src/cowork_pilot/orchestrator_templates` — every hit is inside an `{% if %}` block or inside prose outside the machine-readable `출력 파일:` bullet list.
- [ ] `rg -n "_overview.md" tests` — every hit is in a test that explicitly tests either presence or absence.
- [ ] `rg -n "missing_features" src` — no call site still conflates `shared.md`, feature files, and `_overview.md`.
- [ ] Manually render `phase1_domain.j2` with a `no`-decision fixture and verify the output tells the LLM *not* to create `_overview.md`.
- [ ] Manually render `phase2_auto.j2` with `extracts.overviews={'host': False}` and verify the output contains no `host/_overview.md` path.
- [ ] Re-read the Invariants section at the top of this plan and tick off each one against the final diff.

One-line summary: `_overview.md` stays in the design but is downgraded to an optional artifact governed by a mandatory decision table in `analysis-report.md`; the quality gate splits into hard-fail (shared, features) and warning (overviews); downstream phase templates read overview files only when they exist on disk.
