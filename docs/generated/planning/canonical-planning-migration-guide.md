# Planning Canonical Docs Migration — 구현 가이드

> 이 문서만 보고 구현할 수 있을 정도로 구체적으로 작성함.
> 목표: planning의 stage 산출물을 run-dir 중심에서 고정경로 문서 중심으로 전환.

---

## 1. 목표 디렉토리 구조

### Before (현재)

```
docs/generated/planning-runs/<run_id>/
  inputs/
    request.md
    normalized-request.md
    change-request.md
  planning-references/
    *.md
  stage-handoffs/
    01-classification.md
    02-core_docs_check.md
    ...
  classification-report.md          ← stage 산출물이 run dir에 섞여 있음
  core-docs-check.md
  scope-map.md
  work-sizing.md
  plan-packing.md
  plan-review.md
  exec-plan-skeleton.md
  feature-outlines/
    <feature>.md
  exec-plan-outline.md
  detail-<plan>.md
  code-observations/                ← brownfield
    <slice>.md
  implementation-observation-summary.md
  spec-implementation-gap.md
  change-impact-gap.md
  product-completeness-review.md
  coverage-gap.md
  run-state.json
  pipeline-state.json
  completed-stages.json
  runtime-events.ndjson
  assumptions.md
  answer-log.md
  approval-log.md
  question-queue.md
  assumption-invalidations.md
```

### After (목표)

```
docs/generated/planning/                    ← canonical planning artifacts (고정경로)
  classification-report.md
  core-docs-check.md
  adaptive-docs-selection.md
  product-completeness-review.md
  coverage-gap.md
  scope-map.md
  work-sizing.md
  plan-packing.md
  plan-review.md
  exec-plan-skeleton.md
  feature-outlines/
    <feature>.md
  exec-plan-outline.md
  code-observations/                        ← brownfield
    <slice>.md
  implementation-observation-summary.md
  spec-implementation-gap.md
  change-impact-gap.md

docs/exec-plans/planning/                   ← 최종 exec-plan (기존과 동일)
  01-project-setup.md
  02-auth.md
  ...

docs/generated/planning-runs/<run_id>/      ← 런타임 상태만 (축소됨)
  inputs/
    request.md
    normalized-request.md
    change-request.md
  planning-references/
    *.md
  stage-handoffs/
    01-classification.md
    ...
  run-state.json
  pipeline-state.json
  completed-stages.json
  runtime-events.ndjson
  assumptions.md
  answer-log.md
  approval-log.md
  question-queue.md
  assumption-invalidations.md
```

**핵심 원칙:**
- `docs/generated/planning/` = 사람이 보는 문서, 다음 세션이 읽는 입력
- `docs/generated/planning-runs/<run_id>/` = orchestrator 운영 상태
- `docs/exec-plans/planning/` = 최종 numbered exec-plan (변경 없음)

---

## 2. 새 모듈: `canonical_paths.py`

**위치**: `src/cowork_pilot/planning/canonical_paths.py`

이 모듈이 **경로 해석의 유일한 중앙 지점**이 된다. 현재 `_resolve_stage_artifact_path()`, `_resolve_output_file()`, `ARTIFACT_OWNERSHIP_TABLE`의 상대경로 등이 run_dir 기준으로 흩어져 있는 걸 여기로 모은다.

