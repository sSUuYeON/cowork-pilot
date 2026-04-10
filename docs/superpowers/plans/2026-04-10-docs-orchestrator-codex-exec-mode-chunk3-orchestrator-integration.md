# Docs-Orchestrator Codex Exec Mode — Chunk 4 & 5: Orchestrator Integration + CLI

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs_orchestrator.py`에 Codex backend 분기를 연결하고, `main.py`에 resume CLI를 추가한다.

**Architecture:** 기존 phase 함수들은 `_execute_orchestrator_step()` helper를 통해 Claude/Codex 분기를 처리한다. `run_docs_orchestrator()` main loop에 startup cleanup + waiting pause 규칙을 추가한다. resume은 `--docs-subcommand resume` 단일 진입점으로 제공된다.

**Tech Stack:** 기존 `docs_orchestrator.py` 구조 유지, `docs_orchestrator_codex`, `docs_orchestrator_runtime` 재사용

**선행 조건:** Chunk 1+2+3 완료

**Spec:** `docs/superpowers/plans/2026-04-10-docs-orchestrator-codex-exec-mode-design.md` §10, §11, §15

---

## Chunk 4: Orchestrator Integration

**Files:**
- Modify: `src/cowork_pilot/docs_orchestrator.py`
- Test: `tests/test_docs_orchestrator.py` (Claude 회귀 assertion 추가)

### Task 4-1: `StepExecutionOutcome` + `_execute_orchestrator_step()` 추가

이 helper는 phase 함수들의 "실행 부분"을 담당한다. Claude branch는 기존 helper를 그대로 호출하고, Codex branch는 `run_codex_step()`을 호출한 뒤 runtime 파일을 기록한다.

- [ ] **Step 1: Claude 회귀 테스트 assertion 추가**

`tests/test_docs_orchestrator.py`를 열어 기존 Phase 1 관련 테스트를 확인한다.
아래 assertion을 기존 Claude 경로 테스트에 추가한다 (mock 패턴은 기존 파일의 패턴을 따를 것):

```python
# 기존 테스트에 추가: Claude 경로에서 session_opener가 반드시 호출됨
def test_claude_path_calls_open_orchestrator_session(tmp_path, monkeypatch):
    """engine=claude → _open_orchestrator_session() 반드시 호출."""
    from unittest.mock import MagicMock, patch
    from cowork_pilot.config import Config, DocsOrchestratorConfig
    from cowork_pilot.docs_orchestrator import _execute_orchestrator_step, StepExecutionOutcome

    orch_config = DocsOrchestratorConfig(engine="claude")

    opened = []
    waited = []

    def fake_open(prompt, config, orch_config, base_path):
        opened.append(True)
        return tmp_path / "fake.jsonl"

    def fake_wait(jsonl_path, expected_files, config, orch_config, watch_mode):
        waited.append(True)
        return True

    with patch("cowork_pilot.docs_orchestrator._open_orchestrator_session", side_effect=fake_open), \
         patch("cowork_pilot.docs_orchestrator._wait_for_session_completion", side_effect=fake_wait):

        outcome = _execute_orchestrator_step(
            step_name="phase_1",
            prompt="test prompt",
            expected_files=[],
            watch_mode=False,
            config=Config(project_dir=str(tmp_path)),
            orch_config=orch_config,
            project_dir=tmp_path,
            base_path=tmp_path,
        )

    assert len(opened) == 1, "Claude 경로에서 _open_orchestrator_session이 호출되어야 함"
    assert len(waited) == 1, "Claude 경로에서 _wait_for_session_completion이 호출되어야 함"
    assert outcome.kind == "completed"


