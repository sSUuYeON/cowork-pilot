# Planning Operations Upgrade Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the planning mode pipeline from "structured local pipeline with state" to "production-grade multi-session document factory" by porting docs-orchestrator's operational strengths: outline→numbered exec-plans, quality gate+rollback, crash recovery, session estimation, final summary, and resume CLI.

**Architecture:** The plan modifies the existing planning module in-place. New capabilities are added as new files or extensions to existing files, following the current pattern of small focused modules. The pipeline loop in `pipeline.py` is converted from `enumerate()` to a `while` index loop to support dynamic dispatch injection. It gains a post-stage quality gate hook, a recovery preamble, and a two-phase exec-plan authoring flow (skeleton → per-feature detail). All new code is TDD.

**Tech Stack:** Python 3.11+, pytest, existing planning module conventions (frozen dataclasses, tuple returns, Path-based I/O, monkeypatch-based test mocking).

### Critical Design Decisions

1. **Loop conversion**: The current `for dispatch_index, dispatch in enumerate(dispatches)` loop is converted to `while dispatch_index < len(dispatches)` to allow dynamic injection of detail dispatches after outline completes. This avoids tuple immutability issues and stale iterator state.

2. **Retry counter persistence**: Retry counts per dispatch are stored in `retry-counts.json` alongside `run-state.json`, so they survive crashes and resume.

3. **Completed-stages idempotency**: `write_completed_stage()` deduplicates by `dispatch_index` key to prevent double-counting on resume.

4. **Zero-feature guard**: Quality gate for `EXEC_PLAN_SKELETON` validates both file size AND parsed feature count. If `parse_skeleton_features()` returns 0, gate fails with retry recommendation.

5. **EXEC_PLAN_AUTHORING backward compatibility**: The enum value is kept but deprecated. Recovery logic maps old `exec_plan_authoring` runs to `EXEC_PLAN_SKELETON`. New dispatches never use `EXEC_PLAN_AUTHORING`.

7. **Three-phase exec-plan generation**: Skeleton (1 session, structure only) → per-feature outline (N sessions, chunk decomposition) → local merge (Python, no AI) → per-feature detail (N sessions, session prompts). This keeps each AI session's context clean and focused on one feature at a time.

6. **File deletion logging**: Recovery module logs all deletions to `runtime-events.ndjson` before unlinking, matching existing `append_runtime_event()` pattern.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/cowork_pilot/planning/outline.py` | Skeleton outline generation, per-feature detail session dispatch, outline parsing, merge logic |
| `src/cowork_pilot/planning/quality_gate.py` | Post-stage quality gate evaluation, rollback decision, retry orchestration |
| `src/cowork_pilot/planning/recovery.py` | Crash recovery (3-step policy), completed-step skip logic |
| `src/cowork_pilot/planning/estimation.py` | Session count estimation, time range calculation |
| `src/cowork_pilot/planning/summary.py` | Final completion summary, macOS notification |
| `tests/test_planning_outline.py` | Tests for outline module |
| `tests/test_planning_quality_gate.py` | Tests for quality gate module |
| `tests/test_planning_recovery.py` | Tests for recovery module |
| `tests/test_planning_estimation.py` | Tests for estimation module |
| `tests/test_planning_summary.py` | Tests for summary module |

### Modified Files

| File | Change |
|------|--------|
| `src/cowork_pilot/planning/pipeline.py` | Replace `_write_pipeline_exec_plan()` with outline→detail flow; add quality gate hook after AI stages; add recovery preamble in `_run_planning_stage_graph()`; add completed-step skip; call summary at end |
| `src/cowork_pilot/planning/authoring.py` | Extend `write_exec_plan()` to support numbered plan names; add `write_numbered_exec_plan()` |
| `src/cowork_pilot/planning/models.py` | Add `EXEC_PLAN_OUTLINE` and `EXEC_PLAN_DETAIL` to `PlanningStage` enum; add `OutlinePlan` dataclass; extend `PlanningPipelineResult` with `exec_plan_paths: list[Path]` and `summary: PipelineSummary | None` |
| `src/cowork_pilot/planning/session_profiles.py` | Add session profiles for new stages `EXEC_PLAN_OUTLINE` and `EXEC_PLAN_DETAIL` |
| `src/cowork_pilot/planning/runtime_storage.py` | Add `read_completed_stages()` / `write_completed_stage()` for step-level tracking |
| `src/cowork_pilot/planning/runner.py` | Add `resume_planning_pipeline()` public function for CLI resume |
| `src/cowork_pilot/planning/review.py` | Add `should_rollback()` that converts `ReviewVerdict` into rollback decision |
| `src/cowork_pilot/planning/__init__.py` | Export new public symbols |
| `src/cowork_pilot/main.py` | Add `planning resume` subcommand; add `--estimate` flag; print summary |
| `src/cowork_pilot/planning/prompts.py` | Add prompt templates for `EXEC_PLAN_OUTLINE` and `EXEC_PLAN_DETAIL` stages |

---

## Chunk 1: Outline → Numbered Exec-Plans

This chunk replaces the current single-file `exec-plan.md` generation with a **three-phase** process:

1. **Skeleton session** (1 AI session): produces `exec-plan-skeleton.md` — feature 목록, 의존관계, 전체 실행 순서만 잡음. chunk 분해는 하지 않음.
2. **Per-feature outline sessions** (N AI sessions): 각 feature에 대해 새 세션을 열어 해당 feature의 chunk 분해, completion criteria, task 목록을 상세 작성. 결과는 `feature-outlines/{feature-name}.md`에 저장.
3. **Local merge** (Python): skeleton의 순서 + 각 feature outline을 합쳐서 `exec-plan-outline.md`를 조립.
4. **Per-feature detail sessions** (N AI sessions): 각 numbered plan에 대해 session prompt를 채워 `docs/exec-plans/planning/01-xxx.md`, `02-yyy.md`를 생성.

이 구조의 핵심:
- skeleton 세션은 전체 구조만 잡으므로 컨텍스트가 가벼움
- per-feature outline 세션은 해당 feature의 스펙 + gap 문서만 읽으므로 컨텍스트가 깨끗함
- detail 세션은 완성된 outline을 기반으로 session prompt만 채우면 됨

새 stage 흐름: `... → PLAN_REVIEW → EXEC_PLAN_SKELETON → EXEC_PLAN_FEATURE_OUTLINE (×N) → [local merge] → EXEC_PLAN_DETAIL (×N)`

### Task 1: Add new stage enums and data models

**Files:**
- Modify: `src/cowork_pilot/planning/models.py`
- Test: `tests/test_planning_models.py`

- [ ] **Step 1: Write failing test for new stage enums**

```python
# tests/test_planning_models.py — append

def test_planning_stage_includes_exec_plan_skeleton_feature_outline_and_detail():
    assert PlanningStage.EXEC_PLAN_SKELETON.value == "exec_plan_skeleton"
    assert PlanningStage.EXEC_PLAN_FEATURE_OUTLINE.value == "exec_plan_feature_outline"
    assert PlanningStage.EXEC_PLAN_DETAIL.value == "exec_plan_detail"