```python
"""Canonical path resolution for planning artifacts.

Single source of truth for all planning artifact paths.
Every module that needs to know "이 stage의 출력 파일이 어디에 있는가"는
반드시 이 모듈의 함수를 통해 경로를 얻어야 한다.
"""
from __future__ import annotations

from pathlib import Path

from cowork_pilot.planning.models import PlanningStage

# ── 상수 ──────────────────────────────────────────────
CANONICAL_PLANNING_DIR = "docs/generated/planning"
CANONICAL_EXEC_PLANS_DIR = "docs/exec-plans/planning"
RUN_ROOT = "docs/generated/planning-runs"

# ── Stage → canonical 상대경로 매핑 ─────────────────────
# ARTIFACT_OWNERSHIP_TABLE의 completion_artifacts를 대체한다.
# 모든 경로는 project_dir 기준 상대경로다.
_STAGE_CANONICAL_ARTIFACTS: dict[PlanningStage, tuple[str, ...]] = {
    PlanningStage.CLASSIFICATION: (
        f"{CANONICAL_PLANNING_DIR}/classification-report.md",
    ),
    PlanningStage.CORE_DOCS_CHECK: (
        f"{CANONICAL_PLANNING_DIR}/core-docs-check.md",
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: (
        f"{CANONICAL_PLANNING_DIR}/adaptive-docs-selection.md",
    ),
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: (
        f"{CANONICAL_PLANNING_DIR}/product-completeness-review.md",
    ),
    PlanningStage.SCOPE_STRUCTURING: (
        f"{CANONICAL_PLANNING_DIR}/scope-map.md",
    ),
    PlanningStage.WORK_SIZING: (
        f"{CANONICAL_PLANNING_DIR}/work-sizing.md",
    ),
    PlanningStage.PLAN_PACKING: (
        f"{CANONICAL_PLANNING_DIR}/plan-packing.md",
    ),
    PlanningStage.PLAN_REVIEW: (
        f"{CANONICAL_PLANNING_DIR}/plan-review.md",
    ),
    PlanningStage.EXEC_PLAN_SKELETON: (
        f"{CANONICAL_PLANNING_DIR}/exec-plan-skeleton.md",
    ),
    # 동적 stage — 파일명이 런타임에 결정됨
    # EXEC_PLAN_FEATURE_OUTLINE: resolve_feature_outline_path() 사용
    # EXEC_PLAN_DETAIL: resolve_detail_path() 사용
    # BROWNFIELD_CODE_OBSERVATION_EXTRACTION: resolve_observation_path() 사용

    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: (
        f"{CANONICAL_PLANNING_DIR}/implementation-observation-summary.md",
    ),
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: (
        f"{CANONICAL_PLANNING_DIR}/spec-implementation-gap.md",
        f"{CANONICAL_PLANNING_DIR}/change-impact-gap.md",
    ),
}

# completeness 보조 산출물 (PRODUCT_COMPLETENESS_REVIEW에 딸려 나옴)
COVERAGE_GAP_REL = f"{CANONICAL_PLANNING_DIR}/coverage-gap.md"


def resolve_canonical_artifact(
    stage: PlanningStage,
    project_dir: Path,
) -> Path | None:
    """정적 stage의 primary canonical artifact 절대경로를 반환한다."""
    artifacts = _STAGE_CANONICAL_ARTIFACTS.get(stage)
    if artifacts is None:
        return None
    return project_dir / artifacts[0]


def resolve_canonical_artifacts(
    stage: PlanningStage,
    project_dir: Path,
) -> tuple[Path, ...]:
    """정적 stage의 모든 canonical artifact 절대경로를 반환한다."""
    artifacts = _STAGE_CANONICAL_ARTIFACTS.get(stage)
    if artifacts is None:
        return ()
    return tuple(project_dir / a for a in artifacts)


def resolve_feature_outline_path(
    project_dir: Path,
    feature_name: str,
) -> Path:
    """동적: feature outline 파일의 canonical 절대경로."""
    return project_dir / CANONICAL_PLANNING_DIR / "feature-outlines" / f"{feature_name}.md"


def resolve_exec_plan_outline_path(project_dir: Path) -> Path:
    """exec-plan-outline.md (merge 결과)의 canonical 절대경로."""
    return project_dir / CANONICAL_PLANNING_DIR / "exec-plan-outline.md"


def resolve_observation_path(
    project_dir: Path,
    slice_name: str,
) -> Path:
    """동적: brownfield code observation 파일의 canonical 절대경로."""
    return project_dir / CANONICAL_PLANNING_DIR / "code-observations" / f"{slice_name}.md"


def resolve_detail_path(
    project_dir: Path,
    plan_name: str,
) -> Path:
    """동적: exec-plan detail의 canonical 절대경로 (중간 산출물).
    
    최종본은 docs/exec-plans/planning/ 에 write_numbered_exec_plan()으로 복사된다.
    """
    return project_dir / CANONICAL_PLANNING_DIR / f"detail-{plan_name}.md"


def resolve_final_exec_plan_path(
    project_dir: Path,
    plan_name: str,
) -> Path:
    """최종 numbered exec-plan의 절대경로."""
    return project_dir / CANONICAL_EXEC_PLANS_DIR / f"{plan_name}.md"


def resolve_canonical_planning_dir(project_dir: Path) -> Path:
    return project_dir / CANONICAL_PLANNING_DIR


def resolve_run_dir(project_dir: Path, run_id: str) -> Path:
    return project_dir / RUN_ROOT / run_id


def get_stage_input_artifacts(
    stage: PlanningStage,
    project_dir: Path,
) -> tuple[Path, ...]:
    """stage가 읽어야 하는 이전 stage canonical artifact 경로들.
    
    _STAGE_CONTRACTS.input_files의 상대 파일명을 canonical 절대경로로 변환한다.
    이 함수는 prompts.py와 handoffs.py 양쪽에서 사용한다.
    """
    from cowork_pilot.planning.prompts import _STAGE_CONTRACTS
    contract = _STAGE_CONTRACTS.get(stage)
    if contract is None or not contract.input_files:
        return ()
    
    canonical_dir = project_dir / CANONICAL_PLANNING_DIR
    result: list[Path] = []
    for filename in contract.input_files:
        # planning-references/ 는 run_dir에 있으므로 제외
        if filename.startswith("planning-references/"):
            continue
        # inputs/ 는 run_dir에 있으므로 제외
        if filename.startswith("inputs/"):
            continue
        result.append(canonical_dir / filename)
    return tuple(result)
```

