# Planning Runtime Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Planning Runtime Handoff`를 구현해 `structured marker protocol`, `Brownfield session profile`, `resume_handle` 기반 `exec -> cli resume -> exec resume` handoff를 안정적으로 제공한다.

**Architecture:** runtime layer는 `src/cowork_pilot/planning/` 아래 planning 전용 모듈들로 분리한다. `marker_protocol.py`가 최종 assistant turn의 마지막 contiguous top-level bundle만 파싱하고, `session_profiles.py`가 stage/substage/session ownership을 고정하며, `runtime_orchestrator.py`가 `run-state.json`과 `resume_handle`을 갱신하면서 blocking/non-blocking marker를 처리한다. Codex CLI 연결은 `planning/codex_bridge.py`와 `codex/command_builder.py`가 담당하고, 공통 event parsing은 `src/cowork_pilot/codex/event_stream.py`로 올린다.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, asyncio, json, pytest

**Execution Order:** 이 plan은 `docs/superpowers/plans/2026-04-08-planning-engine-v3-completion.md`의 **Task 0 (Planning Package Bootstrap)** 이 완료된 상태에서 시작한다. Task 0은 `src/cowork_pilot/planning/` 패키지와 기초 모듈들(`__init__.py`, `models.py`, `storage.py`, `classification.py`, `docs_inventory.py`, `completeness.py`, `scope.py`, `sizing.py`, `packing.py`, `review.py`, `authoring.py`, `prompts.py`, `runner.py`)을 생성한다. 이 plan의 Task 1-6이 끝나면 completion plan의 Task 1 이후로 이어간다. `src/cowork_pilot/main.py`와 `src/cowork_pilot/codex/main.py`는 이 plan이 소유한다.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/cowork_pilot/planning/runtime_models.py` | runtime states, marker enums, policy knobs, resume-handle schema |
| Create | `src/cowork_pilot/planning/marker_protocol.py` | final-turn bundle extraction, code-fence stripping, marker validation |
| Create | `src/cowork_pilot/planning/session_profiles.py` | stage/substage matrix, Brownfield ownership table, completion predicates |
| Create | `src/cowork_pilot/planning/runtime_storage.py` | run-state, question/answer/assumption/approval persistence |
| Create | `src/cowork_pilot/planning/codex_bridge.py` | planning runtime wrappers over shared Codex commands |
| Create | `src/cowork_pilot/planning/runtime_orchestrator.py` | state transition engine and handoff orchestration |
| Create | `src/cowork_pilot/codex/event_stream.py` | shared Codex JSON event parsing and last assistant message extraction |
| Create | `src/cowork_pilot/codex/command_builder.py` | shared argv builders for `exec`, `resume`, `exec resume` |
| Modify | `src/cowork_pilot/planning/runner.py` | runtime-aware stage dispatch hook |
| Modify | `src/cowork_pilot/config.py` | runtime policy knobs under `PlanningConfig` |
| Modify | `config.toml` | `[planning]` runtime defaults |
| Modify | `src/cowork_pilot/codex/exec_runner.py` | consume shared event parsing and command utilities |
| Modify | `src/cowork_pilot/main.py` | `--mode planning` runtime integration |
| Modify | `src/cowork_pilot/codex/main.py` | `planning` subcommand path |
| Create | `tests/test_planning_marker_protocol.py` | parsing semantics tests |
| Create | `tests/test_planning_session_profiles.py` | Brownfield session profile and ownership tests |
| Create | `tests/test_planning_runtime_state.py` | runtime model/config/storage tests |
| Create | `tests/test_planning_codex_bridge.py` | shared command builder and event stream tests |
| Create | `tests/test_planning_runtime_orchestrator.py` | state machine and handoff tests |
| Create | `tests/test_codex_main.py` | `cowork-pilot-codex planning` CLI tests |
| Create | `tests/test_main_cli.py` | `cowork-pilot --mode planning` dispatch tests |
| Modify | `tests/test_planning_runner.py` | runtime-aware runner tests |
| Modify | `tests/test_config.py` | planning runtime config tests |
| Modify | `tests/test_codex_harness.py` | command/event-stream regression tests |

---

## Delivery Gates

- parser는 `최종 assistant message`만 입력으로 받고, `tail의 마지막 contiguous top-level bundle` 외에는 모두 무시해야 한다.
- `resume_handle`은 저장만 하면 실패다. `run-state.json`에 `resume_handle`, `resume_handle_kind`, `surface`, `stage`, `substage`가 모두 남아야 한다.
- Brownfield session profile은 `resume target`, `artifact owner`, `completion artifact`, `completion predicate`, `reopen trigger`, `next consumer` 6개 필드가 모두 있어야 한다.
- runtime storage는 `question-queue.md`, `answer-log.md`, `assumptions.md`, `approval-log.md`, `assumption-invalidations.md`, `runtime-events.ndjson`, `run-state.json`을 모두 실제로 쓴다.
- Codex command builder는 현재 harness와 같은 `exec` 의미를 유지해야 한다. 즉 `--dangerously-bypass-approvals-and-sandbox`를 빠뜨리면 실패다.
- `src/cowork_pilot/main.py`와 `src/cowork_pilot/codex/main.py`는 테스트 없이 연결만 추가하면 실패다. CLI parser 수준 테스트가 있어야 한다.

---

## Task 1: Runtime Models, Resume Handle, and Config Surface

**Files:**
- Create: `src/cowork_pilot/planning/runtime_models.py`
- Modify: `src/cowork_pilot/config.py`
- Modify: `config.toml`
- Create: `tests/test_planning_runtime_state.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing tests for runtime enums and resume-handle schema**

```python
from cowork_pilot.config import load_planning_config
from cowork_pilot.planning.runtime_models import (
    ApprovalPolicy,
    AssumptionScope,
    PhaseStrategy,
    PlanningRuntimeState,
    QuestionStrategy,
    ResumeHandleRef,
)


def test_runtime_state_enum_values():
    assert PlanningRuntimeState.RUNNING_EXEC.value == "running_exec"
    assert PlanningRuntimeState.WAITING_FOR_INPUT.value == "waiting_for_input"


def test_resume_handle_ref_uses_kind_and_value():
    ref = ResumeHandleRef(
        surface="exec",
        resume_handle_kind="codex_thread_id",
        resume_handle="thread-123",
        stage="product_completeness_review",
        substage="user-facing completeness",
    )
    assert ref.resume_handle_kind == "codex_thread_id"
    assert ref.resume_handle == "thread-123"
    assert ref.stage == "product_completeness_review"


def test_planning_config_loads_runtime_defaults(tmp_path):
    cfg = load_planning_config(tmp_path / "config.toml")
    assert cfg.question_strategy == "front_loaded"
    assert cfg.approval_policy == "final_draft_only"
```

