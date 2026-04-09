# Planning Stage-Oriented Session Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default one-shot planning pipeline with stage-oriented Codex session orchestration, explicit input contracts, brownfield change-request normalization, and document-based stage handoff.

**Architecture:** Deterministic planning steps stay in local Python, while AI-heavy stages run in isolated `codex exec` sessions selected by `session_profiles.py`. The pipeline snapshots user inputs into the run directory, normalizes brownfield change requests into a canonical document, writes `stage-handoffs/<nn>-<stage>.md` after each completed AI-heavy stage, and only uses `resume` for blocking questions or approvals inside the current stage. `run-state.json` and handoff documents become the source of truth for restart and continuation.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, json, pytest, existing Codex exec/resume bridge

**Git note:** 사용자 요청에 따라 이 plan은 commit step을 포함하지 않는다.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/cowork_pilot/planning/input_contract.py` | resolve CLI/file input priority, snapshot raw request files into run dir, expose user-mode override metadata |
| Create | `src/cowork_pilot/planning/request_normalization.py` | normalize raw request into structured greenfield brief / brownfield change-request docs, render missing-change-request template |
| Create | `src/cowork_pilot/planning/handoffs.py` | stage handoff dataclasses, write/load handoff docs, build next-stage read set |
| Modify | `src/cowork_pilot/planning/models.py` | extend `PlanningContext` / `PlanningPipelineResult` with input and runtime continuation metadata |
| Modify | `src/cowork_pilot/planning/spec_sources.py` | use explicit mode override only when present, keep auto-detect fallback separate |
| Modify | `src/cowork_pilot/planning/classification.py` | consume explicit mode override, normalized input metadata, and clarified brownfield gating |
| Modify | `src/cowork_pilot/planning/prompts.py` | render stage prompt from read set + handoff + marker instructions instead of minimal placeholder string |
| Modify | `src/cowork_pilot/planning/session_profiles.py` | expose AI-heavy/local stage classification helpers and dispatch metadata |
| Modify | `src/cowork_pilot/planning/stage_executor.py` | execute a single AI-heavy stage, persist handoff docs, keep resume intra-stage only |
| Modify | `src/cowork_pilot/planning/pipeline.py` | orchestrate deterministic vs AI-heavy stages, stop on waiting states, continue after resume, use handoff docs between stages |
| Modify | `src/cowork_pilot/planning/runner.py` | run/start/resume entrypoints over the new stage graph |
| Modify | `src/cowork_pilot/main.py` | accept planning input flags and pass them into the planning runner |
| Modify | `src/cowork_pilot/codex/main.py` | accept planning input flags and pass them into the planning runner |
| Create | `tests/test_planning_input_contract.py` | input priority, snapshot, and explicit-mode tests |
| Create | `tests/test_planning_request_normalization.py` | raw request normalization and brownfield template generation tests |
| Create | `tests/test_planning_handoffs.py` | handoff write/load/read-set tests |
| Modify | `tests/test_planning_classification.py` | explicit mode override vs auto-detect fallback tests |
| Modify | `tests/test_planning_stage_executor.py` | stage handoff persistence and intra-stage resume tests |
| Modify | `tests/test_planning_runner.py` | multi-stage orchestration, waiting states, resume continuation, final exec-plan path tests |
| Modify | `tests/test_main_cli.py` | `--project-mode`, `--request`, `--request-file`, `--change-request`, `--change-request-file` parser tests |
| Modify | `tests/test_codex_main.py` | Codex planning subcommand input contract tests |

---

## Delivery Gates

- `planning` surface must no longer run the whole AI-heavy flow in one logical session.
- `resume` must only be used for `waiting_for_input` and `waiting_for_approval` inside the current stage.
- `brownfield` without a change request must create `docs/planning/change-request.md`, snapshot it, and stop in `waiting_for_input`.
- `run-state.json` plus `stage-handoffs/<nn>-<stage>.md` must be sufficient to continue execution after a stop.
- stage prompts must be built from explicit read sets: input snapshot, canonical docs, previous handoff, and required runtime logs.
- final exec plan must still land at `docs/exec-plans/planning/exec-plan.md`.

---

## Task 1: Input Contract and Planning Context Surface

**Files:**
- Create: `src/cowork_pilot/planning/input_contract.py`
- Modify: `src/cowork_pilot/planning/models.py`
- Modify: `src/cowork_pilot/planning/spec_sources.py`
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/codex/main.py`
- Create: `tests/test_planning_input_contract.py`
- Modify: `tests/test_planning_classification.py`
- Modify: `tests/test_main_cli.py`
- Modify: `tests/test_codex_main.py`