---

## 3. 변경 대상 파일 목록과 변경 내용

### 3.1. `session_profiles.py` — ARTIFACT_OWNERSHIP_TABLE 수정

**현재**: `completion_artifacts`가 run_dir 상대 파일명 (`"classification-report.md"`)
**변경**: `completion_artifacts`를 canonical 상대경로로 변경 (`"docs/generated/planning/classification-report.md"`)

```python
# 변경 전
PlanningStage.CLASSIFICATION: ArtifactOwnership(
    artifact_owner="classification session",
    completion_artifacts=("classification-report.md",),
    ...
),

# 변경 후
PlanningStage.CLASSIFICATION: ArtifactOwnership(
    artifact_owner="classification session",
    completion_artifacts=(f"{CANONICAL_PLANNING_DIR}/classification-report.md",),
    ...
),
```

**모든 stage에 동일 패턴 적용.** import 추가:
```python
from cowork_pilot.planning.canonical_paths import CANONICAL_PLANNING_DIR
```

**brownfield도 동일:**
```python
PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: ArtifactOwnership(
    completion_artifacts=(f"{CANONICAL_PLANNING_DIR}/code-observations/<slice>.md",),
    ...
),
PlanningStage.BROWNFIELD_GAP_SYNTHESIS: ArtifactOwnership(
    completion_artifacts=(
        f"{CANONICAL_PLANNING_DIR}/spec-implementation-gap.md",
        f"{CANONICAL_PLANNING_DIR}/change-impact-gap.md",
    ),
    ...
),
```

### 3.2. `completion_verifier.py` — project_dir 기준으로 변경

**현재 시그니처:**
```python
def verify_stage_completion(
    stage: PlanningStage,
    *,
    run_dir: Path,
) -> CompletionVerdict:
```

**변경 후 시그니처:**
```python
def verify_stage_completion(
    stage: PlanningStage,
    *,
    project_dir: Path,
    run_dir: Path | None = None,  # backward compat, 사용하지 않음
) -> CompletionVerdict:
```

**핵심 변경:**
```python
# 변경 전
for artifact_rel in ownership.completion_artifacts:
    artifact_path = run_dir / artifact_rel
    if not artifact_path.exists():
        missing.append(artifact_rel)

primary_path = run_dir / ownership.completion_artifacts[0]

# 변경 후
for artifact_rel in ownership.completion_artifacts:
    artifact_path = project_dir / artifact_rel
    if not artifact_path.exists():
        missing.append(artifact_rel)

primary_path = project_dir / ownership.completion_artifacts[0]
```

이제 `completion_artifacts`가 `"docs/generated/planning/classification-report.md"` 같은 project_dir 기준 상대경로이므로, `project_dir / artifact_rel`로 절대경로가 된다.

**동적 stage 처리:**  
`BROWNFIELD_CODE_OBSERVATION_EXTRACTION`과 `EXEC_PLAN_FEATURE_OUTLINE`은 `<slice>`/`<feature>` 부분이 런타임에 결정되므로 ARTIFACT_OWNERSHIP_TABLE의 패턴 경로로는 직접 검증 불가. 이 stage들은 `canonical_paths.py`의 `resolve_*` 함수를 사용하는 별도 검증 로직 필요:

```python
if stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION:
    # 패턴 경로이므로 ownership table이 아닌 실제 파일 존재로 판정
    obs_dir = project_dir / CANONICAL_PLANNING_DIR / "code-observations"
    if not obs_dir.exists() or not list(obs_dir.glob("*.md")):
        return CompletionVerdict(passed=False, reason="no observation files found")
    # 각 파일에 done marker 확인
    for md_file in obs_dir.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        if _DONE_MARKER not in content:
            return CompletionVerdict(passed=False, reason=f"{md_file.name} missing done marker")
    return CompletionVerdict(passed=True)

if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
    outlines_dir = project_dir / CANONICAL_PLANNING_DIR / "feature-outlines"
    if not outlines_dir.exists() or not list(outlines_dir.glob("*.md")):
        return CompletionVerdict(passed=False, reason="no feature outline files found")
    return CompletionVerdict(passed=True)
```

### 3.3. `pipeline.py` — `_resolve_stage_artifact_path()` 수정

**현재:**
```python
def _resolve_stage_artifact_path(stage: PlanningStage, run_dir: Path) -> Path | None:
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return run_dir / ownership.completion_artifacts[0]
```

**변경 후:**
```python
def _resolve_stage_artifact_path(stage: PlanningStage, project_dir: Path) -> Path | None:
    """Resolve primary artifact path via canonical_paths (single source of truth)."""
    from cowork_pilot.planning.canonical_paths import resolve_canonical_artifact
    return resolve_canonical_artifact(stage, project_dir)
```