def test_outline_plan_dataclass_fields():
    from cowork_pilot.planning.models import OutlinePlan
    plan = OutlinePlan(number="01", name="project-setup", filename="01-project-setup.md", feature_scope=("auth",))
    assert plan.number == "01"
    assert plan.name == "project-setup"
    assert plan.filename == "01-project-setup.md"
    assert plan.feature_scope == ("auth",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_models.py::test_planning_stage_includes_exec_plan_skeleton_feature_outline_and_detail -v`
Expected: FAIL with `AttributeError: EXEC_PLAN_SKELETON`

- [ ] **Step 3: Add enums and dataclass to models.py**

```python
# In PlanningStage enum, add after EXEC_PLAN_AUTHORING:
    EXEC_PLAN_SKELETON = "exec_plan_skeleton"
    EXEC_PLAN_FEATURE_OUTLINE = "exec_plan_feature_outline"
    EXEC_PLAN_DETAIL = "exec_plan_detail"


# New dataclass after PlanningPipelineResult:
@dataclass(frozen=True)
class OutlinePlan:
    number: str
    name: str
    filename: str
    feature_scope: tuple[str, ...] = ()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Extend PlanningPipelineResult**

Add `exec_plan_paths: tuple[Path, ...] = ()` field to `PlanningPipelineResult`. Update `_build_pipeline_result()` in `pipeline.py` to pass this field.

- [ ] **Step 6: Commit**

```bash
git add src/cowork_pilot/planning/models.py tests/test_planning_models.py src/cowork_pilot/planning/pipeline.py
git commit -m "feat(planning): add EXEC_PLAN_SKELETON/FEATURE_OUTLINE/DETAIL stages and OutlinePlan model"
```

### Task 2: Create outline parsing module

**Files:**
- Create: `src/cowork_pilot/planning/outline.py`
- Create: `tests/test_planning_outline.py`

- [ ] **Step 1: Write failing test for outline parsing**

```python
# tests/test_planning_outline.py

from cowork_pilot.planning.outline import parse_outline_plans


_SAMPLE_OUTLINE = """\
## exec-plan 개요

| # | 파일명 | 범위 | Chunk 수 | 의존성 |
|---|--------|------|---------|--------|
| 1 | 01-project-setup.md | 초기화 | 3 | 없음 |
| 2 | 02-auth-flow.md | 인증 | 5 | 01 |
| 3 | 03-data-layer.md | DB | 4 | 01 |

## 01-project-setup.md 상세

### Chunk 1: 환경설정
...

## 02-auth-flow.md 상세

### Chunk 1: 로그인
...

## 03-data-layer.md 상세

### Chunk 1: 스키마
...
"""


def test_parse_outline_plans_extracts_all_plans():
    plans = parse_outline_plans(_SAMPLE_OUTLINE)
    assert len(plans) == 3
    assert plans[0].number == "01"
    assert plans[0].name == "project-setup"
    assert plans[0].filename == "01-project-setup.md"
    assert plans[1].number == "02"
    assert plans[1].name == "auth-flow"
    assert plans[2].number == "03"


def test_parse_outline_plans_deduplicates_table_and_header_matches():
    plans = parse_outline_plans(_SAMPLE_OUTLINE)
    names = [p.filename for p in plans]
    assert len(names) == len(set(names))


def test_parse_outline_plans_returns_empty_on_empty_input():
    assert parse_outline_plans("") == ()


def test_parse_outline_plans_sorted_by_number():
    reversed_outline = """\
| 1 | 03-z.md | z | 1 | - |
| 2 | 01-a.md | a | 1 | - |

## 01-a.md 상세
## 03-z.md 상세
"""
    plans = parse_outline_plans(reversed_outline)
    assert plans[0].number == "01"
    assert plans[1].number == "03"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `parse_outline_plans()`**

```python
# src/cowork_pilot/planning/outline.py
from __future__ import annotations

import re
from pathlib import Path

from cowork_pilot.planning.models import OutlinePlan

_TABLE_PATTERN = re.compile(
    r"^\|\s*\d+\s*\|\s*(\d{2}-[a-zA-Z0-9_-]+)\.md\s*\|",
    re.MULTILINE,
)
_HEADER_PATTERN = re.compile(
    r"^##\s+(\d{2}-[a-zA-Z0-9_-]+)\.md",
    re.MULTILINE,
)


def parse_outline_plans(content: str) -> tuple[OutlinePlan, ...]:
    """Parse exec-plan outline to extract numbered plan entries."""
    seen: set[str] = set()
    plans: list[OutlinePlan] = []

    for pattern in (_TABLE_PATTERN, _HEADER_PATTERN):
        for match in pattern.finditer(content):
            name_with_number = match.group(1)
            if name_with_number in seen:
                continue
            seen.add(name_with_number)
            parts = name_with_number.split("-", 1)
            number = parts[0]
            bare_name = parts[1] if len(parts) > 1 else name_with_number
            plans.append(OutlinePlan(
                number=number,
                name=bare_name,
                filename=f"{name_with_number}.md",
            ))

    plans.sort(key=lambda p: p.number)
    return tuple(plans)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/outline.py tests/test_planning_outline.py
git commit -m "feat(planning): add outline parser for numbered exec-plans"
```

### Task 3: Build per-feature detail dispatch

**Files:**
- Modify: `src/cowork_pilot/planning/outline.py`
- Test: `tests/test_planning_outline.py`

- [ ] **Step 1: Write failing test for feature-to-plan mapping**

```python
# tests/test_planning_outline.py — append

def test_build_detail_dispatches_creates_one_per_plan():
    from cowork_pilot.planning.outline import build_detail_dispatches
    from cowork_pilot.planning.models import OutlinePlan, StageDispatch, PlanningStage

    plans = (
        OutlinePlan(number="01", name="project-setup", filename="01-project-setup.md"),
        OutlinePlan(number="02", name="auth-flow", filename="02-auth-flow.md"),
    )
    dispatches = build_detail_dispatches(plans, start_order=20)
    assert len(dispatches) == 2
    assert all(d.stage is PlanningStage.EXEC_PLAN_DETAIL for d in dispatches)
    assert dispatches[0].substage == "01-project-setup"
    assert dispatches[0].order == 20
    assert dispatches[1].substage == "02-auth-flow"
    assert dispatches[1].order == 21
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py::test_build_detail_dispatches_creates_one_per_plan -v`
Expected: FAIL

- [ ] **Step 3: Implement `build_detail_dispatches()`**

```python
# src/cowork_pilot/planning/outline.py — append

from cowork_pilot.planning.models import StageDispatch, PlanningStage


def build_detail_dispatches(
    plans: tuple[OutlinePlan, ...],
    *,
    start_order: int,
) -> tuple[StageDispatch, ...]:
    """Create one EXEC_PLAN_DETAIL dispatch per outline plan."""
    return tuple(
        StageDispatch(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            execution_kind="ai",
            order=start_order + index,
            substage=f"{plan.number}-{plan.name}",
        )
        for index, plan in enumerate(plans)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/outline.py tests/test_planning_outline.py
git commit -m "feat(planning): add detail dispatch builder for per-feature exec-plan sessions"
```

### Task 3.5: Build per-feature outline dispatch and skeleton parser

**Files:**
- Modify: `src/cowork_pilot/planning/outline.py`
- Test: `tests/test_planning_outline.py`

This task adds the ability to create one `EXEC_PLAN_FEATURE_OUTLINE` dispatch per feature extracted from the skeleton. The skeleton output is simpler than the full outline — it contains only feature names, ordering, and dependencies.

- [ ] **Step 1: Write failing test for skeleton parsing**

```python
# tests/test_planning_outline.py — append

def test_parse_skeleton_features_extracts_ordered_features():
    from cowork_pilot.planning.outline import parse_skeleton_features

    skeleton = """\
# Exec-Plan Skeleton

## 실행 순서

| # | Feature | 의존성 |
|---|---------|--------|
| 1 | auth | 없음 |
| 2 | user-profile | auth |
| 3 | notifications | auth, user-profile |

## 의존관계 요약
auth → user-profile → notifications
"""
    features = parse_skeleton_features(skeleton)
    assert len(features) == 3
    assert features[0] == "auth"
    assert features[1] == "user-profile"
    assert features[2] == "notifications"


def test_parse_skeleton_features_returns_empty_on_no_table():
    from cowork_pilot.planning.outline import parse_skeleton_features
    assert parse_skeleton_features("no table here") == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py::test_parse_skeleton_features_extracts_ordered_features -v`
Expected: FAIL

- [ ] **Step 3: Implement `parse_skeleton_features()`**

```python
# src/cowork_pilot/planning/outline.py — append

_SKELETON_TABLE_PATTERN = re.compile(
    r"^\|\s*\d+\s*\|\s*([a-zA-Z0-9_-]+)\s*\|",
    re.MULTILINE,
)


def parse_skeleton_features(content: str) -> tuple[str, ...]:
    """Parse skeleton output to extract ordered feature names."""
    features: list[str] = []
    seen: set[str] = set()
    for match in _SKELETON_TABLE_PATTERN.finditer(content):
        name = match.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            features.append(name)
    return tuple(features)
```

- [ ] **Step 4: Write failing test for feature outline dispatch builder**

```python
# tests/test_planning_outline.py — append

def test_build_feature_outline_dispatches_creates_one_per_feature():
    from cowork_pilot.planning.outline import build_feature_outline_dispatches
    from cowork_pilot.planning.models import PlanningStage

    features = ("auth", "user-profile", "notifications")
    dispatches = build_feature_outline_dispatches(features, start_order=15)
    assert len(dispatches) == 3
    assert all(d.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE for d in dispatches)
    assert dispatches[0].substage == "auth"
    assert dispatches[0].order == 15
    assert dispatches[1].substage == "user-profile"
    assert dispatches[2].substage == "notifications"
```

- [ ] **Step 5: Implement `build_feature_outline_dispatches()`**

```python
# src/cowork_pilot/planning/outline.py — append

def build_feature_outline_dispatches(
    features: tuple[str, ...],
    *,
    start_order: int,
) -> tuple[StageDispatch, ...]:
    """Create one EXEC_PLAN_FEATURE_OUTLINE dispatch per feature from skeleton."""
    return tuple(
        StageDispatch(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            execution_kind="ai",
            order=start_order + index,
            substage=feature,
        )
        for index, feature in enumerate(features)
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/cowork_pilot/planning/outline.py tests/test_planning_outline.py
git commit -m "feat(planning): add skeleton parser and per-feature outline dispatch builder"
```

### Task 3.6: Local merge — assemble feature outlines into unified outline

**Files:**
- Modify: `src/cowork_pilot/planning/outline.py`
- Test: `tests/test_planning_outline.py`

After all per-feature outline sessions complete, a local Python function reads the skeleton (for ordering) and each `feature-outlines/{feature}.md` file, then assembles them into a single `exec-plan-outline.md` with proper numbering.

- [ ] **Step 1: Write failing test for merge**

```python
# tests/test_planning_outline.py — append

def test_merge_feature_outlines_produces_numbered_outline(tmp_path):
    from cowork_pilot.planning.outline import merge_feature_outlines

    skeleton = """\
| # | Feature | 의존성 |
|---|---------|--------|
| 1 | auth | 없음 |
| 2 | data-layer | auth |
"""
    (tmp_path / "exec-plan-skeleton.md").write_text(skeleton, encoding="utf-8")

    outlines_dir = tmp_path / "feature-outlines"
    outlines_dir.mkdir()
    (outlines_dir / "auth.md").write_text(
        "## auth\n\n### Chunk 1: Login\n- Completion Criteria:\n  - [ ] Login works\n- Tasks:\n  - Task 1: Build form\n",
        encoding="utf-8",
    )
    (outlines_dir / "data-layer.md").write_text(
        "## data-layer\n\n### Chunk 1: Schema\n- Completion Criteria:\n  - [ ] Tables created\n- Tasks:\n  - Task 1: Define schema\n",
        encoding="utf-8",
    )

    result = merge_feature_outlines(run_dir=tmp_path)
    assert result is not None
    content = result.read_text(encoding="utf-8")

    # Check numbering
    assert "01-auth.md" in content
    assert "02-data-layer.md" in content
    # Check feature content is included
    assert "Login" in content
    assert "Schema" in content


def test_merge_feature_outlines_skips_missing_features(tmp_path):
    from cowork_pilot.planning.outline import merge_feature_outlines

    skeleton = "| 1 | auth | - |\n| 2 | missing-feature | - |"
    (tmp_path / "exec-plan-skeleton.md").write_text(skeleton, encoding="utf-8")

    outlines_dir = tmp_path / "feature-outlines"
    outlines_dir.mkdir()
    (outlines_dir / "auth.md").write_text("## auth\n### Chunk 1: Login\n...\n", encoding="utf-8")
    # missing-feature.md intentionally not created

    result = merge_feature_outlines(run_dir=tmp_path)
    content = result.read_text(encoding="utf-8")
    assert "01-auth.md" in content
    # missing feature gets a placeholder warning
    assert "02-missing-feature.md" in content
    assert "WARNING" in content or "missing" in content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py::test_merge_feature_outlines_produces_numbered_outline -v`
Expected: FAIL

- [ ] **Step 3: Implement `merge_feature_outlines()`**

```python
# src/cowork_pilot/planning/outline.py — append

def merge_feature_outlines(*, run_dir: Path) -> Path:
    """Merge skeleton ordering + per-feature outline files into exec-plan-outline.md.

    Reads:
      - run_dir/exec-plan-skeleton.md (for feature ordering)
      - run_dir/feature-outlines/{feature}.md (per-feature chunk details)

    Writes:
      - run_dir/exec-plan-outline.md (unified, numbered outline)
    """
    skeleton_path = run_dir / "exec-plan-skeleton.md"
    skeleton_content = skeleton_path.read_text(encoding="utf-8") if skeleton_path.exists() else ""
    features = parse_skeleton_features(skeleton_content)

    outlines_dir = run_dir / "feature-outlines"
    sections: list[str] = []

    # Header table
    table_lines = [
        "## exec-plan 개요\n",
        "| # | 파일명 | 범위 |",
        "|---|--------|------|",
    ]
    for idx, feature in enumerate(features, 1):
        number = f"{idx:02d}"
        table_lines.append(f"| {idx} | {number}-{feature}.md | {feature} |")
    sections.append("\n".join(table_lines))

    # Per-feature sections
    for idx, feature in enumerate(features, 1):
        number = f"{idx:02d}"
        feature_file = outlines_dir / f"{feature}.md"
        if feature_file.exists():
            feature_content = feature_file.read_text(encoding="utf-8")
            sections.append(f"\n## {number}-{feature}.md 상세\n\n{feature_content}")
        else:
            sections.append(f"\n## {number}-{feature}.md 상세\n\n> WARNING: Feature outline missing for {feature}\n")

    outline_path = run_dir / "exec-plan-outline.md"
    outline_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return outline_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_outline.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/outline.py tests/test_planning_outline.py
git commit -m "feat(planning): add local merge to assemble per-feature outlines into unified outline"
```

### Task 4: Write numbered exec-plan files

**Files:**
- Modify: `src/cowork_pilot/planning/authoring.py`
- Test: `tests/test_planning_runner.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_planning_runner.py — append

def test_write_numbered_exec_plan_creates_file_with_number_prefix(tmp_path):
    from cowork_pilot.planning.authoring import write_numbered_exec_plan

    source = tmp_path / "detail.md"
    source.write_text("# Auth Flow\n\n## Chunk 1\n...", encoding="utf-8")
    dest_dir = tmp_path / "docs" / "exec-plans" / "planning"

    result = write_numbered_exec_plan(source, dest_dir, plan_name="02-auth-flow")
    assert result is not None
    assert result.name == "02-auth-flow.md"
    assert result.read_text(encoding="utf-8").startswith("# Auth Flow")


def test_write_numbered_exec_plan_rejects_path_escape(tmp_path):
    import pytest
    from cowork_pilot.planning.authoring import write_numbered_exec_plan

    source = tmp_path / "detail.md"
    source.write_text("content", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        write_numbered_exec_plan(source, tmp_path, plan_name="../escape")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runner.py::test_write_numbered_exec_plan_creates_file_with_number_prefix -v`
Expected: FAIL

- [ ] **Step 3: Implement `write_numbered_exec_plan()`**

```python
# src/cowork_pilot/planning/authoring.py — append

def write_numbered_exec_plan(
    source_path: Path | None = None,
    destination_dir: Path | None = None,
    plan_name: str = "",
) -> Path | None:
    """Write a single numbered exec-plan file (e.g. 02-auth-flow.md)."""
    if source_path is None or destination_dir is None or not plan_name:
        return None
    _validate_relative_name(f"{plan_name}.md", "plan_name")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / f"{plan_name}.md"
    destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return destination_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runner.py::test_write_numbered_exec_plan_creates_file_with_number_prefix tests/test_planning_runner.py::test_write_numbered_exec_plan_rejects_path_escape -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/authoring.py tests/test_planning_runner.py
git commit -m "feat(planning): add write_numbered_exec_plan for individual plan files"
```

### Task 5: Add session profiles for new stages

**Files:**
- Modify: `src/cowork_pilot/planning/session_profiles.py`
- Test: `tests/test_planning_session_profiles.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_planning_session_profiles.py — append

def test_exec_plan_skeleton_is_ai_stage():
    from cowork_pilot.planning.session_profiles import resolve_stage_execution_kind
    from cowork_pilot.planning.models import PlanningStage, SizeClass
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_SKELETON, SizeClass.SMALL) == "ai"


def test_exec_plan_feature_outline_is_ai_stage():
    from cowork_pilot.planning.session_profiles import resolve_stage_execution_kind
    from cowork_pilot.planning.models import PlanningStage, SizeClass
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_FEATURE_OUTLINE, SizeClass.SMALL) == "ai"


def test_exec_plan_detail_is_ai_stage():
    from cowork_pilot.planning.session_profiles import resolve_stage_execution_kind
    from cowork_pilot.planning.models import PlanningStage, SizeClass
    assert resolve_stage_execution_kind(PlanningStage.EXEC_PLAN_DETAIL, SizeClass.SMALL) == "ai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_session_profiles.py::test_exec_plan_skeleton_is_ai_stage -v`
Expected: FAIL

- [ ] **Step 3: Add profiles to STAGE_SESSION_PROFILE_MATRIX**

Add entries for `EXEC_PLAN_SKELETON`, `EXEC_PLAN_FEATURE_OUTLINE`, and `EXEC_PLAN_DETAIL` in `session_profiles.py`. All three are `single_session` strategy, `ai` execution kind across all size classes. Feature outline and detail dispatches are dynamically created, so no substage expansion in the profile.

- [ ] **Step 4: Run full session profiles test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_session_profiles.py -v`
Expected: ALL PASS (existing test `test_all_current_stages_have_explicit_session_policy_entries` must also pass)

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/session_profiles.py tests/test_planning_session_profiles.py
git commit -m "feat(planning): add session profiles for EXEC_PLAN_OUTLINE and EXEC_PLAN_DETAIL"
```

### Task 6: Add prompt templates for outline and detail stages

**Files:**
- Modify: `src/cowork_pilot/planning/prompts.py`
- Test: `tests/test_planning_stage_executor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_planning_stage_executor.py — append

def test_render_stage_prompt_for_exec_plan_skeleton():
    from cowork_pilot.planning.prompts import render_stage_prompt
    from cowork_pilot.planning.models import PlanningStage
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_SKELETON)
    assert "skeleton" in prompt.lower() or "순서" in prompt or "의존" in prompt


def test_render_stage_prompt_for_exec_plan_feature_outline():
    from cowork_pilot.planning.prompts import render_stage_prompt
    from cowork_pilot.planning.models import PlanningStage
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_FEATURE_OUTLINE, substage="auth")
    assert "auth" in prompt


def test_render_stage_prompt_for_exec_plan_detail():
    from cowork_pilot.planning.prompts import render_stage_prompt
    from cowork_pilot.planning.models import PlanningStage
    prompt = render_stage_prompt(PlanningStage.EXEC_PLAN_DETAIL, substage="02-auth-flow")
    assert "02-auth-flow" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_executor.py::test_render_stage_prompt_for_exec_plan_skeleton -v`
Expected: FAIL

- [ ] **Step 3: Add prompt templates**

In `prompts.py`, add three template branches:

**EXEC_PLAN_SKELETON prompt**: Reads scope map, review notes, gap artifacts. Produces only: feature list with ordering + dependency table. Does NOT write chunk details. Output: `exec-plan-skeleton.md`.

**EXEC_PLAN_FEATURE_OUTLINE prompt**: Reads skeleton (for context on this feature's position/deps) + this feature's specific spec docs + gap docs. Produces detailed chunk decomposition, completion criteria, and task list for this one feature. Output: `feature-outlines/{feature}.md`.

**EXEC_PLAN_DETAIL prompt**: Reads the merged `exec-plan-outline.md` + this plan's section. Fills in session prompts for each chunk. Output: `detail-{substage}.md`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_executor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/prompts.py tests/test_planning_stage_executor.py
git commit -m "feat(planning): add prompt templates for outline and detail exec-plan stages"
```

### Task 7: Replace single exec-plan with skeleton→feature-outline→merge→detail flow in pipeline

**Files:**
- Modify: `src/cowork_pilot/planning/pipeline.py`
- Test: `tests/test_planning_pipeline_units.py`

- [ ] **Step 1: Write failing test for skeleton stage in dispatch plan**

```python
# tests/test_planning_pipeline_units.py — append

def test_dispatch_plan_replaces_authoring_with_skeleton(tmp_path):
    from cowork_pilot.planning.pipeline import build_stage_dispatch_plan
    from cowork_pilot.planning.models import PlanningContext, PlanningStage, ProjectMode, SizeClass

    context = PlanningContext(run_dir=tmp_path, project_dir=tmp_path, mode=ProjectMode.GREENFIELD, explicit_mode=True)
    dispatches = build_stage_dispatch_plan(context, size_class=SizeClass.SMALL)
    stage_names = [d.stage for d in dispatches]

    assert PlanningStage.EXEC_PLAN_SKELETON in stage_names
    assert PlanningStage.EXEC_PLAN_AUTHORING not in stage_names
    # Feature outline and detail dispatches are injected dynamically, not in initial plan
    assert PlanningStage.EXEC_PLAN_FEATURE_OUTLINE not in stage_names
    assert PlanningStage.EXEC_PLAN_DETAIL not in stage_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py::test_dispatch_plan_replaces_authoring_with_skeleton -v`
Expected: FAIL (EXEC_PLAN_AUTHORING is still present)

- [ ] **Step 3: Replace EXEC_PLAN_AUTHORING with EXEC_PLAN_SKELETON in `build_stage_dispatch_plan()`**

In `pipeline.py`, change the last `_append_stage_dispatches(... PlanningStage.EXEC_PLAN_AUTHORING ...)` call to use `PlanningStage.EXEC_PLAN_SKELETON`. Keep `EXEC_PLAN_AUTHORING` in the enum for backward compat but never dispatch it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py -v`
Expected: ALL PASS

- [ ] **Step 5: Convert dispatch loop from `enumerate()` to `while` index loop**

This is critical. The current `for dispatch_index, dispatch in enumerate(dispatches)` pattern cannot support dynamic injection because tuples are immutable and the iterator state becomes stale. Convert to:

```python
# In _run_planning_stage_graph(), replace the for loop (lines 213-251) with:
dispatches_list: list[StageDispatch] = list(dispatches)
dispatch_index = start_index

while dispatch_index < len(dispatches_list):
    dispatch = dispatches_list[dispatch_index]

    if dispatch.execution_kind == "local":
        outputs = _apply_stage_completion(runtime, dispatch)
        previous_handoff = _write_dispatch_handoff(
            runtime=runtime,
            dispatch=dispatch,
            previous_handoff=previous_handoff,
            outputs=outputs,
            stage_result=None,
        )
        _persist_runtime_state(runtime, next_dispatch_index=dispatch_index + 1)
        dispatch_index += 1
        continue

    stage_prompt = _render_dispatch_prompt(runtime, dispatch, previous_handoff)
    stage_result = stage_executor.execute_stage_subsession(
        run_dir=runtime.run_dir,
        stage=dispatch.stage,
        prompt=stage_prompt,
    )
    if stage_result.runtime_state in _STOP_STATES and stage_result.completed_stage is None:
        _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
        return _build_pipeline_result(
            runtime,
            runtime_state=stage_result.runtime_state,
            stopped_stage=dispatch.stage.value,
        )

    outputs = _apply_stage_completion(runtime, dispatch)

    # Dynamic injection phase 1: after SKELETON, inject per-feature outline dispatches
    if dispatch.stage is PlanningStage.EXEC_PLAN_SKELETON:
        skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"
        if skeleton_path.exists():
            from cowork_pilot.planning.outline import parse_skeleton_features, build_feature_outline_dispatches
            features = parse_skeleton_features(skeleton_path.read_text(encoding="utf-8"))
            if features:
                fo_dispatches = build_feature_outline_dispatches(features, start_order=dispatch.order + 1)
                dispatches_list[dispatch_index + 1:dispatch_index + 1] = list(fo_dispatches)

    # Dynamic injection phase 2: after ALL feature outlines done, run local merge + inject detail dispatches
    if dispatch.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
        # Check if this was the last feature outline dispatch
        remaining_fo = any(
            d.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE
            for d in dispatches_list[dispatch_index + 1:]
        )
        if not remaining_fo:
            # All feature outlines done → local merge
            from cowork_pilot.planning.outline import merge_feature_outlines, parse_outline_plans, build_detail_dispatches
            outline_path = merge_feature_outlines(run_dir=runtime.run_dir)
            plans = parse_outline_plans(outline_path.read_text(encoding="utf-8"))
            if plans:
                detail_dispatches = build_detail_dispatches(plans, start_order=dispatch.order + 1)
                dispatches_list[dispatch_index + 1:dispatch_index + 1] = list(detail_dispatches)

    previous_handoff = _write_dispatch_handoff(
        runtime=runtime,
        dispatch=dispatch,
        previous_handoff=previous_handoff,
        outputs=outputs or stage_result.generated_outputs,
        stage_result=stage_result,
    )
    _persist_runtime_state(runtime, next_dispatch_index=dispatch_index + 1)
    dispatch_index += 1
```

- [ ] **Step 6: Add handler for `EXEC_PLAN_SKELETON` in `_apply_stage_completion()`**

```python
if stage is PlanningStage.EXEC_PLAN_SKELETON:
    skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"
    return (str(skeleton_path),) if skeleton_path.exists() else ()
```

- [ ] **Step 6.5: Add handler for `EXEC_PLAN_FEATURE_OUTLINE` in `_apply_stage_completion()`**

```python
if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
    feature_name = dispatch.substage
    outline_file = runtime.run_dir / "feature-outlines" / f"{feature_name}.md"
    return (str(outline_file),) if outline_file.exists() else ()
```

- [ ] **Step 7: Add handler for `EXEC_PLAN_DETAIL` in `_apply_stage_completion()`**

```python
if stage is PlanningStage.EXEC_PLAN_DETAIL:
    detail_source = runtime.run_dir / f"detail-{dispatch.substage}.md"
    if detail_source.exists():
        from cowork_pilot.planning.authoring import write_numbered_exec_plan
        dest_dir = runtime.project_dir / "docs" / "exec-plans" / "planning"
        result_path = write_numbered_exec_plan(detail_source, dest_dir, plan_name=dispatch.substage)
        if result_path is not None:
            runtime.exec_plan_paths = runtime.exec_plan_paths + (result_path,)
            return (str(result_path),)
    return ()
```

Note: Add `exec_plan_paths: tuple[Path, ...] = ()` to `_PipelineRuntime`.

- [ ] **Step 8: Write integration test for full skeleton→feature-outline→merge→detail flow**

```python
# tests/test_planning_pipeline_units.py — append

def test_pipeline_skeleton_feature_outline_merge_detail_produces_numbered_plans(tmp_path, monkeypatch):
    """Verify full dynamic dispatch injection:
    skeleton → parse features → per-feature outline sessions → local merge → detail sessions.
    """
    from cowork_pilot.planning.models import PlanningStage
    from cowork_pilot.planning.stage_executor import StageExecutionResult

    skeleton_content = """\
# Exec-Plan Skeleton

| # | Feature | 의존성 |
|---|---------|--------|
| 1 | auth | 없음 |
| 2 | data-layer | auth |
"""

    call_log = []

    def fake_execute(*, run_dir, stage, prompt, **kwargs):
        call_log.append(stage.value)

        if stage is PlanningStage.EXEC_PLAN_SKELETON:
            (run_dir / "exec-plan-skeleton.md").write_text(skeleton_content, encoding="utf-8")

        if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
            # Each feature outline session writes to feature-outlines/
            outlines_dir = run_dir / "feature-outlines"
            outlines_dir.mkdir(exist_ok=True)
            # Extract feature name from substage in the dispatch
            # The dispatch substage is set to the feature name
            feature = "auth" if "auth" in prompt else "data-layer"
            (outlines_dir / f"{feature}.md").write_text(
                f"## {feature}\n\n### Chunk 1: Setup\n- Completion Criteria:\n  - [ ] Done\n- Tasks:\n  - Task 1: Build\n",
                encoding="utf-8",
            )

        if stage is PlanningStage.EXEC_PLAN_DETAIL:
            # Write detail file
            # substage is like "01-auth" from the merged outline
            (run_dir / f"detail-{call_log[-1]}-{len(call_log)}.md").write_text(
                f"# Detail\n" + "content\n" * 20,
                encoding="utf-8",
            )

        return StageExecutionResult(
            runtime_state="completed",
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle=None,
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.pipeline.stage_executor.execute_stage_subsession",
        fake_execute,
    )

    # ... setup context and run pipeline ...

    # Verify call sequence
    assert "exec_plan_skeleton" in call_log
    assert call_log.count("exec_plan_feature_outline") == 2  # auth + data-layer
    assert call_log.count("exec_plan_detail") == 2  # 01-auth + 02-data-layer

    # Verify skeleton comes before feature outlines
    skel_idx = call_log.index("exec_plan_skeleton")
    fo_indices = [i for i, v in enumerate(call_log) if v == "exec_plan_feature_outline"]
    detail_indices = [i for i, v in enumerate(call_log) if v == "exec_plan_detail"]
    assert all(fi > skel_idx for fi in fo_indices)
    assert all(di > max(fo_indices) for di in detail_indices)

    # Verify merged outline exists
    assert (tmp_path / "run" / "exec-plan-outline.md").exists()  # adjust path as needed

    # Verify numbered plan files in docs/exec-plans/planning/
    # (depends on detail handler writing to correct location)
```

- [ ] **Step 9: Run full pipeline test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py tests/test_planning_runner.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/cowork_pilot/planning/pipeline.py tests/test_planning_pipeline_units.py tests/test_planning_runner.py
git commit -m "feat(planning): replace single exec-plan with outline→per-feature detail flow

Convert dispatch loop from enumerate() to while-index to support dynamic
injection of detail dispatches after outline completes."
```

---

## Chunk 2: Quality Gate + Rollback + Retry

This chunk adds post-stage quality validation with automatic rollback and retry. When a stage produces low-quality output, the pipeline removes it from completed, optionally deletes its artifacts, and re-runs it. A max retry counter prevents infinite loops.

### Task 8: Create quality gate module

**Files:**
- Create: `src/cowork_pilot/planning/quality_gate.py`
- Create: `tests/test_planning_quality_gate.py`

- [x] **Step 1: Write failing test for gate evaluation**

```python
# tests/test_planning_quality_gate.py

from cowork_pilot.planning.quality_gate import evaluate_stage_gate, GateResult


def test_gate_passes_when_all_outputs_exist(tmp_path):
    output = tmp_path / "coverage-gap.md"
    output.write_text("# Coverage Gap\n\nLine 1\nLine 2\nLine 3\nLine 4\nLine 5\n" * 3, encoding="utf-8")
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
    )
    assert result.passed is True
    assert result.reason == ""


def test_gate_fails_when_output_missing(tmp_path):
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=("nonexistent.md",),
    )
    assert result.passed is False
    assert "missing" in result.reason.lower()


def test_gate_fails_when_output_too_short(tmp_path):
    output = tmp_path / "coverage-gap.md"
    output.write_text("# Title\n", encoding="utf-8")
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
        min_lines=10,
    )
    assert result.passed is False
    assert "short" in result.reason.lower() or "lines" in result.reason.lower()


