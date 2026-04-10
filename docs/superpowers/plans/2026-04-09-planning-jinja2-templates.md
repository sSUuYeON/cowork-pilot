# Planning Pipeline Jinja2 Templates Implementation Plan


**Goal:** Replace Python string-concatenation prompt generation with Jinja2 templates, adding docs-orchestrator-level procedural instructions to every planning stage.

**Architecture:** `planning_templates/` directory with 16 stage `.j2` files + 3 `_includes/` common blocks. `prompts.py` loads templates via `_get_jinja_env()` + `_STAGE_TEMPLATE_MAP`, renders with `StageContract` data as kwargs. `completion_verifier.py` deduplicates `_STAGE_REQUIRED_KEYS` by importing from `_STAGE_CONTRACTS`.

**Tech Stack:** Python 3.10+, Jinja2 (already a dependency), pytest

**Spec:** `docs/superpowers/specs/2026-04-09-planning-jinja2-templates-design.md`

---

## Chunk 0: _includes/ common blocks + Jinja2 infrastructure in prompts.py

### Task 0: Create `_includes/` common template blocks

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/_includes/read_set.j2`
- Create: `src/cowork_pilot/planning/planning_templates/_includes/output_format.j2`
- Create: `src/cowork_pilot/planning/planning_templates/_includes/completion_protocol.j2`

- [ ] **Step 1: Create the `_includes/` directory**

Run: `mkdir -p src/cowork_pilot/planning/planning_templates/_includes`

- [ ] **Step 2: Create `read_set.j2`**

```jinja
{% for path in read_set %}
- {{ path }}
{% endfor %}
{% if handoff_summary %}

이전 stage 핸드오프 요약:
{{ handoff_summary }}
{% endif %}
{% if restored_context %}

복원된 컨텍스트:
{{ restored_context }}
{% endif %}
```

- [ ] **Step 3: Create `output_format.j2`**

```jinja
출력 형식:
- Markdown 파일에 fenced JSON 블록(```json ... ```)을 포함하라
- 필수 JSON 키: {{ json_keys | join(', ') }}
- JSON 블록 이후에 분석 근거나 부연 설명을 자유롭게 작성해도 된다
```

- [ ] **Step 4: Create `completion_protocol.j2`**

```jinja
완료 프로토콜:
1. 출력 파일의 마지막 줄에 반드시 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
2. 메시지 끝에 다음 형식의 이벤트 번들을 emit하라:

<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: {{ stage }}
event_id: {{ stage }}-done
reason: stage completed successfully
summary: (작업 요약을 한 줄로)
outputs:
  - {{ output_file }}
</COWORK_PILOT_EVENT>

진행 중 질문이 필요하면 INPUT_REQUIRED, 승인이 필요하면 APPROVAL_REQUIRED,
더 이상 진행 불가하면 NEEDS_HUMAN 타입을 사용하라.
각 이벤트에는 type, stage, event_id, reason 필드가 반드시 포함되어야 한다.
```

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/planning_templates/
git commit -m "feat: add Jinja2 _includes/ common template blocks for planning prompts"
```

### Task 1: Add Jinja2 infrastructure to prompts.py

**Files:**
- Modify: `src/cowork_pilot/planning/prompts.py`

- [ ] **Step 1: Write failing test — Jinja2 env loads**

Add to `tests/test_planning_stage_prompts.py`:

```python
def test_jinja_env_loads_templates_directory():
    from cowork_pilot.planning.prompts import _get_jinja_env
    env = _get_jinja_env()
    # Should be able to list templates
    templates = env.loader.list_templates()
    assert len(templates) > 0, "No templates found in planning_templates/"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py::test_jinja_env_loads_templates_directory -v`
Expected: FAIL — `_get_jinja_env` not defined

- [ ] **Step 3: Add `_get_jinja_env` and `_STAGE_TEMPLATE_MAP` to prompts.py**

Add after the existing imports in `src/cowork_pilot/planning/prompts.py`:

```python
from jinja2 import Environment, FileSystemLoader

_STAGE_TEMPLATE_MAP: dict[PlanningStage, str] = {
    PlanningStage.CLASSIFICATION: "classification.j2",
    PlanningStage.CORE_DOCS_CHECK: "core_docs_check.j2",
    PlanningStage.ADAPTIVE_DOCS_SELECTION: "adaptive_docs_selection.j2",
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: "core_docs_presence_review.j2",
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: "product_completeness_review.j2",
    PlanningStage.SCOPE_STRUCTURING: "scope_structuring.j2",
    PlanningStage.WORK_SIZING: "work_sizing.j2",
    PlanningStage.PLAN_PACKING: "plan_packing.j2",
    PlanningStage.PLAN_REVIEW: "plan_review.j2",
    PlanningStage.EXEC_PLAN_SKELETON: "exec_plan_skeleton.j2",
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: "exec_plan_feature_outline.j2",
    PlanningStage.EXEC_PLAN_DETAIL: "exec_plan_detail.j2",
    PlanningStage.EXEC_PLAN_AUTHORING: "exec_plan_authoring.j2",
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: "brownfield_code_observation_extraction.j2",
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: "brownfield_observation_synthesis.j2",
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: "brownfield_gap_synthesis.j2",
}


def _get_jinja_env(template_dir: Path | None = None) -> Environment:
    """Create Jinja2 environment with the planning_templates directory."""
    if template_dir is None:
        template_dir = Path(__file__).parent / "planning_templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py::test_jinja_env_loads_templates_directory -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/prompts.py tests/test_planning_stage_prompts.py
git commit -m "feat: add Jinja2 environment and stage template map to prompts.py"
```

---

## Chunk 1: First 4 stage templates (classification ~ adaptive_docs_selection + core_docs_presence_review)

### Task 2: Create classification.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/classification.j2`

- [ ] **Step 1: Create the template file**

Write `classification.j2` with full procedural instructions per spec section 6.1. Template must use `{% include '_includes/read_set.j2' %}`, `{% include '_includes/output_format.j2' %}`, `{% include '_includes/completion_protocol.j2' %}`.

- [ ] **Step 2: Write test that renders classification template**

Add to `tests/test_planning_stage_prompts.py`:

```python
def test_classification_template_renders():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.CLASSIFICATION])
    result = template.render(
        stage="classification",
        target_version="v1",
        read_set=("file1.md", "file2.md"),
        handoff_summary="",
        restored_context="",
        output_file="classification-report.md",
        json_keys=("project_mode", "product_type", "size_class"),
        forbidden=("Do NOT produce a plan.",),
        input_files=(),
        purpose="Analyze project inputs.",
        substage="",
    )
    assert "classification-report.md" in result
    assert "ORCHESTRATOR:DONE" in result
    assert "COWORK_PILOT_EVENT" in result
    assert "file1.md" in result
    assert "다음을 수행하라" in result
```

- [ ] **Step 3: Run test — expect PASS**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py::test_classification_template_renders -v`

- [ ] **Step 4: Commit**

```bash
git add src/cowork_pilot/planning/planning_templates/classification.j2 tests/test_planning_stage_prompts.py
git commit -m "feat: add classification.j2 planning template"
```

### Task 3: Create core_docs_check.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/core_docs_check.j2`

- [ ] **Step 1: Create the template file** per spec section 6.2
- [ ] **Step 2: Write render test** (same pattern as Task 2)
- [ ] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

### Task 4: Create adaptive_docs_selection.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/adaptive_docs_selection.j2`

- [ ] **Step 1: Create the template file** per spec section 6.3
- [ ] **Step 2: Write render test**
- [ ] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

### Task 5: Create core_docs_presence_review.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/core_docs_presence_review.j2`

- [ ] **Step 1: Create the template file** per spec section 6.8
- [ ] **Step 2: Write render test**
- [ ] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

---

## Chunk 2: Next 4 stage templates (scope_structuring ~ plan_review + product_completeness_review)

### Task 6: Create product_completeness_review.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/product_completeness_review.j2`