- [ ] **Step 1: Add failing tests for CLI/file priority and explicit mode override**

```python
from pathlib import Path

from cowork_pilot.planning.input_contract import resolve_planning_input_bundle
from cowork_pilot.planning.models import ProjectMode


def test_input_bundle_prefers_cli_request_over_file(tmp_path: Path):
    request_file = tmp_path / "docs" / "planning" / "request.md"
    request_file.parent.mkdir(parents=True)
    request_file.write_text("file request", encoding="utf-8")

    bundle = resolve_planning_input_bundle(
        project_dir=tmp_path,
        project_mode_arg="greenfield",
        request_arg="cli request",
        request_file_arg="",
        change_request_arg="",
        change_request_file_arg="",
    )

    assert bundle.project_mode is ProjectMode.GREENFIELD
    assert bundle.request_text == "cli request"
    assert bundle.request_source == "cli"


def test_input_bundle_uses_request_file_when_cli_request_missing(tmp_path: Path):
    request_file = tmp_path / "incoming.md"
    request_file.write_text("file request", encoding="utf-8")

    bundle = resolve_planning_input_bundle(
        project_dir=tmp_path,
        project_mode_arg="greenfield",
        request_arg="",
        request_file_arg=str(request_file),
        change_request_arg="",
        change_request_file_arg="",
    )

    assert bundle.request_text == "file request"
    assert bundle.request_source == str(request_file)


def test_classification_uses_explicit_mode_over_auto_detect(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    bundle = resolve_planning_input_bundle(
        project_dir=tmp_path,
        project_mode_arg="greenfield",
        request_arg="build a new product spec",
        request_file_arg="",
        change_request_arg="",
        change_request_file_arg="",
    )

    assert bundle.project_mode is ProjectMode.GREENFIELD
    assert bundle.explicit_mode is True
```

- [ ] **Step 2: Run the new input-surface tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_input_contract.py tests/test_main_cli.py tests/test_codex_main.py tests/test_planning_classification.py -q`

Expected:
- import failure for `planning.input_contract`
- planning CLI missing input flags
- classification still treating `context.mode` as an unconditional override path

- [ ] **Step 3: Implement input bundle resolution and snapshot metadata**

```python
# src/cowork_pilot/planning/input_contract.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.spec_sources import discover_planning_inputs


@dataclass(frozen=True)
class PlanningInputBundle:
    project_mode: ProjectMode
    explicit_mode: bool
    request_text: str
    request_source: str
    change_request_text: str
    change_request_source: str


def resolve_planning_input_bundle(
    *,
    project_dir: Path,
    project_mode_arg: str,
    request_arg: str,
    request_file_arg: str,
    change_request_arg: str,
    change_request_file_arg: str,
) -> PlanningInputBundle:
    discovered = discover_planning_inputs(project_dir)
    explicit_mode = bool(project_mode_arg)
    project_mode = ProjectMode(project_mode_arg) if explicit_mode else discovered.project_mode

    request_text, request_source = _resolve_text_input(
        direct_text=request_arg,
        direct_path=request_file_arg,
        fallback_path=project_dir / "docs" / "planning" / "request.md",
    )
    change_request_text, change_request_source = _resolve_text_input(
        direct_text=change_request_arg,
        direct_path=change_request_file_arg,
        fallback_path=project_dir / "docs" / "planning" / "change-request.md",
    )
    return PlanningInputBundle(
        project_mode=project_mode,
        explicit_mode=explicit_mode,
        request_text=request_text,
        request_source=request_source,
        change_request_text=change_request_text,
        change_request_source=change_request_source,
    )
```

```python
# src/cowork_pilot/planning/models.py
@dataclass(frozen=True)
class PlanningContext:
    run_dir: Path | None = None
    project_dir: Path | None = None
    target_version: str = ""
    mode: ProjectMode | None = None
    explicit_mode: bool = False
    request_source: str = ""
    change_request_source: str = ""