**호출 지점 전부 수정** — `_apply_stage_completion()` 내부:
```python
# 변경 전 (모든 stage 공통 패턴)
result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)

# 변경 후
result_file = _resolve_stage_artifact_path(stage, runtime.project_dir)
```

이 변경은 `_apply_stage_completion()` 내 다음 stage들에 적용:
- `CLASSIFICATION` (line 451)
- `CORE_DOCS_CHECK` (line 469)
- `ADAPTIVE_DOCS_SELECTION` (line 479)
- `SCOPE_STRUCTURING` (line 557)
- `WORK_SIZING` (line 570)
- `PLAN_PACKING` (line 580)
- `PLAN_REVIEW` (line 590)

### 3.4. `pipeline.py` — `_apply_stage_completion()` 동적 stage 수정

**PRODUCT_COMPLETENESS_REVIEW (line 488-512):**
```python
# 변경 전
completeness_result = run_completeness_review(
    ..., run_dir=runtime.run_dir,
)

# 변경 후 — completeness.py도 canonical 경로로 쓰게 바꿈
completeness_result = run_completeness_review(
    ..., 
    canonical_dir=runtime.project_dir / CANONICAL_PLANNING_DIR,
    run_dir=runtime.run_dir,  # deprecated, 유지만
)
```

**EXEC_PLAN_SKELETON (line 603-605):**
```python
# 변경 전
skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"

# 변경 후
from cowork_pilot.planning.canonical_paths import resolve_canonical_artifact
skeleton_path = resolve_canonical_artifact(PlanningStage.EXEC_PLAN_SKELETON, runtime.project_dir)
```

**EXEC_PLAN_FEATURE_OUTLINE (line 607-610):**
```python
# 변경 전
feature_name = dispatch.substage
outline_file = runtime.run_dir / "feature-outlines" / f"{feature_name}.md"

# 변경 후
from cowork_pilot.planning.canonical_paths import resolve_feature_outline_path
feature_name = dispatch.substage
outline_file = resolve_feature_outline_path(runtime.project_dir, feature_name)
```

**EXEC_PLAN_DETAIL (line 612-621):**
```python
# 변경 전
detail_source = runtime.run_dir / f"detail-{dispatch.substage}.md"

# 변경 후
from cowork_pilot.planning.canonical_paths import resolve_detail_path
detail_source = resolve_detail_path(runtime.project_dir, dispatch.substage)
```

**Dynamic injection phase 1 — skeleton 후 feature outline dispatch (line 383-391):**
```python
# 변경 전
skeleton_path = runtime.run_dir / "exec-plan-skeleton.md"

# 변경 후
skeleton_path = resolve_canonical_artifact(PlanningStage.EXEC_PLAN_SKELETON, runtime.project_dir)
```

**Dynamic injection phase 2 — outline merge (line 393-405):**
```python
# 변경 전
outline_path = merge_feature_outlines(run_dir=runtime.run_dir)

# 변경 후
outline_path = merge_feature_outlines(project_dir=runtime.project_dir)
```

**File-evidence completion check (line 356-357):**
```python
# 변경 전
file_verdict = verify_stage_completion(dispatch.stage, run_dir=runtime.run_dir)

# 변경 후
file_verdict = verify_stage_completion(dispatch.stage, project_dir=runtime.project_dir)
```

### 3.5. `prompts.py` — `_resolve_output_file()` 수정

**현재:**
```python
def _resolve_output_file(stage: PlanningStage) -> str | None:
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return ownership.completion_artifacts[0]
```

이 함수는 Jinja 템플릿에 `{{ output_file }}`로 전달된다. 현재는 `"classification-report.md"` 같은 bare filename이 들어가고, AI가 이걸 보고 현재 작업 디렉토리에 파일을 만든다.

**변경 후:**
```python
def _resolve_output_file(stage: PlanningStage, project_dir: Path) -> str | None:
    """Return the absolute canonical output path for the stage.
    
    This path is embedded directly into the prompt, so the AI knows
    exactly where to write the file — just like docs-orchestrator.
    """
    from cowork_pilot.planning.canonical_paths import resolve_canonical_artifact
    path = resolve_canonical_artifact(stage, project_dir)
    if path is None:
        return None
    return str(path)
```

**`render_stage_prompt()` 수정:**
```python
# 변경 전
def render_stage_prompt(
    stage: PlanningStage,
    context: PlanningContext | Mapping[str, object] | None = None,
    *,
    read_set: tuple[Path, ...] | tuple[str, ...] | None = None,
    ...
) -> str:
    ...
    output_file = _resolve_output_file(stage) or f"{stage.value}-output.md"
    ...

# 변경 후
def render_stage_prompt(
    stage: PlanningStage,
    context: PlanningContext | Mapping[str, object] | None = None,
    *,
    project_dir: Path | None = None,
    read_set: tuple[Path, ...] | tuple[str, ...] | None = None,
    ...
) -> str:
    ...
    if project_dir is not None:
        output_file = _resolve_output_file(stage, project_dir) or f"{stage.value}-output.md"
    else:
        # fallback for tests / legacy
        output_file = _resolve_output_file_legacy(stage) or f"{stage.value}-output.md"
    ...
```

