# Planning Engine V3 Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 뼈대만 있는 `Planning Engine V3`를 실제 `Greenfield/Brownfield`, `Interactive/Hybrid/Auto`, multi-session planning, delta artifact, question/answer loop가 동작하는 planning engine으로 완성한다.

**Architecture:** `run_planning_pipeline()`의 현재 one-shot placeholder 흐름을 stage/substage 기반 pipeline으로 교체한다. runtime handoff layer가 제공하는 marker, state, session profile, codex bridge를 사용해 각 stage를 실제 Codex session으로 실행하고, intermediate docs를 단계별 산출물로 고정한다. Greenfield와 Brownfield는 별도 입력 adapter를 두고, 모두 동일한 stage executor와 final exec-plan authoring으로 수렴시킨다.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, Jinja2, asyncio subprocess bridge, pytest

**Git note:** 사용자 요청에 따라 이 plan은 commit step을 포함하지 않는다.

---

## File Structure

> **Note:** `src/cowork_pilot/planning/` 디렉토리는 현재 레포에 존재하지 않는다. Task 0이 패키지와 기초 모듈을 모두 생성한다. 이후 task에서 Modify로 표기된 파일은 Task 0이 만든 뼈대 위에서 동작한다.

| Action | File | Responsibility |
|--------|------|----------------|
| **Task 0: Bootstrap** | | |
| Create | `src/cowork_pilot/planning/__init__.py` | planning package exports |
| Create | `src/cowork_pilot/planning/models.py` | stage enums, size class, project mode, snapshot models, document-role/profile models, pipeline dataclasses |
| Create | `src/cowork_pilot/planning/storage.py` | run-id creation, run-dir bootstrap, intermediate artifact write helpers |
| Create | `src/cowork_pilot/planning/classification.py` | provisional classification, Brownfield initial snapshot, Greenfield baseline |
| Create | `src/cowork_pilot/planning/docs_inventory.py` | convention-profile detection, document-role resolution, core/adaptive docs checks |
| Create | `src/cowork_pilot/planning/completeness.py` | core-doc review profile and product completeness rules |
| Create | `src/cowork_pilot/planning/scope.py` | scope-map models and translators |
| Create | `src/cowork_pilot/planning/sizing.py` | work sizing heuristics and report serializer |
| Create | `src/cowork_pilot/planning/packing.py` | chunk packing rules and plan grouping |
| Create | `src/cowork_pilot/planning/review.py` | review verdict rules (coverage/sizing/executionability/overdesign) |
| Create | `src/cowork_pilot/planning/authoring.py` | final exec-plan Markdown generation and parser validation |
| Create | `src/cowork_pilot/planning/prompts.py` | stage prompt builders and template rendering |
| Create | `src/cowork_pilot/planning/runner.py` | placeholder pipeline orchestration entrypoint |
| Create | `tests/test_planning_models.py` | planning models/config/storage tests |
| Create | `tests/test_planning_classification.py` | provisional classification tests |
| Create | `tests/test_planning_docs_inventory.py` | role mapping, profile detection, adaptive-doc selection tests |
| Create | `tests/test_planning_completeness.py` | core-doc review and completeness profile tests |
| Create | `tests/test_planning_runner.py` | placeholder pipeline smoke tests |
| **Task 1+: Behavior completion** | | |
| Create | `src/cowork_pilot/planning/spec_sources.py` | empty project / uploaded spec / existing docs / existing code input discovery + document-role mapping |
| Create | `src/cowork_pilot/planning/question_policy.py` | stage-level question permission, blocking thresholds, assumption eligibility |
| Create | `src/cowork_pilot/planning/greenfield.py` | empty-project bootstrap and uploaded-spec normalization |
| Create | `src/cowork_pilot/planning/brownfield.py` | Brownfield 3-stage sub-pipeline: code observation extraction, observation synthesis, gap synthesis |
| Create | `src/cowork_pilot/planning/stage_executor.py` | one stage/substage execution using runtime orchestrator + prompts + artifact writing |
| Create | `src/cowork_pilot/planning/pipeline.py` | stage graph orchestration across 10 stages and planned substages |
| Modify | `src/cowork_pilot/planning/classification.py` | real input extraction, anchor-case-aware heuristics, classification report schema, reclassification |
| Modify | `src/cowork_pilot/planning/docs_inventory.py` | adaptive docs selection plus size-aware core-doc required-set resolution via document-role mapping |
| Modify | `src/cowork_pilot/planning/completeness.py` | required/conditional/not_applicable logic plus coverage-level pass/fail evaluation |
| Modify | `src/cowork_pilot/planning/prompts.py` | runtime-aware stage prompts and marker protocol instructions |
| Modify | `src/cowork_pilot/planning/runner.py` | replace placeholder one-shot pipeline with stage pipeline entrypoint |
| Modify | `src/cowork_pilot/planning/review.py` | coverage/sizing/executionability/overdesign with gap artifact consumption and anti-overdesign rules |
| Modify | `src/cowork_pilot/docs_orchestrator.py` | planning stage to call completed V3 runtime pipeline |
| Modify | `src/cowork_pilot/orchestrator_state.py` | richer planning run metadata and recovery from runtime states |
| Create | `tests/test_planning_greenfield.py` | empty project / uploaded spec normalization tests |
| Create | `tests/test_planning_brownfield.py` | Brownfield 3-stage sub-pipeline tests (extraction, synthesis, gap synthesis) |
| Create | `tests/test_planning_question_policy.py` | stage-level question / assumption rules tests |
| Create | `tests/test_planning_stage_executor.py` | stage/substage execution with mocked markers tests |
| Modify | `tests/test_planning_classification.py` | real-input classification + reclassification tests |
| Modify | `tests/test_planning_docs_inventory.py` | adaptive docs from real project signals tests |
| Modify | `tests/test_planning_completeness.py` | completeness profile gating tests |
| Create | `tests/test_planning_pipeline_units.py` | scope/sizing/packing/review unit tests |
| Modify | `tests/test_planning_runner.py` | multi-session pipeline integration tests |
| Modify | `tests/test_docs_orchestrator.py` | runtime-state-aware Phase 5 tests |