```

- [ ] **Step 4: Add the planning CLI flags and re-run tests**

```python
# src/cowork_pilot/main.py
parser.add_argument("--project-mode", choices=["greenfield", "brownfield"], default="")
parser.add_argument("--request", type=str, default="")
parser.add_argument("--request-file", type=str, default="")
parser.add_argument("--change-request", type=str, default="")
parser.add_argument("--change-request-file", type=str, default="")
```

```python
# src/cowork_pilot/codex/main.py
planning_parser.add_argument("--project-mode", choices=["greenfield", "brownfield"], default="")
planning_parser.add_argument("--request", type=str, default="")
planning_parser.add_argument("--request-file", type=str, default="")
planning_parser.add_argument("--change-request", type=str, default="")
planning_parser.add_argument("--change-request-file", type=str, default="")
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_input_contract.py tests/test_main_cli.py tests/test_codex_main.py tests/test_planning_classification.py -q`

Expected:
- all input-surface tests PASS

---

## Task 2: Request Normalization and Brownfield Change-Request Gating

**Files:**
- Create: `src/cowork_pilot/planning/request_normalization.py`
- Modify: `src/cowork_pilot/planning/storage.py`
- Modify: `src/cowork_pilot/planning/classification.py`
- Create: `tests/test_planning_request_normalization.py`
- Modify: `tests/test_planning_runner.py`

- [ ] **Step 1: Add failing tests for request normalization and missing brownfield template generation**

```python
from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.request_normalization import normalize_planning_request


def test_greenfield_request_is_normalized_into_run_snapshot(tmp_path: Path):
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.GREENFIELD,
        raw_request_text="관리자용 대시보드와 사용자용 페이지를 기획한다",
        raw_change_request_text="",
    )

    assert result.waiting_for_change_request is False
    assert result.request_snapshot_path == tmp_path / "inputs" / "request.md"
    assert result.normalized_request_path == tmp_path / "inputs" / "normalized-request.md"


def test_brownfield_without_change_request_writes_template_and_stops(tmp_path: Path):
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.BROWNFIELD,
        raw_request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
        raw_change_request_text="",
    )

    assert result.waiting_for_change_request is True
    assert result.change_request_path == tmp_path / "inputs" / "change-request.md"
    assert "변경 목표" in result.change_request_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run normalization tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_request_normalization.py tests/test_planning_runner.py -q`

Expected:
- import failure for `planning.request_normalization`
- runner missing brownfield stop-on-template behavior

- [ ] **Step 3: Implement request normalization and template rendering**

```python
# src/cowork_pilot/planning/request_normalization.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.storage import write_intermediate_doc


@dataclass(frozen=True)
class NormalizedPlanningRequest:
    request_snapshot_path: Path
    normalized_request_path: Path
    change_request_path: Path | None
    waiting_for_change_request: bool


def normalize_planning_request(
    *,
    run_dir: Path,
    project_mode: ProjectMode,
    raw_request_text: str,
    raw_change_request_text: str,
) -> NormalizedPlanningRequest:
    request_snapshot_path = write_intermediate_doc(run_dir, "inputs/request.md", raw_request_text.strip() + "\n")
    normalized_request_path = write_intermediate_doc(
        run_dir,
        "inputs/normalized-request.md",
        _render_normalized_request(raw_request_text),
    )

    if project_mode is ProjectMode.BROWNFIELD and not raw_change_request_text.strip():
        change_request_path = write_intermediate_doc(
            run_dir,
            "inputs/change-request.md",
            _render_change_request_template(raw_request_text),
        )
        return NormalizedPlanningRequest(
            request_snapshot_path=request_snapshot_path,
            normalized_request_path=normalized_request_path,
            change_request_path=change_request_path,
            waiting_for_change_request=True,
        )

    if project_mode is ProjectMode.BROWNFIELD:
        change_request_path = write_intermediate_doc(
            run_dir,
            "inputs/change-request.md",
            _render_structured_change_request(raw_request_text, raw_change_request_text),
        )
    else:
        change_request_path = None
    return NormalizedPlanningRequest(
        request_snapshot_path=request_snapshot_path,
        normalized_request_path=normalized_request_path,
        change_request_path=change_request_path,
        waiting_for_change_request=False,
    )