**Jinja 템플릿의 `{{ output_file }}`은 이제 절대경로가 된다:**
```
출력 파일:
- /Users/user/project/docs/generated/planning/classification-report.md
```

이것이 docs-orchestrator의 `phase5_detail.j2`가 하는 것과 동일한 패턴이다.

### 3.6. `prompts.py` — `_STAGE_CONTRACTS.input_files` 수정

**현재:** bare filename (`"classification-report.md"`)
**변경:** 런타임에 `canonical_paths.get_stage_input_artifacts()`로 해석하므로 contract 자체는 변경하지 않아도 된다. 대신 `render_stage_prompt()`에서 input_files를 절대경로로 변환:

```python
# render_stage_prompt() 내부
if contract and contract.input_files and project_dir is not None:
    canonical_dir = project_dir / CANONICAL_PLANNING_DIR
    resolved_input_files = tuple(
        str(canonical_dir / f) if not f.startswith("planning-references/")
        else f  # planning-references는 read_set에서 run_dir 기준으로 처리
        for f in contract.input_files
    )
else:
    resolved_input_files = contract.input_files if contract else ()

return template.render(
    ...
    input_files=resolved_input_files,
    ...
)
```

### 3.7. `storage.py` — `write_intermediate_doc()` 대상 분리

**현재:** 모든 산출물이 `write_intermediate_doc(run_dir, filename, content)`로 run_dir에 쓰인다.

**추가 함수:**
```python
def write_canonical_doc(canonical_dir: Path, filename: str, content: str) -> Path:
    """Write a planning artifact to the canonical docs directory.
    
    canonical_dir = project_dir / "docs/generated/planning"
    """
    candidate = (canonical_dir / filename).resolve(strict=False)
    root = canonical_dir.resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"filename escapes canonical_dir: {filename}")
    doc_path = candidate
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(content, encoding="utf-8")
    return doc_path
```

**stage_executor가 AI에게 프롬프트를 주면, AI가 절대경로에 직접 파일을 쓴다.** 따라서 `write_intermediate_doc()`는 대부분의 stage 산출물에 대해 호출되지 않게 된다. 이 함수는 handoff/log 같은 run_dir 전용 파일에만 남는다.

### 3.8. `completeness.py` — canonical 경로로 출력

**현재 (line 105-116):**
```python
if run_dir is not None and snapshot.project_mode is ProjectMode.GREENFIELD:
    review_path = run_dir / "product-completeness-review.md"
    ...
    coverage_gap_path = run_dir / "coverage-gap.md"
```

**변경 후:**
```python
def run_completeness_review(
    required_docs: list[str],
    conditional_docs: list[str],
    *,
    snapshot: ClassificationSnapshot,
    canonical_dir: Path | None = None,  # 새 파라미터
    run_dir: Path | None = None,        # deprecated
) -> CompletenessResult:
    ...
    output_dir = canonical_dir or run_dir
    if output_dir is not None and snapshot.project_mode is ProjectMode.GREENFIELD:
        review_path = output_dir / "product-completeness-review.md"
        ...
        coverage_gap_path = output_dir / "coverage-gap.md"
```

### 3.9. `outline.py` — `merge_feature_outlines()` canonical 경로 사용

**현재:**
```python
def merge_feature_outlines(*, run_dir: Path) -> Path:
    skeleton_path = run_dir / "exec-plan-skeleton.md"
    ...
    outlines_dir = run_dir / "feature-outlines"
    ...
    outline_path = run_dir / "exec-plan-outline.md"
```

**변경 후:**
```python
def merge_feature_outlines(*, project_dir: Path, run_dir: Path | None = None) -> Path:
    """Merge feature outlines into unified exec-plan-outline.md.
    
    Reads from canonical paths, writes to canonical path.
    """
    from cowork_pilot.planning.canonical_paths import (
        resolve_canonical_artifact,
        resolve_exec_plan_outline_path,
        CANONICAL_PLANNING_DIR,
    )
    canonical_dir = project_dir / CANONICAL_PLANNING_DIR
    skeleton_path = resolve_canonical_artifact(PlanningStage.EXEC_PLAN_SKELETON, project_dir)
    ...
    outlines_dir = canonical_dir / "feature-outlines"
    ...
    outline_path = resolve_exec_plan_outline_path(project_dir)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return outline_path
```

### 3.10. `handoffs.py` — `build_stage_read_set()` 수정