---

## Task 0: Planning Package Bootstrap

> **Why this task exists:** `src/cowork_pilot/planning/` 디렉토리가 현재 레포에 존재하지 않는다. 이 task가 패키지와 기초 모듈 뼈대를 만들어야 runtime handoff plan과 이후 completion task들이 시작할 수 있다.

**Files:**
- Create: `src/cowork_pilot/planning/__init__.py`
- Create: `src/cowork_pilot/planning/models.py`
- Create: `src/cowork_pilot/planning/storage.py`
- Create: `src/cowork_pilot/planning/classification.py`
- Create: `src/cowork_pilot/planning/docs_inventory.py`
- Create: `src/cowork_pilot/planning/completeness.py`
- Create: `src/cowork_pilot/planning/scope.py`
- Create: `src/cowork_pilot/planning/sizing.py`
- Create: `src/cowork_pilot/planning/packing.py`
- Create: `src/cowork_pilot/planning/review.py`
- Create: `src/cowork_pilot/planning/authoring.py`
- Create: `src/cowork_pilot/planning/prompts.py`
- Create: `src/cowork_pilot/planning/runner.py`
- Create: `tests/test_planning_models.py`
- Create: `tests/test_planning_classification.py`
- Create: `tests/test_planning_docs_inventory.py`
- Create: `tests/test_planning_completeness.py`
- Create: `tests/test_planning_runner.py`

- [ ] **Step 1: Create planning package with core models**

`models.py` must define at minimum:

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


class PlanningStage(str, Enum):
    CLASSIFICATION = "classification"
    BROWNFIELD_CODE_OBSERVATION_EXTRACTION = "brownfield_code_observation_extraction"
    BROWNFIELD_OBSERVATION_SYNTHESIS = "brownfield_observation_synthesis"
    BROWNFIELD_GAP_SYNTHESIS = "brownfield_gap_synthesis"
    CORE_DOCS_CHECK = "core_docs_check"
    ADAPTIVE_DOCS_SELECTION = "adaptive_docs_selection"
    CORE_DOCS_PRESENCE_REVIEW = "core_docs_presence_review"
    PRODUCT_COMPLETENESS_REVIEW = "product_completeness_review"
    SCOPE_STRUCTURING = "scope_structuring"
    WORK_SIZING = "work_sizing"
    PLAN_PACKING = "plan_packing"
    PLAN_REVIEW = "plan_review"
    EXEC_PLAN_AUTHORING = "exec_plan_authoring"


class ProjectConventionProfile(str, Enum):
    SPECS_CENTERED = "specs_centered"
    PRODUCT_SPECS_CENTERED = "product_specs_centered"


@dataclass(frozen=True)
class ClassificationSnapshot:
    project_mode: ProjectMode
    size_class: SizeClass
    product_type: str
    confidence: str  # low | medium | high
    borderline: bool
    classification_snapshot_kind: str = "initial"  # initial | confirmed
    # Brownfield additional fields
    initial_size_class: SizeClass | None = None
    confirmed_size_class: SizeClass | None = None
    initial_borderline: bool | None = None
    confirmed_borderline: bool | None = None
    confirmed_change_impact: str | None = None
    requires_observation_reclassification: bool = False
```

- [ ] **Step 2: Create storage helpers**

`storage.py` must provide:

```python
def create_run_id(mode: str, target_version: str) -> str: ...
def bootstrap_run_dir(base_dir: Path, run_id: str) -> Path: ...
def write_intermediate_doc(run_dir: Path, filename: str, content: str) -> Path: ...
```

- [ ] **Step 3: Create placeholder modules with minimal public API**

Each module should have its core dataclasses and function signatures with placeholder implementations. These are NOT empty files — they must be importable and have enough structure for tests to import from them.

Minimum per module:

- `classification.py`: `classify_project()` → returns `ClassificationSnapshot`
- `docs_inventory.py`: `check_core_docs()`, `select_adaptive_docs()`
- `completeness.py`: `run_completeness_review()`
- `scope.py`: `build_scope_map()`
- `sizing.py`: `size_work_items()`
- `packing.py`: `pack_plans()`
- `review.py`: `run_plan_review()`
- `authoring.py`: `write_exec_plan()`
- `prompts.py`: `render_stage_prompt()`
- `runner.py`: `run_planning_pipeline()`

- [ ] **Step 4: Write baseline tests**

`tests/test_planning_models.py`:

```python
from cowork_pilot.planning.models import PlanningStage, ProjectMode, SizeClass


def test_planning_stage_enums_include_brownfield_substages():
    assert PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION.value == "brownfield_code_observation_extraction"
    assert PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS.value == "brownfield_observation_synthesis"
    assert PlanningStage.BROWNFIELD_GAP_SYNTHESIS.value == "brownfield_gap_synthesis"


def test_project_modes():
    assert ProjectMode.GREENFIELD.value == "greenfield"
    assert ProjectMode.BROWNFIELD.value == "brownfield"