```

- [ ] **Step 4: Make brownfield gating explicit in runner-facing tests**

```python
# tests/test_planning_runner.py
def test_brownfield_missing_change_request_stops_before_any_ai_stage(tmp_path):
    result = run_planning_pipeline(
        PlanningContext(
            run_dir=tmp_path / "run",
            project_dir=tmp_path / "project",
            mode=ProjectMode.BROWNFIELD,
        )
    )

    assert result.runtime_state == "waiting_for_input"
    assert (tmp_path / "run" / "inputs" / "change-request.md").exists()
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_request_normalization.py tests/test_planning_runner.py -q`

Expected:
- normalization and brownfield template tests PASS

---

## Task 3: Stage Handoff Documents and Prompt Read Sets

**Files:**
- Create: `src/cowork_pilot/planning/handoffs.py`
- Modify: `src/cowork_pilot/planning/prompts.py`
- Modify: `src/cowork_pilot/planning/models.py`
- Create: `tests/test_planning_handoffs.py`
- Modify: `tests/test_planning_stage_executor.py`

- [ ] **Step 1: Add failing tests for handoff writing and next-stage read sets**

```python
from pathlib import Path

from cowork_pilot.planning.handoffs import build_stage_read_set, write_stage_handoff
from cowork_pilot.planning.models import PlanningStage


def test_write_stage_handoff_creates_numbered_markdown(tmp_path: Path):
    handoff_path = write_stage_handoff(
        run_dir=tmp_path,
        order=2,
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        decisions=("redirect는 dashboard로 둔다",),
        unresolved_questions=(),
        assumptions=("기본 권한 모델은 관리자/멤버 2종",),
        outputs=("product-completeness-review.md", "coverage-gap.md"),
        next_read_set=("inputs/normalized-request.md", "coverage-gap.md"),
    )

    assert handoff_path == tmp_path / "stage-handoffs" / "02-product_completeness_review.md"
    assert "redirect는 dashboard로 둔다" in handoff_path.read_text(encoding="utf-8")


def test_build_stage_read_set_prefers_previous_handoff_and_inputs(tmp_path: Path):
    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "inputs" / "normalized-request.md").write_text("normalized", encoding="utf-8")
    (tmp_path / "stage-handoffs").mkdir()
    (tmp_path / "stage-handoffs" / "02-product_completeness_review.md").write_text("handoff", encoding="utf-8")

    read_set = build_stage_read_set(
        run_dir=tmp_path,
        canonical_docs=(Path("docs/specs/index.md"),),
        previous_handoff=(tmp_path / "stage-handoffs" / "02-product_completeness_review.md"),
        required_runtime_logs=("assumptions.md",),
    )

    assert read_set[0] == tmp_path / "inputs" / "normalized-request.md"
    assert read_set[1].name == "02-product_completeness_review.md"
```

- [ ] **Step 2: Run handoff/prompt tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_handoffs.py tests/test_planning_stage_executor.py -q`

Expected:
- import failure for `planning.handoffs`
- prompt renderer still too small to express read-set-driven stage prompts

- [ ] **Step 3: Implement handoff writer and read-set resolver**

```python
# src/cowork_pilot/planning/handoffs.py
from __future__ import annotations

from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.storage import write_intermediate_doc


def write_stage_handoff(
    *,
    run_dir: Path,
    order: int,
    stage: PlanningStage,
    decisions: tuple[str, ...],
    unresolved_questions: tuple[str, ...],
    assumptions: tuple[str, ...],
    outputs: tuple[str, ...],
    next_read_set: tuple[str, ...],
) -> Path:
    filename = f"stage-handoffs/{order:02d}-{stage.value}.md"
    body = _render_handoff_body(stage, decisions, unresolved_questions, assumptions, outputs, next_read_set)
    return write_intermediate_doc(run_dir, filename, body)


def build_stage_read_set(
    *,
    run_dir: Path,
    canonical_docs: tuple[Path, ...],
    previous_handoff: Path | None,
    required_runtime_logs: tuple[str, ...],
) -> tuple[Path, ...]:
    paths: list[Path] = [run_dir / "inputs" / "normalized-request.md"]
    if (run_dir / "inputs" / "change-request.md").exists():
        paths.append(run_dir / "inputs" / "change-request.md")
    if previous_handoff is not None:
        paths.append(previous_handoff)
    paths.extend(canonical_docs)
    for relative_path in required_runtime_logs:
        candidate = run_dir / relative_path
        if candidate.exists():
            paths.append(candidate)
    return tuple(paths)
```

- [ ] **Step 4: Make prompt rendering consume read sets**