handoff 자체는 run_dir에 유지한다. 하지만 `build_stage_read_set()`이 반환하는 경로에 canonical artifact 경로가 포함되어야 한다.

**현재:**
```python
def build_stage_read_set(
    *,
    run_dir: Path,
    canonical_docs: tuple[Path, ...] = (),
    previous_handoff: Path | None = None,
    runtime_logs: tuple[Path | str, ...] = (),
) -> tuple[Path, ...]:
```

**변경 후:**
```python
def build_stage_read_set(
    *,
    run_dir: Path,
    project_dir: Path | None = None,
    stage: PlanningStage | None = None,
    canonical_docs: tuple[Path, ...] = (),
    previous_handoff: Path | None = None,
    runtime_logs: tuple[Path | str, ...] = (),
) -> tuple[Path, ...]:
    """Build the ordered read set for a stage.
    
    If project_dir and stage are given, automatically includes
    the stage's canonical input artifacts from canonical_paths.
    """
    ordered_paths: list[Path] = []
    normalized_request = run_dir / "inputs" / "normalized-request.md"
    ordered_paths.append(normalized_request)

    change_request = run_dir / "inputs" / "change-request.md"
    if change_request.exists():
        ordered_paths.append(change_request)

    if previous_handoff is not None:
        ordered_paths.append(previous_handoff)
    
    # canonical input artifacts for this stage
    if project_dir is not None and stage is not None:
        from cowork_pilot.planning.canonical_paths import get_stage_input_artifacts
        for artifact_path in get_stage_input_artifacts(stage, project_dir):
            if artifact_path.exists():
                ordered_paths.append(artifact_path)
    
    ordered_paths.extend(canonical_docs)
    
    for runtime_log in runtime_logs:
        candidate = _resolve_runtime_log_path(run_dir, runtime_log)
        if candidate.exists():
            ordered_paths.append(candidate)
    return _dedupe_paths(ordered_paths)
```

### 3.11. Jinja 템플릿 수정

**`_includes/completion_protocol.j2`의 `outputs:` 섹션:**
```jinja2
{# 변경 전 #}
outputs:
  - {{ output_file }}

{# 변경 후 — output_file이 이제 절대경로이므로 변경 불필요 #}
{# 자동으로 절대경로가 들어간다 #}
outputs:
  - {{ output_file }}
```

실제로 Jinja 템플릿 자체는 변경 불필요. `{{ output_file }}`에 들어가는 값이 `"classification-report.md"` → `"/abs/path/docs/generated/planning/classification-report.md"`로 바뀌기 때문.

**단, 동적 stage 템플릿은 수정 필요:**

`exec_plan_feature_outline.j2`:
```jinja2
{# 현재는 output_file이 ARTIFACT_OWNERSHIP_TABLE에 없어서 fallback 됨 #}
{# 변경: render_stage_prompt()에서 동적 경로를 직접 주입 #}
출력 파일:
- {{ output_file }}
```

`exec_plan_detail.j2`: 동일 패턴.

**`render_stage_prompt()` 에서 동적 stage의 output_file 주입:**
```python
# render_stage_prompt() 내부, 동적 stage 처리
if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE and substage and project_dir:
    from cowork_pilot.planning.canonical_paths import resolve_feature_outline_path
    output_file = str(resolve_feature_outline_path(project_dir, substage))
elif stage is PlanningStage.EXEC_PLAN_DETAIL and substage and project_dir:
    from cowork_pilot.planning.canonical_paths import resolve_detail_path
    output_file = str(resolve_detail_path(project_dir, substage))
elif stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION and substage and project_dir:
    from cowork_pilot.planning.canonical_paths import resolve_observation_path
    output_file = str(resolve_observation_path(project_dir, substage))
else:
    output_file = _resolve_output_file(stage, project_dir) or f"{stage.value}-output.md"
```

### 3.12. `pipeline.py` — `_render_dispatch_prompt()` 수정

이 함수가 `render_stage_prompt()`를 호출하는 중간 함수다. `project_dir`을 전달해야 한다:

```python
# 현재 (추정 — 이 함수의 정확한 시그니처 확인 필요)
def _render_dispatch_prompt(
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
    previous_handoff: Path | None,
) -> str:
    read_set = build_stage_read_set(
        run_dir=runtime.run_dir,
        ...
    )
    return render_stage_prompt(
        dispatch.stage,
        runtime.result_context,
        read_set=read_set,
        ...
        substage=dispatch.substage or "",
    )

# 변경 후
def _render_dispatch_prompt(
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
    previous_handoff: Path | None,
) -> str:
    read_set = build_stage_read_set(
        run_dir=runtime.run_dir,
        project_dir=runtime.project_dir,
        stage=dispatch.stage,
        ...
    )
    return render_stage_prompt(
        dispatch.stage,
        runtime.result_context,
        project_dir=runtime.project_dir,
        read_set=read_set,
        ...
        substage=dispatch.substage or "",
    )
```