def test_codex_path_does_not_call_session_opener(tmp_path, monkeypatch):
    """engine=codex → session_opener와 JSONL helper가 호출되지 않아야 함."""
    from unittest.mock import MagicMock, patch
    from cowork_pilot.config import Config, DocsOrchestratorConfig
    from cowork_pilot.docs_orchestrator import _execute_orchestrator_step
    from cowork_pilot.docs_orchestrator_codex import CodexStepResult

    orch_config = DocsOrchestratorConfig(engine="codex")

    mock_run_codex = MagicMock(return_value=CodexStepResult(
        status="completed",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-001",
        waiting_kind=None,
        pending_event_id=None,
        pending_question=None,
        pending_approval=None,
        error="",
    ))

    with patch("cowork_pilot.docs_orchestrator._open_orchestrator_session") as mock_open, \
         patch("cowork_pilot.docs_orchestrator._wait_for_session_completion") as mock_wait, \
         patch("cowork_pilot.docs_orchestrator.run_codex_step", mock_run_codex):

        _execute_orchestrator_step(
            step_name="phase_1",
            prompt="test prompt",
            expected_files=[],
            watch_mode=False,
            config=Config(project_dir=str(tmp_path)),
            orch_config=orch_config,
            project_dir=tmp_path,
            base_path=tmp_path,
        )

    mock_open.assert_not_called()
    mock_wait.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py::test_claude_path_calls_open_orchestrator_session -v 2>&1 | tail -10
```

Expected: `FAILED` (ImportError on `_execute_orchestrator_step` or `StepExecutionOutcome`)

- [ ] **Step 3: `docs_orchestrator.py`에 `StepExecutionOutcome` + helper 추가**

`docs_orchestrator.py`의 import 섹션에 추가:

```python
from cowork_pilot.docs_orchestrator_codex import run_codex_step, CodexStepResult
from cowork_pilot.docs_orchestrator_runtime import (
    write_runtime,
    runtime_is_waiting,
    cleanup_stale_runtime,
)
from cowork_pilot.orchestrator_prompts import build_codex_session_prompt
```

`_open_orchestrator_session()` 정의 바로 앞(~L1421 부근)에 삽입:

```python
# ── Step execution helper ─────────────────────────────────────────────


from dataclasses import dataclass as _dc
from typing import Literal as _Lit


@_dc(frozen=True)
class StepExecutionOutcome:
    """Result of _execute_orchestrator_step()."""
    kind: _Lit["completed", "waiting", "failed"]
    error: str = ""


def _execute_orchestrator_step(
    *,
    step_name: str,
    prompt: str,
    expected_files: list[Path],
    watch_mode: bool,
    config: "Config",
    orch_config: "DocsOrchestratorConfig",
    project_dir: Path,
    base_path: Path,
    codex_exec_config: object | None = None,
) -> StepExecutionOutcome:
    """Execute one orchestrator step via Claude or Codex backend.

    Claude branch: delegates to _open_orchestrator_session() +
                   _wait_for_session_completion() unchanged.

    Codex branch:  calls run_codex_step(); on waiting, writes runtime sidecar;
                   on completion, returns completed (caller updates state);
                   on failure, returns failed.

    Phase progression is NEVER updated here — that is the caller's job.
    """
    engine = getattr(orch_config, "engine", "claude")

    if engine == "claude":
        jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
        if jsonl_path is None:
            return StepExecutionOutcome(kind="failed", error="세션 열기 실패")
        ok = _wait_for_session_completion(
            jsonl_path, expected_files, config, orch_config, watch_mode,
        )
        if not ok:
            return StepExecutionOutcome(kind="failed", error="세션 완료 대기 실패")
        return StepExecutionOutcome(kind="completed")

    # Codex backend
    codex_cmd = getattr(orch_config, "engine_command", "codex")
    result: CodexStepResult = run_codex_step(
        project_dir=project_dir,
        step=step_name,
        prompt=prompt,
        expected_files=expected_files,
        codex_command=codex_cmd,
        codex_extra_args=None,
    )

    if result.status == "waiting":
        _save_codex_waiting_runtime(
            project_dir=project_dir,
            step_name=step_name,
            result=result,
        )
        return StepExecutionOutcome(kind="waiting")

    if result.status == "failed":
        return StepExecutionOutcome(kind="failed", error=result.error)

    return StepExecutionOutcome(kind="completed")