def test_gate_fails_skeleton_with_zero_parsed_features(tmp_path):
    """Skeleton file exists and is long enough, but contains no parseable feature entries."""
    output = tmp_path / "exec-plan-skeleton.md"
    output.write_text("# Skeleton\n\nSome discussion text.\n" * 10, encoding="utf-8")
    result = evaluate_stage_gate(
        stage="exec_plan_skeleton",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
    )
    assert result.passed is False
    assert "0 features" in result.reason.lower()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_quality_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement quality gate**

```python
# src/cowork_pilot/planning/quality_gate.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""
    retry_recommended: bool = False


_DEFAULT_MIN_LINES: dict[str, int] = {
    "product_completeness_review": 10,
    "scope_structuring": 5,
    "exec_plan_skeleton": 10,
    "exec_plan_feature_outline": 15,
    "exec_plan_detail": 15,
    "brownfield_code_observation_extraction": 10,
    "brownfield_observation_synthesis": 10,
    "brownfield_gap_synthesis": 10,
}


def evaluate_stage_gate(
    *,
    stage: str,
    run_dir: Path,
    expected_outputs: tuple[str, ...] = (),
    min_lines: int | None = None,
) -> GateResult:
    """Evaluate quality gate for a completed stage."""
    effective_min = min_lines if min_lines is not None else _DEFAULT_MIN_LINES.get(stage, 5)

    for output_rel in expected_outputs:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if not output_path.exists():
            return GateResult(passed=False, reason=f"Missing expected output: {output_rel}", retry_recommended=True)

        line_count = len(output_path.read_text(encoding="utf-8").splitlines())
        if line_count < effective_min:
            return GateResult(
                passed=False,
                reason=f"Output too short: {output_rel} has {line_count} lines (min {effective_min})",
                retry_recommended=True,
            )

    # Special check for skeleton: must produce parseable features
    if stage == "exec_plan_skeleton" and expected_outputs:
        from cowork_pilot.planning.outline import parse_skeleton_features
        for output_rel in expected_outputs:
            output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
            if output_path.exists():
                features = parse_skeleton_features(output_path.read_text(encoding="utf-8"))
                if len(features) == 0:
                    return GateResult(
                        passed=False,
                        reason=f"Skeleton has 0 features parsed from {output_rel}",
                        retry_recommended=True,
                    )

    return GateResult(passed=True)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_quality_gate.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/quality_gate.py tests/test_planning_quality_gate.py
git commit -m "feat(planning): add post-stage quality gate evaluation"
```