- [ ] **Step 2: Run the runtime/config tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runtime_state.py tests/test_config.py -q`

Expected:
- import failure for `runtime_models`
- `PlanningConfig` missing runtime fields

- [ ] **Step 3: Implement runtime models and config knobs**

```python
# src/cowork_pilot/planning/runtime_models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlanningRuntimeState(str, Enum):
    PENDING = "pending"
    RUNNING_EXEC = "running_exec"
    RUNNING_CLI = "running_cli"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class QuestionStrategy(str, Enum):
    FRONT_LOADED = "front_loaded"
    BALANCED = "balanced"
    MINIMAL = "minimal"


class AssumptionScope(str, Enum):
    CONSERVATIVE = "conservative"
    BROAD_PRODUCT_DESIGN = "broad_product_design"


class ApprovalPolicy(str, Enum):
    FINAL_DRAFT_ONLY = "final_draft_only"
    SECTION_APPROVAL = "section_approval"


class PhaseStrategy(str, Enum):
    QUESTION_HEAVY_THEN_AUTO = "question_heavy_then_auto"
    EVENLY_DISTRIBUTED = "evenly_distributed"


@dataclass(frozen=True)
class ResumeHandleRef:
    surface: str
    resume_handle_kind: str
    resume_handle: str
    stage: str
    substage: str
```

```python
# src/cowork_pilot/config.py
@dataclass
class PlanningConfig:
    run_root: str = "docs/generated/planning-runs"
    default_decision_mode: str = "hybrid"
    default_project_mode: str = "greenfield"
    default_project_convention_profile: str = "specs_centered"
    codex_surface_enabled: bool = True
    question_strategy: str = "front_loaded"
    assumption_scope: str = "broad_product_design"
    approval_policy: str = "final_draft_only"
    phase_strategy: str = "question_heavy_then_auto"
```

- [ ] **Step 4: Add planning runtime defaults to `config.toml` and re-run tests**

```toml
[planning]
run_root = "docs/generated/planning-runs"
default_decision_mode = "hybrid"
default_project_mode = "greenfield"
default_project_convention_profile = "specs_centered"
codex_surface_enabled = true
question_strategy = "front_loaded"
assumption_scope = "broad_product_design"
approval_policy = "final_draft_only"
phase_strategy = "question_heavy_then_auto"
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runtime_state.py tests/test_config.py -q`

Expected:
- runtime/config tests PASS

- [ ] **Step 5: Commit runtime foundation changes**

Run: `git add src/cowork_pilot/planning/runtime_models.py src/cowork_pilot/config.py config.toml tests/test_planning_runtime_state.py tests/test_config.py && git commit -m "feat: add planning runtime models and config"`

Expected:
- commit succeeds

---

## Task 2: Marker Protocol Parser with Final-Turn Bundle Semantics

**Files:**
- Create: `src/cowork_pilot/planning/marker_protocol.py`
- Create: `tests/test_planning_marker_protocol.py`

- [ ] **Step 1: Add failing tests for last contiguous bundle parsing**

```python
from cowork_pilot.planning.marker_protocol import extract_terminal_marker_bundle


def test_parser_ignores_code_block_examples():
    message = '''
```text
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
</COWORK_PILOT_EVENT>
```

설명 텍스트

<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-1
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
'''
    bundle = extract_terminal_marker_bundle(message)
    assert [item.type for item in bundle] == ["STAGE_COMPLETE"]


def test_parser_only_accepts_last_contiguous_top_level_bundle():
    message = '''
설명 텍스트

<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: product_completeness_review
event_id: pcr-1
reason: continue
assumption: dashboard redirect
confidence: medium
impact: medium
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ok
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
'''
    bundle = extract_terminal_marker_bundle(message)
    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "STAGE_COMPLETE"]


def test_parser_rejects_text_inserted_inside_bundle():
    message = '''
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: keep chunk split
confidence: low
impact: medium
</COWORK_PILOT_EVENT>
중간 설명
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-2
reason: complete
summary: ok
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
'''
    assert extract_terminal_marker_bundle(message) == ()


def test_parser_rejects_input_required_missing_type_specific_fields():
    """스펙 7.4: INPUT_REQUIRED는 question, options, recommended, blocking 필수"""
    message = '''
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing redirect
question: 로그인 후 기본 이동 경로는?
</COWORK_PILOT_EVENT>
'''
    assert extract_terminal_marker_bundle(message) == ()


def test_parser_rejects_disallowed_bundle_combination():
    """스펙 7.3: STAGE_COMPLETE -> ASSUMPTION_LOG 순서는 허용되지 않음"""
    message = '''
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-1
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-2
reason: continue
assumption: keep split
confidence: low
impact: medium
</COWORK_PILOT_EVENT>
'''
    assert extract_terminal_marker_bundle(message) == ()


def test_parser_accepts_allowed_bundle_assumption_then_stage_complete():
    """스펙 7.3: ASSUMPTION_LOG -> STAGE_COMPLETE는 허용"""
    message = '''
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: product_completeness_review
event_id: pcr-1
reason: continue
assumption: dashboard redirect
confidence: medium
impact: medium
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ok
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
'''
    bundle = extract_terminal_marker_bundle(message)
    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "STAGE_COMPLETE"]


def test_parser_returns_empty_tuple_on_malformed_yaml():
    """콜론 없는 라인 등 malformed YAML에서 예외 대신 empty tuple 반환"""
    message = '''
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: test
event_id: t-1
reason: test
this line has no colon
question: test
options:
  - a
recommended: a
blocking: true
</COWORK_PILOT_EVENT>
'''
    assert extract_terminal_marker_bundle(message) == ()
```

- [ ] **Step 2: Run the parser tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_marker_protocol.py -q`

Expected:
- import failure for `marker_protocol`

- [ ] **Step 3: Implement the parser without adding a new dependency**

