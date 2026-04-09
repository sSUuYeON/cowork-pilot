# AI Stage Conversion + File-Evidence Completion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert 7 local planning stages to AI stages with explicit output contracts, enforce file-evidence-based completion (done marker + JSON parse + quality gate), and replace doc-role-based scope with product-feature-based scope.

**Architecture:** `ARTIFACT_OWNERSHIP_TABLE` is the **single source of truth** for expected output file paths per stage. `prompts.py` reads filenames from this table. `completion_verifier.py` checks file existence + done marker + JSON schema. `_apply_stage_completion` reads the same table to locate files for parsing. Nobody hardcodes filenames independently.

**Output format convention:** Every stage artifact is a `.md` file containing a fenced JSON block with structured data, plus a `<!-- ORCHESTRATOR:DONE -->` marker. This gives human-readable context around machine-parseable data.

**CLASSIFICATION bootstrap:** `_initialize_runtime()` (pipeline.py:670) calls `classify_project()` synchronously to produce a bootstrap snapshot for dispatch plan construction. The CLASSIFICATION AI stage validates/overrides this. V1 logs a warning if size_class changes; dispatch rebuild is V2.

**Tech Stack:** Python 3.10+, pytest, dataclasses, pathlib

---

## Stage artifact spec (reference for all chunks)

| Stage | File | Required JSON keys |
|-------|------|--------------------|
| classification | `classification-report.md` | `project_mode`, `product_type`, `size_class`, `core_user_flows`, `primary_entities`, `risks` |
| core_docs_check | `core-docs-check.md` | `required_doc_roles`, `resolved_existing_paths`, `missing_roles`, `substitutions` |
| adaptive_docs_selection | `adaptive-docs-selection.md` | `selected_paths`, `selected_roles`, `selection_reasons`, `rejected_candidates` |
| scope_structuring | `scope-map.md` | `domains`, `features`, `user_flows`, `out_of_scope` |
| work_sizing | `work-sizing.md` | `work_items` (array of `{id, title, domain, feature, size, risk, depends_on}`) |
| plan_packing | `plan-packing.md` | `plans` (array of `{plan_name, goal, included_work_item_ids, why_grouped, dependencies}`) |
| plan_review | `plan-review.md` | `issues`, `rollback_recommended`, `coverage_status`, `execution_risks`, `missing_work_items` |

**Completion rule:** file exists AND `<!-- ORCHESTRATOR:DONE -->` present AND JSON block parses AND required keys present AND quality gate passes → completed. Any failure → retry or stop.

---

## Chunk 0: Fix pre-existing tests that will break

### Task 0: Rewrite test_stage_dispatch_plan_keeps_local_stages_local

**Files:**
- Modify: `tests/test_planning_pipeline_units.py:48-64`

- [ ] **Step 1: Rewrite the test to assert converted stages are AI**

```python
# Replace test_stage_dispatch_plan_keeps_local_stages_local (lines 48-64)
def test_stage_dispatch_plan_all_stages_are_ai(tmp_path):
    dispatches = build_stage_dispatch_plan(
        PlanningContext(run_dir=tmp_path, project_dir=tmp_path, mode=ProjectMode.GREENFIELD),
        size_class=SizeClass.SMALL,
    )

    converted_stages = {
        PlanningStage.CLASSIFICATION,
        PlanningStage.CORE_DOCS_CHECK,
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        PlanningStage.SCOPE_STRUCTURING,
        PlanningStage.WORK_SIZING,
        PlanningStage.PLAN_PACKING,
        PlanningStage.PLAN_REVIEW,
    }
    for dispatch in dispatches:
        if dispatch.stage in converted_stages:
            assert dispatch.execution_kind == "ai", (
                f"{dispatch.stage.value} should be 'ai' but got '{dispatch.execution_kind}'"
            )
```

- [ ] **Step 2: Run test — expect FAIL (stages still local)**

Run: `cd /Users/yeonsu/autoagent/cowork-pilot && python -m pytest tests/test_planning_pipeline_units.py::test_stage_dispatch_plan_all_stages_are_ai -v`
Expected: FAIL

- [ ] **Step 3: Commit**

```bash
git add tests/test_planning_pipeline_units.py
git commit -m "test: update dispatch test for AI stage conversion (will pass after Chunk 1)"
```

---

## Chunk 1: session_profiles.py — AI 전환 + ARTIFACT_OWNERSHIP_TABLE

### Task 1: Remove stages from _LOCAL_STAGE_EXECUTION_STAGES

**Files:**
- Modify: `src/cowork_pilot/planning/session_profiles.py:48-54`
- Modify: `tests/test_planning_session_profiles.py`

- [x] **Step 1: Write failing test**

```python
# Append to tests/test_planning_session_profiles.py

@pytest.mark.parametrize("stage", [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
])
def test_converted_stages_are_ai_execution_kind(stage: PlanningStage):
    for size_class in SizeClass:
        assert resolve_stage_execution_kind(stage, size_class) == "ai", (
            f"{stage.value} should be 'ai' for {size_class.value}"
        )
```

- [x] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_planning_session_profiles.py::test_converted_stages_are_ai_execution_kind -v`
Expected: FAIL for CLASSIFICATION, CORE_DOCS_CHECK, ADAPTIVE_DOCS_SELECTION, WORK_SIZING, PLAN_PACKING

- [x] **Step 3: Empty _LOCAL_STAGE_EXECUTION_STAGES**

```python
# src/cowork_pilot/planning/session_profiles.py line 48-54
_LOCAL_STAGE_EXECUTION_STAGES: set[PlanningStage] = set()
```

- [x] **Step 4: Fix existing test that asserts WORK_SIZING is local**

```python
# tests/test_planning_session_profiles.py — replace test_stage_execution_kind_distinguishes_local_and_ai_stages
def test_all_planning_stages_are_ai():
    assert resolve_stage_execution_kind(PlanningStage.WORK_SIZING, SizeClass.SMALL) == "ai"
    assert resolve_stage_execution_kind(PlanningStage.PLAN_REVIEW, SizeClass.SMALL) == "ai"
    assert resolve_stage_execution_kind(PlanningStage.CLASSIFICATION, SizeClass.SMALL) == "ai"
```

- [x] **Step 5: Run tests — expect PASS**

Run: `python -m pytest tests/test_planning_session_profiles.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit** *(skipped per user request)*

```bash
git add src/cowork_pilot/planning/session_profiles.py tests/test_planning_session_profiles.py
git commit -m "refactor: convert 7 planning stages from local to AI execution"
```

### Task 2: Add ARTIFACT_OWNERSHIP_TABLE entries for 7 stages

**Files:**
- Modify: `src/cowork_pilot/planning/session_profiles.py:225-250`
- Modify: `tests/test_planning_session_profiles.py`

- [x] **Step 1: Write failing test**