- [x] **Step 1: Create the template file** per spec section 6.9
- [x] **Step 2: Write render test**
- [x] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

### Task 7: Create scope_structuring.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/scope_structuring.j2`

- [x] **Step 1: Create the template file** per spec section 6.4
- [x] **Step 2: Write render test — include forbidden doc-role names check**

```python
def test_scope_structuring_template_contains_forbidden_doc_roles():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.SCOPE_STRUCTURING])
    result = template.render(
        stage="scope_structuring", target_version="v1",
        read_set=(), handoff_summary="", restored_context="",
        output_file="scope-map.md", json_keys=("domains",),
        forbidden=(), input_files=(), purpose="", substage="",
    )
    assert "agents" in result.lower()
    assert "spec_index" in result.lower()
```

- [x] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

### Task 8: Create work_sizing.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/work_sizing.j2`

- [x] **Step 1: Create the template file** per spec section 6.5
- [x] **Step 2: Write render test**
- [x] **Step 3: Run test — expect PASS**
- [ ] **Step 4: Commit**

### Task 9: Create plan_packing.j2 and plan_review.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/plan_packing.j2`
- Create: `src/cowork_pilot/planning/planning_templates/plan_review.j2`

- [x] **Step 1: Create both template files** per spec sections 6.6 and 6.7
- [x] **Step 2: Write render tests for both**
- [x] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

---

## Chunk 3: exec_plan templates (3) + exec_plan_authoring

### Task 10: Create exec_plan_skeleton.j2, exec_plan_feature_outline.j2, exec_plan_detail.j2, exec_plan_authoring.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/exec_plan_skeleton.j2`
- Create: `src/cowork_pilot/planning/planning_templates/exec_plan_feature_outline.j2`
- Create: `src/cowork_pilot/planning/planning_templates/exec_plan_detail.j2`
- Create: `src/cowork_pilot/planning/planning_templates/exec_plan_authoring.j2`

- [x] **Step 1: Create all 4 template files** per spec sections 6.10, 6.11, 6.12, 6.15
- [x] **Step 2: Write render tests — feature_outline and detail use `substage` variable**

```python
def test_exec_plan_feature_outline_template_uses_substage():
    from cowork_pilot.planning.prompts import _get_jinja_env, _STAGE_TEMPLATE_MAP
    env = _get_jinja_env()
    template = env.get_template(_STAGE_TEMPLATE_MAP[PlanningStage.EXEC_PLAN_FEATURE_OUTLINE])
    result = template.render(
        stage="exec_plan_feature_outline", target_version="v1",
        read_set=(), handoff_summary="", restored_context="",
        output_file="feature-outlines/authentication.md",
        json_keys=(), forbidden=(), input_files=(),
        purpose="", substage="authentication",
    )
    assert "authentication" in result
```

- [x] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

---

## Chunk 4: brownfield templates (3)

### Task 11: Create brownfield_code_observation_extraction.j2, brownfield_observation_synthesis.j2, brownfield_gap_synthesis.j2

**Files:**
- Create: `src/cowork_pilot/planning/planning_templates/brownfield_code_observation_extraction.j2`
- Create: `src/cowork_pilot/planning/planning_templates/brownfield_observation_synthesis.j2`
- Create: `src/cowork_pilot/planning/planning_templates/brownfield_gap_synthesis.j2`

- [x] **Step 1: Create all 3 template files** per spec sections 6.13, 6.14, 6.16
- [x] **Step 2: Write render tests for all 3**
- [x] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

---

## Chunk 5: Extend `_STAGE_CONTRACTS` + rewrite `render_stage_prompt()` to use Jinja2

> **Dependency:** This chunk requires Chunks 0-4 complete (all 16 `.j2` templates must exist before `render_stage_prompt()` can render them).

### Task 12: Extend `_STAGE_CONTRACTS` with 9 new stages

**Files:**
- Modify: `src/cowork_pilot/planning/prompts.py:33-127` (`_STAGE_CONTRACTS`)