```python
# src/cowork_pilot/planning/prompts.py
def render_stage_prompt(
    stage: PlanningStage,
    *,
    read_set: tuple[Path, ...],
    handoff_summary: str,
    target_version: str,
) -> str:
    read_lines = "\n".join(f"- {path}" for path in read_set)
    return (
        f"stage={stage.value}\n"
        f"target_version={target_version}\n"
        "Read these files before acting:\n"
        f"{read_lines}\n\n"
        "Carry forward only the recorded decisions and assumptions.\n"
        f"Handoff summary:\n{handoff_summary}\n\n"
        "Emit a final COWORK_PILOT_EVENT bundle when the stage needs input, approval, assumption logging, completion, or human escalation."
    )
```

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_handoffs.py tests/test_planning_stage_executor.py -q`

Expected:
- handoff and prompt tests PASS

---

## Task 4: Session-Profile-Driven Stage Graph

**Files:**
- Modify: `src/cowork_pilot/planning/session_profiles.py`
- Modify: `src/cowork_pilot/planning/pipeline.py`
- Modify: `src/cowork_pilot/planning/models.py`
- Modify: `tests/test_planning_runner.py`
- Modify: `tests/test_planning_pipeline_units.py`

- [ ] **Step 1: Add failing tests for deterministic vs AI-heavy dispatch and brownfield substage expansion**

```python
from cowork_pilot.planning.models import PlanningContext, PlanningStage, ProjectMode, SizeClass
from cowork_pilot.planning.pipeline import build_stage_dispatch_plan


def test_stage_dispatch_plan_keeps_sizing_and_packing_local(tmp_path):
    dispatches = build_stage_dispatch_plan(
        PlanningContext(run_dir=tmp_path, project_dir=tmp_path, mode=ProjectMode.GREENFIELD),
        size_class=SizeClass.SMALL,
    )

    work_sizing = next(item for item in dispatches if item.stage is PlanningStage.WORK_SIZING)
    plan_packing = next(item for item in dispatches if item.stage is PlanningStage.PLAN_PACKING)
    assert work_sizing.execution_kind == "local"
    assert plan_packing.execution_kind == "local"


def test_brownfield_large_dispatch_expands_extraction_slices(tmp_path):
    dispatches = build_stage_dispatch_plan(
        PlanningContext(run_dir=tmp_path, project_dir=tmp_path, mode=ProjectMode.BROWNFIELD),
        size_class=SizeClass.LARGE,
    )

    extraction = [item for item in dispatches if item.stage is PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION]
    assert len(extraction) >= 3
    assert all(item.execution_kind == "ai" for item in extraction)
```

- [ ] **Step 2: Run stage-graph tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_planning_pipeline_units.py -q`

Expected:
- `build_stage_dispatch_plan` missing
- session profiles not exposed as actual dispatch metadata

- [ ] **Step 3: Implement explicit stage dispatch planning**

```python
# src/cowork_pilot/planning/pipeline.py
@dataclass(frozen=True)
class StageDispatch:
    stage: PlanningStage
    execution_kind: str  # "local" | "ai"
    order: int
    substage: str = ""
    slice_name: str = ""


def build_stage_dispatch_plan(
    context: PlanningContext,
    *,
    size_class: SizeClass,
) -> tuple[StageDispatch, ...]:
    dispatches: list[StageDispatch] = []
    dispatches.append(StageDispatch(PlanningStage.CLASSIFICATION, "local", 1))
    dispatches.append(StageDispatch(PlanningStage.CORE_DOCS_CHECK, "local", 2))
    dispatches.append(StageDispatch(PlanningStage.ADAPTIVE_DOCS_SELECTION, "local", 3))
    if context.mode is ProjectMode.BROWNFIELD:
        dispatches.extend(_brownfield_dispatches(size_class=size_class, start_order=4))
    else:
        dispatches.append(StageDispatch(PlanningStage.PRODUCT_COMPLETENESS_REVIEW, "ai", 4))
    dispatches.append(StageDispatch(PlanningStage.SCOPE_STRUCTURING, "ai", 20))
    dispatches.append(StageDispatch(PlanningStage.WORK_SIZING, "local", 21))
    dispatches.append(StageDispatch(PlanningStage.PLAN_PACKING, "local", 22))
    dispatches.append(StageDispatch(PlanningStage.PLAN_REVIEW, "ai", 23))
    dispatches.append(StageDispatch(PlanningStage.EXEC_PLAN_AUTHORING, "ai", 24))
    return tuple(dispatches)
```