### 3.13. `config.toml` — canonical_planning_dir 추가

```toml
[planning]
run_root = "docs/generated/planning-runs"
canonical_dir = "docs/generated/planning"        # 새로 추가
# ... 나머지 동일
```

---

## 4. Brownfield Per-Run Refresh 정책 구현

### 4.1. 개념

brownfield 재실행 시 canonical planning docs가 이미 존재할 수 있다.
정책: **현재 run이 canonical planning docs 전체를 최신 상태로 재생성한다.**
이전 상태는 run dir에 스냅샷으로 남긴다.

### 4.2. 구현: `canonical_refresh.py`

**위치**: `src/cowork_pilot/planning/canonical_refresh.py`

```python
"""Per-run canonical refresh: snapshot existing → clear → regenerate."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from cowork_pilot.planning.canonical_paths import CANONICAL_PLANNING_DIR


def snapshot_existing_canonical(
    project_dir: Path,
    run_dir: Path,
) -> Path | None:
    """Run 시작 전에 기존 canonical planning docs를 run dir에 스냅샷으로 복사.
    
    Returns snapshot directory path, or None if no existing docs.
    """
    canonical_dir = project_dir / CANONICAL_PLANNING_DIR
    if not canonical_dir.exists():
        return None
    
    # 스냅샷 이름에 타임스탬프 포함
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_dir = run_dir / "canonical-snapshots" / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    # canonical dir 전체를 스냅샷으로 복사
    shutil.copytree(canonical_dir, snapshot_dir / "planning", dirs_exist_ok=True)
    return snapshot_dir


def clear_canonical_planning_docs(project_dir: Path) -> None:
    """기존 canonical planning docs를 삭제하여 재생성 준비.
    
    docs/exec-plans/planning/ 은 건드리지 않는다 — 
    최종 exec-plan은 별도 lifecycle.
    """
    canonical_dir = project_dir / CANONICAL_PLANNING_DIR
    if canonical_dir.exists():
        shutil.rmtree(canonical_dir)
    canonical_dir.mkdir(parents=True, exist_ok=True)
```

### 4.3. pipeline.py에서 refresh 호출

`run_planning_stage_graph()` 진입점에서, 파이프라인 시작 직전:

```python
def run_planning_stage_graph(...):
    ...
    # Bootstrap run dir
    run_dir = bootstrap_run_dir(base_dir, run_id)
    
    # Per-run canonical refresh
    from cowork_pilot.planning.canonical_refresh import (
        snapshot_existing_canonical,
        clear_canonical_planning_docs,
    )
    snapshot_existing_canonical(project_dir, run_dir)
    clear_canonical_planning_docs(project_dir)
    
    # Continue with pipeline...
```

---

## 5. 실행 순서

이 변경은 한 번에 해야 한다. 부분 적용 시 경로가 이중화된다.

### Phase 1: 기반 (먼저)
1. `canonical_paths.py` 생성
2. `canonical_refresh.py` 생성
3. `config.toml`에 `canonical_dir` 추가

### Phase 2: 경로 해석 중앙화 (동시)
4. `session_profiles.py` — `ARTIFACT_OWNERSHIP_TABLE` 경로 변경
5. `completion_verifier.py` — `project_dir` 기준으로 변경
6. `prompts.py` — `_resolve_output_file()`, `render_stage_prompt()` 변경
7. `storage.py` — `write_canonical_doc()` 추가

### Phase 3: 파이프라인 적용 (동시)
8. `pipeline.py` — `_resolve_stage_artifact_path()` 변경
9. `pipeline.py` — `_apply_stage_completion()` 전체 stage 변경
10. `pipeline.py` — dynamic injection (skeleton→outline→detail) 경로 변경
11. `pipeline.py` — file-evidence completion check 변경
12. `pipeline.py` — `_render_dispatch_prompt()` 변경
13. `pipeline.py` — `run_planning_stage_graph()` 진입점에 refresh 추가

### Phase 4: 보조 모듈 (동시)
14. `handoffs.py` — `build_stage_read_set()` 변경
15. `completeness.py` — canonical_dir 파라미터 추가
16. `outline.py` — `merge_feature_outlines()` 변경
17. `request_normalization.py` — 변경 없음 (이미 canonical에 change-request.md 씀)

### Phase 5: 검증
18. 기존 테스트 수정 (run_dir → project_dir 변경 반영)
19. 통합 테스트: greenfield full pipeline → canonical dir에 모든 산출물 생성 확인
20. 통합 테스트: brownfield 재실행 → snapshot 생성 + canonical refresh 확인
21. 통합 테스트: resume (continue_planning_stage_graph) → canonical 파일 기준 skip 정상 작동 확인

---

## 6. 주의사항