```

`tests/test_planning_classification.py`, `tests/test_planning_docs_inventory.py`, `tests/test_planning_completeness.py`, `tests/test_planning_runner.py`: baseline import and smoke tests.

- [ ] **Step 5: Run bootstrap tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_classification.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py tests/test_planning_runner.py -q`

Expected:
- all bootstrap tests PASS
- all planning modules importable

---

## Task 1: Input Discovery and Project Mode Resolution

**Files:**
- Create: `src/cowork_pilot/planning/spec_sources.py`
- Modify: `src/cowork_pilot/planning/classification.py`
- Create: `tests/test_planning_greenfield.py`
- Modify: `tests/test_planning_classification.py`

- [ ] **Step 1: Write failing tests for empty-project, uploaded-spec, and Brownfield source discovery**

Add tests like:

```python
from cowork_pilot.planning.spec_sources import discover_planning_inputs
from cowork_pilot.planning.models import ProjectMode


def test_discover_inputs_marks_empty_project_as_greenfield(tmp_path):
    result = discover_planning_inputs(tmp_path)
    assert result.project_mode is ProjectMode.GREENFIELD
    assert result.empty_project is True


def test_discover_inputs_treats_existing_spec_as_source_material(tmp_path):
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "incoming.md").write_text("# Legacy Spec", encoding="utf-8")
    result = discover_planning_inputs(tmp_path)
    assert result.uploaded_spec_path == spec_dir / "incoming.md"
    assert result.source_material_only is True
```

- [ ] **Step 2: Run the new discovery tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_greenfield.py tests/test_planning_classification.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: Implement source discovery primitives**

`spec_sources.py` should discover:

- empty project
- canonical docs present
- uploaded source-material spec
- existing codebase indicators
- Brownfield current-state signals

Public API:

```python
@dataclass(frozen=True)
class PlanningInputs:
    project_mode: ProjectMode
    canonical_spec_paths: tuple[Path, ...]
    uploaded_spec_path: Path | None
    empty_project: bool
    has_existing_code: bool
    source_material_only: bool
```

- [ ] **Step 4: Implement Document Role Mapping**

> **Design reference:** V3 설계 스펙 9.2.1.
> planning engine은 고정 경로가 아니라 `document_role`을 기준으로 문서를 인식한다.

`spec_sources.py`에 document role resolver를 추가한다.

각 role은 다음 4개 계약을 가져야 한다:

- `allowed_path_aliases`: 해당 role이 인식하는 경로 목록 (예: `docs/specs/index.md`, `docs/product-specs/index.md`)
- `preferred_read_order`: alias 중 어떤 경로를 먼저 시도할지 (스펙 9.2.1 요구사항)
- `preferred_write_target`: 새 문서 생성 시 사용할 경로 (`project_convention_profile`에 따라 결정)
- `required_by_profile`: 어떤 convention profile에서 이 role이 필수인지

V1 필수 role 목록 (8개):

- `agents` → `AGENTS.md`
- `spec_index` → `docs/specs/index.md`, `docs/product-specs/index.md`
- `spec_documents` → `docs/specs/*.md`, `docs/product-specs/*.md`
- `architecture` → `ARCHITECTURE.md`, `docs/ARCHITECTURE.md`
- `design_guide` → `docs/DESIGN_GUIDE.md`
- `security` → `docs/SECURITY.md`
- `core_beliefs` → `docs/design-docs/core-beliefs.md`
- `data_model` → `docs/design-docs/data-model.md`

Convention profile 감지 순서:

1. `config` 또는 `AGENTS.md`의 명시 override
2. 기존 파일 레이아웃 감지
3. default profile 적용 (`specs_centered`)

Core models:

```python
@dataclass(frozen=True)
class DocumentRoleMapping:
    role: str
    allowed_path_aliases: tuple[str, ...]
    preferred_read_order: tuple[str, ...]
    preferred_write_target: Path
    required_by_profile: tuple[str, ...]


class ProjectConventionProfile(str, Enum):
    SPECS_CENTERED = "specs_centered"
    PRODUCT_SPECS_CENTERED = "product_specs_centered"


def detect_project_convention_profile(
    project_dir: Path,
    explicit_override: str | None = None,
    agents_text: str = "",
) -> ProjectConventionProfile: ...


def resolve_document_role_mapping(
    profile: ProjectConventionProfile,
) -> dict[str, DocumentRoleMapping]: ...
```

Tests:

```python
def test_detect_convention_profile_uses_explicit_override():
    profile = detect_project_convention_profile(tmp_path, explicit_override="product_specs_centered")
    assert profile is ProjectConventionProfile.PRODUCT_SPECS_CENTERED


def test_resolve_role_mapping_covers_all_8_roles():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)
    assert set(mapping.keys()) == {"agents", "spec_index", "spec_documents", "architecture", "design_guide", "security", "core_beliefs", "data_model"}


def test_role_mapping_includes_preferred_read_order():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)
    assert mapping["spec_index"].preferred_read_order[0] == "docs/specs/index.md"


def test_role_mapping_write_target_follows_profile():
    mapping = resolve_document_role_mapping(ProjectConventionProfile.SPECS_CENTERED)
    assert mapping["spec_index"].preferred_write_target == Path("docs/specs/index.md")
```

- [ ] **Step 5: Extend classification to use discovered inputs**

`ClassificationInputs` should no longer default to `ProjectMode.GREENFIELD` only. It must accept:

- discovered project mode
- feature/role/flow/integration estimates
- Brownfield change impact
- source-material / canonical-doc presence
- downstream core-doc requirement strength hints
- resolved `document_role_mapping` from Step 4

- [ ] **Step 5A: Add classification report schema and anchor cases**

`classification.py` should emit a structured result that includes:

- `size_class`
- `product_type`
- `axis_observations`
- `rationale`
- `confidence`
- `borderline`

Add explicit anchor-case tests:

- clear `small anchor`
- clear `medium anchor`
- clear `large anchor`
- borderline `medium/large` case

- [ ] **Step 6: Re-run classification/discovery/role-mapping tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_greenfield.py tests/test_planning_classification.py -q`

Expected:
- discovery + classification + document role mapping tests PASS

---

## Task 2: Greenfield Adapters (Empty Project Bootstrap + Uploaded Spec Normalization)

**Files:**
- Create: `src/cowork_pilot/planning/greenfield.py`
- Modify: `src/cowork_pilot/planning/prompts.py`
- Modify: `tests/test_planning_greenfield.py`

- [ ] **Step 1: Write failing tests for both Greenfield entry flows**

Add tests for:

- empty project => bootstrap prompt/artifacts seeded
- uploaded spec => source material converted into canonical draft inputs

```python
from cowork_pilot.planning.greenfield import (
    bootstrap_empty_project_inputs,
    normalize_uploaded_spec,
)


def test_bootstrap_empty_project_inputs_creates_seed_context(tmp_path):
    seed = bootstrap_empty_project_inputs(tmp_path)
    assert "AGENTS.md" in seed.required_outputs
    assert "docs/specs" in seed.required_outputs


def test_normalize_uploaded_spec_preserves_original_reference(tmp_path):
    src = tmp_path / "legacy.md"
    src.write_text("# Legacy", encoding="utf-8")
    normalized = normalize_uploaded_spec(src)
    assert normalized.source_material_path == src
    assert normalized.target_stage == "project_classification"
