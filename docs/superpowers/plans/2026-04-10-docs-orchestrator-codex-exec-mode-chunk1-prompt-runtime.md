# Docs-Orchestrator Codex Exec Mode — Chunk 1 & 2: Prompt System + Runtime Sidecar

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex용 prompt wrapper 시스템과 runtime sidecar 파일 관리 모듈을 추가한다.

**Architecture:** 기존 Jinja2 env를 그대로 사용해 `codex_wrapper.j2`가 base phase template을 include하고 `_includes/codex_runtime_contract.j2`를 덧붙인다. Runtime sidecar는 atomic write(temp+rename)로 `orchestrator-runtime.json`을 관리하며 phase progression state와 독립적으로 유지된다.

**Tech Stack:** Python 3.11+, Jinja2 (기존 `Environment + FileSystemLoader`), `os.replace` atomic write

**Spec:** `docs/superpowers/plans/2026-04-10-docs-orchestrator-codex-exec-mode-design.md` §5.1, §5.2, §7, §8

---

## Chunk 1: Prompt System

**Files:**
- Modify: `src/cowork_pilot/orchestrator_prompts.py`
- Create: `src/cowork_pilot/orchestrator_templates/_includes/codex_runtime_contract.j2`
- Create: `src/cowork_pilot/orchestrator_templates/codex_wrapper.j2`
- Test: `tests/test_orchestrator_prompts.py`

### Task 1-1: `get_phase_template_name()` 추가

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_orchestrator_prompts.py`에 추가:

```python
from cowork_pilot.orchestrator_prompts import get_phase_template_name

def test_get_phase_template_name_known():
    assert get_phase_template_name("phase1_single") == "phase1_single.j2"
    assert get_phase_template_name("phase2_manual") == "phase2_manual.j2"

def test_get_phase_template_name_unknown():
    import pytest
    with pytest.raises(ValueError, match="Unknown phase"):
        get_phase_template_name("phase99_bogus")
```

- [ ] **Step 2: 실패 확인**

```bash
cd /path/to/cowork-pilot && python -m pytest tests/test_orchestrator_prompts.py::test_get_phase_template_name_known tests/test_orchestrator_prompts.py::test_get_phase_template_name_unknown -v
```

Expected: `FAILED` (ImportError or AttributeError)

- [ ] **Step 3: `orchestrator_prompts.py`에 함수 추가**

기존 `build_session_prompt()` 아래에:

```python
def get_phase_template_name(phase: str) -> str:
    """Return the .j2 filename for *phase*.

    Raises ValueError if *phase* is not in the map.
    """
    template_name = _PHASE_TEMPLATE_MAP.get(phase)
    if template_name is None:
        raise ValueError(
            f"Unknown phase {phase!r}. "
            f"Valid phases: {sorted(_PHASE_TEMPLATE_MAP)}"
        )
    return template_name
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_orchestrator_prompts.py::test_get_phase_template_name_known tests/test_orchestrator_prompts.py::test_get_phase_template_name_unknown -v
```

Expected: `PASSED`

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/orchestrator_prompts.py tests/test_orchestrator_prompts.py
git commit -m "feat(orchestrator-prompts): add get_phase_template_name()"
```

---

### Task 1-2: `codex_runtime_contract.j2` 생성

이 파일은 Codex 세션의 marker protocol 계약을 담는다. 순수 텍스트이므로 테스트는 렌더링으로 검증한다.

- [ ] **Step 1: `_includes/` 디렉토리와 파일 생성**

`src/cowork_pilot/orchestrator_templates/_includes/codex_runtime_contract.j2`:

```jinja2
---
## Codex Runtime Contract

You are running inside a non-interactive `codex exec` session managed by docs-orchestrator.

### Output rules (follow the base prompt above for file paths and content)

All file output rules from the base prompt above remain in effect.

### Interaction rules

This session has no interactive tool access. Instead, use marker bundles:

- If you need information from the user → emit `INPUT_REQUIRED`
- If you need approval for a decision → emit `APPROVAL_REQUIRED`
- If you cannot proceed without human intervention → emit `NEEDS_HUMAN`
- If you made a reasonable assumption to continue → emit `ASSUMPTION_LOG` then continue
- On successful completion → emit `STAGE_COMPLETE` (after all output files are written)

**If the base prompt above says "AskUserQuestion" or asks you to confirm with the user or request approval, do NOT call any tool. Instead emit the appropriate marker bundle (`INPUT_REQUIRED` or `APPROVAL_REQUIRED`) at the end of your message.**

### Marker bundle format

Each marker is a JSON object wrapped in `<COWORK_PILOT_EVENT>` tags.
Emit all markers as the final contiguous block at the end of your message.

```json
<COWORK_PILOT_EVENT>
{
  "type": "INPUT_REQUIRED",
  "stage": "<current step name>",
  "event_id": "<step_name>_q<N>",
  "reason": "<why you need this information>",
  "payload": {
    "question": "<question text>",
    "options": ["option1", "option2"],
    "recommended": "option1",
    "blocking": true
  }
}
</COWORK_PILOT_EVENT>
```

For `APPROVAL_REQUIRED`:

```json
<COWORK_PILOT_EVENT>
{
  "type": "APPROVAL_REQUIRED",
  "stage": "<current step name>",
  "event_id": "<step_name>_a<N>",
  "reason": "<why approval is needed>",
  "payload": {
    "subject": "<decision subject>",
    "proposed_decision": "<what you propose to do>",
    "blocking": true
  }
}
</COWORK_PILOT_EVENT>
```

For `STAGE_COMPLETE` (emit ONLY after all output files end with `<!-- ORCHESTRATOR:DONE -->`):

```json
<COWORK_PILOT_EVENT>
{
  "type": "STAGE_COMPLETE",
  "stage": "<current step name>",
  "event_id": "<step_name>_done",
  "reason": "All outputs written successfully",
  "payload": {
    "summary": "<one-line summary of what was done>",
    "outputs": ["<relative path1>", "<relative path2>"]
  }
}
</COWORK_PILOT_EVENT>
```

### Completion requirement

A step is complete ONLY when ALL of the following are true:
1. Every expected output file exists and ends with `<!-- ORCHESTRATOR:DONE -->`
2. `STAGE_COMPLETE` marker bundle is emitted as the final block of your message

Do not emit `STAGE_COMPLETE` until both conditions are met.
```

- [ ] **Step 2: 파일이 존재하는지 확인**

```bash
ls src/cowork_pilot/orchestrator_templates/_includes/codex_runtime_contract.j2
```

- [ ] **Step 3: 커밋**

```bash
git add src/cowork_pilot/orchestrator_templates/_includes/
git commit -m "feat(templates): add codex_runtime_contract.j2 include"
```

---

### Task 1-3: `codex_wrapper.j2` 생성

- [ ] **Step 1: 파일 생성**

`src/cowork_pilot/orchestrator_templates/codex_wrapper.j2`:

```jinja2
{% include base_template_name %}

{% include "_includes/codex_runtime_contract.j2" %}
```

참고: Jinja2 `FileSystemLoader`에서 `{% include variable %}` 문법은 변수가 템플릿 이름 문자열일 때 그대로 동작한다.

- [ ] **Step 2: 커밋**

```bash
git add src/cowork_pilot/orchestrator_templates/codex_wrapper.j2
git commit -m "feat(templates): add codex_wrapper.j2 Codex prompt wrapper"
```

---

### Task 1-4: `build_codex_session_prompt()` 추가 + 테스트

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_orchestrator_prompts.py`에 추가:

```python
from cowork_pilot.orchestrator_prompts import build_codex_session_prompt

def test_build_codex_session_prompt_contains_base(tmp_path):
    """Codex prompt must include base template content."""
    # Minimal fake templates
    inc_dir = tmp_path / "_includes"
    inc_dir.mkdir()
    (tmp_path / "phase1_single.j2").write_text("BASE_CONTENT {{ project_dir }}", encoding="utf-8")
    (inc_dir / "codex_runtime_contract.j2").write_text("CODEX_CONTRACT", encoding="utf-8")
    (tmp_path / "codex_wrapper.j2").write_text(
        "{% include base_template_name %}\n{% include '_includes/codex_runtime_contract.j2' %}",
        encoding="utf-8",
    )

    result = build_codex_session_prompt(
        "phase1_single",
        template_dir=tmp_path,
        project_dir="/proj",
    )
    assert "BASE_CONTENT /proj" in result
    assert "CODEX_CONTRACT" in result