### Task 9: Add rollback logic

**Files:**
- Modify: `src/cowork_pilot/planning/quality_gate.py`
- Test: `tests/test_planning_quality_gate.py`

- [x] **Step 1: Write failing test for rollback**

```python
# tests/test_planning_quality_gate.py — append

def test_rollback_stage_removes_outputs_and_returns_new_index(tmp_path):
    from cowork_pilot.planning.quality_gate import rollback_stage

    artifact = tmp_path / "coverage-gap.md"
    artifact.write_text("bad content", encoding="utf-8")

    result = rollback_stage(
        run_dir=tmp_path,
        dispatch_index=5,
        outputs_to_remove=(str(artifact),),
    )
    assert result.rolled_back is True
    assert result.retry_dispatch_index == 5
    assert not artifact.exists()


def test_rollback_stage_caps_at_max_retries(tmp_path):
    import json
    from cowork_pilot.planning.quality_gate import rollback_stage

    # Pre-set retry count to 3 (at max)
    (tmp_path / "retry-counts.json").write_text(json.dumps({"5": 3}), encoding="utf-8")

    result = rollback_stage(
        run_dir=tmp_path,
        dispatch_index=5,
        outputs_to_remove=(),
        max_retries=3,
    )
    assert result.rolled_back is False
    assert result.escalated is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_quality_gate.py::test_rollback_stage_removes_outputs_and_returns_new_index -v`
