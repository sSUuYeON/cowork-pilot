# Planning Engine V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 `docs-orchestrator`의 planning 역할을 대체할 `Planning Engine V3` core를 구현하고, `docs-orchestrator`와 `Codex CLI`에서 같은 core를 호출하도록 연결한다.

**Architecture:** 새 코드는 `src/cowork_pilot/planning/` 패키지에 모은다. `Project Classification -> Core Docs Check -> Adaptive Docs Selection -> Core Docs Presence Review -> Product Completeness Review -> Scope Structuring -> Work Sizing -> Plan Packing -> Plan Review -> Exec-Plan Authoring` 10단계를 runner가 orchestration하고, 각 단계는 `docs/generated/planning-runs/<run-id>/`에 intermediate docs를 남긴다. 기존 `docs_orchestrator.py`는 문서 생성 phase를 유지하되 planning phase는 V3 core adapter로 바꾸고, `cowork-pilot-codex`에는 planning subcommand를 추가해 같은 pipeline을 실행한다.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, Jinja2, pytest

**Git note:** 사용자 요청에 따라 이 plan은 commit step을 포함하지 않는다.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/cowork_pilot/planning/__init__.py` | planning package public exports |
| Create | `src/cowork_pilot/planning/models.py` | run/stage/review/classification/packing dataclasses + enums |
| Create | `src/cowork_pilot/planning/storage.py` | run-id 생성, `docs/generated/planning-runs/<run-id>/` 생성, intermediate doc writer |
| Create | `src/cowork_pilot/planning/classification.py` | `small/medium/large`, `greenfield/brownfield`, decision mode classification |
| Create | `src/cowork_pilot/planning/docs_inventory.py` | core docs check, adaptive docs selection, presence review profiles |
| Create | `src/cowork_pilot/planning/completeness.py` | product completeness checklist model + required/conditional/not_applicable resolution |
| Create | `src/cowork_pilot/planning/scope.py` | scope map dataclasses + stage output parsing helpers |
| Create | `src/cowork_pilot/planning/sizing.py` | work item sizing model + report serializer |
| Create | `src/cowork_pilot/planning/packing.py` | plan/chunk packing rules, especially `small` 규모 chunk split rule |
| Create | `src/cowork_pilot/planning/review.py` | coverage/sizing/executionability/overdesign review model |
| Create | `src/cowork_pilot/planning/authoring.py` | final exec-plan authoring + `plan_parser.parse_exec_plan()` validation |
| Create | `src/cowork_pilot/planning/prompts.py` | AI-assisted stage prompt builder |
| Create | `src/cowork_pilot/planning/runner.py` | end-to-end planning pipeline orchestration |
| Create | `src/cowork_pilot/planning_templates/*.j2` | completeness/scope/sizing/review/authoring stage prompt templates |
| Modify | `src/cowork_pilot/config.py` | `PlanningConfig` dataclass + loader |
| Modify | `config.toml` | `[planning]` defaults |
| Modify | `src/cowork_pilot/main.py` | `--mode planning` 추가 |
| Modify | `src/cowork_pilot/docs_orchestrator.py` | Phase 5 planning 역할을 V3 core adapter 호출로 전환 |
| Modify | `src/cowork_pilot/orchestrator_state.py` | planning run metadata/state 저장 필드 추가 |
| Modify | `src/cowork_pilot/orchestrator_prompts.py` | 기존 phase prompt loader를 planning prompt loader와 공존 가능하게 정리 |
| Modify | `src/cowork_pilot/codex/main.py` | `planning` subcommand 추가 |
| Create | `tests/test_planning_models.py` | planning models/config/storage 단위 테스트 |
| Create | `tests/test_planning_classification.py` | classification heuristic + reclassification rule 테스트 |
| Create | `tests/test_planning_docs_inventory.py` | core docs/adaptive docs/presence review 테스트 |
| Create | `tests/test_planning_completeness.py` | product completeness checklist profile 테스트 |
| Create | `tests/test_planning_packing.py` | sizing/packing/review/authoring 테스트 |
| Create | `tests/test_planning_runner.py` | pipeline runner + run directory + intermediate docs integration 테스트 |
| Modify | `tests/test_docs_orchestrator.py` | Phase 5 adapter 연동 테스트 |
| Modify | `tests/test_config.py` | `PlanningConfig` 로딩 테스트 |

---

## Task 1: Planning Foundation (Config + Models + Run Storage)

**Files:**
- Create: `src/cowork_pilot/planning/__init__.py`
- Create: `src/cowork_pilot/planning/models.py`
- Create: `src/cowork_pilot/planning/storage.py`
- Modify: `src/cowork_pilot/config.py`
- Modify: `config.toml`
- Create: `tests/test_planning_models.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 모델/설정 테스트부터 작성**

`tests/test_planning_models.py`와 `tests/test_config.py`에 다음 테스트를 추가한다.

```python
from pathlib import Path

from cowork_pilot.config import load_planning_config
from cowork_pilot.planning.models import (
    PlanningStage,
    ProjectMode,
    SizeClass,
    DecisionMode,
    PlanningRunContext,
)
from cowork_pilot.planning.storage import build_run_id, ensure_run_dirs


def test_build_run_id_contains_timestamp_mode_and_version():
    run_id = build_run_id(
        timestamp="2026-04-07T22-10-00Z",
        project_mode=ProjectMode.GREENFIELD,
        target_version="v1-draft",
    )
    assert run_id == "2026-04-07T22-10-00Z-greenfield-v1-draft"


def test_ensure_run_dirs_creates_expected_paths(tmp_path: Path):
    root = ensure_run_dirs(tmp_path, "2026-04-07T22-10-00Z-greenfield-v1-draft")
    assert (root / "classification-report.md").parent == root
    assert root.name == "2026-04-07T22-10-00Z-greenfield-v1-draft"


def test_load_planning_config_defaults(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    cfg = load_planning_config(config_path)
    assert cfg.default_decision_mode == "hybrid"
    assert cfg.run_root == "docs/generated/planning-runs"
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_config.py -q`

Expected:
- `ModuleNotFoundError: No module named 'cowork_pilot.planning'`
- `ImportError` for `load_planning_config`

- [ ] **Step 3: planning models/config/storage 최소 구현**

`src/cowork_pilot/planning/models.py`에 enum/dataclass를 추가한다.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ProjectMode(str, Enum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class SizeClass(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class DecisionMode(str, Enum):
    INTERACTIVE = "interactive"
    HYBRID = "hybrid"
    AUTO = "auto"


class PlanningStage(str, Enum):
    CLASSIFICATION = "classification"
    CORE_DOCS_CHECK = "core-docs-check"
    ADAPTIVE_DOCS_SELECTION = "adaptive-docs-selection"
    CORE_DOCS_PRESENCE_REVIEW = "core-docs-presence-review"
    PRODUCT_COMPLETENESS_REVIEW = "product-completeness-review"
    SCOPE_STRUCTURING = "scope-structuring"
    WORK_SIZING = "work-sizing"
    PLAN_PACKING = "plan-packing"
    PLAN_REVIEW = "plan-review"
    EXEC_PLAN_AUTHORING = "exec-plan-authoring"


@dataclass(frozen=True)
class PlanningRunContext:
    project_dir: Path
    project_mode: ProjectMode
    decision_mode: DecisionMode
    target_version: str
    run_id: str
    run_dir: Path
    size_class: SizeClass | None = None
```

`src/cowork_pilot/planning/storage.py`에 최소 런 디렉토리 유틸을 추가한다.

```python
from __future__ import annotations

from pathlib import Path

from cowork_pilot.planning.models import ProjectMode


def build_run_id(*, timestamp: str, project_mode: ProjectMode, target_version: str) -> str:
    return f"{timestamp}-{project_mode.value}-{target_version}"


def ensure_run_dirs(root: Path, run_id: str) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
```

`src/cowork_pilot/config.py`에는 다음 dataclass/loader를 추가한다.

```python
@dataclass
class PlanningConfig:
    run_root: str = "docs/generated/planning-runs"
    default_decision_mode: str = "hybrid"
    default_project_mode: str = "greenfield"
    codex_surface_enabled: bool = True


def load_planning_config(path: Path) -> PlanningConfig:
    cfg = PlanningConfig()
    if not path.exists():
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    p = data.get("planning", {})
    return PlanningConfig(
        run_root=p.get("run_root", cfg.run_root),
        default_decision_mode=p.get("default_decision_mode", cfg.default_decision_mode),
        default_project_mode=p.get("default_project_mode", cfg.default_project_mode),
        codex_surface_enabled=p.get("codex_surface_enabled", cfg.codex_surface_enabled),
    )
```

`config.toml`에는 다음 기본값을 추가한다.

```toml
[planning]
run_root = "docs/generated/planning-runs"
default_decision_mode = "hybrid"
default_project_mode = "greenfield"
codex_surface_enabled = true
```

- [ ] **Step 4: 테스트 재실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_config.py -q`

Expected:
- 새 planning tests PASS
- 기존 `tests/test_config.py` PASS

- [ ] **Step 5: regression smoke**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_config.py tests/test_orchestrator_state.py -q`

Expected:
- 기존 config/orchestrator_state regression PASS

---

## Task 2: Classification + Reclassification Rules

**Files:**
- Create: `src/cowork_pilot/planning/classification.py`
- Create: `tests/test_planning_classification.py`

- [ ] **Step 1: classification heuristic 테스트 작성**

`tests/test_planning_classification.py`에 최소 세 케이스를 추가한다.

```python
from cowork_pilot.planning.classification import (
    ClassificationInputs,
    classify_project,
    maybe_reclassify_after_completeness,
)
from cowork_pilot.planning.models import ProjectMode, SizeClass


def test_classify_small_greenfield():
    result = classify_project(
        ClassificationInputs(
            project_mode=ProjectMode.GREENFIELD,
            feature_groups=2,
            roles=1,
            user_flows=2,
            integrations=0,
            ops_complexity=1,
            non_functional_complexity=1,
            change_impact=0,
        )
    )
    assert result.size_class == SizeClass.SMALL


def test_classify_large_brownfield():
    result = classify_project(
        ClassificationInputs(
            project_mode=ProjectMode.BROWNFIELD,
            feature_groups=8,
            roles=4,
            user_flows=10,
            integrations=5,
            ops_complexity=4,
            non_functional_complexity=4,
            change_impact=4,
        )
    )
    assert result.size_class == SizeClass.LARGE


def test_reclassification_allowed_once_after_completeness_review():
    updated = maybe_reclassify_after_completeness(
        current=SizeClass.SMALL,
        suggested=SizeClass.MEDIUM,
        already_reclassified=False,
    )
    assert updated == (SizeClass.MEDIUM, True)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_classification.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: classification module 구현**

`src/cowork_pilot/planning/classification.py`에 휴리스틱 기반 분류기를 추가한다.

```python
from __future__ import annotations

from dataclasses import dataclass

from cowork_pilot.planning.models import ProjectMode, SizeClass


@dataclass(frozen=True)
class ClassificationInputs:
    project_mode: ProjectMode
    feature_groups: int
    roles: int
    user_flows: int
    integrations: int
    ops_complexity: int
    non_functional_complexity: int
    change_impact: int


@dataclass(frozen=True)
class ClassificationResult:
    size_class: SizeClass
    rationale: list[str]


def classify_project(inputs: ClassificationInputs) -> ClassificationResult:
    score = 0
    score += 2 if inputs.feature_groups >= 6 else 1 if inputs.feature_groups >= 3 else 0
    score += 2 if inputs.roles >= 3 else 1 if inputs.roles == 2 else 0
    score += 2 if inputs.user_flows >= 6 else 1 if inputs.user_flows >= 3 else 0
    score += 2 if inputs.integrations >= 3 else 1 if inputs.integrations >= 1 else 0
    score += min(inputs.ops_complexity, 2)
    score += min(inputs.non_functional_complexity, 2)
    score += min(inputs.change_impact, 2)

    if score >= 9:
        return ClassificationResult(SizeClass.LARGE, [f"score={score}", "high complexity"])
    if score >= 4:
        return ClassificationResult(SizeClass.MEDIUM, [f"score={score}", "moderate complexity"])
    return ClassificationResult(SizeClass.SMALL, [f"score={score}", "low complexity"])


def maybe_reclassify_after_completeness(
    *,
    current: SizeClass,
    suggested: SizeClass,
    already_reclassified: bool,
) -> tuple[SizeClass, bool]:
    if already_reclassified or current == suggested:
        return (current, already_reclassified)
    return (suggested, True)
```

- [ ] **Step 4: 테스트 재실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_classification.py -q`

Expected:
- PASS

- [ ] **Step 5: config + models regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_classification.py -q`

Expected:
- PASS

---

## Task 3: Core Docs / Adaptive Docs / Product Completeness Reviews

**Files:**
- Create: `src/cowork_pilot/planning/docs_inventory.py`
- Create: `src/cowork_pilot/planning/completeness.py`
- Create: `tests/test_planning_docs_inventory.py`
- Create: `tests/test_planning_completeness.py`

- [ ] **Step 1: docs inventory 테스트 작성**

`tests/test_planning_docs_inventory.py`에 core docs/adaptive docs 선택 테스트를 추가한다.

```python
from pathlib import Path

from cowork_pilot.planning.docs_inventory import (
    CORE_DOC_KEYS,
    check_core_docs,
    select_adaptive_docs,
)


def test_check_core_docs_reports_missing_files(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Agents", encoding="utf-8")
    result = check_core_docs(tmp_path)
    assert "agents" in result.present
    assert "architecture" in result.missing


def test_select_adaptive_docs_for_ops_heavy_project():
    docs = select_adaptive_docs(
        product_type="saas",
        feature_tags={"billing", "admin", "notifications"},
        integrations={"stripe", "resend"},
        ops_required=True,
    )
    assert {"billing", "integrations", "ops-runbook"} <= docs.selected
```

`tests/test_planning_completeness.py`에는 review profile 테스트를 추가한다.

```python
from cowork_pilot.planning.completeness import (
    build_completeness_profile,
    resolve_checklist_statuses,
)
from cowork_pilot.planning.models import SizeClass


def test_small_profile_marks_operator_workflow_conditional():
    profile = build_completeness_profile(SizeClass.SMALL)
    statuses = resolve_checklist_statuses(profile)
    assert statuses["operator-workflow"] == "conditional"


def test_large_profile_requires_role_flow_and_non_functional():
    profile = build_completeness_profile(SizeClass.LARGE)
    statuses = resolve_checklist_statuses(profile)
    assert statuses["role-flow"] == "required"
    assert statuses["non-functional"] == "required"
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_docs_inventory.py tests/test_planning_completeness.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: docs inventory 구현**

`src/cowork_pilot/planning/docs_inventory.py`에 core docs key map과 adaptive selector를 추가한다.

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CORE_DOC_KEYS = {
    "agents": Path("AGENTS.md"),
    "architecture": Path("ARCHITECTURE.md"),
    "design-guide": Path("docs/DESIGN_GUIDE.md"),
    "security": Path("docs/SECURITY.md"),
    "core-beliefs": Path("docs/design-docs/core-beliefs.md"),
    "data-model": Path("docs/design-docs/data-model.md"),
    "product-specs-index": Path("docs/product-specs/index.md"),
}


@dataclass(frozen=True)
class CoreDocsCheckResult:
    present: set[str]
    missing: set[str]


@dataclass(frozen=True)
class AdaptiveDocsSelection:
    selected: set[str]
    rationale: dict[str, str]


def check_core_docs(project_dir: Path) -> CoreDocsCheckResult:
    present: set[str] = set()
    missing: set[str] = set()
    for key, rel_path in CORE_DOC_KEYS.items():
        path = project_dir / rel_path
        if path.exists() and path.read_text(encoding="utf-8").strip():
            present.add(key)
        else:
            missing.add(key)
    return CoreDocsCheckResult(present=present, missing=missing)


def select_adaptive_docs(*, product_type: str, feature_tags: set[str], integrations: set[str], ops_required: bool) -> AdaptiveDocsSelection:
    selected: set[str] = set()
    rationale: dict[str, str] = {}
    if "billing" in feature_tags:
        selected.add("billing")
        rationale["billing"] = "feature_tags contains billing"
    if integrations:
        selected.add("integrations")
        rationale["integrations"] = f"integrations={sorted(integrations)}"
    if ops_required:
        selected.add("ops-runbook")
        rationale["ops-runbook"] = "ops_required is true"
    if product_type in {"saas", "marketplace"}:
        selected.add("admin-console")
        rationale["admin-console"] = f"product_type={product_type}"
    return AdaptiveDocsSelection(selected=selected, rationale=rationale)
```

- [ ] **Step 4: completeness profile 구현**

`src/cowork_pilot/planning/completeness.py`에 profile resolver를 추가한다.

```python
from __future__ import annotations

from dataclasses import dataclass

from cowork_pilot.planning.models import SizeClass


@dataclass(frozen=True)
class CompletenessProfile:
    size_class: SizeClass
    checklist: dict[str, str]


def build_completeness_profile(size_class: SizeClass) -> CompletenessProfile:
    base = {
        "page-list": "required",
        "user-flow": "required",
        "role-flow": "conditional",
        "login-redirect": "required",
        "baseline-screens": "required",
        "empty-loading-error": "required",
        "crud-lifecycle": "conditional",
        "feedback": "conditional",
        "operator-workflow": "conditional",
        "integrations": "conditional",
        "post-version-ops": "conditional",
        "non-functional": "conditional",
    }
    if size_class == SizeClass.LARGE:
        for key in ("role-flow", "crud-lifecycle", "feedback", "operator-workflow", "integrations", "post-version-ops", "non-functional"):
            base[key] = "required"
    return CompletenessProfile(size_class=size_class, checklist=base)


def resolve_checklist_statuses(profile: CompletenessProfile) -> dict[str, str]:
    return dict(profile.checklist)
```

- [ ] **Step 5: 테스트 재실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_docs_inventory.py tests/test_planning_completeness.py -q`

Expected:
- PASS

- [ ] **Step 6: regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_classification.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py -q`

Expected:
- PASS

---

## Task 4: Scope Structuring + Work Sizing + Plan Packing

**Files:**
- Create: `src/cowork_pilot/planning/scope.py`
- Create: `src/cowork_pilot/planning/sizing.py`
- Create: `src/cowork_pilot/planning/packing.py`
- Create: `tests/test_planning_packing.py`

- [ ] **Step 1: packing rules 테스트 작성**

`tests/test_planning_packing.py`에 `small` 프로젝트의 분해 규칙 테스트를 추가한다.

```python
from cowork_pilot.planning.models import SizeClass
from cowork_pilot.planning.packing import pack_work_items
from cowork_pilot.planning.scope import WorkItem


def test_small_project_splits_chunk_only_when_dependency_boundary_exists():
    items = [
        WorkItem(key="auth", title="Auth flow", dependency_group="core", verification="login smoke"),
        WorkItem(key="settings", title="Settings page", dependency_group="core", verification="settings smoke"),
    ]
    packed = pack_work_items(items, size_class=SizeClass.SMALL)
    assert len(packed.plans) == 1
    assert len(packed.plans[0].chunks) == 1


def test_large_project_can_pack_multiple_dependency_streams():
    items = [
        WorkItem(key="billing", title="Billing", dependency_group="payments", verification="billing smoke"),
        WorkItem(key="admin", title="Admin", dependency_group="ops", verification="admin smoke"),
    ]
    packed = pack_work_items(items, size_class=SizeClass.LARGE)
    assert len(packed.plans[0].chunks) >= 2
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_packing.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: scope/sizing dataclasses 추가**

`src/cowork_pilot/planning/scope.py`와 `src/cowork_pilot/planning/sizing.py`에 최소 모델을 구현한다.

```python
# scope.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkItem:
    key: str
    title: str
    dependency_group: str
    verification: str
```

```python
# sizing.py
from __future__ import annotations

from dataclasses import dataclass

from cowork_pilot.planning.scope import WorkItem


@dataclass(frozen=True)
class SizedWorkItem:
    item: WorkItem
    complexity: int
    coupling: int
    uncertainty: int


def size_work_item(item: WorkItem, *, complexity: int, coupling: int, uncertainty: int) -> SizedWorkItem:
    return SizedWorkItem(item=item, complexity=complexity, coupling=coupling, uncertainty=uncertainty)
```

- [ ] **Step 4: packing 구현**

`src/cowork_pilot/planning/packing.py`에 `small` 분해 규칙을 명시한다.

```python
from __future__ import annotations

from dataclasses import dataclass, field

from cowork_pilot.planning.models import SizeClass
from cowork_pilot.planning.scope import WorkItem


@dataclass(frozen=True)
class PackedChunk:
    name: str
    work_items: list[WorkItem]


@dataclass(frozen=True)
class PackedPlan:
    name: str
    chunks: list[PackedChunk] = field(default_factory=list)


@dataclass(frozen=True)
class PackedPlanningResult:
    plans: list[PackedPlan]


def pack_work_items(items: list[WorkItem], *, size_class: SizeClass) -> PackedPlanningResult:
    if size_class == SizeClass.SMALL:
        dependency_groups = {item.dependency_group for item in items}
        if len(dependency_groups) <= 1:
            return PackedPlanningResult(
                plans=[PackedPlan(name="01-core", chunks=[PackedChunk(name="Chunk 1", work_items=items)])]
            )

    grouped: dict[str, list[WorkItem]] = {}
    for item in items:
        grouped.setdefault(item.dependency_group, []).append(item)

    chunks = [
        PackedChunk(name=f"Chunk {idx}", work_items=group_items)
        for idx, group_items in enumerate(grouped.values(), start=1)
    ]
    return PackedPlanningResult(plans=[PackedPlan(name="01-planning", chunks=chunks)])
```

- [ ] **Step 5: 테스트 재실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_packing.py -q`

Expected:
- PASS

- [ ] **Step 6: packing + prior modules regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_classification.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py tests/test_planning_packing.py -q`

Expected:
- PASS

---

## Task 5: Prompts + Stage Runner + Exec-Plan Authoring

**Files:**
- Create: `src/cowork_pilot/planning/prompts.py`
- Create: `src/cowork_pilot/planning/authoring.py`
- Create: `src/cowork_pilot/planning/review.py`
- Create: `src/cowork_pilot/planning/runner.py`
- Create: `src/cowork_pilot/planning_templates/classification_review.j2`
- Create: `src/cowork_pilot/planning_templates/product_completeness_review.j2`
- Create: `src/cowork_pilot/planning_templates/scope_structuring.j2`
- Create: `src/cowork_pilot/planning_templates/work_sizing.j2`
- Create: `src/cowork_pilot/planning_templates/plan_review.j2`
- Create: `src/cowork_pilot/planning_templates/exec_plan_authoring.j2`
- Create: `tests/test_planning_runner.py`

- [ ] **Step 1: exec-plan authoring 테스트 작성**

`tests/test_planning_runner.py`에 parser-friendly exec-plan 생성 테스트를 추가한다.

```python
from pathlib import Path

from cowork_pilot.plan_parser import parse_exec_plan
from cowork_pilot.planning.authoring import write_exec_plan
from cowork_pilot.planning.packing import PackedChunk, PackedPlan, PackedPlanningResult
from cowork_pilot.planning.scope import WorkItem


def test_write_exec_plan_generates_plan_parser_compatible_markdown(tmp_path: Path):
    result = PackedPlanningResult(
        plans=[
            PackedPlan(
                name="01-core",
                chunks=[
                    PackedChunk(
                        name="Chunk 1",
                        work_items=[
                            WorkItem(
                                key="auth",
                                title="Auth flow",
                                dependency_group="core",
                                verification="pytest tests/test_auth.py -q",
                            )
                        ],
                    )
                ],
            )
        ]
    )

    output = write_exec_plan(
        result,
        planning_dir=tmp_path,
        project_dir="/tmp/project",
        spec_path="docs/specs/2026-04-07-sample.md",
    )

    plan = parse_exec_plan(output[0])
    assert plan.chunks[0].tasks
    assert plan.chunks[0].completion_criteria
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: prompt loader와 review dataclass 구현**

`src/cowork_pilot/planning/prompts.py`와 `src/cowork_pilot/planning/review.py`에 최소 구조를 추가한다.

```python
# prompts.py
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def build_planning_prompt(stage: str, *, template_dir: Path | None = None, **kwargs: object) -> str:
    root = template_dir or (Path(__file__).parent.parent / "planning_templates")
    env = Environment(loader=FileSystemLoader(str(root)), keep_trailing_newline=True)
    template = env.get_template(f"{stage}.j2")
    return template.render(**kwargs)
```

```python
# review.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanReviewResult:
    coverage_ok: bool
    sizing_ok: bool
    executionability_ok: bool
    overdesign_ok: bool
    findings: list[str]
```

- [ ] **Step 4: exec-plan authoring 구현**

`src/cowork_pilot/planning/authoring.py`에 기존 `plan_parser.py` 규칙과 호환되는 writer를 구현한다.

```python
from __future__ import annotations

from pathlib import Path

from cowork_pilot.planning.packing import PackedPlanningResult


def write_exec_plan(result: PackedPlanningResult, *, planning_dir: Path, project_dir: str, spec_path: str) -> list[Path]:
    planning_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for idx, plan in enumerate(result.plans, start=1):
        path = planning_dir / f"{idx:02d}-{plan.name}.md"
        lines = [
            f"# {plan.name}",
            "",
            "## Metadata",
            f"- project_dir: {project_dir}",
            f"- spec: {spec_path}",
            "- created: 2026-04-07",
            "- status: pending",
            "",
            "---",
            "",
        ]
        for chunk_idx, chunk in enumerate(plan.chunks, start=1):
            lines.extend(
                [
                    f"## Chunk {chunk_idx}: {chunk.name}",
                    "",
                    "### Completion Criteria",
                    *(f"- [ ] {item.verification}" for item in chunk.work_items),
                    "",
                    "### Tasks",
                    *(f"- Task {i}: {item.title}" for i, item in enumerate(chunk.work_items, start=1)),
                    "",
                    "### Session Prompt",
                    "```",
                    f"{chunk.name} 구현 후 completion criteria를 직접 검증하고 체크해라.",
                    "```",
                    "",
                    "---",
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        paths.append(path)
    return paths
```

- [ ] **Step 5: runner 최소 구현**

`src/cowork_pilot/planning/runner.py`에 단계 문서 생성 흐름을 추가한다. 처음 버전은 pure-python stage output을 intermediate docs로 쓰고, prompt builder는 이후 AI-assisted 단계로 확장 가능한 구조만 만든다.

```python
from __future__ import annotations

from pathlib import Path

from cowork_pilot.planning.authoring import write_exec_plan
from cowork_pilot.planning.classification import classify_project
from cowork_pilot.planning.docs_inventory import check_core_docs
from cowork_pilot.planning.storage import ensure_run_dirs


def run_planning_pipeline(*, project_dir: Path, run_id: str, planning_dir: Path, spec_path: str) -> list[Path]:
    run_dir = ensure_run_dirs(project_dir / "docs" / "generated" / "planning-runs", run_id)
    (run_dir / "classification-report.md").write_text("# classification\n", encoding="utf-8")
    (run_dir / "core-docs-check.md").write_text("# core docs\n", encoding="utf-8")
    return write_exec_plan(
        result=...,  # replace with packed result from prior stages in follow-up step
        planning_dir=planning_dir,
        project_dir=str(project_dir),
        spec_path=spec_path,
    )
```

Replace the `...` immediately in the same change with the smallest deterministic packed result used by the runner tests; do not leave a placeholder in the actual implementation.

- [ ] **Step 6: 테스트 재실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_plan_parser.py -q`

Expected:
- PASS

---

## Task 6: docs-orchestrator Adapter (Phase 5 Replacement)

**Files:**
- Modify: `src/cowork_pilot/docs_orchestrator.py`
- Modify: `src/cowork_pilot/orchestrator_state.py`
- Modify: `tests/test_docs_orchestrator.py`

- [ ] **Step 1: adapter behavior 테스트 작성**

`tests/test_docs_orchestrator.py`에 새 테스트를 추가한다.

```python
def test_phase_5_uses_planning_v3_runner(monkeypatch, phase1_completed_state, base_config, orch_config, tmp_path):
    calls = []

    def fake_run_planning_pipeline(**kwargs):
        calls.append(kwargs)
        planning_dir = tmp_path / "docs" / "exec-plans" / "planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        path = planning_dir / "01-core.md"
        path.write_text(
            "# sample\n\n## Metadata\n- project_dir: /tmp/x\n- status: pending\n\n---\n\n"
            "## Chunk 1: sample\n\n### Completion Criteria\n- [ ] pytest -q\n\n"
            "### Tasks\n- Task 1: sample\n\n### Session Prompt\n```\nsample\n```\n",
            encoding="utf-8",
        )
        return [path]

    monkeypatch.setattr(
        "cowork_pilot.docs_orchestrator.run_planning_pipeline",
        fake_run_planning_pipeline,
    )

    state = _run_phase_5_outline(
        phase1_completed_state,
        base_config,
        orch_config,
        tmp_path,
        tmp_path / "sessions",
        tmp_path / "state.json",
    )

    assert calls
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_docs_orchestrator.py::test_phase_5_uses_planning_v3_runner -q`

Expected:
- `AttributeError` / existing phase 5 session behavior mismatch

- [ ] **Step 3: docs-orchestrator Phase 5 adapter 구현**

`src/cowork_pilot/docs_orchestrator.py`에서 `_run_phase_5_outline`를 새 planning runner adapter로 교체한다.

```python
from cowork_pilot.planning.runner import run_planning_pipeline


def _run_phase_5_outline(...):
    step = "phase_5_outline"
    state = _update_state_running(state, step)
    save_state(state, state_path)

    planning_dir = project_dir / "docs" / "exec-plans" / "planning"
    outputs = run_planning_pipeline(
        project_dir=project_dir,
        run_id=_build_planning_run_id(state),
        planning_dir=planning_dir,
        spec_path=_resolve_primary_spec_path(project_dir),
    )

    if not outputs:
        return _update_state_error(state, step, "Planning V3 did not create exec-plans")

    state = _update_state_completed(state, step, "Planning Engine V3 exec-plan 생성 완료")
    save_state(state, state_path)
    return state
```

Keep the old `phase_5_detail` path readable for backward compatibility, but make `_determine_next_step()` stop generating new `phase_5_detail:*` work for V3-created runs.

- [ ] **Step 4: state metadata 추가**

`src/cowork_pilot/orchestrator_state.py`에 planning run metadata를 추가한다.

```python
current={"phase": "phase_5", "step": "phase_5_outline", "status": "idle", "planning_run_id": ""}
```

Extend serializer/deserializer to preserve `planning_run_id` and any future `planning_profile`.

- [ ] **Step 5: docs-orchestrator regression 실행**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_docs_orchestrator.py tests/test_orchestrator_state.py -q`

Expected:
- PASS

---

## Task 7: CLI Surfaces (`cowork-pilot --mode planning` + `cowork-pilot-codex planning`)

**Files:**
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/codex/main.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_planning_runner.py` (extend)

- [ ] **Step 1: CLI contract 테스트 작성**

Add tests that assert:

- `cowork-pilot --mode planning` dispatches to `run_planning_pipeline()`
- `cowork-pilot-codex planning` dispatches to the same runner

Use `unittest.mock.patch` around imported runner functions instead of spawning real subprocesses.

```python
@patch("cowork_pilot.main.run_planning_pipeline")
def test_main_planning_mode_dispatches(mock_run, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    ...
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py -q`

Expected:
- parser/argparse dispatch failures

- [ ] **Step 3: main CLI에 planning mode 추가**

`src/cowork_pilot/main.py`에서 argparse choice를 늘리고 planning dispatch를 연결한다.

```python
parser.add_argument(
    "--mode",
    type=str,
    choices=["watch", "harness", "meta", "docs-orchestrator", "planning"],
    default="watch",
)
...
elif args.mode == "planning":
    from cowork_pilot.config import load_planning_config
    from cowork_pilot.planning.runner import run_planning_pipeline
    planning_config = load_planning_config(Path(args.config))
    run_planning_pipeline(
        project_dir=Path(config.project_dir),
        run_id=...,
        planning_dir=Path(config.project_dir) / "docs" / "exec-plans" / "planning",
        spec_path=_resolve_primary_spec_path(Path(config.project_dir)),
    )
```

Replace the `...` in the real code with the same run-id builder introduced in Task 1.

- [ ] **Step 4: codex CLI planning subcommand 추가**

`src/cowork_pilot/codex/main.py`에 planning subcommand를 추가한다.

```python
planning_parser = subparsers.add_parser(
    "planning",
    help="Run Planning Engine V3 via shared planning core",
)
planning_parser.add_argument("--project-dir", type=str, default="")
planning_parser.add_argument("--target-version", type=str, default="v-next")
```

Dispatch:

```python
elif args.command == "planning":
    exit_code = asyncio.run(_run_planning(args))
    sys.exit(exit_code)
```

Implementation may call the shared runner synchronously inside `asyncio.to_thread(...)` if needed; keep the contract shared with `cowork-pilot --mode planning`.

- [ ] **Step 5: full planning regression**

Run:

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest \
  tests/test_planning_models.py \
  tests/test_planning_classification.py \
  tests/test_planning_docs_inventory.py \
  tests/test_planning_completeness.py \
  tests/test_planning_packing.py \
  tests/test_planning_runner.py \
  tests/test_docs_orchestrator.py \
  tests/test_config.py -q
```

Expected:
- PASS

- [ ] **Step 6: final repo smoke**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest -q`

Expected:
- full suite PASS

---

## Self-Review Checklist

- [ ] `Planning Engine V3` spec의 핵심 목표가 모두 task에 매핑되는지 확인
- [ ] `Ghost CTO Domain + Workflow Core`와 충돌하는 가정이 없는지 확인
- [ ] `docs-orchestrator 대체`와 `Codex CLI 실행 가능성`이 구현 task에 실제 반영됐는지 확인
- [ ] `small 규모 chunk 분리 규칙`이 테스트와 구현에 모두 박혀 있는지 확인
- [ ] `run 단위 intermediate docs`가 실제 파일 경로와 테스트에 반영됐는지 확인
- [ ] `TODO`, `TBD`, `...`, “나중에” 같은 placeholder가 plan 본문에 남지 않았는지 확인

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-07-planning-engine-v3-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Choose one when you want to start implementation.