def test_build_codex_session_prompt_unknown_phase():
    import pytest
    with pytest.raises(ValueError, match="Unknown phase"):
        build_codex_session_prompt("phase99_bogus")


def test_build_codex_session_prompt_does_not_modify_base_template(tmp_path):
    """Base template file must be unchanged after rendering."""
    inc_dir = tmp_path / "_includes"
    inc_dir.mkdir()
    base_content = "ORIGINAL {{ project_dir }}"
    base_file = tmp_path / "phase1_single.j2"
    base_file.write_text(base_content, encoding="utf-8")
    (inc_dir / "codex_runtime_contract.j2").write_text("", encoding="utf-8")
    (tmp_path / "codex_wrapper.j2").write_text(
        "{% include base_template_name %}\n{% include '_includes/codex_runtime_contract.j2' %}",
        encoding="utf-8",
    )

    build_codex_session_prompt("phase1_single", template_dir=tmp_path, project_dir="/p")
    assert base_file.read_text(encoding="utf-8") == base_content
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_orchestrator_prompts.py::test_build_codex_session_prompt_contains_base -v
```

Expected: `FAILED` (ImportError)

- [ ] **Step 3: `orchestrator_prompts.py`에 함수 추가**

`get_phase_template_name()` 아래에:

```python
def build_codex_session_prompt(
    phase: str,
    *,
    template_dir: Path | None = None,
    **kwargs: object,
) -> str:
    """Build a Codex-backend session prompt for *phase*.

    Renders ``codex_wrapper.j2`` which includes the canonical base template
    for *phase* followed by ``_includes/codex_runtime_contract.j2``.

    The base template is never modified. The Codex runtime contract is
    appended only through the wrapper.

    Parameters
    ----------
    phase:
        One of the keys in ``_PHASE_TEMPLATE_MAP``.
    template_dir:
        Override the template directory (useful for testing).
    **kwargs:
        Template variables passed to the base template via the wrapper.

    Raises
    ------
    ValueError
        If *phase* is not recognised.
    """
    base_template_name = get_phase_template_name(phase)  # raises ValueError if unknown
    env = _get_jinja_env(template_dir)
    wrapper = env.get_template("codex_wrapper.j2")
    return wrapper.render(base_template_name=base_template_name, **kwargs)
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_orchestrator_prompts.py -k "codex" -v
```

Expected: 3개 모두 `PASSED`

- [ ] **Step 5: 기존 테스트 회귀 확인**

```bash
python -m pytest tests/test_orchestrator_prompts.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 6: 커밋**

```bash
git add src/cowork_pilot/orchestrator_prompts.py tests/test_orchestrator_prompts.py
git commit -m "feat(orchestrator-prompts): add build_codex_session_prompt()"
```

---

## Chunk 2: Runtime Sidecar

**Files:**
- Create: `src/cowork_pilot/docs_orchestrator_runtime.py`
- Test: `tests/test_docs_orchestrator_runtime.py` (신규)