Expected: FAIL

- [x] **Step 3: Implement rollback**

```python
# src/cowork_pilot/planning/quality_gate.py — append

@dataclass(frozen=True)
class RollbackResult:
    rolled_back: bool
    retry_dispatch_index: int = -1
    escalated: bool = False


_RETRY_COUNTS_FILENAME = "retry-counts.json"


def _read_retry_counts(run_dir: Path) -> dict[str, int]:
    path = run_dir / _RETRY_COUNTS_FILENAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_retry_count(run_dir: Path, dispatch_index: int, count: int) -> None:
    counts = _read_retry_counts(run_dir)
    counts[str(dispatch_index)] = count
    (run_dir / _RETRY_COUNTS_FILENAME).write_text(
        json.dumps(counts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def rollback_stage(
    *,
    run_dir: Path,
    dispatch_index: int,
    outputs_to_remove: tuple[str, ...] = (),
    max_retries: int = 3,
) -> RollbackResult:
    """Rollback a failed stage: remove outputs, return index to retry.

    Retry count is persisted in retry-counts.json so it survives crashes/resume.
    """
    counts = _read_retry_counts(run_dir)
    current = counts.get(str(dispatch_index), 0)

    if current >= max_retries:
        return RollbackResult(rolled_back=False, escalated=True)

    for output_rel in outputs_to_remove:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if output_path.exists():
            from cowork_pilot.planning.runtime_storage import append_runtime_event
            append_runtime_event(run_dir, {
                "type": "rollback_file_deleted",
                "dispatch_index": dispatch_index,
                "path": str(output_path),
            })
            output_path.unlink()

    _write_retry_count(run_dir, dispatch_index, current + 1)
    return RollbackResult(rolled_back=True, retry_dispatch_index=dispatch_index)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_quality_gate.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/quality_gate.py tests/test_planning_quality_gate.py
git commit -m "feat(planning): add stage rollback with max retry guard"
```