def _save_codex_waiting_runtime(
    *,
    project_dir: Path,
    step_name: str,
    result: "CodexStepResult",
) -> None:
    """Write orchestrator-runtime.json for a waiting Codex step."""
    runtime_state = (
        "waiting_for_input" if result.waiting_kind == "input" else "waiting_for_approval"
    )
    payload: dict[str, object] = {
        "backend": "codex",
        "step": step_name,
        "runtime_state": runtime_state,
        "resume_handle": result.resume_handle,
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": result.pending_event_id or "",
        "pending_question": result.pending_question,
        "pending_approval": result.pending_approval,
    }
    write_runtime(project_dir, payload)
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py::test_claude_path_calls_open_orchestrator_session tests/test_docs_orchestrator.py::test_codex_path_does_not_call_session_opener -v
```

Expected: `PASSED`

- [ ] **Step 5: 전체 orchestrator 테스트 회귀 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 6: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator.py tests/test_docs_orchestrator.py
git commit -m "feat(docs-orchestrator): add StepExecutionOutcome and _execute_orchestrator_step()"
```

---

### Task 4-2: Phase 함수들을 `_execute_orchestrator_step()` 기반으로 리팩터

각 phase 함수에서 반복되는 `_open_orchestrator_session()` + `_wait_for_session_completion()` 패턴을 `_execute_orchestrator_step()` 호출로 교체한다.

**적용 대상:** `_run_phase_1()`, `_run_phase_2()`, `_run_phase_3_group_a/b/c/d()`, `_run_phase_5_detail()`. Phase 1.5는 제외 (로컬 quality gate만 실행하는 비-AI 단계).

아래는 `_run_phase_1()` 단일 세션 경로를 예시로 보여준다. 나머지 phase는 동일 패턴으로 교체한다.

- [ ] **Step 1: `_run_phase_1()` 단일 세션 경로 리팩터**

기존:

```python
jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
if jsonl_path is None:
    return _update_state_error(state, "phase_1", "세션 열기 실패")

completed = _wait_for_session_completion(
    jsonl_path, expected_files, config, orch_config, watch_mode,
)
if not completed:
    return _update_state_error(state, "phase_1", "세션 완료 대기 실패")

state = _update_state_completed(state, "phase_1", "1세션 처리 완료")
```

교체 후:

```python
outcome = _execute_orchestrator_step(
    step_name="phase_1",
    prompt=prompt,
    expected_files=expected_files,
    watch_mode=watch_mode,
    config=config,
    orch_config=orch_config,
    project_dir=project_dir,
    base_path=base_path,
)
if outcome.kind == "failed":
    return _update_state_error(state, "phase_1", outcome.error or "단계 실행 실패")
if outcome.kind == "waiting":
    return state  # runtime sidecar already written; state.current stays "running"

state = _update_state_completed(state, "phase_1", "1세션 처리 완료")
```

- [ ] **Step 2: 동일 패턴으로 나머지 phase 함수 전체 교체**

교체 대상 목록 (파일 내 grep으로 확인):

```bash
grep -n "_open_orchestrator_session\|_wait_for_session_completion" src/cowork_pilot/docs_orchestrator.py
```

각 호출 쌍을 `_execute_orchestrator_step()` 호출로 교체한다. step_name은 해당 위치에서 이미 결정된 `step_name` 변수를 그대로 사용한다.