- [ ] **Step 4: Re-run dispatch tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_runner.py tests/test_planning_pipeline_units.py -q`

Expected:
- dispatch plan tests PASS

---

## Task 5: Stage Executor Integration, Waiting States, and Resume Continuation

**Files:**
- Modify: `src/cowork_pilot/planning/stage_executor.py`
- Modify: `src/cowork_pilot/planning/pipeline.py`
- Modify: `src/cowork_pilot/planning/runner.py`
- Modify: `src/cowork_pilot/planning/runtime_storage.py`
- Modify: `tests/test_planning_stage_executor.py`
- Modify: `tests/test_planning_runner.py`

- [ ] **Step 1: Add failing tests for stage boundary session resets and resume staying inside one stage**

```python
from cowork_pilot.planning.models import PlanningContext, ProjectMode
from cowork_pilot.planning.runner import resume_planning_pipeline_with_user_response, run_planning_pipeline


def test_blocking_question_resumes_same_stage_then_moves_to_next_stage(tmp_path, monkeypatch):
    events = []

    def fake_exec(stage: str, prompt: str, run_dir: str):
        events.append(("exec", stage))
        if stage == "product_completeness_review":
            return type(
                "ExecResult",
                (),
                {
                    "event_lines": ['{"type":"thread.started","thread_id":"thread-completeness"}'],
                    "assistant_message": """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing_redirect
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
""",
                    "exit_code": 0,
                },
            )()
        return type(
            "ExecResult",
            (),
            {
                "event_lines": ['{"type":"thread.started","thread_id":"thread-scope"}'],
                "assistant_message": """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: scope_structuring
event_id: ss-1
reason: complete
summary: done
outputs:
  - scope-map.md
</COWORK_PILOT_EVENT>
""",
                "exit_code": 0,
            },
        )()

    monkeypatch.setattr("cowork_pilot.planning.stage_executor.run_exec_stage", fake_exec)

    result = run_planning_pipeline(
        PlanningContext(run_dir=tmp_path / "run", project_dir=tmp_path, mode=ProjectMode.GREENFIELD)
    )
    assert result.runtime_state == "waiting_for_input"

    resumed = resume_planning_pipeline_with_user_response(
        run_dir=tmp_path / "run",
        response_text="dashboard",
        response_kind="answer",
    )

    assert resumed.runtime_state == "completed"
    assert events[:2] == [
        ("exec", "product_completeness_review"),
        ("exec", "scope_structuring"),
    ]
```

- [ ] **Step 2: Run orchestration tests and confirm failure**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_stage_executor.py tests/test_planning_runner.py -q`

Expected:
- resume helper missing
- pipeline not stopping at waiting states or continuing from saved stage order

- [ ] **Step 3: Integrate stage executor with handoffs and saved continuation state**

```python
# src/cowork_pilot/planning/runner.py
def run_planning_pipeline(context: PlanningContext | None = None) -> PlanningPipelineResult:
    return run_planning_stage_graph(context)


def resume_planning_pipeline_with_user_response(
    *,
    run_dir: Path,
    response_text: str,
    response_kind: str,
) -> PlanningPipelineResult:
    resumed_stage = resume_stage_subsession(
        run_dir=run_dir,
        response_text=response_text,
        response_kind=response_kind,
    )
    if resumed_stage.runtime_state in {"waiting_for_input", "waiting_for_approval", "waiting_for_human", "failed", "escalated"}:
        return load_pipeline_result_from_run_dir(run_dir)
    return continue_planning_stage_graph(run_dir=run_dir)
```

```python
# src/cowork_pilot/planning/pipeline.py
def run_planning_stage_graph(context: PlanningContext | None = None) -> PlanningPipelineResult:
    ...
    for dispatch in dispatches:
        if dispatch.execution_kind == "local":
            _run_local_stage(...)
            continue
        stage_result = execute_stage_subsession(...)
        write_stage_handoff(...)
        if stage_result.runtime_state in {"waiting_for_input", "waiting_for_approval", "waiting_for_human", "failed", "escalated"}:
            return _build_pipeline_result(..., runtime_state=stage_result.runtime_state, stopped_stage=dispatch.stage.value)
    return _build_pipeline_result(..., runtime_state="completed", stopped_stage="")
```