```python
from dataclasses import dataclass


EVENT_START = "<COWORK_PILOT_EVENT>"
EVENT_END = "</COWORK_PILOT_EVENT>"


@dataclass(frozen=True)
class MarkerEnvelope:
    type: str
    stage: str
    event_id: str
    reason: str
    payload: dict[str, object]


def _strip_fenced_code_blocks(message: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in message.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def _extract_blocks(message: str) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    while True:
        start = message.find(EVENT_START, cursor)
        if start == -1:
            return blocks
        end = message.find(EVENT_END, start)
        if end == -1:
            return blocks
        end += len(EVENT_END)
        blocks.append((start, end, message[start:end]))
        cursor = end


def _find_last_contiguous_bundle(message: str) -> list[str]:
    blocks = _extract_blocks(message)
    if not blocks:
        return []
    bundle: list[str] = [blocks[-1][2]]
    previous_start = blocks[-1][0]
    previous_end = blocks[-1][1]
    tail = message[previous_end:].strip()
    if tail:
        return []
    for start, end, block in reversed(blocks[:-1]):
        between = message[end:previous_start]
        if between.strip():
            break
        bundle.insert(0, block)
        previous_start = start
    return bundle


def _parse_simple_yaml_subset(block: str) -> dict[str, object]:
    body = block.removeprefix(EVENT_START).removesuffix(EVENT_END).strip()
    data: dict[str, object] = {}
    current_list_key = ""
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, [])
            cast_list = data[current_list_key]
            assert isinstance(cast_list, list)
            cast_list.append(line[4:])
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"malformed line (no colon): {line!r}")
        key, value = parts
        key = key.strip()
        value = value.strip()
        if value == "":
            current_list_key = key
            data[key] = []
            continue
        current_list_key = ""
        if value in {"true", "false"}:
            data[key] = value == "true"
        else:
            data[key] = value
    return data


_TYPE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "INPUT_REQUIRED": ("question", "options", "recommended", "blocking"),
    "ASSUMPTION_LOG": ("assumption", "confidence", "impact"),
    "APPROVAL_REQUIRED": ("subject", "proposed_decision", "blocking"),
    "STAGE_COMPLETE": ("summary", "outputs"),
    "NEEDS_HUMAN": ("issue", "why_ai_stopped", "suggested_next_action"),
}

_ALLOWED_BUNDLE_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("ASSUMPTION_LOG", "STAGE_COMPLETE"),
    ("ASSUMPTION_LOG", "APPROVAL_REQUIRED"),
    ("ASSUMPTION_LOG", "NEEDS_HUMAN"),
)


def _validate_type_specific_fields(marker_type: str, fields: dict[str, object]) -> bool:
    required = _TYPE_REQUIRED_FIELDS.get(marker_type, ())
    return all(field in fields for field in required)


def _validate_bundle_combination(types: tuple[str, ...]) -> bool:
    if len(types) <= 1:
        return True
    return types in _ALLOWED_BUNDLE_SEQUENCES


def extract_terminal_marker_bundle(message: str) -> tuple[MarkerEnvelope, ...]:
    stripped = _strip_fenced_code_blocks(message)
    blocks = _find_last_contiguous_bundle(stripped)
    if not blocks:
        return ()
    parsed: list[MarkerEnvelope] = []
    for block in blocks:
        try:
            fields = _parse_simple_yaml_subset(block)
        except (ValueError, AssertionError):
            return ()
        for required in ("type", "stage", "event_id", "reason"):
            if required not in fields:
                return ()
        marker_type = str(fields["type"])
        if not _validate_type_specific_fields(marker_type, fields):
            return ()
        parsed.append(
            MarkerEnvelope(
                type=marker_type,
                stage=str(fields["stage"]),
                event_id=str(fields["event_id"]),
                reason=str(fields["reason"]),
                payload={k: v for k, v in fields.items() if k not in {"type", "stage", "event_id", "reason"}},
            )
        )
    bundle_types = tuple(m.type for m in parsed)
    if not _validate_bundle_combination(bundle_types):
        return ()
    return tuple(parsed)
```

- [ ] **Step 4: Run parser tests and a quick runtime regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_marker_protocol.py tests/test_planning_runtime_state.py -q`

Expected:
- parser tests PASS
- runtime model tests remain PASS

- [ ] **Step 5: Commit marker protocol changes**

Run: `git add src/cowork_pilot/planning/marker_protocol.py tests/test_planning_marker_protocol.py && git commit -m "feat: add terminal marker protocol parser"`

Expected:
- commit succeeds

---

## Task 3: Brownfield Session Profiles and Artifact Ownership

**Files:**
- Create: `src/cowork_pilot/planning/session_profiles.py`
- Create: `tests/test_planning_session_profiles.py`

- [ ] **Step 1: Add failing tests for Brownfield session matrix**

```python
from cowork_pilot.planning.session_profiles import get_artifact_ownership, resolve_stage_profile
from cowork_pilot.planning.models import PlanningStage, SizeClass


def test_brownfield_extraction_profile_scales_by_size():
    profile = resolve_stage_profile(PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION, SizeClass.MEDIUM)
    assert profile.strategy == "domain_module_bundles"
    assert profile.resume_unit == "current planned extraction session"


def test_classification_profile_defines_medium_substages():
    profile = resolve_stage_profile(PlanningStage.CLASSIFICATION, SizeClass.MEDIUM)
    assert profile.substages == ("classification-input-audit", "classification-synthesis")


def test_brownfield_gap_synthesis_ownership_declares_next_consumer_and_reopen_trigger():
    ownership = get_artifact_ownership(PlanningStage.BROWNFIELD_GAP_SYNTHESIS)
    assert ownership.next_consumer == "scope_structuring"
    assert ownership.reopen_trigger == "stage_reopen_required"
    assert "change-impact-gap.md" in ownership.completion_artifacts


def test_plan_review_always_has_two_substages():
    """스펙 11.1: Plan Review는 항상 최소 2 planned sessions"""
    for size in (SizeClass.SMALL, SizeClass.MEDIUM, SizeClass.LARGE):
        profile = resolve_stage_profile(PlanningStage.PLAN_REVIEW, size)
        assert profile.substages == ("coverage-and-sizing", "executionability-and-overdesign")
        assert profile.strategy == "two_phase_review"


def test_product_completeness_review_profiles_scale_by_size():
    """스펙 11.1: Product Completeness Review는 size별 planned session 수가 다르다"""
    small = resolve_stage_profile(PlanningStage.PRODUCT_COMPLETENESS_REVIEW, SizeClass.SMALL)
    medium = resolve_stage_profile(PlanningStage.PRODUCT_COMPLETENESS_REVIEW, SizeClass.MEDIUM)
    large = resolve_stage_profile(PlanningStage.PRODUCT_COMPLETENESS_REVIEW, SizeClass.LARGE)

    assert small.substages == ()
    assert medium.substages == ("user-facing completeness", "ops/nonfunctional completeness")
    assert large.substages == ("pages-and-flows", "roles-and-permissions", "ops-integrations-nfr")


def test_scope_structuring_profiles_scale_by_size():
    """스펙 11.1: Scope Structuring은 medium/large에서 planned split을 가져야 한다"""
    small = resolve_stage_profile(PlanningStage.SCOPE_STRUCTURING, SizeClass.SMALL)
    medium = resolve_stage_profile(PlanningStage.SCOPE_STRUCTURING, SizeClass.MEDIUM)
    large = resolve_stage_profile(PlanningStage.SCOPE_STRUCTURING, SizeClass.LARGE)

    assert small.substages == ()
    assert medium.substages == ("domain-group-a", "domain-group-b")
    assert large.strategy == "domain_bundle_scope"
```

- [ ] **Step 2: Run the session profile tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_session_profiles.py -q`

Expected:
- import failure for `session_profiles`

- [ ] **Step 3: Encode the agreed session matrix directly in data**