- [ ] **Step 3: 회귀 테스트 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 4: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator.py
git commit -m "refactor(docs-orchestrator): delegate phase execution to _execute_orchestrator_step()"
```

---

### Task 4-3: Codex prompt 빌드 연결

`_execute_orchestrator_step()` Codex branch에서 `build_codex_session_prompt()`를 사용한다. 현재 caller(phase 함수)는 `build_session_prompt()`로 prompt를 미리 만들어 넘긴다. Codex branch에서는 wrapper 버전으로 다시 빌드해야 한다.

**방식:** `_execute_orchestrator_step()`에 `prompt_phase` + `prompt_kwargs`를 추가로 받아 Codex branch에서 `build_codex_session_prompt()`를 호출한다.

- [ ] **Step 1: `_execute_orchestrator_step()` 시그니처 확장**

```python
def _execute_orchestrator_step(
    *,
    step_name: str,
    prompt: str,                        # Claude용 (기존 build_session_prompt 결과)
    prompt_phase: str | None = None,    # Codex branch에서 wrapper 재빌드에 사용
    prompt_kwargs: dict[str, object] | None = None,
    expected_files: list[Path],
    watch_mode: bool,
    config: "Config",
    orch_config: "DocsOrchestratorConfig",
    project_dir: Path,
    base_path: Path,
    codex_exec_config: object | None = None,
) -> StepExecutionOutcome:
```

Codex branch 시작 부분에 추가:

```python
    # Codex backend: rebuild prompt with wrapper
    if prompt_phase is not None:
        codex_prompt = build_codex_session_prompt(
            prompt_phase,
            **(prompt_kwargs or {}),
        )
    else:
        codex_prompt = prompt  # fallback: use Claude prompt as-is

    result: CodexStepResult = run_codex_step(
        project_dir=project_dir,
        step=step_name,
        prompt=codex_prompt,
        ...
    )
```

- [ ] **Step 2: Phase 함수들에서 `prompt_phase` + `prompt_kwargs` 전달**

`_run_phase_1()` 예시:

```python
outcome = _execute_orchestrator_step(
    step_name="phase_1",
    prompt=prompt,                    # Claude용
    prompt_phase="phase1_single",     # Codex wrapper 빌드용
    prompt_kwargs=dict(               # 템플릿 변수
        project_dir=str(project_dir),
        source_docs=source_docs,
        domains=domains,
        features=features,
    ),
    expected_files=expected_files,
    watch_mode=watch_mode,
    config=config,
    orch_config=orch_config,
    project_dir=project_dir,
    base_path=base_path,
)
```

Phase 2 예시:

```python
outcome = _execute_orchestrator_step(
    step_name=step_name,
    prompt=prompt,
    prompt_phase=phase_template,      # "phase2_auto" or "phase2_manual"
    prompt_kwargs=dict(
        project_dir=str(project_dir),
        features=features_for_prompt,
        domain=first_domain,
        feature=first_feature,
    ),
    ...
)
```

- [ ] **Step 3: 회귀 테스트 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 4: Codex prompt test 추가**

`tests/test_docs_orchestrator.py`에:

```python
def test_codex_path_uses_wrapper_prompt(tmp_path, monkeypatch):
    """engine=codex에서 build_codex_session_prompt()가 호출되어야 함."""
    from unittest.mock import patch, MagicMock
    from cowork_pilot.config import Config, DocsOrchestratorConfig
    from cowork_pilot.docs_orchestrator import _execute_orchestrator_step
    from cowork_pilot.docs_orchestrator_codex import CodexStepResult

    orch_config = DocsOrchestratorConfig(engine="codex")

    mock_result = CodexStepResult(
        status="completed", event_lines=[], assistant_message="",
        exit_code=0, resume_handle="t", waiting_kind=None,
        pending_event_id=None, pending_question=None, pending_approval=None, error="",
    )

    with patch("cowork_pilot.docs_orchestrator.build_codex_session_prompt") as mock_build, \
         patch("cowork_pilot.docs_orchestrator.run_codex_step", return_value=mock_result):
        mock_build.return_value = "CODEX_PROMPT"

        _execute_orchestrator_step(
            step_name="phase_1",
            prompt="CLAUDE_PROMPT",
            prompt_phase="phase1_single",
            prompt_kwargs={"project_dir": "/p"},
            expected_files=[],
            watch_mode=False,
            config=Config(project_dir=str(tmp_path)),
            orch_config=orch_config,
            project_dir=tmp_path,
            base_path=tmp_path,
        )

    mock_build.assert_called_once_with("phase1_single", project_dir="/p")