### Task 10: Wire quality gate into pipeline loop

**Files:**
- Modify: `src/cowork_pilot/planning/pipeline.py`
- Test: `tests/test_planning_pipeline_units.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_planning_pipeline_units.py — append

def test_pipeline_retries_stage_on_gate_failure(tmp_path, monkeypatch):
    # Setup: mock AI stage to produce short output first time, good output second time
    # Verify: stage is called twice, final result is good
    call_count = {"n": 0}

    def mock_exec(**kwargs):
        call_count["n"] += 1
        # First call: short output triggers gate failure
        # Second call: sufficient output passes gate
        ...

    # Assert call_count["n"] == 2
    # Assert pipeline completed
    ...
```

- [x] **Step 2: Implement gate check in main dispatch loop**

After each AI stage completes in `_run_planning_stage_graph()`:
1. Call `evaluate_stage_gate()` with the stage's outputs
2. If gate fails and `retry_recommended`, call `rollback_stage()`
3. If rollback succeeds, decrement `dispatch_index` to retry
4. Track retry count per stage in `_PipelineRuntime`
5. If rollback escalates, set `ESCALATED` state and return

- [x] **Step 3: Run full test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py tests/test_planning_runner.py -v`
Expected: ALL PASS

- [x] **Step 4: Commit**

```bash
git add src/cowork_pilot/planning/pipeline.py tests/test_planning_pipeline_units.py
git commit -m "feat(planning): wire quality gate + rollback into pipeline dispatch loop"
```

### Task 11: Extend review.py with rollback decision helper

**Files:**
- Modify: `src/cowork_pilot/planning/review.py`
- Test: `tests/test_planning_pipeline_units.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_planning_pipeline_units.py — append

def test_should_rollback_returns_true_on_blocking_coverage_failure():
    from cowork_pilot.planning.review import run_plan_review, should_rollback
    verdict = run_plan_review(["plan-a"], gap_artifacts={"gap.md": ["missing-item"]})
    assert should_rollback(verdict) is True


def test_should_rollback_returns_false_on_warnings_only():
    from cowork_pilot.planning.review import run_plan_review, should_rollback
    plans = [f"plan-{i}" for i in range(10)]  # triggers sizing warning
    verdict = run_plan_review(plans)
    assert should_rollback(verdict) is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py::test_should_rollback_returns_true_on_blocking_coverage_failure -v`
Expected: FAIL

- [x] **Step 3: Implement `should_rollback()`**

```python
# src/cowork_pilot/planning/review.py — append

def should_rollback(verdict: ReviewVerdict) -> bool:
    """Return True if verdict contains blocking issues that warrant rollback."""
    return any(issue.severity == "blocking" for issue in verdict.issues)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/review.py tests/test_planning_pipeline_units.py
git commit -m "feat(planning): add should_rollback helper for review verdict"
```

---

## Chunk 3: Crash Recovery + Completed-Step Skip

This chunk makes the pipeline resumable after crashes and skips already-completed stages on restart.

### Task 12: Create recovery module

**Files:**
- Create: `src/cowork_pilot/planning/recovery.py`
- Create: `tests/test_planning_recovery.py`

- [x] **Step 1: Write failing test for 3-step recovery**

```python
# tests/test_planning_recovery.py

from cowork_pilot.planning.recovery import recover_interrupted_stage, RecoveryDecision


def test_recovery_completes_when_outputs_exist_and_valid(tmp_path):
    output = tmp_path / "stage-output.md"
    output.write_text("# Good Output\n" + "content\n" * 20, encoding="utf-8")

    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=(str(output),),
        min_lines=5,
    )
    assert decision == RecoveryDecision.MARK_COMPLETED


def test_recovery_retries_when_outputs_exist_but_short(tmp_path):
    output = tmp_path / "stage-output.md"
    output.write_text("# Short\n", encoding="utf-8")

    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=(str(output),),
        min_lines=10,
    )
    assert decision == RecoveryDecision.DELETE_AND_RETRY
    assert not output.exists()


def test_recovery_retries_when_no_outputs(tmp_path):
    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=("missing.md",),
    )
    assert decision == RecoveryDecision.RETRY
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_recovery.py -v`
Expected: FAIL

- [x] **Step 3: Implement recovery module**

```python
# src/cowork_pilot/planning/recovery.py
from __future__ import annotations

from enum import Enum
from pathlib import Path

from cowork_pilot.planning.quality_gate import _DEFAULT_MIN_LINES


class RecoveryDecision(str, Enum):
    MARK_COMPLETED = "mark_completed"
    DELETE_AND_RETRY = "delete_and_retry"
    RETRY = "retry"