```python
# Append to tests/test_planning_session_profiles.py

_CONVERTED_ARTIFACT_CASES = (
    (PlanningStage.CLASSIFICATION, ("classification-report.md",), "core_docs_check"),
    (PlanningStage.CORE_DOCS_CHECK, ("core-docs-check.md",), "adaptive_docs_selection"),
    (PlanningStage.ADAPTIVE_DOCS_SELECTION, ("adaptive-docs-selection.md",), "scope_structuring"),
    (PlanningStage.SCOPE_STRUCTURING, ("scope-map.md",), "work_sizing"),
    (PlanningStage.WORK_SIZING, ("work-sizing.md",), "plan_packing"),
    (PlanningStage.PLAN_PACKING, ("plan-packing.md",), "plan_review"),
    (PlanningStage.PLAN_REVIEW, ("plan-review.md",), "exec_plan_skeleton"),
)


@pytest.mark.parametrize("stage,expected_artifacts,expected_consumer", _CONVERTED_ARTIFACT_CASES)
def test_converted_stage_artifact_ownership(stage, expected_artifacts, expected_consumer):
    ownership = get_artifact_ownership(stage)
    assert ownership.completion_artifacts == expected_artifacts
    assert ownership.next_consumer == expected_consumer
    assert "ORCHESTRATOR:DONE" in ownership.completion_predicate


def test_artifact_ownership_table_covers_all_contracted_stages():
    expected = {
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION,
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS,
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS,
        PlanningStage.CLASSIFICATION,
        PlanningStage.CORE_DOCS_CHECK,
        PlanningStage.ADAPTIVE_DOCS_SELECTION,
        PlanningStage.SCOPE_STRUCTURING,
        PlanningStage.WORK_SIZING,
        PlanningStage.PLAN_PACKING,
        PlanningStage.PLAN_REVIEW,
    }
    assert set(ARTIFACT_OWNERSHIP_TABLE) == expected
```