- [x] **Step 1: Write failing test — all PlanningStage values have contracts**

```python
def test_all_stages_have_contracts():
    from cowork_pilot.planning.prompts import _STAGE_CONTRACTS
    from cowork_pilot.planning.models import PlanningStage
    for stage in PlanningStage:
        assert stage in _STAGE_CONTRACTS, f"{stage.value} missing from _STAGE_CONTRACTS"
```

- [x] **Step 2: Run test — expect FAIL (9 stages missing)**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py::test_all_stages_have_contracts -v`

- [x] **Step 3: Add 9 new StageContract entries**

Add to `_STAGE_CONTRACTS` in `prompts.py` — the 9 stages listed in spec section 8.1 with `json_keys=()` and appropriate `purpose`/`forbidden` values.

- [x] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Commit**

### Task 13: Rewrite `render_stage_prompt()` to use Jinja2 rendering

**Files:**
- Modify: `src/cowork_pilot/planning/prompts.py:130-224` (`render_stage_prompt`)

- [x] **Step 1: Write failing test — Jinja2 rendering produces procedure instructions**

```python
def test_render_stage_prompt_produces_procedure_instructions():
    prompt = render_stage_prompt(
        PlanningStage.CLASSIFICATION,
        read_set=(Path("dummy.md"),),
        target_version="v1",
    )
    assert "다음을 수행하라" in prompt
    assert "품질 규칙" in prompt
```

- [x] **Step 2: Run test — expect FAIL (current prompts don't contain "다음을 수행하라")**

- [x] **Step 3a: Remove old code**

Remove from `render_stage_prompt()`:
1. Delete `_MARKER_INSTRUCTIONS` constant (line 10-13)
2. Delete the 3 hardcoded `if stage is PlanningStage.EXEC_PLAN_*` branches (lines 140-167)
3. Delete the `lines.append()` construction block (lines 186-224)

- [x] **Step 3b: Write Jinja2 rendering logic**

Replace with:
1. Extract `restored_context` and `resolved_target_version` from context (keep existing extraction logic from lines 169-176)
2. Look up `_STAGE_TEMPLATE_MAP.get(stage)` — if found, use Jinja2
3. Look up `StageContract` from `_STAGE_CONTRACTS.get(stage)`
4. Call `_resolve_output_file(stage)`
5. Render template with kwargs: `stage`, `target_version`, `read_set`, `handoff_summary`, `restored_context`, `output_file`, `json_keys`, `forbidden`, `input_files`, `purpose`, `substage`
6. Safety fallback for unmapped stages: `f"{stage.value}:{target_version}\n완료 시 <!-- ORCHESTRATOR:DONE --> 마커 기록\n"`

- [x] **Step 4: Run the new test — expect PASS**

- [x] **Step 5: Run ALL existing prompt tests**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py -v`

Existing tests check for `PURPOSE:`, `FORBIDDEN:`, `JSON` keywords — these may need updating since Jinja2 templates use different section headers (Korean headings like "품질 규칙" instead of "FORBIDDEN:").

- [x] **Step 6: Update existing tests to match new template format**

Run failing tests from Step 5 and update each:

`test_prompt_contains_purpose` — old: `assert "PURPOSE:" in prompt` → new: assert the contract's purpose text appears in the rendered prompt. E.g.:
```python
def test_prompt_contains_purpose(stage: PlanningStage):
    from cowork_pilot.planning.prompts import _STAGE_CONTRACTS
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    contract = _STAGE_CONTRACTS[stage]
    assert contract.purpose[:30] in prompt or "다음을 수행하라" in prompt
```

`test_prompt_contains_forbidden` — old: `assert "FORBIDDEN:" in prompt` → new: check forbidden text or "품질 규칙":
```python
def test_prompt_contains_forbidden(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "품질 규칙" in prompt or "금지" in prompt.lower()
```