```

- [ ] **Step 2: Run Greenfield adapter tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_greenfield.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: Implement empty-project bootstrap**

This adapter should define the initial canonical-doc targets without pretending they already exist.

Core outputs to seed:

- `AGENTS.md`
- canonical spec draft path
- `docs/DESIGN_GUIDE.md`
- `docs/product-specs/index.md`

And mark these as always-required baseline docs for `small`:

- `AGENTS.md`
- canonical spec draft path
- `docs/DESIGN_GUIDE.md`
- `docs/product-specs/index.md`

The following start as `conditional` for `small`, but may become `required` depending on product type / integrations / risk:

- `ARCHITECTURE.md`
- `docs/SECURITY.md`
- `docs/design-docs/core-beliefs.md`
- `docs/design-docs/data-model.md`
- detailed `docs/product-specs/*`

- [ ] **Step 4: Implement uploaded-spec normalization**

Normalization rules:

- uploaded spec is treated as `source material`
- original path is retained in metadata
- canonical draft is produced in planning run artifacts first
- later approval promotes normalized content into canonical docs

- [ ] **Step 5: Re-run Greenfield adapter tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_greenfield.py tests/test_planning_runner.py -q`

Expected:
- Greenfield entry tests PASS
- existing runner tests remain green or fail only on expected downstream pipeline changes

---

## Task 3: Brownfield 3-Stage Sub-Pipeline (Extraction → Synthesis → Gap Synthesis)

> **Design reference:** V3 설계 스펙 12.1.1–12.1.3, 런타임 핸드오프 스펙 11.2.
> Brownfield 구현 상태 파악은 코드 전체를 한 번에 읽지 않는다. `분할 관찰 → 관찰 합성 → gap synthesis` 3단계를 거쳐야 한다.
> 런타임 핸드오프 플랜 Task 3의 session profile / artifact ownership이 이 3단계에 대응한다.

**Files:**
- Create: `src/cowork_pilot/planning/brownfield.py`
- Create: `tests/test_planning_brownfield.py`
- Modify: `src/cowork_pilot/planning/prompts.py`

- [ ] **Step 1: Write failing tests for the 3-stage Brownfield sub-pipeline**

Add tests covering each stage independently and the full pipeline flow:

```python
from cowork_pilot.planning.brownfield import (
    run_code_observation_extraction,
    run_observation_synthesis,
    run_gap_synthesis,
    BrownfieldSubPipeline,
)
from cowork_pilot.planning.models import SizeClass


def test_extraction_produces_per_slice_observation_files(tmp_path):
    """Stage 1: 도메인/모듈 단위로 분할 관찰 기록을 생성한다."""
    result = run_code_observation_extraction(
        project_dir=tmp_path,
        slices=("auth", "dashboard"),
        size_class=SizeClass.MEDIUM,
    )
    assert "code-observations/auth.md" in result.generated_files
    assert "code-observations/dashboard.md" in result.generated_files
    for path in result.generated_files:
        assert result.completion_markers[path] is True  # <!-- ORCHESTRATOR:DONE -->


def test_observation_synthesis_reads_only_observation_files(tmp_path):
    """Stage 2: raw code를 다시 읽지 않고 code-observations/ 만 읽어 합성한다."""
    obs_dir = tmp_path / "code-observations"
    obs_dir.mkdir()
    (obs_dir / "auth.md").write_text("# Auth\nroutes: /login, /signup\n<!-- ORCHESTRATOR:DONE -->")
    (obs_dir / "dashboard.md").write_text("# Dashboard\nroutes: /home\n<!-- ORCHESTRATOR:DONE -->")

    result = run_observation_synthesis(run_dir=tmp_path)
    assert "implementation-observation-summary.md" in result.generated_files
    assert result.raw_code_accessed is False  # 원본 코드 직접 접근 금지


def test_gap_synthesis_requires_observation_summary(tmp_path):
    """Stage 3: observation summary 없이 gap synthesis를 시도하면 실패한다."""
    import pytest
    with pytest.raises(FileNotFoundError):
        run_gap_synthesis(
            run_dir=tmp_path,
            canonical_specs=("docs/specs/v2.md",),
            change_request_summary="Add notifications",
        )


def test_gap_synthesis_emits_both_gap_artifacts(tmp_path):
    """Stage 3: spec-implementation-gap.md + change-impact-gap.md 모두 생성."""
    (tmp_path / "implementation-observation-summary.md").write_text("# Summary\n<!-- ORCHESTRATOR:DONE -->")
    result = run_gap_synthesis(
        run_dir=tmp_path,
        canonical_specs=("docs/specs/v2.md",),
        change_request_summary="Add notifications",
    )
    assert "spec-implementation-gap.md" in result.generated_files
    assert "change-impact-gap.md" in result.generated_files


def test_full_brownfield_sub_pipeline_flows_in_order(tmp_path):
    """3단계가 extraction → synthesis → gap synthesis 순서로 실행된다."""
    pipeline = BrownfieldSubPipeline(
        project_dir=tmp_path,
        run_dir=tmp_path,
        canonical_specs=("docs/specs/v2.md",),
        change_request_summary="Add notifications",
        size_class=SizeClass.MEDIUM,
    )
    result = pipeline.run()
    assert result.stages_completed == [
        "brownfield_code_observation_extraction",
        "brownfield_observation_synthesis",
        "brownfield_gap_synthesis",
    ]
```

- [ ] **Step 2: Run Brownfield tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_brownfield.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: Implement Stage 1 — Code Observation Extraction**

`brownfield.py` 내 `run_code_observation_extraction()`:

- 프로젝트를 도메인/모듈/기능/entrypoint 단위 slice로 분할
- 각 slice별로 별도 세션에서 관찰 기록 생성 (`code-observations/<slice>.md`)
- 각 observation 문서에 최소 포함: 담당 범위, 엔트리포인트/라우트, 핵심 데이터 모델, 권한/역할 분기, 외부 연동 흔적, spec과 달라 보이는 지점, unknowns
- `<!-- ORCHESTRATOR:DONE -->` completion marker로 완료 표시
- slice 전략은 `SizeClass`에 따라 결정 (small: lightweight slices, medium: domain/module bundles, large: explicit slice sessions)

Core models:

```python
@dataclass(frozen=True)
class ExtractionResult:
    generated_files: tuple[str, ...]
    completion_markers: dict[str, bool]

@dataclass(frozen=True)
class SynthesisResult:
    generated_files: tuple[str, ...]
    raw_code_accessed: bool  # must always be False

@dataclass(frozen=True)
class GapSynthesisResult:
    generated_files: tuple[str, ...]
    gap_entries: tuple[GapEntry, ...]

@dataclass(frozen=True)
class GapEntry:
    path: str
    category: str  # spec_outdated | implementation_missing | intentional_divergence | undocumented_behavior
    description: str
```

- [ ] **Step 4: Implement Stage 2 — Observation Synthesis**

`brownfield.py` 내 `run_observation_synthesis()`:

- `code-observations/` 문서들**만** 읽는다 (원본 코드 재접근 금지)
- 분할 관찰 결과를 하나의 현재 시스템 그림으로 합침
- 중복/충돌 관찰 정리, 불명확 영역은 `unknown`으로 명시
- `implementation-observation-summary.md` 생성 + `<!-- ORCHESTRATOR:DONE -->` marker

- [ ] **Step 5: Implement Stage 3 — Gap Synthesis**

`brownfield.py` 내 `run_gap_synthesis()`:

- `implementation-observation-summary.md` + canonical docs + change request를 비교
- `spec-implementation-gap.md` 생성: 각 diff entry를 `spec_outdated | implementation_missing | intentional_divergence | undocumented_behavior`로 분류
- `change-impact-gap.md` 생성: 변경 요청이 기존 구현에 미치는 영향 범위 분석
- observation summary가 없으면 `FileNotFoundError` raise (3단계 순서 강제)
- 구현 상태가 불명확한 경우 추측으로 메우지 않고 `unknown`으로 남김

- [ ] **Step 6: Implement `BrownfieldSubPipeline` orchestrator**

3단계를 순서대로 연결하는 orchestrator:

```python
class BrownfieldSubPipeline:
    """classification → extraction[*] → synthesis → gap_synthesis → core_docs_check"""
    def run(self) -> BrownfieldPipelineResult: ...
```

- [ ] **Step 7: Re-run Brownfield tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_brownfield.py tests/test_planning_classification.py -q`

Expected:
- Brownfield 3-stage tests PASS
- classification still PASS

---

## Task 4: Stage-Level Question Policy and Marker-Driven Stage Execution

**Files:**
- Create: `src/cowork_pilot/planning/question_policy.py`
- Create: `src/cowork_pilot/planning/stage_executor.py`
- Create: `tests/test_planning_question_policy.py`
- Create: `tests/test_planning_stage_executor.py`
- Modify: `src/cowork_pilot/planning/prompts.py`

- [ ] **Step 1: Write failing tests for front-loaded questioning and broad-product assumptions**

Add tests like:

```python
from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.question_policy import should_allow_question, can_use_assumption


def test_front_loaded_policy_allows_questions_in_product_completeness_review():
    assert should_allow_question(
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        phase_strategy="question_heavy_then_auto",
    ) is True


def test_front_loaded_policy_discourages_questions_in_exec_plan_authoring():
    assert should_allow_question(
        stage=PlanningStage.EXEC_PLAN_AUTHORING,
        phase_strategy="question_heavy_then_auto",
    ) is False
```

- [ ] **Step 2: Run question policy tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_question_policy.py tests/test_planning_stage_executor.py -q`

Expected:
- missing module/function failures

- [ ] **Step 3: Implement question policy helpers**

Encode the agreed policy:

- question-heavy stages:
  - `Project Classification`
  - `Adaptive Docs Selection`
  - `Product Completeness Review`
  - `Scope Structuring`
  - `Plan Review`
- low-question stages:
  - `Core Docs Check`
  - `Core Docs Presence Review`
  - `Work Sizing`
  - `Plan Packing`
  - `Exec-Plan Authoring`

And encode `broad_product_design` assumption eligibility.

Also encode the V1 invalidation rule:

- non-blocking questions may be absorbed as assumptions
- if later contradicted, the stage executor must emit an invalidation side effect
- the affected stage must be marked for reopen or replan rather than silently rewritten

- [ ] **Step 4: Implement stage executor**

`stage_executor.py` should:

- open one planned stage/substage session
- render stage prompt with explicit marker instructions
- call runtime orchestrator / codex bridge
- persist outputs to the correct intermediate doc
- return stage result plus any queued question/assumption/approval metadata
- **non-blocking `INPUT_REQUIRED` absorption rule**: `source=exec`에서 `INPUT_REQUIRED(blocking=false)`가 들어오면, runtime layer가 question-queue에 기록한 뒤 stage_executor가 해당 질문에 대응하는 `ASSUMPTION_LOG` record를 생성하고 prompt context에 주입해야 한다. 즉 assumption record 생성의 owner는 `stage_executor`이며, runtime layer는 question 기록과 상태 유지만 담당한다.
- resumed exec prompt에는 기존 `answer-log.md`, `approval-log.md`, non-blocking 질문에서 생성된 assumption record를 다시 주입해야 한다. 즉 stage_executor는 runtime persistence를 읽어 후속 세션 context를 복원하는 owner이기도 하다.

Core shape:

```python
def execute_stage_subsession(... ) -> StageExecutionResult:
    ...
```

- [ ] **Step 5: Re-run stage executor tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_question_policy.py tests/test_planning_stage_executor.py -q`

Expected:
- policy and stage-execution tests PASS

---

## Task 5: Replace Placeholder Runner with Multi-Session Stage Pipeline

**Files:**
- Create: `src/cowork_pilot/planning/pipeline.py`
- Modify: `src/cowork_pilot/planning/runner.py`
- Modify: `src/cowork_pilot/planning/completeness.py`
- Modify: `src/cowork_pilot/planning/docs_inventory.py`
- Modify: `src/cowork_pilot/planning/scope.py`
- Modify: `src/cowork_pilot/planning/sizing.py`
- Modify: `src/cowork_pilot/planning/review.py`
- Modify: `tests/test_planning_runner.py`
- Modify: `tests/test_planning_docs_inventory.py`
- Modify: `tests/test_planning_completeness.py`

- [ ] **Step 1: Write failing integration tests for multi-stage pipeline behavior**

Add tests asserting:

- runtime pipeline creates all intermediate docs through staged execution
- `hybrid` uses front-loaded questions
- `brownfield` runs 3-stage sub-pipeline (extraction → synthesis → gap synthesis) before scope/sizing
- `brownfield` sub-pipeline produces `code-observations/`, `implementation-observation-summary.md`, `spec-implementation-gap.md`, `change-impact-gap.md` in order
- stage session profiles are honored
- `Greenfield Product Completeness Review` generates both `product-completeness-review.md` and `coverage-gap.md`
- blocking `INPUT_REQUIRED` / `APPROVAL_REQUIRED`가 `waiting_for_input` / `waiting_for_approval`로 중단된 뒤 `running_cli -> running_exec` roundtrip으로 재개된다
- non-blocking `INPUT_REQUIRED(blocking=false)`가 question queue + `ASSUMPTION_LOG`로 흡수되고, 후속 stage에서 invalidation 시 `NEEDS_HUMAN(reason=stage_reopen_required|replan_required)`로 surfaced 된다

- [ ] **Step 2: Run the planning integration tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py -q`

Expected:
- current placeholder runner fails the new integration assertions

- [ ] **Step 3: Implement stage graph orchestrator**

`pipeline.py` should:

- discover inputs
- classify (initial snapshot)
- resolve session profile for each stage
- execute stage/substage via `stage_executor`
- write named intermediate docs
- stop/resume correctly around blocking markers
- detect and surface non-blocking assumption invalidation
- **reclassify once at the designated trigger point** (see Step 3R below)
- call final `write_exec_plan(...)`

`pipeline.py` and runtime orchestration must use a single explicit contract:

```python
@dataclass(frozen=True)
class StageExecutionResult:
    runtime_state: str
    completed_stage: str | None
    emitted_markers: tuple[MarkerPayload, ...]
    generated_outputs: tuple[GeneratedArtifact, ...]
    resume_handle: ResumeHandle | None
    queued_questions: tuple[QueuedQuestion, ...]
    queued_approvals: tuple[QueuedApproval, ...]
    assumption_records: tuple[AssumptionRecord, ...]
```

Pipeline progression rules:

- `pipeline.py`는 `runtime_state == "running_exec"` 이고 `completed_stage == current_stage`일 때만 다음 stage로 진행한다.
- `waiting_for_input`, `waiting_for_approval`, `waiting_for_human`, `escalated`, `failed`면 다음 stage로 넘어가지 않고 run metadata만 기록한 뒤 종료한다.
- resumed path에서는 runtime plan의 `resume_planning_waiting_run_with_cli(...)`를 호출해 `waiting_* -> running_cli -> running_exec`를 마친 후, 반환된 `StageExecutionResult`를 같은 규칙으로 해석한다.

- [ ] **Step 3R: Implement one-time reclassification logic**

> **Design reference:** V3 설계 스펙 8.7, 8.4 (`classification_snapshot_kind`).
> 분류 결과는 planning 전체 동안 무한정 바꾸지 않는다. 딱 한 번만 재조정 가능하다.

Reclassification rules:

- **Greenfield:** `Product Completeness Review` 종료 후 한 번만 재조정 가능
- **Brownfield:** `Brownfield Observation Synthesis` 종료 후 한 번만 재조정 가능

Implementation requirements:

1. `classification.py`에 reclassification 함수 추가:

```python
def reclassify_greenfield_after_completeness(
    current_snapshot: ClassificationSnapshot,
    completeness_result: CompletenessResult,
    already_reclassified: bool,
) -> ClassificationSnapshot:
    if already_reclassified:
        return current_snapshot  # noop — 2번째 시도는 무시
    # completeness 결과를 반영해 size_class/borderline 재판정
    ...


def reclassify_brownfield_after_observation(
    current_snapshot: ClassificationSnapshot,
    observation_summary: ObservationSummary,
    confirmed_change_impact: str,
    already_reclassified: bool,
) -> ClassificationSnapshot:
    if already_reclassified:
        return current_snapshot  # noop
    # observation synthesis 결과로 confirmed_size_class, confirmed_borderline, confirmed_change_impact 계산
    ...
```

2. Snapshot 보존 규칙:
   - `initial_*` (초기 classification)와 `confirmed_*` (재조정 후)를 **함께** run metadata에 보존
   - `confirmed_*`만 현재 유효값으로 승격
   - Brownfield에서는 `classification_snapshot_kind: initial | confirmed` 필드 필수

3. `pipeline.py`에서 reclassification trigger 삽입:
   - Greenfield: `product_completeness_review` stage 완료 직후 `reclassify_greenfield_after_completeness()` 호출
   - Brownfield: `brownfield_observation_synthesis` stage 완료 직후 `reclassify_brownfield_after_observation()` 호출
   - `already_reclassified` flag로 2회 이상 호출 방지

4. Tests:

```python
def test_greenfield_reclassification_happens_once_after_completeness():
    result = reclassify_greenfield_after_completeness(
        current_snapshot=initial_snapshot,
        completeness_result=completeness_result,
        already_reclassified=False,
    )
    assert result.classification_snapshot_kind == "confirmed"
    assert result.size_class == "medium"  # example reclassification

    noop = reclassify_greenfield_after_completeness(
        current_snapshot=result,
        completeness_result=completeness_result,
        already_reclassified=True,
    )
    assert noop is result  # unchanged


def test_brownfield_reclassification_preserves_initial_and_confirmed():
    confirmed = reclassify_brownfield_after_observation(
        current_snapshot=initial_snapshot,
        observation_summary=summary,
        confirmed_change_impact="high",
        already_reclassified=False,
    )
    assert confirmed.confirmed_size_class is not None
    assert confirmed.confirmed_borderline is not None
    assert confirmed.confirmed_change_impact == "high"
    assert confirmed.initial_size_class == initial_snapshot.size_class  # preserved
```

- [ ] **Step 3A: Resolve size-aware core-doc requirements before completeness review**

`docs_inventory.py` and `completeness.py` must compute:

- `core_doc_axes`
- `required_core_docs`
- `conditional_core_docs`
- `not_applicable_core_docs`

> **Important:** `docs_inventory.py`는 고정 경로가 아니라 Task 1에서 구현한 `resolve_document_role_mapping()`을 통해 문서를 찾아야 한다. `preferred_read_order`를 따라 alias를 순서대로 시도하고, `preferred_write_target`으로 새 문서 경로를 결정한다.

At minimum:

- `design_guide` role stays `required` for `small / medium / large`
- `agents`, canonical spec, `spec_index` roles stay `required` for all sizes
- `architecture`, `security`, `core_beliefs`, `data_model`, `spec_documents` roles can be `conditional` in `small`
- `medium` and `large` should promote more of those roles into `required`

- [ ] **Step 3B: Add completeness coverage levels and minimum-pass evaluation**

`completeness.py` must evaluate each category using:

- `missing`
- `mentioned`
- `scoped`
- `implementation_ready`
- `not_applicable`

And must compute:

- `required_minimum`
- `pass | fail`
- `follow_up_action`

Owner rule:

- Greenfield `Product Completeness Review`의 산출 owner는 `completeness.py`다.
- 이 stage는 `product-completeness-review.md`와 함께 `coverage-gap.md`를 **반드시** 생성한다.
- `pipeline.py`와 `review.py`는 `coverage-gap.md`를 소비할 수는 있어도 생성 owner가 아니다.

Add tests in `tests/test_planning_completeness.py` for:

- `small` page/function coverage passes at `scoped`
- `medium` page/function coverage fails at `mentioned`
- `small` 비기능 요구 passes at `mentioned`
- integration-heavy category requires at least `scoped`
- `not_applicable` skips failure
- Greenfield completeness stage writes `coverage-gap.md` with uncovered categories/items

- [ ] **Step 3C: Implement Plan Review rules in `review.py`**

> **Design reference:** V3 설계 스펙 12.9, 16절 (Anti-Overdesign).
> review는 별도 단계이며, 2 planned sessions (coverage-and-sizing / executionability-and-overdesign)로 나뉜다.

`review.py`에 다음 4개 review 관점의 판정 로직을 구현한다:

1. **coverage**: spec과 completeness 요구가 plan에 빠짐없이 반영되었는가
   - Greenfield: `coverage-gap.md`를 읽고 판정
   - Brownfield: `spec-implementation-gap.md`, `change-impact-gap.md`를 읽고 판정
2. **sizing**: 프로젝트 규모 대비 과소/과대 분해는 아닌가
3. **executionability**: 각 plan/chunk가 실제로 실행 가능하고, 검증/완료 판정이 가능한가
4. **overdesign**: 불필요한 문서, 화면, 플로우, 분해를 억지로 넣지 않았는가

Anti-overdesign 규칙 (스펙 16절):

- **YAGNI gate**: 추가 문서/화면/플로우는 실제 사용자 가치, 운영 필수성, 보안/권한/실행 완결성 중 하나에 근거해야 한다
- **Evidence rule**: AI가 무언가를 추가하면 어떤 요구사항/문서에서 유도됐는지, 어떤 빈 구멍을 메우는 것인지 intermediate docs에 근거를 남긴다
- **Surface area cap**: 질문 없이 자동 추가 가능한 범위를 제한. 큰 구조 변화, 많은 신규 문서, 역할 체계 변경은 질문 대상

Core public API:

```python
@dataclass(frozen=True)
class ReviewVerdict:
    coverage_pass: bool
    sizing_pass: bool
    executionability_pass: bool
    overdesign_pass: bool
    issues: tuple[ReviewIssue, ...]
    gap_artifacts_consumed: tuple[str, ...]


@dataclass(frozen=True)
class ReviewIssue:
    category: str  # coverage | sizing | executionability | overdesign
    severity: str  # blocking | warning
    description: str
    evidence: str
```

Tests:

```python
def test_review_fails_coverage_when_gap_artifact_items_not_in_plan():
    ...

def test_review_flags_overdesign_when_plan_adds_undocumented_screens():
    ...

def test_review_consumes_brownfield_gap_artifacts():
    ...

def test_review_passes_small_project_without_excessive_decomposition():
    ...
```

- [ ] **Step 4: Replace the old one-shot `run_planning_pipeline()`**

`runner.py` should become a thin entrypoint:

```python
def run_planning_pipeline(...):
    return run_planning_stage_graph(...)
```

The current placeholder logic:

- `ClassificationInputs(project_mode=ProjectMode.GREENFIELD)`
- hardcoded `web-app`
- single scope item from spec heading
- fixed review result

must be deleted.

- [ ] **Step 5: Re-run planning integration tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py tests/test_planning_pipeline_units.py -q`

Expected:
- pipeline tests PASS
- packing tests still PASS

---

## Task 6: Surface Integration (Main CLI, Codex CLI, Docs Orchestrator)

**Files:**
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/codex/main.py`
- Modify: `src/cowork_pilot/docs_orchestrator.py`
- Modify: `src/cowork_pilot/orchestrator_state.py`
- Modify: `tests/test_docs_orchestrator.py`
- Modify: `tests/test_planning_runner.py`

- [ ] **Step 1: Write failing integration tests for all three execution surfaces**

Add assertions that:

- `main --mode planning` creates runtime-aware run artifacts
- `cowork-pilot-codex planning` uses the same pipeline
- docs-orchestrator Phase 5 understands runtime-created outputs and run metadata

- [ ] **Step 2: Run surface integration tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_docs_orchestrator.py -q`

Expected:
- surface integration assertions fail until all callsites are switched

- [ ] **Step 3: Update all callsites to the completed pipeline**

Integration requirements:

- same `run_id` and `run_dir` semantics
- same runtime state persistence
- same intermediate doc names
- same final exec-plan authoring path

`orchestrator_state.py` must understand runtime states like:

- `waiting_for_input`
- `waiting_for_approval`
- `escalated`

- [ ] **Step 4: Re-run surface integration tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_docs_orchestrator.py tests/test_config.py -q`

Expected:
- all planning surface tests PASS

---

## Task 7: End-to-End Verification

**Files:**
- Modify: `tests/test_planning_runner.py`
- Modify: `tests/test_docs_orchestrator.py`
- Modify: `tests/test_codex_harness.py` (only if needed for shared event utility changes)

- [ ] **Step 1: Add final end-to-end regression tests**

Cover at least:

- Greenfield empty project bootstrap
- uploaded spec normalization
- Brownfield 3-stage sub-pipeline (extraction → synthesis → gap synthesis) produces all expected artifacts
- Brownfield reclassification after observation synthesis preserves `initial_*` + `confirmed_*` snapshots
- Greenfield reclassification after completeness review triggers once and is noop on second call
- document role mapping resolves paths via `preferred_read_order` (not hardcoded paths)
- blocking marker => `waiting_for_input`
- blocking approval => `waiting_for_approval`
- `waiting_for_input -> running_cli -> running_exec` roundtrip
- `waiting_for_approval -> running_cli -> running_exec` roundtrip
- non-blocking question absorption creates `ASSUMPTION_LOG`, and later invalidation reaches `waiting_for_human`
- Greenfield completeness stage emits `coverage-gap.md`
- final exec-plan output written to `docs/exec-plans/planning/`

- [ ] **Step 2: Run targeted regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_greenfield.py tests/test_planning_brownfield.py tests/test_planning_question_policy.py tests/test_planning_stage_executor.py tests/test_planning_runtime_orchestrator.py tests/test_planning_runner.py tests/test_docs_orchestrator.py tests/test_config.py -q`

Expected:
- all new V3 behavior tests PASS

- [ ] **Step 3: Run full project regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest -q`

Expected:
- full suite PASS