- [ ] **Step 4: Re-run orchestration tests**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_stage_executor.py tests/test_planning_runner.py -q`

Expected:
- stage boundary and resume tests PASS

---

## Task 6: Planning Surface Integration and End-to-End Verification

**Files:**
- Modify: `src/cowork_pilot/main.py`
- Modify: `src/cowork_pilot/codex/main.py`
- Modify: `tests/test_main_cli.py`
- Modify: `tests/test_codex_main.py`
- Modify: `tests/test_planning_runner.py`
- Modify: `tests/test_planning_stage_executor.py`

- [ ] **Step 1: Add end-to-end tests for the supported user workflows**

```python
def test_greenfield_cli_request_generates_exec_plan_and_handoffs(tmp_path):
    ...
    assert (run_dir / "stage-handoffs").exists()
    assert (project_dir / "docs" / "exec-plans" / "planning" / "exec-plan.md").exists()


def test_brownfield_cli_change_request_skips_template_wait(tmp_path):
    ...
    assert result.runtime_state == "completed"
    assert not (run_dir / "inputs" / "change-request.md").read_text(encoding="utf-8").startswith("# Fill")


def test_brownfield_missing_change_request_creates_template_and_waits(tmp_path):
    ...
    assert result.runtime_state == "waiting_for_input"
    assert "승인 기준" in (run_dir / "inputs" / "change-request.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the planning verification suite**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_input_contract.py tests/test_planning_request_normalization.py tests/test_planning_handoffs.py tests/test_planning_classification.py tests/test_planning_stage_executor.py tests/test_planning_pipeline_units.py tests/test_planning_runner.py tests/test_main_cli.py tests/test_codex_main.py -q`

Expected:
- all stage-orchestration tests PASS

- [ ] **Step 3: Run the broader planning/runtime regression batch**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_marker_protocol.py tests/test_planning_session_profiles.py tests/test_planning_runtime_state.py tests/test_planning_codex_bridge.py tests/test_planning_runtime_orchestrator.py tests/test_planning_greenfield.py tests/test_planning_brownfield.py tests/test_planning_question_policy.py tests/test_planning_stage_executor.py tests/test_planning_pipeline_units.py tests/test_planning_classification.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py tests/test_planning_runner.py tests/test_main_cli.py tests/test_codex_main.py tests/test_codex_harness.py tests/test_config.py -q`

Expected:
- planning/runtime regression batch PASS

- [ ] **Step 4: Run full project regression**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest -q`

Expected:
- full repository test suite PASS

---

## Spec Coverage Review

- `mode exposed to user`
  - Task 1 CLI flags and explicit-mode resolution
- `CLI > file priority`
  - Task 1 input bundle tests and resolver
- `brownfield change request normalization`
  - Task 2 normalization module and gating tests
- `missing brownfield change request -> template + waiting_for_input`
  - Task 2 and Task 6 end-to-end tests
- `documents carry context across stage sessions`
  - Task 3 handoff writer and read-set builder
- `AI-heavy stage only gets new session`
  - Task 4 dispatch planning
- `resume only inside current stage`
  - Task 5 stage-boundary orchestration tests
- `final exec-plan path preserved`
  - Task 6 end-to-end verification

## Anti-Scaffolding Review

- `input_contract.py` is not done until explicit mode and auto-detect are represented separately; a single `mode` field that hides whether the user specified it is insufficient.
- `request_normalization.py` is not done until it writes both request snapshot files and brownfield template files under the run directory; returning strings only is insufficient.
- `handoffs.py` is not done until next-stage read sets are explicit ordered paths, not free-form summary text.
- `pipeline.py` is not done until it can stop on waiting states and continue from saved state without rerunning completed stages.
- `stage_executor.py` is not done until handoff persistence happens on stage completion and `resume` remains intra-stage only.

## Self-Review

- Placeholder scan:
  - no `TODO`, `TBD`, or “implement later” placeholders remain
  - each task has explicit file paths, commands, and concrete function names
- Spec coverage:
  - stage-oriented sessions, brownfield input gating, handoff docs, and explicit mode exposure all map to at least one task
- Type consistency:
  - `PlanningInputBundle`, `NormalizedPlanningRequest`, `StageDispatch`, and `resume_planning_pipeline_with_user_response()` are introduced before later tasks depend on them