def recover_interrupted_stage(
    *,
    run_dir: Path,
    stage: str,
    expected_outputs: tuple[str, ...] = (),
    min_lines: int | None = None,
) -> RecoveryDecision:
    """3-step recovery policy for interrupted stages.

    1. Outputs exist + sufficient lines → MARK_COMPLETED
    2. Outputs exist but too short → DELETE_AND_RETRY
    3. No outputs → RETRY
    """
    effective_min = min_lines if min_lines is not None else _DEFAULT_MIN_LINES.get(stage, 5)

    any_exists = False
    for output_rel in expected_outputs:
        output_path = Path(output_rel) if Path(output_rel).is_absolute() else run_dir / output_rel
        if output_path.exists():
            any_exists = True
            line_count = len(output_path.read_text(encoding="utf-8").splitlines())
            if line_count < effective_min:
                # Step 2: exists but bad → log, delete, retry
                from cowork_pilot.planning.runtime_storage import append_runtime_event
                append_runtime_event(run_dir, {
                    "type": "recovery_file_deleted",
                    "stage": stage,
                    "path": str(output_path),
                    "line_count": line_count,
                    "min_required": effective_min,
                })
                output_path.unlink()
                return RecoveryDecision.DELETE_AND_RETRY

    if not any_exists and expected_outputs:
        # Step 3: nothing produced → retry
        return RecoveryDecision.RETRY

    # Step 1: all exist with sufficient content → completed
    return RecoveryDecision.MARK_COMPLETED
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_recovery.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/recovery.py tests/test_planning_recovery.py
git commit -m "feat(planning): add 3-step crash recovery for interrupted stages"
```

### Task 13: Add completed-step tracking to runtime storage

**Files:**
- Modify: `src/cowork_pilot/planning/runtime_storage.py`
- Test: `tests/test_planning_runtime_state.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_planning_runtime_state.py — append

def test_completed_stages_roundtrip(tmp_path):
    from cowork_pilot.planning.runtime_storage import write_completed_stage, read_completed_stages

    write_completed_stage(tmp_path, stage="classification", dispatch_index=0, outputs=("mode=greenfield",))
    write_completed_stage(tmp_path, stage="core_docs_check", dispatch_index=1, outputs=("product-spec",))

    completed = read_completed_stages(tmp_path)
    assert len(completed) == 2
    assert completed[0]["stage"] == "classification"
    assert completed[1]["stage"] == "core_docs_check"


def test_read_completed_stages_returns_empty_when_no_file(tmp_path):
    from cowork_pilot.planning.runtime_storage import read_completed_stages
    assert read_completed_stages(tmp_path) == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runtime_state.py::test_completed_stages_roundtrip -v`
Expected: FAIL

- [x] **Step 3: Implement completed-stage tracking**

```python
# src/cowork_pilot/planning/runtime_storage.py — append

_COMPLETED_STAGES_FILENAME = "completed-stages.json"