```

- [ ] **Step 5: 통과 확인 후 커밋**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
git add src/cowork_pilot/docs_orchestrator.py tests/test_docs_orchestrator.py
git commit -m "feat(docs-orchestrator): wire Codex prompt wrapper in _execute_orchestrator_step()"
```

---

### Task 4-4: Main loop pause/recovery 규칙 추가

`run_docs_orchestrator()`에 startup cleanup + waiting pause 규칙을 추가한다.

- [ ] **Step 1: 테스트 작성**

`tests/test_docs_orchestrator.py`에 추가:

```python
def test_run_loop_pauses_when_codex_waiting(tmp_path, monkeypatch):
    """Codex waiting runtime이 있으면 run loop이 즉시 종료되어야 함 (재실행 없이)."""
    import json
    from unittest.mock import patch, MagicMock
    from cowork_pilot.config import Config, DocsOrchestratorConfig
    from cowork_pilot.docs_orchestrator import run_docs_orchestrator

    # Setup: state running + runtime waiting
    gen_dir = tmp_path / "docs" / "generated"
    gen_dir.mkdir(parents=True)
    state_data = {
        "current": {"step": "phase_2:x:y", "status": "running"},
        "completed": [],
        "pending": [],
        "errors": [],
        "project_summary": {"domains": [], "features": {}, "source_docs": [], "source_line_count": 0},
        "updated_at": "",
        "mode": "auto",
        "manual_override": [],
        "project_dir": str(tmp_path),
    }
    (gen_dir / "orchestrator-state.json").write_text(json.dumps(state_data))
    (gen_dir / "orchestrator-runtime.json").write_text(json.dumps({
        "backend": "codex",
        "step": "phase_2:x:y",
        "runtime_state": "waiting_for_input",
        "resume_handle": "tid-001",
    }))

    phase_executed = []
    orch_config = DocsOrchestratorConfig(engine="codex")
    config = Config(project_dir=str(tmp_path))

    with patch("cowork_pilot.docs_orchestrator._execute_orchestrator_step") as mock_exec:
        run_docs_orchestrator(config, orch_config)

    # Phase execution must NOT have been called (loop paused on waiting)
    mock_exec.assert_not_called()
```

- [ ] **Step 2: `run_docs_orchestrator()` 수정**

`run_docs_orchestrator()`에서 state load 직후:

```python
    # 1. state load
    state = load_state(state_path)

    # 2. runtime cleanup (stale detection; inconsistency → abort with message)
    if orch_config.engine == "codex":
        try:
            cleanup_stale_runtime(state=state, project_dir=project_dir)
        except RuntimeError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            _notify_escalate_message(str(e))
            return

    # 3. Codex waiting check: if waiting runtime exists, pause immediately
    if orch_config.engine == "codex" and runtime_is_waiting(project_dir):
        print(
            "docs-orchestrator paused: Codex session waiting for user input.\n"
            "Run with --docs-subcommand resume --response '...' to continue.",
            file=sys.stderr,
        )
        return

    # 4. existing recovery (Claude path or non-waiting Codex)
    if state.current.get("status") == "running":
        state = recover_running_step(state, state_path)
```

注意: `_notify_escalate_message()` 헬퍼가 없으면 단순 print로 대체한다. 기존 `_notify_escalate()`는 Event 객체를 받으므로 그대로 쓸 수 없다. 아래 헬퍼를 추가한다:

```python
def _notify_escalate_message(msg: str) -> None:
    """Send macOS notification for a fatal orchestrator error."""
    try:
        from cowork_pilot.responder import notify
        notify("⚠️ docs-orchestrator FATAL", msg[:100], tts=False)
    except Exception:
        pass
```

그리고 각 phase 실행 후 waiting 체크:

```python
    # main loop 내에서 각 phase 함수 호출 뒤
    if orch_config.engine == "codex" and runtime_is_waiting(project_dir):
        save_state(state, state_path)
        print(
            "docs-orchestrator paused: waiting for user response.\n"
            "Run with --docs-subcommand resume to continue.",
            file=sys.stderr,
        )
        return
```