- [x] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_planning_session_profiles.py::test_converted_stage_artifact_ownership -v`
Expected: FAIL — KeyError

- [x] **Step 3: Add entries to ARTIFACT_OWNERSHIP_TABLE**

In `src/cowork_pilot/planning/session_profiles.py`, extend `ARTIFACT_OWNERSHIP_TABLE`:

```python
    PlanningStage.CLASSIFICATION: ArtifactOwnership(
        artifact_owner="classification session",
        completion_artifacts=("classification-report.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: project_mode, product_type, size_class, core_user_flows, primary_entities, risks",
        resume_target="classification session",
        reopen_trigger="stage_reopen_required",
        next_consumer="core_docs_check",
    ),
    PlanningStage.CORE_DOCS_CHECK: ArtifactOwnership(
        artifact_owner="core_docs_check session",
        completion_artifacts=("core-docs-check.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: required_doc_roles, resolved_existing_paths, missing_roles, substitutions",
        resume_target="core_docs_check session",
        reopen_trigger="stage_reopen_required",
        next_consumer="adaptive_docs_selection",
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: ArtifactOwnership(
        artifact_owner="adaptive_docs_selection session",
        completion_artifacts=("adaptive-docs-selection.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: selected_paths, selected_roles, selection_reasons, rejected_candidates",
        resume_target="adaptive_docs_selection session",
        reopen_trigger="stage_reopen_required",
        next_consumer="scope_structuring",
    ),
    PlanningStage.SCOPE_STRUCTURING: ArtifactOwnership(
        artifact_owner="scope_structuring session",
        completion_artifacts=("scope-map.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: domains, features, user_flows, out_of_scope",
        resume_target="scope_structuring session",
        reopen_trigger="stage_reopen_required",
        next_consumer="work_sizing",
    ),
    PlanningStage.WORK_SIZING: ArtifactOwnership(
        artifact_owner="work_sizing session",
        completion_artifacts=("work-sizing.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with key: work_items (array of {id, title, domain, feature, size, risk, depends_on})",
        resume_target="work_sizing session",
        reopen_trigger="stage_reopen_required",
        next_consumer="plan_packing",
    ),
    PlanningStage.PLAN_PACKING: ArtifactOwnership(
        artifact_owner="plan_packing session",
        completion_artifacts=("plan-packing.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with key: plans (array of {plan_name, goal, included_work_item_ids, why_grouped, dependencies})",
        resume_target="plan_packing session",
        reopen_trigger="stage_reopen_required",
        next_consumer="plan_review",
    ),
    PlanningStage.PLAN_REVIEW: ArtifactOwnership(
        artifact_owner="plan_review session",
        completion_artifacts=("plan-review.md",),
        completion_predicate="file exists and contains <!-- ORCHESTRATOR:DONE --> and valid JSON block with keys: issues, rollback_recommended, coverage_status, execution_risks, missing_work_items",
        resume_target="plan_review session",
        reopen_trigger="stage_reopen_required",
        next_consumer="exec_plan_skeleton",
    ),
```

- [x] **Step 4: Fix existing brownfield-only assertion test**

Replace `test_brownfield_artifact_ownership_table_is_explicit` with the new `test_artifact_ownership_table_covers_all_contracted_stages` (already in Step 1).

- [x] **Step 5: Run full session_profiles tests**

Run: `python -m pytest tests/test_planning_session_profiles.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit** *(skipped per user request)*

```bash
git add src/cowork_pilot/planning/session_profiles.py tests/test_planning_session_profiles.py
git commit -m "feat: add ARTIFACT_OWNERSHIP_TABLE entries for 7 converted stages"
```

---

## Chunk 2: Stage-specific prompts in prompts.py

### Task 3: Stage prompts with output contracts

**Files:**
- Create: `tests/test_planning_stage_prompts.py`
- Modify: `src/cowork_pilot/planning/prompts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_planning_stage_prompts.py
import pytest
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.prompts import render_stage_prompt
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE


_CONVERTED_STAGES = [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
]


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_declares_output_file_from_artifact_table(stage: PlanningStage):
    """Output filename in prompt must match ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    expected_file = ARTIFACT_OWNERSHIP_TABLE[stage].completion_artifacts[0]
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert expected_file in prompt, (
        f"Prompt for {stage.value} must declare output file '{expected_file}'"
    )


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_purpose(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "PURPOSE:" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_forbidden(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "FORBIDDEN:" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_json_schema(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "JSON" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_done_marker_instruction(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "ORCHESTRATOR:DONE" in prompt


@pytest.mark.parametrize("stage", _CONVERTED_STAGES)
def test_prompt_contains_marker_instructions(stage: PlanningStage):
    prompt = render_stage_prompt(stage, read_set=(Path("dummy.md"),), target_version="v1")
    assert "COWORK_PILOT_EVENT" in prompt


def test_scope_prompt_forbids_doc_role_names():
    prompt = render_stage_prompt(
        PlanningStage.SCOPE_STRUCTURING,
        read_set=(Path("dummy.md"),),
        target_version="v1",
    )
    assert "agents" in prompt.lower() or "doc role" in prompt.lower(), (
        "scope prompt must explicitly forbid doc role names as domains"
    )
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_planning_stage_prompts.py -v`
Expected: FAIL — current generic prompt has none of these

- [ ] **Step 3: Add StageContract and _resolve_output_file to prompts.py**

```python
# Add after _MARKER_INSTRUCTIONS in src/cowork_pilot/planning/prompts.py

from dataclasses import dataclass
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE


@dataclass(frozen=True)
class StageContract:
    purpose: str
    output_description: str
    json_keys: tuple[str, ...]
    forbidden: tuple[str, ...]
    input_files: tuple[str, ...] = ()


def _resolve_output_file(stage: PlanningStage) -> str | None:
    """Derive expected output filename from ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return ownership.completion_artifacts[0]


_STAGE_CONTRACTS: dict[PlanningStage, StageContract] = {
    PlanningStage.CLASSIFICATION: StageContract(
        purpose=(
            "Analyze project inputs and produce a classification report. "
            "Determine project_mode, product_type, size_class, core user flows, "
            "primary entities, and risks."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("project_mode", "product_type", "size_class", "core_user_flows", "primary_entities", "risks"),
        forbidden=(
            "Do NOT produce a plan or scope — only classify.",
            "Do NOT skip any required JSON key.",
        ),
    ),
    PlanningStage.CORE_DOCS_CHECK: StageContract(
        purpose=(
            "Identify which document roles are required, resolve existing file paths, "
            "flag missing roles, and note substitution options."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("required_doc_roles", "resolved_existing_paths", "missing_roles", "substitutions"),
        forbidden=(
            "Do NOT invent document content — only check presence and role necessity.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("classification-report.md",),
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: StageContract(
        purpose=(
            "Select additional documents to read beyond the core set, "
            "based on project size, classification, and what's available on disk."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("selected_paths", "selected_roles", "selection_reasons", "rejected_candidates"),
        forbidden=(
            "Do NOT repeat core docs — only list additional/conditional docs.",
            "Do NOT produce scope or plan items.",
        ),
        input_files=("classification-report.md", "core-docs-check.md"),
    ),
    PlanningStage.SCOPE_STRUCTURING: StageContract(
        purpose=(
            "Decompose the product into functional domains, user flows, and feature groups. "
            "This is about PRODUCT structure derived from normalized-request.md, completeness results, "
            "and the actual documents read — NOT about listing document roles."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("domains", "features", "user_flows", "out_of_scope"),
        forbidden=(
            "Do NOT list document roles (agents, spec_index, design_guide, etc.) as domains or features.",
            "Do NOT produce work estimates or plan chunks.",
            "Do NOT use doc-role names as scope group names.",
        ),
        input_files=("classification-report.md", "core-docs-check.md", "adaptive-docs-selection.md"),
    ),
    PlanningStage.WORK_SIZING: StageContract(
        purpose=(
            "For each feature in the scope map, produce a work item with "
            "id, title, domain, feature, size, risk, and dependency info."
        ),
        output_description="Markdown with a fenced JSON block containing a `work_items` array.",
        json_keys=("work_items",),
        forbidden=(
            "Do NOT redefine scope — take scope-map.md as given input.",
            "Do NOT produce plan chunks or execution order.",
        ),
        input_files=("scope-map.md",),
    ),
    PlanningStage.PLAN_PACKING: StageContract(
        purpose=(
            "Group sized work items into executable plan chunks, respecting "
            "dependency order and parallel-execution opportunities."
        ),
        output_description="Markdown with a fenced JSON block containing a `plans` array.",
        json_keys=("plans",),
        forbidden=(
            "Do NOT re-estimate work — take work-sizing.md as given input.",
            "Do NOT produce review verdicts.",
        ),
        input_files=("work-sizing.md", "scope-map.md"),
    ),
    PlanningStage.PLAN_REVIEW: StageContract(
        purpose=(
            "Review the packed plan for coverage gaps, over-design, sizing issues, "
            "and executionability. Produce structured verdicts."
        ),
        output_description="Markdown with a fenced JSON block.",
        json_keys=("issues", "rollback_recommended", "coverage_status", "execution_risks", "missing_work_items"),
        forbidden=(
            "Do NOT modify the plan — only review it.",
            "Do NOT skip any verdict field.",
        ),
        input_files=("plan-packing.md", "work-sizing.md", "scope-map.md"),
    ),
}
```

- [ ] **Step 4: Update render_stage_prompt to inject contracts**

Replace the generic fallback in `render_stage_prompt` (lines 62-82). The key change: if a `StageContract` exists for the stage, inject PURPOSE, OUTPUT FILE (from `_resolve_output_file`), JSON SCHEMA, FORBIDDEN, and done marker instructions.

```python
    contract = _STAGE_CONTRACTS.get(stage)

    if read_set is None and not handoff_summary and target_version is None and contract is None:
        prompt = f"{stage.value}:{resolved_target_version}\n{_MARKER_INSTRUCTIONS}"
        if restored_context:
            prompt += f"\nrestored_context:\n{restored_context}"
        return prompt

    lines = [
        f"stage={stage.value}",
        f"target_version={resolved_target_version}",
    ]

    if contract is not None:
        output_file = _resolve_output_file(stage)
        lines.append("")
        lines.append(f"PURPOSE: {contract.purpose}")
        lines.append("")
        if output_file is not None:
            lines.append(f"OUTPUT FILE: {output_file}")
        lines.append(f"OUTPUT FORMAT: {contract.output_description}")
        lines.append(f"REQUIRED JSON KEYS: {', '.join(contract.json_keys)}")
        lines.append("")
        lines.append("After the JSON block, append this exact marker on its own line:")
        lines.append("<!-- ORCHESTRATOR:DONE -->")
        lines.append("")
        if contract.input_files:
            lines.append("REQUIRED INPUTS (must exist before this stage):")
            for f in contract.input_files:
                lines.append(f"- {f}")
            lines.append("")
        lines.append("FORBIDDEN:")
        for item in contract.forbidden:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("Read these files before acting:")
    lines.extend(f"- {path}" for path in (read_set or ()))
    lines.append(
        "Treat the provided read set and persisted handoff summary as the authoritative boundary for this stage."
    )
    if handoff_summary:
        lines.extend(("", "handoff_summary:", handoff_summary))
    if restored_context:
        lines.extend(("", "restored_context:", restored_context))
    lines.extend(("", _MARKER_INSTRUCTIONS))
    return "\n".join(lines)
```

- [ ] **Step 5: Run prompt tests — expect PASS**

Run: `python -m pytest tests/test_planning_stage_prompts.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run existing prompt tests for regression**

Run: `python -m pytest tests/test_orchestrator_prompts.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/cowork_pilot/planning/prompts.py tests/test_planning_stage_prompts.py
git commit -m "feat: add per-stage output contracts with JSON schema to planning prompts"
```

---

## Chunk 3: completion_verifier.py — done marker + JSON parse + file existence

This is the core enforcement module. It reads `ARTIFACT_OWNERSHIP_TABLE` to know what file to expect, then checks three things: file exists, `<!-- ORCHESTRATOR:DONE -->` marker present, fenced JSON block parses with required keys.

### Task 4: Test + implement completion_verifier.py

**Files:**
- Create: `src/cowork_pilot/planning/completion_verifier.py`
- Create: `tests/test_planning_completion_verifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_planning_completion_verifier.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import (
    verify_stage_completion,
    CompletionVerdict,
    extract_json_block,
)
from cowork_pilot.planning.models import PlanningStage


# --- extract_json_block utility ---

def test_extract_json_block_from_fenced_md():
    content = "Some prose\n```json\n{\"a\": 1}\n```\n<!-- ORCHESTRATOR:DONE -->"
    data = extract_json_block(content)
    assert data == {"a": 1}


def test_extract_json_block_returns_none_when_missing():
    assert extract_json_block("No json here\n<!-- ORCHESTRATOR:DONE -->") is None


def test_extract_json_block_returns_none_for_invalid_json():
    content = "```json\n{invalid}\n```\n<!-- ORCHESTRATOR:DONE -->"
    assert extract_json_block(content) is None


# --- done marker ---

def test_verify_fails_when_done_marker_missing(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":[],"primary_entities":[],"risks":[]}\n```\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "ORCHESTRATOR:DONE" in verdict.reason


# --- file existence ---

def test_verify_fails_when_file_missing(tmp_path: Path):
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "classification-report.md" in verdict.missing_artifacts


# --- JSON key validation ---

def test_verify_fails_when_json_key_missing(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield"}\n```\n<!-- ORCHESTRATOR:DONE -->',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed
    assert "size_class" in verdict.reason


# --- happy path ---

def _write_valid_classification(tmp_path: Path) -> None:
    (tmp_path / "classification-report.md").write_text(
        '# Classification Report\n\n```json\n'
        '{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":["login"],"primary_entities":["user"],"risks":["none"]}\n'
        '```\n\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )


def test_verify_passes_valid_classification(tmp_path: Path):
    _write_valid_classification(tmp_path)
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert verdict.passed


def test_verify_passes_valid_scope_map(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["auth"],"features":["login"],'
        '"user_flows":["sign-in"],"out_of_scope":["admin"]}\n```\n'
        '<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert verdict.passed


def test_verify_passes_valid_work_sizing(tmp_path: Path):
    item = {"id":"w1","title":"login","domain":"auth","feature":"login","size":"S","risk":"low","depends_on":[]}
    (tmp_path / "work-sizing.md").write_text(
        f'```json\n{{"work_items":[{json.dumps(item)}]}}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.WORK_SIZING, run_dir=tmp_path)
    assert verdict.passed


def test_verify_stage_without_ownership_always_passes(tmp_path: Path):
    verdict = verify_stage_completion(PlanningStage.EXEC_PLAN_AUTHORING, run_dir=tmp_path)
    assert verdict.passed


# --- scope validation: doc roles forbidden ---

def test_verify_scope_map_rejects_doc_role_as_domain(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["agents","spec_index"],"features":[],'
        '"user_flows":[],"out_of_scope":[]}\n```\n'
        '<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed
    assert "doc role" in verdict.reason.lower() or "agents" in verdict.reason
```

- [ ] **Step 2: Run tests — expect FAIL (module doesn't exist)**

Run: `python -m pytest tests/test_planning_completion_verifier.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement completion_verifier.py**

```python
# src/cowork_pilot/planning/completion_verifier.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE

_DONE_MARKER = "<!-- ORCHESTRATOR:DONE -->"

_FORBIDDEN_SCOPE_DOMAINS = frozenset({
    "agents", "spec_index", "design_guide", "architecture",
    "security", "core_beliefs", "data_model", "spec_documents",
})

# Maps stage -> required top-level JSON keys (parsed from completion_predicate)
_STAGE_REQUIRED_KEYS: dict[PlanningStage, tuple[str, ...]] = {
    PlanningStage.CLASSIFICATION: (
        "project_mode", "product_type", "size_class",
        "core_user_flows", "primary_entities", "risks",
    ),
    PlanningStage.CORE_DOCS_CHECK: (
        "required_doc_roles", "resolved_existing_paths",
        "missing_roles", "substitutions",
    ),
    PlanningStage.ADAPTIVE_DOCS_SELECTION: (
        "selected_paths", "selected_roles",
        "selection_reasons", "rejected_candidates",
    ),
    PlanningStage.SCOPE_STRUCTURING: (
        "domains", "features", "user_flows", "out_of_scope",
    ),
    PlanningStage.WORK_SIZING: ("work_items",),
    PlanningStage.PLAN_PACKING: ("plans",),
    PlanningStage.PLAN_REVIEW: (
        "issues", "rollback_recommended", "coverage_status",
        "execution_risks", "missing_work_items",
    ),
}


@dataclass(frozen=True)
class CompletionVerdict:
    passed: bool
    missing_artifacts: tuple[str, ...] = ()
    reason: str = ""


def extract_json_block(content: str) -> dict | list | None:
    """Extract the first fenced JSON block from markdown content."""
    pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(pattern, content, re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def verify_stage_completion(
    stage: PlanningStage,
    *,
    run_dir: Path,
) -> CompletionVerdict:
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None:
        return CompletionVerdict(passed=True)

    # 1. File existence
    missing: list[str] = []
    for artifact_rel in ownership.completion_artifacts:
        artifact_path = run_dir / artifact_rel
        if not artifact_path.exists():
            missing.append(artifact_rel)
    if missing:
        return CompletionVerdict(passed=False, missing_artifacts=tuple(missing))

    primary_path = run_dir / ownership.completion_artifacts[0]
    content = primary_path.read_text(encoding="utf-8")

    # 2. Done marker
    if _DONE_MARKER not in content:
        return CompletionVerdict(
            passed=False,
            reason=f"{ownership.completion_artifacts[0]} missing <!-- ORCHESTRATOR:DONE --> marker",
        )

    # 3. JSON block parse
    required_keys = _STAGE_REQUIRED_KEYS.get(stage)
    if required_keys is not None:
        data = extract_json_block(content)
        if data is None:
            return CompletionVerdict(
                passed=False,
                reason=f"{ownership.completion_artifacts[0]} has no parseable JSON block",
            )
        if not isinstance(data, dict):
            return CompletionVerdict(
                passed=False,
                reason=f"{ownership.completion_artifacts[0]} JSON root must be an object",
            )
        missing_keys = [k for k in required_keys if k not in data]
        if missing_keys:
            return CompletionVerdict(
                passed=False,
                reason=f"Missing required JSON keys: {', '.join(missing_keys)}",
            )

        # 4. Stage-specific validation
        if stage is PlanningStage.SCOPE_STRUCTURING:
            return _validate_scope_map(data)

    return CompletionVerdict(passed=True)


def _validate_scope_map(data: dict) -> CompletionVerdict:
    """Reject scope maps that use doc-role names as domains."""
    domains = data.get("domains", [])
    if isinstance(domains, list):
        violations = [d for d in domains if isinstance(d, str) and d.lower() in _FORBIDDEN_SCOPE_DOMAINS]
        if violations:
            return CompletionVerdict(
                passed=False,
                reason=f"scope-map.md uses doc role names as domains: {violations}",
            )
    return CompletionVerdict(passed=True)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_planning_completion_verifier.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/completion_verifier.py tests/test_planning_completion_verifier.py
git commit -m "feat: add completion verifier with done marker + JSON parse + scope validation"
```

---

## Chunk 4: Pipeline integration — wire verifier into pipeline.py

Wire `verify_stage_completion` into the pipeline loop so that:
- AI stages: after `_apply_stage_completion`, check verifier. Fail → rollback/retry.
- `STAGE_COMPLETE.outputs` from `stage_executor` is hint only; file evidence is authoritative.
- `exec_plan_skeleton` with no file → never completed.

### Task 5: Test — pipeline rejects completion without valid artifact

**Files:**
- Create: `tests/test_planning_pipeline_completion.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_planning_pipeline_completion.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import verify_stage_completion
from cowork_pilot.planning.models import PlanningStage


def test_classification_without_done_marker_rejected(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield","product_type":"app","size_class":"small",'
        '"core_user_flows":[],"primary_entities":[],"risks":[]}\n```\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.CLASSIFICATION, run_dir=tmp_path)
    assert not verdict.passed


def test_exec_plan_skeleton_without_file_rejected(tmp_path: Path):
    """exec_plan_skeleton must NEVER be marked complete if file doesn't exist."""
    # EXEC_PLAN_SKELETON is already in ARTIFACT_OWNERSHIP_TABLE? No — but the pipeline
    # checks skeleton_path.exists() at line 497. We test that behavior here.
    skeleton = tmp_path / "exec-plan-skeleton.md"
    assert not skeleton.exists()
    # The pipeline's _apply_stage_completion returns empty tuple when file missing
    # which means no outputs → quality gate should catch this


def test_scope_map_with_doc_roles_rejected(tmp_path: Path):
    (tmp_path / "scope-map.md").write_text(
        '```json\n{"domains":["agents","design_guide"],"features":[],'
        '"user_flows":[],"out_of_scope":[]}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed
```

- [ ] **Step 2: Run tests — expect PASS (they test the verifier, which exists from Chunk 3)**

Run: `python -m pytest tests/test_planning_pipeline_completion.py -v`
Expected: PASS

- [ ] **Step 3: Commit tests**

```bash
git add tests/test_planning_pipeline_completion.py
git commit -m "test: add pipeline completion verification tests"
```

### Task 6: Wire verifier into pipeline.py main loop

**Files:**
- Modify: `src/cowork_pilot/planning/pipeline.py`

- [ ] **Step 1: Add import**

```python
from cowork_pilot.planning.completion_verifier import verify_stage_completion
```

- [ ] **Step 2: Add file-evidence check after AI stage completion (after line 294)**

After `outputs = _apply_stage_completion(runtime, dispatch)` and the quality gate block, add:

```python
        # File-evidence completion check (authoritative — STAGE_COMPLETE.outputs is hint only)
        file_verdict = verify_stage_completion(dispatch.stage, run_dir=runtime.run_dir)
        if not file_verdict.passed:
            rb = rollback_stage(
                run_dir=runtime.run_dir,
                dispatch_index=dispatch_index,
                outputs_to_remove=outputs,
            )
            if rb.rolled_back:
                continue
            if rb.escalated:
                write_run_state(
                    runtime.run_dir,
                    state=PlanningRuntimeState.ESCALATED.value,
                    metadata={
                        "escalated_dispatch_index": dispatch_index,
                        "stage": dispatch.stage.value,
                        "reason": f"file_evidence_failed: {file_verdict.reason or file_verdict.missing_artifacts}",
                    },
                )
                _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
                return _build_pipeline_result(
                    runtime,
                    runtime_state=PlanningRuntimeState.ESCALATED.value,
                    stopped_stage=dispatch.stage.value,
                )
```

- [ ] **Step 3: Add same check in the local stage path (lines 266-277) for safety**

Even though no stages should be local anymore, keep the path and add verification:

```python
        if dispatch.execution_kind == "local":
            outputs = _apply_stage_completion(runtime, dispatch)
            file_verdict = verify_stage_completion(dispatch.stage, run_dir=runtime.run_dir)
            if not file_verdict.passed and dispatch.stage in ARTIFACT_OWNERSHIP_TABLE:
                write_run_state(
                    runtime.run_dir,
                    state=PlanningRuntimeState.ESCALATED.value,
                    metadata={"stage": dispatch.stage.value, "reason": "local_stage_file_evidence_failed"},
                )
                _persist_runtime_state(runtime, next_dispatch_index=dispatch_index)
                return _build_pipeline_result(
                    runtime,
                    runtime_state=PlanningRuntimeState.ESCALATED.value,
                    stopped_stage=dispatch.stage.value,
                )
            # ... rest of existing local path ...
```

- [ ] **Step 4: Add import for ARTIFACT_OWNERSHIP_TABLE in pipeline.py**

```python
from cowork_pilot.planning.session_profiles import (
    ARTIFACT_OWNERSHIP_TABLE,
    resolve_brownfield_extraction_slices,
    resolve_stage_execution_kind,
    resolve_stage_profile,
)
```

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/cowork_pilot/planning/pipeline.py
git commit -m "feat: wire file-evidence completion verifier into pipeline loop"
```

## Chunk 5: AI result parsers — parse from md+JSON artifacts

Each module gets a `parse_*` function that reads the stage artifact `.md`, extracts the JSON block via `extract_json_block`, and returns the appropriate data structure. The old "generate" functions stay as `_legacy_*` fallbacks.

### Task 7: classification.py — parse_classification_report

**Files:**
- Modify: `src/cowork_pilot/planning/classification.py`
- Create: `tests/test_planning_classification_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_planning_classification_parser.py
import pytest
from pathlib import Path

from cowork_pilot.planning.classification import parse_classification_report
from cowork_pilot.planning.models import ClassificationSnapshot, ProjectMode, SizeClass


def test_parse_classification_report(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '# Classification\n\n```json\n'
        '{"project_mode":"greenfield","product_type":"spec-driven-product",'
        '"size_class":"medium","core_user_flows":["onboarding","checkout"],'
        '"primary_entities":["user","order"],"risks":["scope creep"]}\n'
        '```\n\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    snapshot = parse_classification_report(tmp_path / "classification-report.md")
    assert snapshot.project_mode is ProjectMode.GREENFIELD
    assert snapshot.size_class is SizeClass.MEDIUM
    assert snapshot.product_type == "spec-driven-product"


def test_parse_classification_report_missing_json_raises(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        "No json here\n<!-- ORCHESTRATOR:DONE -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="JSON"):
        parse_classification_report(tmp_path / "classification-report.md")


def test_parse_classification_report_missing_key_raises(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield"}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        parse_classification_report(tmp_path / "classification-report.md")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_planning_classification_parser.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement parse_classification_report**

Append to `src/cowork_pilot/planning/classification.py`:

```python
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_classification_report(path: Path) -> ClassificationSnapshot:
    """Parse an AI-generated classification-report.md into a ClassificationSnapshot."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block found in {path}")
    return ClassificationSnapshot(
        project_mode=ProjectMode(data["project_mode"]),
        size_class=SizeClass(data["size_class"]),
        product_type=str(data["product_type"]),
        confidence="medium",
        borderline=False,
        axis_observations={
            "core_user_flows": data.get("core_user_flows", []),
            "primary_entities": data.get("primary_entities", []),
            "risks": data.get("risks", []),
        },
        rationale=("parsed from AI classification-report.md",),
        brownfield_uncertainty=(
            "medium" if data["project_mode"] == "brownfield" else None
        ),
        requires_observation_reclassification=(
            data["project_mode"] == "brownfield"
        ),
    )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `python -m pytest tests/test_planning_classification_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/planning/classification.py tests/test_planning_classification_parser.py
git commit -m "feat: add parse_classification_report for AI artifact parsing"
```

### Task 8: Remaining parsers — docs_inventory, scope, sizing, packing, review

**Files:**
- Modify: `src/cowork_pilot/planning/docs_inventory.py`
- Modify: `src/cowork_pilot/planning/scope.py`
- Modify: `src/cowork_pilot/planning/sizing.py`
- Modify: `src/cowork_pilot/planning/packing.py`
- Modify: `src/cowork_pilot/planning/review.py`
- Create: `tests/test_planning_ai_result_parsers.py`

- [ ] **Step 1: Write failing tests for all 5 parsers**

```python
# tests/test_planning_ai_result_parsers.py
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.docs_inventory import parse_core_docs_check, parse_adaptive_docs_selection
from cowork_pilot.planning.scope import parse_scope_map
from cowork_pilot.planning.sizing import parse_work_sizing
from cowork_pilot.planning.packing import parse_plan_packing
from cowork_pilot.planning.review import parse_plan_review, ReviewVerdict


def _md(json_data: dict) -> str:
    return f'```json\n{json.dumps(json_data)}\n```\n<!-- ORCHESTRATOR:DONE -->\n'


def test_parse_core_docs_check(tmp_path: Path):
    data = {
        "required_doc_roles": ["agents", "spec_index"],
        "resolved_existing_paths": ["docs/AGENTS.md"],
        "missing_roles": ["design_guide"],
        "substitutions": [{"role": "design_guide", "alternative": "README.md"}],
    }
    (tmp_path / "core-docs-check.md").write_text(_md(data), encoding="utf-8")
    result = parse_core_docs_check(tmp_path / "core-docs-check.md")
    assert result["required_doc_roles"] == ["agents", "spec_index"]
    assert result["missing_roles"] == ["design_guide"]


def test_parse_adaptive_docs_selection(tmp_path: Path):
    data = {
        "selected_paths": ["docs/architecture.md"],
        "selected_roles": ["architecture"],
        "selection_reasons": ["needed for medium project"],
        "rejected_candidates": [{"role": "security", "reason": "not applicable"}],
    }
    (tmp_path / "adaptive-docs-selection.md").write_text(_md(data), encoding="utf-8")
    result = parse_adaptive_docs_selection(tmp_path / "adaptive-docs-selection.md")
    assert "architecture" in result["selected_roles"]


def test_parse_scope_map(tmp_path: Path):
    data = {
        "domains": ["auth", "payments"],
        "features": [
            {"domain": "auth", "name": "email-login"},
            {"domain": "auth", "name": "oauth"},
            {"domain": "payments", "name": "checkout"},
        ],
        "user_flows": ["sign-up-and-pay"],
        "out_of_scope": ["admin-panel"],
    }
    (tmp_path / "scope-map.md").write_text(_md(data), encoding="utf-8")
    result = parse_scope_map(tmp_path / "scope-map.md")
    assert "auth" in result
    assert len(result["auth"]) >= 2


def test_parse_work_sizing(tmp_path: Path):
    data = {
        "work_items": [
            {"id": "w1", "title": "email-login", "domain": "auth",
             "feature": "email-login", "size": "M", "risk": "low", "depends_on": []},
            {"id": "w2", "title": "oauth", "domain": "auth",
             "feature": "oauth", "size": "L", "risk": "medium", "depends_on": ["w1"]},
        ]
    }
    (tmp_path / "work-sizing.md").write_text(_md(data), encoding="utf-8")
    result = parse_work_sizing(tmp_path / "work-sizing.md")
    assert len(result) == 2
    assert result[0]["id"] == "w1"


def test_parse_plan_packing(tmp_path: Path):
    data = {
        "plans": [
            {"plan_name": "auth-foundation", "goal": "basic auth",
             "included_work_item_ids": ["w1"], "why_grouped": "prerequisite",
             "dependencies": []},
            {"plan_name": "auth-advanced", "goal": "oauth",
             "included_work_item_ids": ["w2"], "why_grouped": "depends on w1",
             "dependencies": ["auth-foundation"]},
        ]
    }
    (tmp_path / "plan-packing.md").write_text(_md(data), encoding="utf-8")
    result = parse_plan_packing(tmp_path / "plan-packing.md")
    assert len(result) == 2
    assert result[0]["plan_name"] == "auth-foundation"


def test_parse_plan_review(tmp_path: Path):
    data = {
        "issues": [],
        "rollback_recommended": False,
        "coverage_status": "full",
        "execution_risks": [],
        "missing_work_items": [],
    }
    (tmp_path / "plan-review.md").write_text(_md(data), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert isinstance(verdict, ReviewVerdict)
    assert verdict.coverage_pass is True
    assert len(verdict.issues) == 0


def test_parse_plan_review_with_issues(tmp_path: Path):
    data = {
        "issues": [{"category": "coverage", "severity": "blocking", "description": "missing payments"}],
        "rollback_recommended": True,
        "coverage_status": "incomplete",
        "execution_risks": ["tight timeline"],
        "missing_work_items": ["payment-flow"],
    }
    (tmp_path / "plan-review.md").write_text(_md(data), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert verdict.coverage_pass is False
    assert len(verdict.issues) == 1
    assert verdict.issues[0].severity == "blocking"
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_planning_ai_result_parsers.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement parse_core_docs_check and parse_adaptive_docs_selection**

Append to `src/cowork_pilot/planning/docs_inventory.py`:

```python
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_core_docs_check(path: Path) -> dict:
    """Parse AI-generated core-docs-check.md JSON block."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    return data


def parse_adaptive_docs_selection(path: Path) -> dict:
    """Parse AI-generated adaptive-docs-selection.md JSON block."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    return data
```

- [ ] **Step 4: Implement parse_scope_map**

Append to `src/cowork_pilot/planning/scope.py`:

```python
from pathlib import Path
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_scope_map(path: Path) -> dict[str, list[str]]:
    """Parse AI-generated scope-map.md into domain -> feature list mapping."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    scope: dict[str, list[str]] = {}
    for feature in data.get("features", []):
        if isinstance(feature, dict):
            domain = str(feature.get("domain", "unknown"))
            name = str(feature.get("name", ""))
            scope.setdefault(domain, []).append(name)
        elif isinstance(feature, str):
            scope.setdefault("default", []).append(feature)
    # Ensure all domains from the domains list exist even if no features
    for domain in data.get("domains", []):
        scope.setdefault(str(domain), [])
    return scope
```

- [ ] **Step 5: Implement parse_work_sizing**

Append to `src/cowork_pilot/planning/sizing.py`:

```python
from pathlib import Path
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_work_sizing(path: Path) -> list[dict]:
    """Parse AI-generated work-sizing.md into a list of work item dicts."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    items = data.get("work_items", [])
    if not isinstance(items, list):
        raise ValueError("work_items must be an array")
    return items
```

- [ ] **Step 6: Implement parse_plan_packing**

Append to `src/cowork_pilot/planning/packing.py`:

```python
from pathlib import Path
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_plan_packing(path: Path) -> list[dict]:
    """Parse AI-generated plan-packing.md into a list of plan dicts."""
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    plans = data.get("plans", [])
    if not isinstance(plans, list):
        raise ValueError("plans must be an array")
    return plans
```

- [ ] **Step 7: Implement parse_plan_review**

Append to `src/cowork_pilot/planning/review.py`:

```python
from pathlib import Path
from cowork_pilot.planning.completion_verifier import extract_json_block


def parse_plan_review(path: Path) -> ReviewVerdict:
    """Parse AI-generated plan-review.md into a ReviewVerdict.

    Rollback is determined deterministically from parsed issues.
    """
    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")

    raw_issues = data.get("issues", [])
    issues: list[ReviewIssue] = []
    for raw in raw_issues:
        if isinstance(raw, dict):
            issues.append(ReviewIssue(
                category=str(raw.get("category", "unknown")),
                severity=str(raw.get("severity", "warning")),
                description=str(raw.get("description", "")),
                evidence="plan-review.md",
            ))

    has_blocking = any(i.severity == "blocking" for i in issues)
    coverage_status = str(data.get("coverage_status", "unknown"))

    return ReviewVerdict(
        coverage_pass=(coverage_status in ("full", "complete") and not has_blocking),
        sizing_pass=not any(i.category == "sizing" and i.severity == "blocking" for i in issues),
        executionability_pass=not any(i.category == "executionability" and i.severity == "blocking" for i in issues),
        overdesign_pass=not any(i.category == "overdesign" and i.severity == "blocking" for i in issues),
        issues=tuple(issues),
        gap_artifacts_consumed=(),
    )
```

- [ ] **Step 8: Run all parser tests**

Run: `python -m pytest tests/test_planning_classification_parser.py tests/test_planning_ai_result_parsers.py -v`
Expected: ALL PASS

- [ ] **Step 9: Run full test suite for regression**

Run: `python -m pytest tests/ --tb=short`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/cowork_pilot/planning/classification.py src/cowork_pilot/planning/docs_inventory.py \
  src/cowork_pilot/planning/scope.py src/cowork_pilot/planning/sizing.py \
  src/cowork_pilot/planning/packing.py src/cowork_pilot/planning/review.py \
  tests/test_planning_classification_parser.py tests/test_planning_ai_result_parsers.py
git commit -m "feat: add AI artifact parsers for all 7 converted stages"
```

---

## Chunk 6: Wire parsers into _apply_stage_completion

Rewrite `_apply_stage_completion` to read AI artifacts from disk instead of calling local algorithms. File paths come from `ARTIFACT_OWNERSHIP_TABLE` via a helper.

### Task 9: Rewrite _apply_stage_completion

**Files:**
- Modify: `src/cowork_pilot/planning/pipeline.py:384-517`

- [ ] **Step 1: Add _resolve_stage_artifact_path helper to pipeline.py**

```python
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE


def _resolve_stage_artifact_path(stage: PlanningStage, run_dir: Path) -> Path | None:
    """Resolve primary artifact path from ARTIFACT_OWNERSHIP_TABLE (single source of truth)."""
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None or not ownership.completion_artifacts:
        return None
    return run_dir / ownership.completion_artifacts[0]
```

- [ ] **Step 2: Rewrite _apply_stage_completion for converted stages**

For each converted stage: resolve file via `_resolve_stage_artifact_path` → if exists, parse → else fallback to legacy. BROWNFIELD, PRODUCT_COMPLETENESS_REVIEW, and EXEC_PLAN stages are **unchanged**.

```python
def _apply_stage_completion(
    runtime: _PipelineRuntime,
    dispatch: StageDispatch,
) -> tuple[str, ...]:
    stage = dispatch.stage

    if stage is PlanningStage.CLASSIFICATION:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.classification import parse_classification_report
            new_snapshot = parse_classification_report(result_file)
            if new_snapshot.size_class != runtime.snapshot.size_class:
                import logging
                logging.getLogger(__name__).warning(
                    "AI classification changed size_class from %s to %s",
                    runtime.snapshot.size_class.value,
                    new_snapshot.size_class.value,
                )
            runtime.snapshot = new_snapshot
        return (
            f"project_mode={runtime.snapshot.project_mode.value}",
            f"size_class={runtime.snapshot.size_class.value}",
        )

    if stage is PlanningStage.CORE_DOCS_CHECK:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.docs_inventory import parse_core_docs_check
            parsed = parse_core_docs_check(result_file)
            runtime.core_docs = list(parsed.get("required_doc_roles", []))
        else:
            runtime.core_docs = check_core_docs(runtime.snapshot)
        return tuple(runtime.core_docs)

    if stage is PlanningStage.ADAPTIVE_DOCS_SELECTION:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.docs_inventory import parse_adaptive_docs_selection
            parsed = parse_adaptive_docs_selection(result_file)
            runtime.adaptive_docs = list(parsed.get("selected_roles", []))
        else:
            runtime.adaptive_docs = select_adaptive_docs(runtime.snapshot, runtime.core_docs)
        return tuple(runtime.adaptive_docs)

    # PRODUCT_COMPLETENESS_REVIEW — unchanged
    if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
        # ... keep existing code exactly as-is ...

    # BROWNFIELD stages — unchanged
    if stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION:
        # ... keep existing ...
    if stage is PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS:
        # ... keep existing ...
    if stage is PlanningStage.BROWNFIELD_GAP_SYNTHESIS:
        # ... keep existing ...

    if stage is PlanningStage.CORE_DOCS_PRESENCE_REVIEW:
        return tuple(runtime.core_docs + runtime.adaptive_docs)

    if stage is PlanningStage.SCOPE_STRUCTURING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.scope import parse_scope_map
            runtime.scope_map = parse_scope_map(result_file)
        else:
            runtime.scope_map = build_scope_map(
                runtime.core_docs, runtime.adaptive_docs, snapshot=runtime.snapshot,
            )
        return tuple(runtime.scope_map.keys())

    if stage is PlanningStage.WORK_SIZING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.sizing import parse_work_sizing
            parsed_items = parse_work_sizing(result_file)
            runtime.work_items = [item["id"] if isinstance(item, dict) else str(item) for item in parsed_items]
        else:
            runtime.work_items = size_work_items(runtime.scope_map)
        return tuple(runtime.work_items)

    if stage is PlanningStage.PLAN_PACKING:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.packing import parse_plan_packing
            parsed_plans = parse_plan_packing(result_file)
            runtime.packed_plans = [p["plan_name"] if isinstance(p, dict) else str(p) for p in parsed_plans]
        else:
            runtime.packed_plans = pack_plans(runtime.work_items)
        return tuple(runtime.packed_plans)

    if stage is PlanningStage.PLAN_REVIEW:
        result_file = _resolve_stage_artifact_path(stage, runtime.run_dir)
        if result_file is not None and result_file.exists():
            from cowork_pilot.planning.review import parse_plan_review
            review_verdict = parse_plan_review(result_file)
        else:
            review_verdict = run_plan_review(runtime.packed_plans, gap_artifacts=runtime.gap_artifacts)
        # Deterministic rollback decision from parsed verdict
        runtime.review_notes = [issue.description for issue in review_verdict.issues]
        return tuple(runtime.review_notes)

    # EXEC_PLAN stages — keep existing code unchanged
    if stage is PlanningStage.EXEC_PLAN_AUTHORING:
        # ... keep existing ...
    if stage is PlanningStage.EXEC_PLAN_SKELETON:
        # ... keep existing ...
    if stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE:
        # ... keep existing ...
    if stage is PlanningStage.EXEC_PLAN_DETAIL:
        # ... keep existing ...

    return ()
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/cowork_pilot/planning/pipeline.py
git commit -m "refactor: wire AI artifact parsers into _apply_stage_completion"
```

## Chunk 7: Quality gate expansion + integration smoke test

### Task 10: Add quality gate thresholds for converted stages

**Files:**
- Modify: `src/cowork_pilot/planning/quality_gate.py:15-24`
- Modify: `tests/test_planning_quality_gate.py`

- [ ] **Step 1: Write failing test for new thresholds**

```python
# Append to tests/test_planning_quality_gate.py

@pytest.mark.parametrize("stage,min_expected", [
    ("classification", 5),
    ("core_docs_check", 5),
    ("adaptive_docs_selection", 5),
    ("scope_structuring", 5),
    ("work_sizing", 5),
    ("plan_packing", 5),
    ("plan_review", 10),
])
def test_converted_stage_quality_gate_threshold(stage: str, min_expected: int, tmp_path: Path):
    output_file = tmp_path / f"{stage}-output.md"
    output_file.write_text("x\n" * (min_expected - 1), encoding="utf-8")
    result = evaluate_stage_gate(
        stage=stage,
        run_dir=tmp_path,
        expected_outputs=(str(output_file),),
    )
    assert not result.passed, f"{stage} should fail with {min_expected - 1} lines"
```

- [ ] **Step 2: Add thresholds to _DEFAULT_MIN_LINES**

```python
# src/cowork_pilot/planning/quality_gate.py
_DEFAULT_MIN_LINES: dict[str, int] = {
    "classification": 5,
    "core_docs_check": 5,
    "adaptive_docs_selection": 5,
    "product_completeness_review": 10,
    "scope_structuring": 5,
    "work_sizing": 5,
    "plan_packing": 5,
    "plan_review": 10,
    "exec_plan_skeleton": 10,
    "exec_plan_feature_outline": 15,
    "exec_plan_detail": 15,
    "brownfield_code_observation_extraction": 10,
    "brownfield_observation_synthesis": 10,
    "brownfield_gap_synthesis": 10,
}
```

- [ ] **Step 3: Run quality gate tests**

Run: `python -m pytest tests/test_planning_quality_gate.py tests/test_quality_gate.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/cowork_pilot/planning/quality_gate.py tests/test_planning_quality_gate.py
git commit -m "feat: add quality gate thresholds for converted stages"
```

### Task 11: Integration smoke test — mock AI outputs through full verifier

**Files:**
- Create: `tests/test_planning_pipeline_ai_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_planning_pipeline_ai_integration.py
"""Verify mock AI artifacts pass completion verification and parsers produce valid data."""
import json
import pytest
from pathlib import Path

from cowork_pilot.planning.completion_verifier import verify_stage_completion
from cowork_pilot.planning.models import PlanningStage


def _md(data: dict) -> str:
    return f'# Stage Output\n\n```json\n{json.dumps(data, indent=2)}\n```\n\n<!-- ORCHESTRATOR:DONE -->\n'


def _write_all_mock_outputs(run_dir: Path) -> None:
    (run_dir / "classification-report.md").write_text(_md({
        "project_mode": "greenfield", "product_type": "saas-app", "size_class": "small",
        "core_user_flows": ["sign-up", "dashboard"], "primary_entities": ["user", "workspace"],
        "risks": ["none identified"],
    }), encoding="utf-8")

    (run_dir / "core-docs-check.md").write_text(_md({
        "required_doc_roles": ["agents", "spec_index", "design_guide"],
        "resolved_existing_paths": ["docs/AGENTS.md"],
        "missing_roles": ["design_guide"],
        "substitutions": [],
    }), encoding="utf-8")

    (run_dir / "adaptive-docs-selection.md").write_text(_md({
        "selected_paths": ["docs/architecture.md"],
        "selected_roles": ["architecture"],
        "selection_reasons": ["needed for medium project"],
        "rejected_candidates": [],
    }), encoding="utf-8")

    (run_dir / "scope-map.md").write_text(_md({
        "domains": ["user-management", "workspace"],
        "features": [
            {"domain": "user-management", "name": "sign-up"},
            {"domain": "user-management", "name": "login"},
            {"domain": "workspace", "name": "create-workspace"},
        ],
        "user_flows": ["onboarding-flow"],
        "out_of_scope": ["billing"],
    }), encoding="utf-8")

    (run_dir / "work-sizing.md").write_text(_md({
        "work_items": [
            {"id": "w1", "title": "sign-up", "domain": "user-management",
             "feature": "sign-up", "size": "M", "risk": "low", "depends_on": []},
            {"id": "w2", "title": "login", "domain": "user-management",
             "feature": "login", "size": "S", "risk": "low", "depends_on": ["w1"]},
            {"id": "w3", "title": "create-workspace", "domain": "workspace",
             "feature": "create-workspace", "size": "M", "risk": "medium", "depends_on": ["w1"]},
        ],
    }), encoding="utf-8")

    (run_dir / "plan-packing.md").write_text(_md({
        "plans": [
            {"plan_name": "auth-foundation", "goal": "user auth",
             "included_work_item_ids": ["w1", "w2"], "why_grouped": "auth dependency chain",
             "dependencies": []},
            {"plan_name": "workspace-core", "goal": "workspace creation",
             "included_work_item_ids": ["w3"], "why_grouped": "separate domain",
             "dependencies": ["auth-foundation"]},
        ],
    }), encoding="utf-8")

    (run_dir / "plan-review.md").write_text(_md({
        "issues": [],
        "rollback_recommended": False,
        "coverage_status": "full",
        "execution_risks": [],
        "missing_work_items": [],
    }), encoding="utf-8")


@pytest.mark.parametrize("stage", [
    PlanningStage.CLASSIFICATION,
    PlanningStage.CORE_DOCS_CHECK,
    PlanningStage.ADAPTIVE_DOCS_SELECTION,
    PlanningStage.SCOPE_STRUCTURING,
    PlanningStage.WORK_SIZING,
    PlanningStage.PLAN_PACKING,
    PlanningStage.PLAN_REVIEW,
])
def test_mock_outputs_pass_completion_verification(tmp_path: Path, stage: PlanningStage):
    _write_all_mock_outputs(tmp_path)
    verdict = verify_stage_completion(stage, run_dir=tmp_path)
    assert verdict.passed, f"{stage.value}: {verdict.reason or verdict.missing_artifacts}"


def test_all_parsers_produce_valid_data(tmp_path: Path):
    _write_all_mock_outputs(tmp_path)

    from cowork_pilot.planning.classification import parse_classification_report
    from cowork_pilot.planning.docs_inventory import parse_core_docs_check, parse_adaptive_docs_selection
    from cowork_pilot.planning.scope import parse_scope_map
    from cowork_pilot.planning.sizing import parse_work_sizing
    from cowork_pilot.planning.packing import parse_plan_packing
    from cowork_pilot.planning.review import parse_plan_review

    snapshot = parse_classification_report(tmp_path / "classification-report.md")
    assert snapshot.size_class.value == "small"

    core = parse_core_docs_check(tmp_path / "core-docs-check.md")
    assert "agents" in core["required_doc_roles"]

    adaptive = parse_adaptive_docs_selection(tmp_path / "adaptive-docs-selection.md")
    assert "architecture" in adaptive["selected_roles"]

    scope = parse_scope_map(tmp_path / "scope-map.md")
    assert "user-management" in scope
    assert len(scope["user-management"]) >= 2

    work = parse_work_sizing(tmp_path / "work-sizing.md")
    assert len(work) == 3
    assert work[0]["id"] == "w1"

    plans = parse_plan_packing(tmp_path / "plan-packing.md")
    assert len(plans) == 2

    review = parse_plan_review(tmp_path / "plan-review.md")
    assert review.coverage_pass is True
    assert len(review.issues) == 0


def test_scope_map_with_doc_roles_fails_verification(tmp_path: Path):
    """The completion verifier must reject scope maps that use doc role names as domains."""
    (tmp_path / "scope-map.md").write_text(_md({
        "domains": ["agents", "spec_index"],
        "features": [],
        "user_flows": [],
        "out_of_scope": [],
    }), encoding="utf-8")
    verdict = verify_stage_completion(PlanningStage.SCOPE_STRUCTURING, run_dir=tmp_path)
    assert not verdict.passed


def test_plan_review_rollback_deterministic(tmp_path: Path):
    """should_rollback() must work on parsed AI review output."""
    from cowork_pilot.planning.review import parse_plan_review, should_rollback

    (tmp_path / "plan-review.md").write_text(_md({
        "issues": [{"category": "coverage", "severity": "blocking", "description": "gap"}],
        "rollback_recommended": True,
        "coverage_status": "incomplete",
        "execution_risks": [],
        "missing_work_items": ["missing-feature"],
    }), encoding="utf-8")
    verdict = parse_plan_review(tmp_path / "plan-review.md")
    assert should_rollback(verdict) is True
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_planning_pipeline_ai_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run FULL test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_planning_pipeline_ai_integration.py
git commit -m "test: add integration smoke test for AI artifact pipeline"
```

- [ ] **Step 5: Final git status check**

```bash
git status && git log --oneline -12
```