def write_completed_stage(
    run_dir: Path,
    *,
    stage: str,
    dispatch_index: int,
    outputs: tuple[str, ...] = (),
) -> None:
    """Record a stage as completed. Idempotent: skips if dispatch_index already exists."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _COMPLETED_STAGES_FILENAME
    entries = _read_json_list(path)

    # Dedup by dispatch_index
    existing_indices = {entry.get("dispatch_index") for entry in entries}
    if dispatch_index in existing_indices:
        return

    entries.append({
        "stage": stage,
        "dispatch_index": dispatch_index,
        "outputs": list(outputs),
    })
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_completed_stages(run_dir: Path) -> list[dict[str, object]]:
    return _read_json_list(run_dir / _COMPLETED_STAGES_FILENAME)


def _read_json_list(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runtime_state.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/runtime_storage.py tests/test_planning_runtime_state.py
git commit -m "feat(planning): add completed-stage tracking for step-level skip"
```

### Task 14: Wire recovery + skip into pipeline

**Files:**
- Modify: `src/cowork_pilot/planning/pipeline.py`
- Test: `tests/test_planning_runner.py`

- [x] **Step 1: Write failing test for skip**

```python
# tests/test_planning_runner.py — append

def test_pipeline_skips_already_completed_stages(tmp_path, monkeypatch):
    from cowork_pilot.planning.runtime_storage import write_completed_stage
    # Pre-populate completed stages
    write_completed_stage(tmp_path / "run", stage="classification", dispatch_index=0)
    write_completed_stage(tmp_path / "run", stage="core_docs_check", dispatch_index=1)
    # Mock pipeline to track which stages actually execute
    # Assert classification and core_docs_check are NOT called
    ...
```

- [x] **Step 2: Add recovery preamble to `_run_planning_stage_graph()`**

At the start of `_run_planning_stage_graph()`, before the main loop:
1. Read `run-state.json` to check if last run was `RUNNING_EXEC`
2. If so, call `recover_interrupted_stage()` for the interrupted stage
3. Based on `RecoveryDecision`, either mark completed or reset dispatch index

- [x] **Step 3: Add completed-step skip to main loop**

In the main dispatch loop, before executing each dispatch:
1. Read `completed_stages` from storage
2. If this `dispatch_index` is already in the completed set, skip it
3. After successful stage completion, call `write_completed_stage()`

- [x] **Step 4: Run full test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runner.py tests/test_planning_pipeline_units.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/pipeline.py tests/test_planning_runner.py
git commit -m "feat(planning): wire crash recovery and completed-step skip into pipeline"
```

---

## Chunk 4: Session Estimation + Final Summary

### Task 15: Create estimation module

**Files:**
- Create: `src/cowork_pilot/planning/estimation.py`
- Create: `tests/test_planning_estimation.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_planning_estimation.py

from cowork_pilot.planning.estimation import estimate_sessions, SessionEstimate


def test_estimate_small_greenfield():
    est = estimate_sessions(
        mode="greenfield",
        size_class="small",
        feature_count=5,
        domain_count=2,
    )
    assert est.total_sessions > 0
    assert est.time_range_minutes[0] < est.time_range_minutes[1]


def test_estimate_large_brownfield_more_sessions_than_small():
    small = estimate_sessions(mode="greenfield", size_class="small", feature_count=3, domain_count=1)
    large = estimate_sessions(mode="brownfield", size_class="large", feature_count=15, domain_count=4)
    assert large.total_sessions > small.total_sessions


def test_estimate_includes_skeleton_feature_outline_and_detail_sessions():
    est = estimate_sessions(mode="greenfield", size_class="medium", feature_count=6, domain_count=2)
    assert est.skeleton_sessions == 1
    assert est.feature_outline_sessions == 6  # 1 per feature
    assert est.detail_sessions == 6  # 1 per feature
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_estimation.py -v`
Expected: FAIL

- [x] **Step 3: Implement estimation module**

```python
# src/cowork_pilot/planning/estimation.py
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionEstimate:
    total_sessions: int
    skeleton_sessions: int
    feature_outline_sessions: int
    detail_sessions: int
    stage_sessions: int
    time_range_minutes: tuple[int, int]
    breakdown: dict[str, int]


def estimate_sessions(
    *,
    mode: str,
    size_class: str,
    feature_count: int,
    domain_count: int,
    minutes_per_session: tuple[int, int] = (3, 8),
) -> SessionEstimate:
    """Estimate total sessions and time for planning pipeline."""
    # Base stage sessions (classification through plan review)
    base = _base_stage_count(mode, size_class, domain_count)

    # Skeleton: always 1 session (feature list + ordering only)
    skeleton_sessions = 1

    # Feature outline: 1 session per feature (chunk decomposition per feature)
    feature_outline_sessions = max(1, feature_count)

    # Detail: 1 session per feature (session prompt filling)
    detail_sessions = max(1, feature_count)

    total = base + skeleton_sessions + feature_outline_sessions + detail_sessions

    return SessionEstimate(
        total_sessions=total,
        skeleton_sessions=skeleton_sessions,
        feature_outline_sessions=feature_outline_sessions,
        detail_sessions=detail_sessions,
        stage_sessions=base,
        time_range_minutes=(total * minutes_per_session[0], total * minutes_per_session[1]),
        breakdown={
            "base_stages": base,
            "skeleton": skeleton_sessions,
            "feature_outline": feature_outline_sessions,
            "detail": detail_sessions,
        },
    )


def _base_stage_count(mode: str, size_class: str, domain_count: int) -> int:
    """Count non-exec-plan AI stages based on mode and size."""
    count = 0
    # Classification substages
    if size_class in ("medium", "large"):
        count += 2  # input-audit + synthesis
    else:
        count += 1

    if mode == "brownfield":
        # Extraction slices + synthesis + gap
        slices = {"small": 1, "medium": 2, "large": 3}.get(size_class, 1)
        count += slices + 2  # slices + observation_synthesis + gap_synthesis
        count += 1  # core_docs_presence_review

    # Completeness review substages
    if size_class == "large":
        count += 3
    elif size_class == "medium":
        count += 2
    else:
        count += 1

    # Scope structuring
    if size_class == "medium":
        count += 2
    else:
        count += 1

    # Plan review (always 2 substages)
    count += 2

    return count
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_estimation.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/estimation.py tests/test_planning_estimation.py
git commit -m "feat(planning): add session count and time estimation"
```

### Task 16: Create summary module

**Files:**
- Create: `src/cowork_pilot/planning/summary.py`
- Create: `tests/test_planning_summary.py`

- [x] **Step 1: Write failing test**

```python
# tests/test_planning_summary.py

from cowork_pilot.planning.summary import build_pipeline_summary, PipelineSummary


def test_build_summary_counts_stages_and_plans(tmp_path):
    # Create some completed-stages.json and exec-plan files
    import json
    (tmp_path / "completed-stages.json").write_text(json.dumps([
        {"stage": "classification", "dispatch_index": 0},
        {"stage": "core_docs_check", "dispatch_index": 1},
        {"stage": "exec_plan_outline", "dispatch_index": 10},
        {"stage": "exec_plan_detail", "dispatch_index": 11},
        {"stage": "exec_plan_detail", "dispatch_index": 12},
    ]), encoding="utf-8")

    plans_dir = tmp_path / "docs" / "exec-plans" / "planning"
    plans_dir.mkdir(parents=True)
    (plans_dir / "01-setup.md").write_text("plan 1", encoding="utf-8")
    (plans_dir / "02-auth.md").write_text("plan 2", encoding="utf-8")

    summary = build_pipeline_summary(run_dir=tmp_path, project_dir=tmp_path)
    assert summary.total_stages_completed == 5
    assert summary.exec_plan_count == 2
    assert summary.errors == 0


def test_build_summary_returns_none_on_empty_run(tmp_path):
    summary = build_pipeline_summary(run_dir=tmp_path, project_dir=tmp_path)
    assert summary.total_stages_completed == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_summary.py -v`
Expected: FAIL

- [x] **Step 3: Implement summary module**

```python
# src/cowork_pilot/planning/summary.py
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.runtime_storage import read_completed_stages, read_run_state


@dataclass(frozen=True)
class PipelineSummary:
    total_stages_completed: int
    exec_plan_count: int
    errors: int
    exec_plan_files: tuple[str, ...]


def build_pipeline_summary(*, run_dir: Path, project_dir: Path) -> PipelineSummary:
    """Build final pipeline summary from run artifacts."""
    completed = read_completed_stages(run_dir)

    plans_dir = project_dir / "docs" / "exec-plans" / "planning"
    plan_files = sorted(plans_dir.glob("*.md")) if plans_dir.is_dir() else []
    plan_files = [f for f in plan_files if f.name != "exec-plan.md"]  # exclude legacy single file

    run_state = read_run_state(run_dir)
    error_count = int(run_state.get("error_count", 0))

    return PipelineSummary(
        total_stages_completed=len(completed),
        exec_plan_count=len(plan_files),
        errors=error_count,
        exec_plan_files=tuple(f.name for f in plan_files),
    )


def print_pipeline_summary(summary: PipelineSummary) -> None:
    """Print human-readable summary to stderr."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("Planning Pipeline — Final Summary", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Stages completed: {summary.total_stages_completed}", file=sys.stderr)
    print(f"  Exec-plan files: {summary.exec_plan_count}", file=sys.stderr)
    print(f"  Errors: {summary.errors}", file=sys.stderr)
    if summary.exec_plan_files:
        for name in summary.exec_plan_files:
            print(f"    - {name}", file=sys.stderr)
    else:
        print("  WARNING: No exec-plan files generated", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_summary.py -v`
Expected: ALL PASS

- [x] **Step 5: Wire summary into pipeline completion**

In `pipeline.py`, after the main dispatch loop sets `COMPLETED` state, call:
```python
summary = build_pipeline_summary(run_dir=runtime.run_dir, project_dir=runtime.project_dir)
print_pipeline_summary(summary)
```

Store summary in the pipeline result.

- [x] **Step 6: Commit**

```bash
git add src/cowork_pilot/planning/summary.py tests/test_planning_summary.py src/cowork_pilot/planning/pipeline.py
git commit -m "feat(planning): add session estimation and final pipeline summary"
```

---

## Chunk 5: Planning Resume CLI

This chunk exposes the existing internal resume machinery as a user-facing CLI command.

### Task 17: Add resume subcommand to CLI

**Files:**
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/planning/runner.py`

- [ ] **Step 1: Write failing test for resume public API**

```python
# tests/test_planning_runner.py — append

def test_resume_planning_pipeline_restores_from_run_dir(tmp_path, monkeypatch):
    import json
    from cowork_pilot.planning.runner import resume_planning_pipeline
    from cowork_pilot.planning.runtime_storage import write_run_state, write_pipeline_state
    from cowork_pilot.planning.models import PlanningContext, PlanningRuntimeState

    run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "run-001"
    run_dir.mkdir(parents=True)
    project_dir = tmp_path

    write_run_state(run_dir, state="waiting_for_input", metadata={
        "stage": "scope_structuring",
        "resume_handle": "thread-abc",
        "resume_handle_kind": "codex_thread_id",
        "surface": "exec",
        "event_id": "evt-1",
    })
    write_pipeline_state(run_dir, context=PlanningContext(
        run_dir=run_dir, project_dir=project_dir, mode=ProjectMode.GREENFIELD, explicit_mode=True,
    ), next_dispatch_index=5)

    # Mock resume to just return
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.resume_planning_pipeline_with_user_response",
        lambda **kwargs: load_planning_pipeline_result_from_run_dir(run_dir),
    )

    result = resume_planning_pipeline(run_dir=run_dir, response_text="approved", response_kind="approval")
    assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runner.py::test_resume_planning_pipeline_restores_from_run_dir -v`
Expected: FAIL

- [ ] **Step 3: Add `resume_planning_pipeline()` to runner.py**

```python
# src/cowork_pilot/planning/runner.py — add function

def resume_planning_pipeline(
    *,
    run_dir: Path,
    response_text: str = "",
    response_kind: str = "answer",
) -> PlanningPipelineResult:
    """Public API for resuming a waiting planning pipeline.

    This is the function called by the CLI `planning resume` command.
    """
    run_state = read_run_state(run_dir)
    current_state = str(run_state.get("state", ""))

    if current_state in {
        PlanningRuntimeState.WAITING_FOR_INPUT.value,
        PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
    }:
        return resume_planning_pipeline_with_user_response(
            run_dir=run_dir,
            response_text=response_text,
            response_kind=response_kind,
        )

    # Not waiting — try continuing from checkpoint
    return continue_planning_stage_graph(run_dir=run_dir)
```

- [ ] **Step 4: Add CLI argument parsing for `planning resume`**

In `main.py`, under the planning mode handler, add:
```python
# After existing argument parsing:
if args.planning_subcommand == "resume":
    run_dir = Path(args.run_dir)
    response_text = args.response or ""
    response_kind = args.response_kind or "answer"
    result = resume_planning_pipeline(run_dir=run_dir, response_text=response_text, response_kind=response_kind)
    ...
```

Add argparse subparser for `planning resume --run-dir <path> [--response <text>] [--response-kind answer|approval]`.

- [ ] **Step 5: Add `--estimate` flag to planning CLI**

Add `--estimate` flag that calls `estimate_sessions()` and prints the estimate before running the pipeline. If `--estimate` is passed alone (without `--run`), just print and exit.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_runner.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/cowork_pilot/planning/runner.py src/cowork_pilot/main.py tests/test_planning_runner.py
git commit -m "feat(planning): add planning resume CLI and --estimate flag"
```

### Task 18: Update __init__.py exports

**Files:**
- Modify: `src/cowork_pilot/planning/__init__.py`

- [ ] **Step 1: Add new public symbols**

Export: `OutlinePlan`, `parse_outline_plans`, `parse_skeleton_features`, `merge_feature_outlines`, `build_feature_outline_dispatches`, `GateResult`, `RecoveryDecision`, `SessionEstimate`, `estimate_sessions`, `PipelineSummary`, `build_pipeline_summary`, `resume_planning_pipeline`

- [ ] **Step 2: Run import test**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -c "from cowork_pilot.planning import OutlinePlan, parse_outline_plans, GateResult, RecoveryDecision, SessionEstimate, estimate_sessions, PipelineSummary, build_pipeline_summary, resume_planning_pipeline; print('OK')"
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/cowork_pilot/planning/__init__.py
git commit -m "feat(planning): export new public symbols from planning package"
```

### Task 19: Final verification

- [ ] **Step 1: Run entire planning test suite**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m pytest tests/test_planning_*.py -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Run type check if available**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -m mypy src/cowork_pilot/planning/ --ignore-missing-imports 2>/dev/null || echo "mypy not configured, skipping"`

- [ ] **Step 3: Verify no circular imports**

Run: `cd /sessions/cool-wizardly-dijkstra/mnt/cowork-pilot && python -c "import cowork_pilot.planning; print('No circular imports')"`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(planning): final verification pass for ops upgrade"
```