- [ ] **Step 3: 통과 확인**

```bash
python -m pytest tests/test_docs_orchestrator.py -v
```

Expected: 전체 `PASSED`

- [ ] **Step 4: 커밋**

```bash
git add src/cowork_pilot/docs_orchestrator.py tests/test_docs_orchestrator.py
git commit -m "feat(docs-orchestrator): add main loop pause/recovery for Codex waiting state"
```

---

## Chunk 5: CLI Resume

**Files:**
- Modify: `src/cowork_pilot/main.py`
- Test: `tests/test_main_cli.py`

### Task 5-1: `--docs-subcommand`, `--response`, `--response-kind` 인자 추가

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_main_cli.py`에 추가:

```python
def test_docs_resume_requires_response(tmp_path, monkeypatch):
    """--docs-subcommand resume without --response must exit with error."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "cowork_pilot.main",
         "--mode", "docs-orchestrator",
         "--docs-subcommand", "resume",
         "--project-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "response" in result.stderr.lower() or "response" in result.stdout.lower()


def test_docs_resume_error_when_no_runtime(tmp_path, monkeypatch):
    """resume when no runtime file exists must exit with non-zero code."""
    import subprocess, sys
    # no orchestrator-runtime.json in tmp_path
    result = subprocess.run(
        [sys.executable, "-m", "cowork_pilot.main",
         "--mode", "docs-orchestrator",
         "--docs-subcommand", "resume",
         "--response", "some answer",
         "--project-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_main_cli.py::test_docs_resume_requires_response -v 2>&1 | tail -10
```

Expected: `FAILED` (unknown argument `--docs-subcommand`)

- [ ] **Step 3: `main.py`에 인자 추가**

기존 `--docs-mode` 인자 아래에:

```python
parser.add_argument(
    "--docs-subcommand",
    type=str,
    choices=["run", "resume"],
    default="run",
    help="docs-orchestrator subcommand: run (default) / resume",
)
parser.add_argument(
    "--response",
    type=str,
    default=None,
    help="User response text for docs-orchestrator resume",
)
parser.add_argument(
    "--response-kind",
    type=str,
    choices=["answer", "approval"],
    default="answer",
    help="Response kind for resume: answer (default) / approval",
)
```

그리고 docs-orchestrator 분기 내:

```python
    elif args.mode == "docs-orchestrator":
        from cowork_pilot.config import load_docs_orchestrator_config
        from cowork_pilot.docs_orchestrator import run_docs_orchestrator
        orch_config = load_docs_orchestrator_config(Path(args.config), config)
        orch_config.docs_mode = args.docs_mode

        if args.docs_subcommand == "resume":
            _run_docs_orchestrator_resume(args, config, orch_config)
        else:
            run_docs_orchestrator(config, orch_config)
```

- [ ] **Step 4: `_run_docs_orchestrator_resume()` 추가**

`main.py` 내 (또는 파일 하단):

```python
def _run_docs_orchestrator_resume(args, config, orch_config) -> None:
    """Handle --docs-subcommand resume."""
    import sys
    from pathlib import Path
    from cowork_pilot.docs_orchestrator_runtime import (
        load_runtime,
        write_runtime,
        clear_runtime,
        runtime_is_waiting,
    )
    from cowork_pilot.docs_orchestrator_codex import resume_codex_step
    from cowork_pilot.orchestrator_state import load_state, save_state
    from cowork_pilot.docs_orchestrator import (
        _update_state_completed,
        _update_state_error,
        _STATE_FILENAME,
        _GENERATED_DIR,
    )

    project_dir = Path(config.project_dir)
    state_path = project_dir / _GENERATED_DIR / _STATE_FILENAME

    # 1. --response required
    if not args.response:
        print("ERROR: --response is required for resume", file=sys.stderr)
        sys.exit(1)

    # 2. runtime file must exist and be in waiting state
    runtime = load_runtime(project_dir)
    if runtime is None:
        print("ERROR: No orchestrator-runtime.json found. Nothing to resume.", file=sys.stderr)
        sys.exit(1)

    if not runtime_is_waiting(project_dir):
        print(
            f"ERROR: Runtime is not in a waiting state "
            f"(current: {runtime.get('runtime_state')})",
            file=sys.stderr,
        )
        sys.exit(1)

    resume_handle = runtime.get("resume_handle", "")
    if not resume_handle:
        print("ERROR: runtime file has no resume_handle.", file=sys.stderr)
        sys.exit(1)

    step = str(runtime.get("step", ""))
    state = load_state(state_path)

    # 3. resume — wrap in try/except so I/O and Codex errors are user-friendly
    try:
        codex_cmd = getattr(orch_config, "engine_command", "codex")
        result = resume_codex_step(
            project_dir=project_dir,
            step=step,
            response_text=args.response,
            response_kind=args.response_kind,
            runtime_payload=dict(runtime),
            expected_files=[],          # re-verify on STAGE_COMPLETE; simplified for V1
            codex_command=codex_cmd,
        )
    except Exception as exc:
        msg = f"Codex resume raised an exception: {exc}"
        print(f"FATAL: {msg}", file=sys.stderr)
        try:
            from cowork_pilot.docs_orchestrator import _notify_escalate_message
            _notify_escalate_message(msg)
        except Exception:
            pass
        sys.exit(1)

    # 4. handle result
    # Write ordering contract (spec §5.2 §7):
    #   completed → save_state FIRST, THEN clear_runtime (crash-safe: stale runtime is handled by cleanup_stale_runtime on next startup)
    #   waiting   → write_runtime only (do NOT advance state)
    #   failed    → save_state, then write_runtime with "failed"
    if result.status == "completed":
        state = _update_state_completed(state, step, "Codex resume 완료")
        save_state(state, state_path)   # state first
        clear_runtime(project_dir)      # then remove runtime
        print(f"Step {step} completed. Continuing orchestration...", file=sys.stderr)
        # Auto-continue immediately (spec §11.3): same process continues
        from cowork_pilot.docs_orchestrator import run_docs_orchestrator
        run_docs_orchestrator(config, orch_config)

    elif result.status == "waiting":
        # Update runtime with new pending payload; state stays untouched
        new_runtime = {
            "backend": "codex",
            "step": step,
            "runtime_state": (
                "waiting_for_input" if result.waiting_kind == "input"
                else "waiting_for_approval"
            ),
            "resume_handle": result.resume_handle,
            "resume_handle_kind": "codex_thread_id",
            "pending_event_id": result.pending_event_id or "",
            "pending_question": result.pending_question,
            "pending_approval": result.pending_approval,
        }
        write_runtime(project_dir, new_runtime)
        print(
            f"Step {step} still waiting. "
            f"Run resume again with the next response.",
            file=sys.stderr,
        )

    else:  # failed
        state = _update_state_error(state, step, result.error or "Codex resume failed")
        save_state(state, state_path)
        new_runtime = dict(runtime)
        new_runtime["runtime_state"] = "failed"
        write_runtime(project_dir, new_runtime)
        print(f"ERROR: resume failed: {result.error}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 5: 통과 확인**

```bash
python -m pytest tests/test_main_cli.py::test_docs_resume_requires_response tests/test_main_cli.py::test_docs_resume_error_when_no_runtime -v
```

Expected: `PASSED`

- [ ] **Step 6: 커밋**

```bash
git add src/cowork_pilot/main.py tests/test_main_cli.py
git commit -m "feat(main): add docs-orchestrator resume CLI subcommand"
```

---

### Task 5-2: resume CLI 추가 테스트

- [ ] **Step 1: 성공 resume 테스트 추가**

```python
def test_docs_resume_completed_clears_runtime(tmp_path, monkeypatch):
    """Successful resume must clear runtime and advance state."""
    import json
    from pathlib import Path
    from unittest.mock import patch
    from cowork_pilot.docs_orchestrator_codex import CodexStepResult

    gen_dir = tmp_path / "docs" / "generated"
    gen_dir.mkdir(parents=True)
    state_data = {
        "current": {"step": "phase_2:x:y", "status": "running"},
        "completed": [], "pending": [], "errors": [],
        "project_summary": {"domains": [], "features": {}, "source_docs": [], "source_line_count": 0},
        "updated_at": "", "mode": "auto", "manual_override": [],
        "project_dir": str(tmp_path),
    }
    (gen_dir / "orchestrator-state.json").write_text(json.dumps(state_data))
    (gen_dir / "orchestrator-runtime.json").write_text(json.dumps({
        "backend": "codex",
        "step": "phase_2:x:y",
        "runtime_state": "waiting_for_input",
        "resume_handle": "tid-001",
        "pending_event_id": "q1",
    }))

    mock_result = CodexStepResult(
        status="completed", event_lines=[], assistant_message="",
        exit_code=0, resume_handle="tid-001",
        waiting_kind=None, pending_event_id=None,
        pending_question=None, pending_approval=None, error="",
    )

    from unittest.mock import MagicMock
    mock_continue = MagicMock()  # captures auto-continuation call

    with patch("cowork_pilot.docs_orchestrator_codex.resume_codex_step", return_value=mock_result), \
         patch("cowork_pilot.docs_orchestrator.run_docs_orchestrator", mock_continue):

        from cowork_pilot.main import _run_docs_orchestrator_resume
        from cowork_pilot.config import Config, DocsOrchestratorConfig
        import argparse

        args = argparse.Namespace(
            response="admin approves",
            response_kind="answer",
        )
        config = Config(project_dir=str(tmp_path))
        orch_config = DocsOrchestratorConfig(engine="codex")
        _run_docs_orchestrator_resume(args, config, orch_config)

    # runtime file must be gone (state written first, then runtime cleared)
    assert not (gen_dir / "orchestrator-runtime.json").exists()
    # state must have the step completed
    state = json.loads((gen_dir / "orchestrator-state.json").read_text())
    completed_steps = [s["step"] for s in state["completed"]]
    assert "phase_2:x:y" in completed_steps
    # auto-continuation must have been called (spec §11.3)
    mock_continue.assert_called_once()
```

- [ ] **Step 2: 통과 확인**

```bash
python -m pytest tests/test_main_cli.py -k "resume" -v
```

Expected: 전체 `PASSED`

- [ ] **Step 3: 커밋**

```bash
git add tests/test_main_cli.py
git commit -m "test(main-cli): add docs-orchestrator resume scenarios"
```

---

### Task 5-3: 최종 전체 회귀 확인

- [ ] **Step 1: 전체 테스트 스위트 실행**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: 전체 `PASSED`. 실패 시 Claude 경로와 Codex 경로를 분리해서 디버깅:

```bash
# Claude 경로만
python -m pytest tests/test_docs_orchestrator.py -v

# Codex 신규
python -m pytest tests/test_docs_orchestrator_codex.py tests/test_docs_orchestrator_runtime.py -v

# CLI
python -m pytest tests/test_main_cli.py -k "docs" -v
```

- [ ] **Step 2: 완료 기준 체크리스트 확인**

설계 문서 §17 기준:

- [ ] `--engine claude` 경로가 기존과 동일하게 동작 (기존 테스트 통과)
- [ ] `--engine codex` 경로가 `codex exec`로 각 step 실행 (mock 테스트 통과)
- [ ] Codex step waiting 시 `orchestrator-runtime.json` 생성 (unit test 통과)
- [ ] `--docs-subcommand resume` 로 waiting step 재개 가능 (CLI test 통과)
- [ ] 완료 시 state.json 진행 + runtime.json 삭제 (unit test 통과)
- [ ] stale runtime 자동 정리 (cleanup_stale_runtime test 통과)
- [ ] Claude 테스트와 Codex 신규 테스트 모두 통과

- [ ] **Step 3: 최종 커밋**

```bash
git add -A
git commit -m "feat: docs-orchestrator Codex exec mode complete (Chunks 1-5)"
```