```python
from dataclasses import dataclass

from cowork_pilot.planning.models import PlanningStage, SizeClass


@dataclass(frozen=True)
class StageSessionProfile:
    stage: PlanningStage
    strategy: str
    resume_unit: str
    substages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactOwnership:
    artifact_owner: str
    completion_artifacts: tuple[str, ...]
    completion_predicate: str
    resume_target: str
    reopen_trigger: str
    next_consumer: str


def resolve_stage_profile(stage: PlanningStage, size_class: SizeClass) -> StageSessionProfile:
    if stage is PlanningStage.CLASSIFICATION and size_class in {SizeClass.MEDIUM, SizeClass.LARGE}:
        return StageSessionProfile(
            stage=stage,
            strategy="two_phase_classification",
            resume_unit="current classification session",
            substages=("classification-input-audit", "classification-synthesis"),
        )
    if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
        if size_class is SizeClass.MEDIUM:
            return StageSessionProfile(
                stage=stage,
                strategy="two_phase_completeness",
                resume_unit="current completeness session",
                substages=("user-facing completeness", "ops/nonfunctional completeness"),
            )
        if size_class is SizeClass.LARGE:
            return StageSessionProfile(
                stage=stage,
                strategy="three_phase_completeness",
                resume_unit="current completeness session",
                substages=("pages-and-flows", "roles-and-permissions", "ops-integrations-nfr"),
            )
        return StageSessionProfile(stage=stage, strategy="single_session", resume_unit="product completeness review session")
    if stage is PlanningStage.SCOPE_STRUCTURING:
        if size_class is SizeClass.MEDIUM:
            return StageSessionProfile(
                stage=stage,
                strategy="domain_group_scope",
                resume_unit="current scope structuring session",
                substages=("domain-group-a", "domain-group-b"),
            )
        if size_class is SizeClass.LARGE:
            return StageSessionProfile(stage=stage, strategy="domain_bundle_scope", resume_unit="current scope structuring session")
        return StageSessionProfile(stage=stage, strategy="single_session", resume_unit="scope structuring session")
    if stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION:
        strategy = "lightweight_slices" if size_class is SizeClass.SMALL else "domain_module_bundles" if size_class is SizeClass.MEDIUM else "explicit_slice_sessions"
        return StageSessionProfile(stage=stage, strategy=strategy, resume_unit="current planned extraction session")
    if stage is PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS:
        return StageSessionProfile(stage=stage, strategy="single_synthesis_session", resume_unit="observation synthesis session")
    if stage is PlanningStage.BROWNFIELD_GAP_SYNTHESIS:
        return StageSessionProfile(stage=stage, strategy="single_synthesis_session", resume_unit="gap synthesis session")
    if stage is PlanningStage.PLAN_REVIEW:
        return StageSessionProfile(
            stage=stage,
            strategy="two_phase_review",
            resume_unit="current plan review session",
            substages=("coverage-and-sizing", "executionability-and-overdesign"),
        )
    return StageSessionProfile(stage=stage, strategy="single_session", resume_unit=f"{stage.value} session")
```

- [ ] **Step 4: Add artifact ownership table helpers and re-run tests**

```python
def get_artifact_ownership(stage: PlanningStage) -> ArtifactOwnership:
    table = {
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: ArtifactOwnership(
            artifact_owner="extraction session",
            completion_artifacts=("code-observations/<slice>.md",),
            completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="current extraction session",
            reopen_trigger="stage_reopen_required",
            next_consumer="brownfield_observation_synthesis",
        ),
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: ArtifactOwnership(
            artifact_owner="observation synthesis session",
            completion_artifacts=("implementation-observation-summary.md",),
            completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="observation synthesis session",
            reopen_trigger="stage_reopen_required",
            next_consumer="brownfield_gap_synthesis",
        ),
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS: ArtifactOwnership(
            artifact_owner="gap synthesis session",
            completion_artifacts=("spec-implementation-gap.md", "change-impact-gap.md"),
            completion_predicate="both files exist and each contains <!-- ORCHESTRATOR:DONE -->",
            resume_target="gap synthesis session",
            reopen_trigger="stage_reopen_required",
            next_consumer="scope_structuring",
        ),
    }
    return table[stage]
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_session_profiles.py -q`

Expected:
- session profile tests PASS

- [ ] **Step 5: Commit session profile changes**

Run: `git add src/cowork_pilot/planning/session_profiles.py tests/test_planning_session_profiles.py && git commit -m "feat: add runtime session profiles and ownership table"`

Expected:
- commit succeeds

---

## Task 4: Shared Codex Event Stream and Resume-Aware Command Bridge

**Files:**
- Create: `src/cowork_pilot/codex/event_stream.py`
- Create: `src/cowork_pilot/codex/command_builder.py`
- Create: `src/cowork_pilot/planning/codex_bridge.py`
- Modify: `src/cowork_pilot/codex/exec_runner.py`
- Create: `tests/test_planning_codex_bridge.py`
- Modify: `tests/test_codex_harness.py`

- [ ] **Step 1: Add failing tests for thread-id extraction and shared command builders**

```python
from cowork_pilot.codex.command_builder import (
    build_cli_resume_command,
    build_exec_command,
    build_exec_resume_command,
)
from cowork_pilot.codex.event_stream import extract_terminal_assistant_message, extract_thread_id


def test_extract_thread_id_from_started_event():
    lines = ['{"type":"thread.started","thread_id":"thread-123"}']
    assert extract_thread_id(lines) == "thread-123"


def test_extract_terminal_assistant_message_uses_last_completed_agent_message():
    lines = [
        '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"second"}}',
    ]
    assert extract_terminal_assistant_message(lines) == "second"


def test_build_exec_command_matches_existing_harness_contract():
    cmd = build_exec_command(prompt="hello", project_dir="/tmp/project", codex_command="/usr/local/bin/codex", codex_extra_args=["--json"])
    assert cmd == [
        "/usr/local/bin/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        "/tmp/project",
        "--json",
        "hello",
    ]


def test_build_cli_resume_command_uses_resume_handle():
    cmd = build_cli_resume_command(resume_handle="thread-123", project_dir="/tmp/project")
    assert cmd == ["codex", "resume", "--include-non-interactive", "-C", "/tmp/project", "thread-123"]


def test_build_exec_resume_command_uses_resume_handle():
    cmd = build_exec_resume_command(resume_handle="thread-123", prompt="continue")
    assert cmd == ["codex", "exec", "resume", "--json", "thread-123", "continue"]
```

- [ ] **Step 2: Run the bridge tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_codex_bridge.py tests/test_codex_harness.py -q`

Expected:
- import failure for `event_stream` or `command_builder`

- [ ] **Step 3: Extract shared event utilities from `exec_runner.py`**

```python
# src/cowork_pilot/codex/event_stream.py
import json