### 6.1. `stage_executor.execute_stage_subsession()`의 작업 디렉토리

현재 AI 세션은 `run_dir`을 작업 디렉토리로 사용할 가능성이 높다. 프롬프트에 절대경로를 박아서 출력 위치를 명시하면, AI가 그 절대경로에 파일을 생성한다. 하지만 `stage_executor`가 `run_dir`을 `cwd`로 설정하는 경우, AI가 상대경로로 쓸 수 있다. 

**확인 필요:** `stage_executor.py`에서 AI 세션의 working directory 설정 방식. 절대경로 프롬프트를 줘도 AI가 working dir에 파일을 만들 수 있으므로, 이 경우 `stage_executor`도 수정해야 한다.

**대안:** AI가 파일을 어디에 만들든, pipeline에서 완료 체크는 canonical 경로에서 하므로, AI가 canonical 경로에 안 쓰면 stage가 실패로 판정된다. 이게 정확한 행동이다.

### 6.2. planning-references의 위치

현재 `copy_planning_references()`로 run_dir에 복사한다. 이건 유지한다. planning-references는 "참조 입력"이지 "산출물"이 아니다. run_dir에 있는 게 맞다.

### 6.3. inputs/ 의 위치

`inputs/normalized-request.md`, `inputs/change-request.md`도 run_dir에 유지한다. 이것들은 "이 run의 입력 스냅샷"이다.

### 6.4. continue_planning_stage_graph()의 호환성

resume 시에는 `snapshot_existing_canonical()` / `clear_canonical_planning_docs()`를 호출하면 안 된다. 이미 진행 중인 canonical docs를 날리게 된다. resume는 기존 canonical docs를 그대로 이어써야 한다.

```python
def continue_planning_stage_graph(run_dir: Path, ...):
    # canonical refresh 하지 않음 — 기존 canonical docs 위에 이어쓴다
    ...
```

### 6.5. `_STAGE_CONTRACTS.input_files`의 특수 경로

`planning-references/observation-format.md` 같은 건 run_dir 기준이다. `canonical_paths.get_stage_input_artifacts()`에서 이 prefix를 감지하고 run_dir 기준으로 해석해야 한다. 위의 `canonical_paths.py` 코드에서 이미 `planning-references/` prefix를 skip하고 있다.

read_set 빌드 시 planning-references는 기존대로 run_dir 기준으로 추가된다.

---

## 7. 변경 요약 (파일 × 변경 유형)

| 파일 | 변경 유형 | 핵심 |
|------|-----------|------|
| `canonical_paths.py` | **신규** | 경로 해석 중앙 모듈 |
| `canonical_refresh.py` | **신규** | per-run snapshot + clear |
| `session_profiles.py` | 수정 | `completion_artifacts` 경로 변경 |
| `completion_verifier.py` | 수정 | `project_dir` 기준 검증 |
| `prompts.py` | 수정 | `output_file` 절대경로, `input_files` 해석 |
| `pipeline.py` | 수정 | 전체 경로 해석 + refresh + 동적 stage |
| `storage.py` | 추가 | `write_canonical_doc()` |
| `handoffs.py` | 수정 | `build_stage_read_set()` canonical 경로 포함 |
| `completeness.py` | 수정 | `canonical_dir` 파라미터 |
| `outline.py` | 수정 | `project_dir` 기준 merge |
| `config.toml` | 추가 | `canonical_dir` 설정 |
| Jinja 템플릿 | 변경 없음 | `{{ output_file }}`이 자동으로 절대경로가 됨 |

---

## 8. 검증 체크리스트

- [ ] greenfield: `docs/generated/planning/classification-report.md` ~ `plan-review.md` 전부 생성됨
- [ ] greenfield: `docs/generated/planning/exec-plan-skeleton.md` 생성됨
- [ ] greenfield: `docs/generated/planning/feature-outlines/*.md` 생성됨
- [ ] greenfield: `docs/generated/planning/exec-plan-outline.md` 생성됨 (merge)
- [ ] greenfield: `docs/exec-plans/planning/*.md` 최종 plan 생성됨
- [ ] brownfield: `docs/generated/planning/code-observations/*.md` 생성됨
- [ ] brownfield: gap 문서들 canonical에 생성됨
- [ ] brownfield 재실행: 이전 canonical docs가 run dir에 스냅샷됨
- [ ] brownfield 재실행: canonical dir이 clear 후 재생성됨
- [ ] resume: canonical docs가 clear되지 않고 이어써짐
- [ ] completion verifier: canonical 경로에서 파일 + done marker + JSON 검증 통과
- [ ] handoff read_set: canonical artifact 경로가 포함됨
- [ ] 프롬프트 내 `출력 파일:` 섹션에 절대경로가 나옴
- [ ] run dir에는 stage 산출물 없이 운영 파일만 남음

<!-- ORCHESTRATOR:DONE -->