`test_prompt_contains_json_schema` — keep but relax: assert JSON-related keys appear (e.g., "JSON" in prompt)
`test_prompt_contains_done_marker_instruction` — keep as-is (templates still include `ORCHESTRATOR:DONE`)
`test_prompt_contains_marker_instructions` — keep as-is (templates still include `COWORK_PILOT_EVENT`)
`test_scope_prompt_forbids_doc_role_names` — keep as-is (scope template includes doc-role forbidden list)

- [x] **Step 7: Run ALL prompt tests — expect PASS**
- [x] **Step 8: Run full test suite**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/ -v --timeout=30`

- [ ] **Step 9: Commit**

```bash
git add src/cowork_pilot/planning/prompts.py tests/test_planning_stage_prompts.py
git commit -m "feat: rewrite render_stage_prompt() to use Jinja2 templates"
```

---

## Chunk 6: Deduplicate `_STAGE_REQUIRED_KEYS` in completion_verifier.py

### Task 14: Remove `_STAGE_REQUIRED_KEYS` and import from `_STAGE_CONTRACTS`

**Files:**
- Modify: `src/cowork_pilot/planning/completion_verifier.py:20-42`

- [x] **Step 1: Write failing test — verifier uses contracts**

```python
def test_completion_verifier_uses_stage_contracts_keys():
    """After dedup, verifier should get keys from _STAGE_CONTRACTS."""
    from cowork_pilot.planning.completion_verifier import _get_required_keys
    from cowork_pilot.planning.models import PlanningStage
    keys = _get_required_keys(PlanningStage.CLASSIFICATION)
    assert keys is not None
    assert "project_mode" in keys
    assert "size_class" in keys
```

- [x] **Step 2: Run test — expect FAIL (`_get_required_keys` not defined)**

- [x] **Step 3: Replace `_STAGE_REQUIRED_KEYS` with `_get_required_keys()` function**

In `completion_verifier.py`:
1. Remove `_STAGE_REQUIRED_KEYS` dict (lines 20-42)
2. Add import: `from cowork_pilot.planning.prompts import _STAGE_CONTRACTS`
3. Add `_get_required_keys()` function per spec section 8.2
4. Update `verify_stage_completion()` to call `_get_required_keys(stage)` instead of `_STAGE_REQUIRED_KEYS.get(stage)`

- [x] **Step 4: Run test — expect PASS**

- [x] **Step 5: Run full completion verifier tests**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/ -k "completion" -v`

- [x] **Step 6: Run full test suite**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/ -v --timeout=30`

- [ ] **Step 7: Commit**

```bash
git add src/cowork_pilot/planning/completion_verifier.py tests/
git commit -m "refactor: deduplicate _STAGE_REQUIRED_KEYS by importing from _STAGE_CONTRACTS"
```

---

## Chunk 7: Parametrized coverage test + final verification

### Task 15: Add parametrized template rendering test for all 16 stages

**Files:**
- Modify: `tests/test_planning_stage_prompts.py`

- [x] **Step 1: Write parametrized test over all stages**

```python
@pytest.mark.parametrize("stage", list(PlanningStage))
def test_all_stage_templates_render_without_error(stage: PlanningStage):
    """Every PlanningStage must have a working Jinja2 template."""
    prompt = render_stage_prompt(
        stage,
        read_set=(Path("test-input.md"),),
        target_version="v1",
        substage="test-feature" if "outline" in stage.value or "detail" in stage.value else "",
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50, f"Prompt for {stage.value} is suspiciously short"
    assert "ORCHESTRATOR:DONE" in prompt
    assert "COWORK_PILOT_EVENT" in prompt
```

- [x] **Step 2: Run test — expect PASS for all 16 stages**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/test_planning_stage_prompts.py::test_all_stage_templates_render_without_error -v`

- [x] **Step 3: Run full test suite as final verification**

Run: `cd /sessions/adoring-gifted-knuth/mnt/cowork-pilot && python -m pytest tests/ -v --timeout=30`

- [ ] **Step 4: Commit**

```bash
git add tests/test_planning_stage_prompts.py
git commit -m "test: add parametrized template rendering coverage for all 16 planning stages"
```