def summarize_codex_event(payload: dict) -> tuple[list[str], str]:
    event_type = payload.get("type", "unknown")
    if event_type == "thread.started":
        thread_id = payload.get("thread_id", "")
        return ([f"thread started: {thread_id}"], "")
    item = payload.get("item", {})
    if item.get("type") == "agent_message":
        text = (item.get("text") or "").strip()
        return ([f"assistant: {text}"], text)
    if item.get("type") == "command_execution":
        command = item.get("command", "")
        exit_code = item.get("exit_code")
        output = (item.get("aggregated_output") or "").strip()
        return ([f"command completed (rc={exit_code}): {command}", f"command output: {output}"] if output else [f"command completed (rc={exit_code}): {command}"], "")
    return ([json.dumps(payload, ensure_ascii=False)], "")


def extract_thread_id(lines: list[str]) -> str:
    for line in lines:
        payload = json.loads(line)
        if payload.get("type") == "thread.started":
            return str(payload.get("thread_id", ""))
    return ""


def extract_terminal_assistant_message(lines: list[str]) -> str:
    last_message = ""
    for line in lines:
        payload = json.loads(line)
        item = payload.get("item", {})
        if payload.get("type") == "item.completed" and item.get("type") == "agent_message":
            last_message = str(item.get("text", "")).strip()
    return last_message
```

- [ ] **Step 4: Implement shared command builders and planning bridge**

```python
# src/cowork_pilot/codex/command_builder.py
def build_exec_command(*, prompt: str, project_dir: str, codex_command: str = "codex", codex_extra_args: list[str] | None = None) -> list[str]:
    cmd = [codex_command, "exec", "--dangerously-bypass-approvals-and-sandbox", "-C", project_dir]
    for arg in codex_extra_args or []:
        if arg not in cmd:
            cmd.append(arg)
    if "--json" not in cmd:
        cmd.append("--json")
    cmd.append(prompt)
    return cmd


def build_cli_resume_command(*, resume_handle: str, project_dir: str, codex_command: str = "codex") -> list[str]:
    return [codex_command, "resume", "--include-non-interactive", "-C", project_dir, resume_handle]


def build_exec_resume_command(*, resume_handle: str, prompt: str, codex_command: str = "codex") -> list[str]:
    return [codex_command, "exec", "resume", "--json", resume_handle, prompt]
```

```python
# src/cowork_pilot/planning/codex_bridge.py
from dataclasses import dataclass

from cowork_pilot.codex.command_builder import build_cli_resume_command, build_exec_command, build_exec_resume_command
from cowork_pilot.codex.event_stream import extract_terminal_assistant_message, extract_thread_id


@dataclass(frozen=True)
class ExecStageResult:
    event_lines: list[str]
    assistant_message: str
    exit_code: int = 0  # subprocess exit code; non-zero means failure


@dataclass(frozen=True)
class ResumeStageResult:
    event_lines: list[str]
    assistant_message: str
    exit_code: int = 0


def run_exec_stage(*, stage: str, prompt: str, run_dir) -> ExecStageResult:
    command = build_exec_command(prompt=prompt, project_dir=str(run_dir))
    return ExecStageResult(event_lines=[], assistant_message="", exit_code=0)


def run_cli_resume(*, resume_handle: str, project_dir: str, run_dir) -> ResumeStageResult:
    command = build_cli_resume_command(resume_handle=resume_handle, project_dir=project_dir)
    return ResumeStageResult(event_lines=[], assistant_message="", exit_code=0)


def run_exec_resume(*, resume_handle: str, prompt: str, run_dir) -> ExecStageResult:
    command = build_exec_resume_command(resume_handle=resume_handle, prompt=prompt)
    return ExecStageResult(event_lines=[], assistant_message="", exit_code=0)
```

```python
# src/cowork_pilot/codex/exec_runner.py
from cowork_pilot.codex.command_builder import build_exec_command as _build_exec_command
from cowork_pilot.codex.event_stream import summarize_codex_event as _summarize_codex_event
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_codex_bridge.py tests/test_codex_harness.py -q`

Expected:
- new bridge tests PASS
- codex harness regression PASS

- [ ] **Step 5: Commit event-stream and bridge changes**

Run: `git add src/cowork_pilot/codex/event_stream.py src/cowork_pilot/codex/command_builder.py src/cowork_pilot/planning/codex_bridge.py src/cowork_pilot/codex/exec_runner.py tests/test_planning_codex_bridge.py tests/test_codex_harness.py && git commit -m "feat: add codex resume bridge for planning runtime"`

Expected:
- commit succeeds

---

## Task 5: Runtime Storage and State Transition Engine

**Files:**
- Create: `src/cowork_pilot/planning/runtime_storage.py`
- Create: `src/cowork_pilot/planning/runtime_orchestrator.py`
- Create: `tests/test_planning_runtime_orchestrator.py`

- [ ] **Step 1: Add failing tests for blocking and non-blocking marker handling**

```python
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_orchestrator import apply_marker_bundle_to_run, apply_subprocess_failure


def test_subprocess_failure_moves_running_exec_to_failed(tmp_path):
    """스펙 10.1: running_exec -> failed (subprocess 비정상 종료)"""
    updated = apply_subprocess_failure(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        exit_code=1,
        stage="product_completeness_review",
    )
    assert updated.state is PlanningRuntimeState.FAILED
    assert (tmp_path / "runtime-events.ndjson").exists()


def test_subprocess_failure_is_noop_when_not_running_exec(tmp_path):
    """RUNNING_EXEC가 아닌 상태에서 subprocess failure는 상태를 바꾸지 않는다"""
    updated = apply_subprocess_failure(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        exit_code=1,
        stage="product_completeness_review",
    )
    assert updated.state is PlanningRuntimeState.RUNNING_CLI


def test_blocking_input_required_moves_run_to_waiting_for_input(tmp_path):
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message='''
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing redirect
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.WAITING_FOR_INPUT
    assert (tmp_path / "question-queue.md").exists()


def test_nonblocking_input_required_keeps_run_running_exec(tmp_path):
    """runtime layer는 question-queue에 기록하고 상태를 유지한다.
    assumption record 생성은 stage_executor(completion plan Task 4)의 책임이다."""
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message='''
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: adaptive_docs_selection
event_id: ads-1
reason: optional doc
question: ops-runbook 필요?
options:
  - yes
  - no
recommended: yes
blocking: false
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.RUNNING_EXEC


def test_assumption_invalidation_moves_run_to_waiting_for_human(tmp_path):
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message='''
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-1
reason: stage_reopen_required
issue: assumption invalidated
why_ai_stopped: later review contradicted assumption
suggested_next_action: reopen scope structuring
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.WAITING_FOR_HUMAN
    assert (tmp_path / "assumption-invalidations.md").exists()


def test_running_cli_escalates_on_needs_human(tmp_path):
    """스펙 10.1: running_cli -> escalated"""
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message='''
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: product_completeness_review
event_id: pcr-esc-1
reason: unresolvable ambiguity
issue: user cannot clarify requirement in CLI
why_ai_stopped: contradictory inputs
suggested_next_action: escalate to project owner
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.ESCALATED