### Task 2-1: `docs_orchestrator_runtime.py` 기본 구조

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_docs_orchestrator_runtime.py` 신규 생성:

```python
"""Unit tests for docs_orchestrator_runtime.py.

All tests use tmp_path — no real filesystem side effects.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cowork_pilot.docs_orchestrator_runtime import (
    RUNTIME_FILENAME,
    clear_runtime,
    load_runtime,
    runtime_is_waiting,
    write_runtime,
)


def _runtime_path(project_dir: Path) -> Path:
    return project_dir / "docs" / "generated" / RUNTIME_FILENAME


# ── load_runtime ─────────────────────────────────────────────────────

def test_load_runtime_returns_none_when_missing(tmp_path):
    assert load_runtime(tmp_path) is None


def test_load_runtime_returns_dict_when_present(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "runtime_state": "running_exec"}))
    result = load_runtime(tmp_path)
    assert result is not None
    assert result["backend"] == "codex"


# ── write_runtime / atomic write ────────────────────────────────────

def test_write_runtime_creates_file(tmp_path):
    payload = {
        "backend": "codex",
        "step": "phase_2:payment:refund",
        "runtime_state": "waiting_for_input",
        "resume_handle": "abc-123",
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": "phase_2_payment_refund_q1",
        "pending_question": {"question": "Q?", "options": [], "recommended": "", "blocking": True},
        "pending_approval": None,
        "updated_at": "2026-04-10T14:00:00",
    }
    write_runtime(tmp_path, payload)
    p = _runtime_path(tmp_path)
    assert p.exists()
    loaded = json.loads(p.read_text())
    assert loaded["step"] == "phase_2:payment:refund"


def test_write_runtime_is_atomic(tmp_path, monkeypatch):
    """write_runtime must use temp+rename (no partial writes visible)."""
    import os
    replaced_calls: list[tuple[str, str]] = []
    original_replace = os.replace
    def mock_replace(src, dst):
        replaced_calls.append((src, dst))
        return original_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)

    write_runtime(tmp_path, {"backend": "codex", "runtime_state": "running_exec"})
    assert len(replaced_calls) == 1
    src, dst = replaced_calls[0]
    assert dst == str(_runtime_path(tmp_path))
    assert src != dst


# ── clear_runtime ────────────────────────────────────────────────────

def test_clear_runtime_removes_file(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    clear_runtime(tmp_path)
    assert not p.exists()


def test_clear_runtime_noop_when_missing(tmp_path):
    clear_runtime(tmp_path)  # Must not raise


# ── runtime_is_waiting ───────────────────────────────────────────────

def test_runtime_is_waiting_false_when_no_file(tmp_path):
    assert runtime_is_waiting(tmp_path) is False


def test_runtime_is_waiting_true_for_waiting_states(tmp_path):
    for state in ("waiting_for_input", "waiting_for_approval"):
        p = _runtime_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"runtime_state": state}))
        assert runtime_is_waiting(tmp_path) is True


def test_runtime_is_waiting_false_for_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"runtime_state": "running_exec"}))
    assert runtime_is_waiting(tmp_path) is False
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_docs_orchestrator_runtime.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: `docs_orchestrator_runtime.py` 구현**

`src/cowork_pilot/docs_orchestrator_runtime.py` 신규 생성:

```python
"""Runtime sidecar state management for docs-orchestrator Codex backend.

Manages ``docs/generated/orchestrator-runtime.json`` — the single source of
truth for Codex handoff state (resume_handle, waiting status, pending events).

This file is SEPARATE from ``orchestrator-state.json`` which tracks phase
progression.  The two files must never be merged.

Write ordering contract (from §5.2):
- On waiting: write runtime file only (do NOT advance orchestrator-state.json)
- On completion: advance orchestrator-state.json FIRST, then delete runtime file
- Crash recovery: if state.current.status != "running", runtime file is stale → delete
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cowork_pilot.orchestrator_state import OrchestratorState


# ── Constants ────────────────────────────────────────────────────────

RUNTIME_FILENAME = "orchestrator-runtime.json"

_WAITING_STATES = frozenset({"waiting_for_input", "waiting_for_approval"})
_VALID_STATES = frozenset({"running_exec", "waiting_for_input", "waiting_for_approval", "failed"})


def _runtime_path(project_dir: Path) -> Path:
    return project_dir / "docs" / "generated" / RUNTIME_FILENAME


# ── Public API ───────────────────────────────────────────────────────

def load_runtime(project_dir: Path) -> dict[str, object] | None:
    """Return the runtime payload dict, or None if the file does not exist."""
    p = _runtime_path(project_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_runtime(project_dir: Path, payload: dict[str, object]) -> None:
    """Write *payload* to the runtime file atomically (temp + os.replace).

    The parent directory is created if it does not exist.
    ``updated_at`` is always set to the current UTC time.
    """
    p = _runtime_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(payload)
    payload["updated_at"] = datetime.now(tz=timezone.utc).isoformat()

    content = json.dumps(payload, ensure_ascii=False, indent=2)

    # Write to a temp file in the same directory, then atomically rename.
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(p))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_runtime(project_dir: Path) -> None:
    """Delete the runtime file if it exists (no-op if already absent)."""
    p = _runtime_path(project_dir)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def runtime_is_waiting(project_dir: Path) -> bool:
    """Return True iff the runtime file exists and its state is waiting."""
    payload = load_runtime(project_dir)
    if payload is None:
        return False
    return payload.get("runtime_state") in _WAITING_STATES
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator_runtime.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator_runtime.py tests/test_docs_orchestrator_runtime.py
git commit -m "feat(orchestrator-runtime): add runtime sidecar module with atomic write"
```

---

### Task 2-2: `cleanup_stale_runtime()` 구현

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_docs_orchestrator_runtime.py`에 추가:

```python
from cowork_pilot.docs_orchestrator_runtime import cleanup_stale_runtime
from cowork_pilot.orchestrator_state import OrchestratorState, StepStatus


def _make_state(status: str, step: str = "phase_2:payment:refund", completed: list[str] | None = None) -> OrchestratorState:
    completed_steps = [StepStatus(step=s, status="completed") for s in (completed or [])]
    return OrchestratorState(
        current={"step": step, "status": status},
        completed=completed_steps,
    )


def test_cleanup_stale_noop_when_no_runtime(tmp_path):
    state = _make_state("running")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)  # Must not raise


def test_cleanup_stale_deletes_when_state_not_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("idle")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert not p.exists()


def test_cleanup_stale_deletes_when_step_already_completed(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("running", step="phase_3_A", completed=["phase_2:x:y"])
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert not p.exists()


def test_cleanup_stale_raises_on_step_mismatch(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    # state.current.step is different from runtime.step, both are "running"
    state = _make_state("running", step="phase_3_A")
    with pytest.raises(RuntimeError, match="inconsistent"):
        cleanup_stale_runtime(state=state, project_dir=tmp_path)


def test_cleanup_stale_noop_when_step_matches_and_running(tmp_path):
    p = _runtime_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"backend": "codex", "step": "phase_2:x:y", "runtime_state": "waiting_for_input"}))
    state = _make_state("running", step="phase_2:x:y")
    cleanup_stale_runtime(state=state, project_dir=tmp_path)
    assert p.exists()  # Must NOT be deleted
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_docs_orchestrator_runtime.py -k "stale" -v 2>&1 | head -20
```

Expected: `FAILED` (ImportError on `cleanup_stale_runtime`)

- [ ] **Step 3: `docs_orchestrator_runtime.py`에 `cleanup_stale_runtime()` 추가**

`clear_runtime()` 아래에:

```python
def cleanup_stale_runtime(
    *,
    state: OrchestratorState,
    project_dir: Path,
) -> None:
    """Delete the runtime file if it is stale; raise if state is inconsistent.

    Stale: state.current.status != "running", OR runtime.step is already
           in state.completed.

    Inconsistent: state.current.status == "running" AND runtime.step !=
                  state.current.step.  This indicates a write-ordering bug
                  or manual file mutation.  Human review required.

    Call this at startup BEFORE any recovery logic.
    """
    payload = load_runtime(project_dir)
    if payload is None:
        return

    current_status = str(state.current.get("status", ""))
    current_step = str(state.current.get("step", ""))
    completed_steps = {s.step for s in state.completed}
    runtime_step = str(payload.get("step", ""))

    # Case 1: state is no longer running → stale
    if current_status != "running":
        clear_runtime(project_dir)
        return

    # Case 2: runtime step already completed → stale
    if runtime_step in completed_steps:
        clear_runtime(project_dir)
        return

    # Case 3: step mismatch with running state → inconsistent, abort
    if runtime_step != current_step:
        raise RuntimeError(
            f"Orchestrator runtime is inconsistent: "
            f"state.current.step={current_step!r} but runtime.step={runtime_step!r}. "
            f"Human review required. "
            f"Do NOT auto-recover. Check docs/generated/orchestrator-runtime.json "
            f"and docs/generated/orchestrator-state.json manually."
        )

    # Case 4: step matches and running → valid waiting state, leave as-is
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator_runtime.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator_runtime.py tests/test_docs_orchestrator_runtime.py
git commit -m "feat(orchestrator-runtime): add cleanup_stale_runtime() with inconsistency guard"
```

---

### Task 2-3: Chunk 1+2 전체 회귀 확인

- [ ] **Step 1: 관련 테스트 전체 실행**

```bash
python -m pytest tests/test_orchestrator_prompts.py tests/test_docs_orchestrator_runtime.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 2: 기존 orchestrator 테스트 회귀 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
```

Expected: 전체 `PASSED` (변경 없음)