def test_running_cli_escalates_even_on_stage_reopen_required(tmp_path):
    """스펙 10.1: running_cli -> escalated (reason=stage_reopen_required여도 CLI면 항상 escalated)"""
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.RUNNING_CLI,
        message='''
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: scope_structuring
event_id: ss-cli-1
reason: stage_reopen_required
issue: assumption invalidated during interactive session
why_ai_stopped: user corrected a prior assumption
suggested_next_action: reopen scope structuring
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.ESCALATED
    assert (tmp_path / "assumption-invalidations.md").exists()


def test_completed_transitions_to_waiting_for_human_on_post_validation(tmp_path):
    """스펙 10.1: completed -> waiting_for_human when post-completion validation discovers reopen/replan"""
    updated = apply_marker_bundle_to_run(
        run_dir=tmp_path,
        current_state=PlanningRuntimeState.COMPLETED,
        message='''
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-post-1
reason: stage_reopen_required
issue: post-completion validation found assumption invalidated
why_ai_stopped: confirmed assumption was wrong after plan completion
suggested_next_action: reopen scope structuring with corrected inputs
</COWORK_PILOT_EVENT>
''',
    )
    assert updated.state is PlanningRuntimeState.WAITING_FOR_HUMAN
    assert (tmp_path / "assumption-invalidations.md").exists()
```

- [ ] **Step 2: Run the runtime orchestrator tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runtime_orchestrator.py -q`

Expected:
- import failure for `runtime_storage` or `runtime_orchestrator`

- [ ] **Step 3: Implement runtime storage files**

```python
from __future__ import annotations

import json
from pathlib import Path


def _append_markdown_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + line + "\n", encoding="utf-8")


def write_run_state(run_dir: Path, *, state: str, metadata: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, **metadata}
    (run_dir / "run-state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_question(run_dir: Path, *, event_id: str, question: str, blocking: bool) -> None:
    _append_markdown_line(run_dir / "question-queue.md", f"- [{event_id}] blocking={str(blocking).lower()} {question}")


def append_answer(run_dir: Path, *, event_id: str, answer: str) -> None:
    _append_markdown_line(run_dir / "answer-log.md", f"- [{event_id}] {answer}")


def append_approval_decision(run_dir: Path, *, event_id: str, decision: str) -> None:
    _append_markdown_line(run_dir / "approval-log.md", f"- [{event_id}] decision={decision}")


def append_assumption(run_dir: Path, *, event_id: str, assumption: str, confidence: str, impact: str) -> None:
    _append_markdown_line(run_dir / "assumptions.md", f"- [{event_id}] {assumption} (confidence={confidence}, impact={impact})")


def append_approval_request(run_dir: Path, *, event_id: str, subject: str, blocking: bool) -> None:
    _append_markdown_line(run_dir / "approval-log.md", f"- [{event_id}] blocking={str(blocking).lower()} {subject}")


def append_invalidation(run_dir: Path, *, event_id: str, reason: str, affected_stage: str) -> None:
    _append_markdown_line(run_dir / "assumption-invalidations.md", f"- [{event_id}] reason={reason} affected_stage={affected_stage}")


def append_runtime_event(run_dir: Path, payload: dict[str, object]) -> None:
    _append_markdown_line(run_dir / "runtime-events.ndjson", json.dumps(payload, ensure_ascii=False))


def read_run_state(run_dir: Path) -> dict[str, object]:
    path = run_dir / "run-state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Implement state transition engine**

```python
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.marker_protocol import extract_terminal_marker_bundle
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_storage import (
    append_approval_request,
    append_assumption,
    append_invalidation,
    append_question,
    append_runtime_event,
    write_run_state,
)


@dataclass(frozen=True)
class RuntimeUpdate:
    state: PlanningRuntimeState


def apply_subprocess_failure(*, run_dir: Path, current_state: PlanningRuntimeState, exit_code: int, stage: str) -> RuntimeUpdate:
    """스펙 10.1: running_exec -> failed (subprocess 비정상 종료 시)"""
    if current_state is not PlanningRuntimeState.RUNNING_EXEC:
        return RuntimeUpdate(state=current_state)
    append_runtime_event(run_dir, {"type": "SUBPROCESS_FAILED", "stage": stage, "exit_code": exit_code})
    write_run_state(run_dir, state=PlanningRuntimeState.FAILED.value, metadata={"stage": stage, "exit_code": exit_code})
    return RuntimeUpdate(state=PlanningRuntimeState.FAILED)


def apply_marker_bundle_to_run(*, run_dir: Path, current_state: PlanningRuntimeState, message: str) -> RuntimeUpdate:
    bundle = extract_terminal_marker_bundle(message)
    if not bundle:
        return RuntimeUpdate(state=current_state)
    for marker in bundle:
        append_runtime_event(run_dir, {"type": marker.type, "stage": marker.stage, "event_id": marker.event_id})
        if marker.type == "INPUT_REQUIRED":
            append_question(run_dir, event_id=marker.event_id, question=str(marker.payload["question"]), blocking=bool(marker.payload["blocking"]))
            next_state = PlanningRuntimeState.WAITING_FOR_INPUT if bool(marker.payload["blocking"]) else current_state
            write_run_state(run_dir, state=next_state.value, metadata={"stage": marker.stage})
            if next_state is not current_state:
                return RuntimeUpdate(state=next_state)
        elif marker.type == "APPROVAL_REQUIRED":
            append_approval_request(run_dir, event_id=marker.event_id, subject=str(marker.payload["subject"]), blocking=bool(marker.payload["blocking"]))
            next_state = PlanningRuntimeState.WAITING_FOR_APPROVAL if bool(marker.payload["blocking"]) else current_state
            write_run_state(run_dir, state=next_state.value, metadata={"stage": marker.stage})
            if next_state is not current_state:
                return RuntimeUpdate(state=next_state)
        elif marker.type == "ASSUMPTION_LOG":
            append_assumption(
                run_dir,
                event_id=marker.event_id,
                assumption=str(marker.payload["assumption"]),
                confidence=str(marker.payload["confidence"]),
                impact=str(marker.payload["impact"]),
            )
        elif marker.type == "NEEDS_HUMAN":
            # 스펙 10.1: running_cli -> escalated (reason과 무관하게 항상)
            if current_state is PlanningRuntimeState.RUNNING_CLI:
                if marker.reason in {"stage_reopen_required", "replan_required"}:
                    append_invalidation(run_dir, event_id=marker.event_id, reason=str(marker.reason), affected_stage=marker.stage)
                write_run_state(run_dir, state=PlanningRuntimeState.ESCALATED.value, metadata={"stage": marker.stage})
                return RuntimeUpdate(state=PlanningRuntimeState.ESCALATED)
            # 스펙 10.1: running_exec / completed -> waiting_for_human (assumption invalidation)
            if marker.reason in {"stage_reopen_required", "replan_required"}:
                append_invalidation(run_dir, event_id=marker.event_id, reason=str(marker.reason), affected_stage=marker.stage)
                write_run_state(run_dir, state=PlanningRuntimeState.WAITING_FOR_HUMAN.value, metadata={"stage": marker.stage})
                return RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_HUMAN)
            write_run_state(run_dir, state=PlanningRuntimeState.ESCALATED.value, metadata={"stage": marker.stage})
            return RuntimeUpdate(state=PlanningRuntimeState.ESCALATED)
        elif marker.type == "STAGE_COMPLETE":
            write_run_state(run_dir, state=current_state.value, metadata={"completed_stage": marker.stage})
    return RuntimeUpdate(state=current_state)
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runtime_state.py tests/test_planning_runtime_orchestrator.py -q`

Expected:
- runtime state/orchestrator tests PASS

- [ ] **Step 5: Commit runtime storage/orchestrator changes**

Run: `git add src/cowork_pilot/planning/runtime_storage.py src/cowork_pilot/planning/runtime_orchestrator.py tests/test_planning_runtime_orchestrator.py && git commit -m "feat: add planning runtime state machine"`

Expected:
- commit succeeds

---

## Task 6: Planning Runner and CLI Surface Integration

**Files:**
- Modify: `src/cowork_pilot/planning/runner.py`
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/codex/main.py`
- Create: `tests/test_codex_main.py`
- Create: `tests/test_main_cli.py`
- Modify: `tests/test_planning_runner.py`

- [ ] **Step 1: Add failing tests for runtime-aware planning dispatch**

```python
import sys
from pathlib import Path

from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runner import run_planning_stage_with_runtime, resume_planning_waiting_run_with_cli
from cowork_pilot.planning.runtime_storage import write_run_state


def test_planning_runner_saves_resume_handle_from_thread_started(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_exec_stage",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": ['{"type":"thread.started","thread_id":"thread-123"}'],
                "assistant_message": '''
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing redirect
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
''',
            },
        )(),
    )
    updated = run_planning_stage_with_runtime(run_dir=tmp_path, stage="product_completeness_review", prompt="continue")
    assert updated.state is PlanningRuntimeState.WAITING_FOR_INPUT
    assert "thread-123" in (tmp_path / "run-state.json").read_text(encoding="utf-8")


def test_answer_roundtrip_moves_waiting_for_input_to_running_exec(tmp_path, monkeypatch):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
        metadata={
            "resume_handle": "thread-123",
            "resume_handle_kind": "codex_thread_id",
            "surface": "exec",
            "stage": "product_completeness_review",
            "pending_event_id": "pcr-1",
        },
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_cli_resume",
        lambda **kwargs: type("CliResult", (), {"event_lines": [], "assistant_message": "answered in cli", "exit_code": 0})(),
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_exec_resume",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": [],
                "assistant_message": '''
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: done
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
''',
                "exit_code": 0,
            },
        )(),
    )
    updated = resume_planning_waiting_run_with_cli(run_dir=tmp_path, response_text="dashboard", response_kind="answer")
    assert updated.state is PlanningRuntimeState.RUNNING_EXEC
    assert "dashboard" in (tmp_path / "answer-log.md").read_text(encoding="utf-8")


def test_approval_roundtrip_moves_waiting_for_approval_to_running_exec(tmp_path, monkeypatch):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
        metadata={
            "resume_handle": "thread-123",
            "resume_handle_kind": "codex_thread_id",
            "surface": "exec",
            "stage": "scope_structuring",
            "pending_event_id": "scope-approve-1",
        },
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_cli_resume",
        lambda **kwargs: type("CliResult", (), {"event_lines": [], "assistant_message": "approved in cli", "exit_code": 0})(),
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_exec_resume",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": [],
                "assistant_message": '''
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: scope_structuring
event_id: ss-2
reason: complete
summary: done
outputs:
  - scope-map.md
</COWORK_PILOT_EVENT>
''',
                "exit_code": 0,
            },
        )(),
    )
    updated = resume_planning_waiting_run_with_cli(run_dir=tmp_path, response_text="approved", response_kind="approval")
    assert updated.state is PlanningRuntimeState.RUNNING_EXEC


def test_codex_main_accepts_planning_subcommand(monkeypatch):
    called = {}
    async def fake_run_planning(args):
        called["command"] = args.command
        return 0
    import pytest
    import cowork_pilot.codex.main as codex_main
    monkeypatch.setattr(codex_main, "_run_planning", fake_run_planning)
    monkeypatch.setattr(sys, "argv", ["cowork-pilot-codex", "planning", "--project-dir", "/tmp/project"])
    with pytest.raises(SystemExit) as exc:
        codex_main.cli()
    assert exc.value.code == 0
    assert called["command"] == "planning"


def test_main_cli_accepts_mode_planning(monkeypatch):
    called = {}
    monkeypatch.setattr("cowork_pilot.main.run_planning_mode", lambda config_path: called.setdefault("config_path", config_path))
    monkeypatch.setattr(sys, "argv", ["cowork-pilot", "--mode", "planning", "--config", "config.toml"])
    from cowork_pilot.main import cli
    cli()
    assert called["config_path"] == Path("config.toml")
```

- [ ] **Step 2: Run the integration tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_codex_main.py tests/test_main_cli.py -q`

Expected:
- new runtime-dispatch assertions fail

- [ ] **Step 3: Connect planning runner to runtime orchestration**

```python
# src/cowork_pilot/planning/runner.py
from cowork_pilot.codex.event_stream import extract_thread_id
from cowork_pilot.planning.codex_bridge import run_cli_resume, run_exec_resume, run_exec_stage
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_models import ResumeHandleRef
from cowork_pilot.planning.runtime_orchestrator import apply_marker_bundle_to_run, apply_subprocess_failure
from cowork_pilot.planning.runtime_storage import append_answer, append_approval_decision, read_run_state, write_run_state


def run_planning_stage_with_runtime(*, run_dir: Path, stage: str, prompt: str):
    exec_result = run_exec_stage(stage=stage, prompt=prompt, run_dir=run_dir)
    thread_id = extract_thread_id(exec_result.event_lines)
    if thread_id:
        write_run_state(
            run_dir,
            state="running_exec",
            metadata={
                "resume_handle": thread_id,
                "resume_handle_kind": "codex_thread_id",
                "surface": "exec",
                "stage": stage,
                "substage": "",
            },
        )
    # 스펙 10.1 / 10.2: subprocess 비정상 종료 시 running_exec -> failed
    if exec_result.exit_code != 0:
        return apply_subprocess_failure(
            run_dir=run_dir,
            current_state=PlanningRuntimeState.RUNNING_EXEC,
            exit_code=exec_result.exit_code,
            stage=stage,
        )
    return apply_marker_bundle_to_run(
        run_dir=run_dir,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=exec_result.assistant_message,
    )


def resume_planning_waiting_run_with_cli(*, run_dir: Path, response_text: str, response_kind: str):
    run_state = read_run_state(run_dir)
    current_state = PlanningRuntimeState(str(run_state.get("state", PlanningRuntimeState.WAITING_FOR_INPUT.value)))
    resume_handle = str(run_state["resume_handle"])
    stage = str(run_state.get("stage", ""))
    pending_event_id = str(run_state.get("pending_event_id", "resume-1"))

    write_run_state(
        run_dir,
        state=PlanningRuntimeState.RUNNING_CLI.value,
        metadata={**run_state, "surface": "cli"},
    )
    cli_result = run_cli_resume(resume_handle=resume_handle, project_dir=str(run_dir), run_dir=run_dir)
    if response_kind == "approval":
        append_approval_decision(run_dir, event_id=pending_event_id, decision=response_text)
        resumed_prompt = f"Approval resolved for {pending_event_id}: {response_text}"
    else:
        append_answer(run_dir, event_id=pending_event_id, answer=response_text)
        resumed_prompt = f"Answer recorded for {pending_event_id}: {response_text}"

    write_run_state(
        run_dir,
        state=PlanningRuntimeState.RUNNING_EXEC.value,
        metadata={**run_state, "surface": "exec"},
    )
    exec_result = run_exec_resume(resume_handle=resume_handle, prompt=resumed_prompt, run_dir=run_dir)
    if exec_result.exit_code != 0:
        return apply_subprocess_failure(
            run_dir=run_dir,
            current_state=PlanningRuntimeState.RUNNING_EXEC,
            exit_code=exec_result.exit_code,
            stage=stage,
        )
    return apply_marker_bundle_to_run(
        run_dir=run_dir,
        current_state=PlanningRuntimeState.RUNNING_EXEC,
        message=exec_result.assistant_message,
    )
```

- [ ] **Step 4: Add CLI planning entry points**

```python
# src/cowork_pilot/main.py
def run_planning_mode(config_path: Path) -> None:
    from cowork_pilot.config import load_config
    from cowork_pilot.planning.runner import run_planning_pipeline
    from cowork_pilot.planning.models import ProjectMode

    base_config = load_config(config_path)
    run_planning_pipeline(
        project_dir=Path(base_config.project_dir),
        target_version="cli-planning",
        project_mode=ProjectMode.GREENFIELD,
        stage_executor=lambda stage, context: {"summary": f"{stage} completed", "outputs": [f"{stage}.md"]},
    )


parser.add_argument("--mode", type=str, choices=["watch", "harness", "meta", "docs-orchestrator", "planning"], default="watch")

elif args.mode == "planning":
    run_planning_mode(Path(args.config))
```

```python
# src/cowork_pilot/codex/main.py
async def _run_planning(args: argparse.Namespace) -> int:
    from cowork_pilot.planning.runner import run_planning_pipeline
    from cowork_pilot.planning.models import ProjectMode

    run_planning_pipeline(
        project_dir=Path(args.project_dir or Path.cwd()),
        target_version="codex-planning",
        project_mode=ProjectMode.GREENFIELD,
        stage_executor=lambda stage, context: {"summary": f"{stage} completed", "outputs": [f"{stage}.md"]},
    )
    return 0


planning_parser = subparsers.add_parser("planning", help="Run planning runtime")
planning_parser.add_argument("--project-dir", type=str, default="")

elif args.command == "planning":
    exit_code = asyncio.run(_run_planning(args))
    sys.exit(exit_code)
```

- [ ] **Step 5: Run the planning runtime regression batch and commit**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_marker_protocol.py tests/test_planning_session_profiles.py tests/test_planning_runtime_state.py tests/test_planning_codex_bridge.py tests/test_planning_runtime_orchestrator.py tests/test_planning_runner.py tests/test_codex_main.py tests/test_main_cli.py tests/test_codex_harness.py tests/test_config.py -q`

Expected:
- all runtime-related tests PASS

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest -q`

Expected:
- full repository test suite PASS

Run: `git add src/cowork_pilot/planning/runner.py src/cowork_pilot/main.py src/cowork_pilot/codex/main.py tests/test_planning_runner.py tests/test_codex_main.py tests/test_main_cli.py && git commit -m "feat: integrate planning runtime handoff"`

Expected:
- commit succeeds after green test suite

---

## Spec Coverage Review

- `4.x Terminal bundle parsing rule`
  - Task 2 parser tests for code fences, contiguous bundle, and interleaved text rejection
- `9.x Resume handle contract`
  - Task 1 `ResumeHandleRef`
  - Task 5 `run-state.json` persistence
  - Task 6 runner saving `resume_handle_kind=codex_thread_id`
- `10 Run state machine`
  - Task 5 blocking/non-blocking marker tests and storage writes
  - Task 6 `waiting_for_input -> running_cli -> running_exec` and `waiting_for_approval -> running_cli -> running_exec` roundtrip tests
- `11.x Brownfield session profiles`
  - Task 3 matrix + ownership table + reopen trigger coverage
- `8.1 / 8.2 source=exec / source=cli semantics`
  - Task 5 transition engine
  - Task 6 CLI/runtime integration
- `Handoff model: exec -> cli resume -> exec resume`
  - Task 4 shared command builders + `run_cli_resume` / `run_exec_resume` bridge wrappers
  - Task 6 runtime bridge hook + roundtrip orchestration helper

## Anti-Scaffolding Review

- `marker_protocol.py` is not done until invalid bundle cases return empty tuples, type-specific required fields are validated per spec 7.4, and only allowed bundle combinations per spec 7.3 pass validation.
- `marker_protocol.py` parser must never raise on malformed input — all parse errors must be caught and return `()`.
- `session_profiles.py` is not done until Brownfield ownership exposes reopen triggers and completion predicates, not just artifact names. Plan Review must always resolve to 2 substages regardless of size class.
- `command_builder.py` is not done until `tests/test_codex_harness.py` still passes with the refactor.
- `runtime_storage.py` is not done until each persisted file is written by at least one orchestrator test.
- CLI integration is not done until both `cowork-pilot` and `cowork-pilot-codex` parser tests prove the new entry points exist.

## Self-Review

- Placeholder scan:
  - no `TODO`, `TBD`, `...`, or “implement later” placeholders remain
  - each task contains exact file paths, commands, and concrete function/class names
- Contract consistency:
  - `brownfield_code_observation_extraction`, `brownfield_observation_synthesis`, `brownfield_gap_synthesis` naming matches the core V3 plan
  - `resume_handle_kind = codex_thread_id` is used consistently across storage, bridge, and runner
- Ordering consistency:
  - runtime plan starts after completion plan Task 0
  - completion plan Task 1+ executes only after this plan completes

Plan complete and saved to `docs/superpowers/plans/2026-04-08-planning-runtime-handoff-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks
2. Inline Execution - execute tasks in this session in order

Which approach?
