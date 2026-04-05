# Build-Repair Retry Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BUILD_FAILED를 즉시 중단이 아닌 자동 수리 루프로 전환하여, codex exec이 빌드 오류만 최소 수정하도록 재시도한다.

**Architecture:** `_verify_and_update_chunk`의 force-check 제거 → 검증 결과를 COMPLETED / INCOMPLETE / BUILD_FAILED로 정확히 분리 → BUILD_FAILED일 때 전용 repair prompt로 codex를 재실행 → harness가 로컬 빌드 재검증 → 최대 N회 반복 후 escalate. Claude Desktop 쪽 `process_chunk`과 동일한 "실패 시 피드백 → 재시도" 패턴을 codex 백엔드에 적용.

**Tech Stack:** Python 3.10+, asyncio, pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/cowork_pilot/codex/harness.py` | force-check 제거, verify 결과 분류, build-repair loop 추가, 메인 루프 분기 수정 |
| Modify | `src/cowork_pilot/codex/config.py` | `build_repair_max_retries` 설정 필드 추가 |
| Modify | `config.toml` | `build_repair_max_retries = 3` 기본값 추가 |
| Modify | `tests/test_codex_harness.py` | 기존 force-check 테스트 수정, build-repair 테스트 추가 |
| Create | `tests/fixtures/sample_exec_plan_build_partial.md` | non-build 일부 체크 + BUILD 미체크 fixture |

---

## Chunk 1: force-check 제거 + verify 결과 분류

### Task 1: `_verify_and_update_chunk` 리팩터

`_verify_and_update_chunk`의 마지막 부분에서 unchecked criteria를 force-check하는 로직(240~248행)을 제거하고, 대신 `INCOMPLETE`를 반환한다.

**Files:**
- Modify: `src/cowork_pilot/codex/harness.py:228-248`
- Modify: `tests/test_codex_harness.py`
- Create: `tests/fixtures/sample_exec_plan_build_partial.md`

- [ ] **Step 1: 테스트 fixture 생성**

`tests/fixtures/sample_exec_plan_build_partial.md` — non-build criteria 하나가 이미 `[x]`이고, [BUILD] criteria는 미체크인 fixture.

```markdown
# Build Partial Plan

> **For agentic workers:** Fixture for build-repair tests.

**Goal:** Test build-repair retry with partially checked criteria.

## Metadata
- project_dir: /Users/test/build-project
- spec: docs/specs/sample.md
- created: 2026-04-04
- status: pending

---

## Chunk 1: Setup

### Completion Criteria
- [x] vercel.json 파일 존재
- [ ] [BUILD] npm run lint
- [ ] [BUILD] npm run build

### Tasks
- Task 1: Vercel 설정
- Task 2: Lint 설정

### Session Prompt
```
프로젝트 설정을 완료하라.
```
```

- [ ] **Step 2: force-check 제거 — 실패 테스트 작성**

`tests/test_codex_harness.py`에 테스트 추가: codex exec SUCCESS + 빌드 PASSED + non-build 미체크 남아있으면 INCOMPLETE 반환 (force-check 안 됨).

```python
def test_verify_returns_incomplete_when_non_build_criteria_unchecked(
    tmp_path,
    monkeypatch,
    capsys,
):
    """codex exec 성공 + 빌드 통과했지만 non-build 체크박스가 남아있으면
    force-check 하지 않고 INCOMPLETE를 반환해야 한다."""
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("PASSED", ""),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(),
        )
    )

    after = plan_path.read_text(encoding="utf-8")

    # non-build criterion "vercel.json 파일 존재" should NOT be force-checked
    assert "- [ ] vercel.json 파일 존재" in after
    assert result is False  # INCOMPLETE → escalate eventually
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_codex_harness.py::test_verify_returns_incomplete_when_non_build_criteria_unchecked -v`
Expected: FAIL — 현재 force-check가 `- [x]`로 바꿔버림

- [ ] **Step 4: `_verify_and_update_chunk` 수정**

`src/cowork_pilot/codex/harness.py` — 기존 228~248행의 force-check 블록을 제거하고 INCOMPLETE 반환으로 교체:

```python
def _verify_and_update_chunk(
    plan_path: Path,
    chunk: Chunk,
    project_dir: str,
    build_timeout: float = 600.0,
) -> tuple[str, str]:
    """After codex exec finishes, verify the chunk and update checkboxes.

    Steps:
    1. Re-parse the plan to check if codex already updated checkboxes
    2. Run [BUILD] criteria locally
    3. Check remaining unchecked criteria

    Returns:
        (status, detail)
        status ∈ {"COMPLETED", "INCOMPLETE", "BUILD_FAILED"}
    """
    # Re-parse to see current state
    fresh_chunk = _find_chunk_by_number(plan_path, chunk.number)

    if fresh_chunk is None:
        return ("INCOMPLETE", "Chunk not found after re-parsing exec-plan")

    # Run [BUILD] criteria locally
    has_unchecked_builds = any(
        c.build_command and not c.checked
        for c in fresh_chunk.completion_criteria
    )

    if has_unchecked_builds:
        build_status, build_detail = run_build_criteria(
            fresh_chunk, project_dir, plan_path,
            timeout=build_timeout,
        )
        if build_status == "FAILED":
            logger.warning("Build failed for chunk %d: %s", chunk.number, build_detail)
            return ("BUILD_FAILED", build_detail)

    # Re-parse after build criteria may have updated checkboxes
    fresh_chunk = _find_chunk_by_number(plan_path, chunk.number)
    if fresh_chunk is None:
        return ("INCOMPLETE", "Chunk disappeared after build verification")

    # Check if all criteria are now satisfied
    unchecked = [
        cr for cr in fresh_chunk.completion_criteria
        if not cr.checked
    ]

    if not unchecked:
        return ("COMPLETED", "")

    # Report remaining unchecked criteria — do NOT force-check
    unchecked_desc = ", ".join(
        _format_completion_criterion_label(cr.description, cr.build_command)
        for cr in unchecked
    )
    logger.info(
        "Chunk %d: %d criteria still unchecked: %s",
        chunk.number, len(unchecked), unchecked_desc,
    )
    return ("INCOMPLETE", unchecked_desc)
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_codex_harness.py::test_verify_returns_incomplete_when_non_build_criteria_unchecked -v`
Expected: PASS

- [ ] **Step 6: 기존 `test_harness_stops_on_build_failed` 테스트 업데이트**

이 테스트는 BUILD_FAILED 시 즉시 escalate+stop을 기대하는데, Task 3에서 repair loop가 추가되면 동작이 바뀐다. 지금은 _verify_and_update_chunk 단위 테스트로 분리해두고, 통합 테스트는 Task 3에서 수정한다.

현재 `test_harness_stops_on_build_failed_and_keeps_unchecked_criteria`는 `_verify_and_update_chunk`가 BUILD_FAILED를 반환하는 것 자체는 변하지 않으므로 아직 통과해야 한다. 확인:

Run: `pytest tests/test_codex_harness.py::test_harness_stops_on_build_failed_and_keeps_unchecked_criteria -v`
Expected: PASS (BUILD_FAILED 자체는 동일, escalate 분기는 Task 3에서 변경)

- [ ] **Step 7: 전체 테스트 실행**

Run: `pytest tests/test_codex_harness.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/cowork_pilot/codex/harness.py tests/test_codex_harness.py tests/fixtures/sample_exec_plan_build_partial.md
git commit -m "refactor: remove force-check from _verify_and_update_chunk, return INCOMPLETE instead"
```

---

## Chunk 2: config + build-repair prompt

### Task 2: `CodexExecConfig`에 `build_repair_max_retries` 추가

**Files:**
- Modify: `src/cowork_pilot/codex/config.py:18-25`
- Modify: `config.toml`
- Test: `tests/test_codex_harness.py` (config 로딩은 기존 테스트로 커버)

- [ ] **Step 1: config 필드 추가 — 테스트 작성**

```python
def test_codex_exec_config_loads_build_repair_max_retries(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[codex.exec]\n"
        "command = \"codex\"\n"
        "build_repair_max_retries = 5\n",
        encoding="utf-8",
    )
    from cowork_pilot.codex.config import load_codex_exec_config
    cfg = load_codex_exec_config(config_file)
    assert cfg.build_repair_max_retries == 5


def test_codex_exec_config_default_build_repair_max_retries():
    from cowork_pilot.codex.config import CodexExecConfig
    cfg = CodexExecConfig()
    assert cfg.build_repair_max_retries == 3
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_codex_harness.py::test_codex_exec_config_loads_build_repair_max_retries tests/test_codex_harness.py::test_codex_exec_config_default_build_repair_max_retries -v`
Expected: FAIL — `build_repair_max_retries` 필드 없음

- [ ] **Step 3: `CodexExecConfig` + `load_codex_exec_config` 수정**

`src/cowork_pilot/codex/config.py`:

```python
@dataclass
class CodexExecConfig:
    """Configuration for ``codex exec`` plan execution."""
    command: str = "codex"
    extra_args: list[str] = field(default_factory=list)
    build_timeout_seconds: float = 1800.0
    stalled_output_timeout_seconds: float = 600.0
    max_retries: int = 3
    build_repair_max_retries: int = 3
```

`load_codex_exec_config`의 `exec_section` 블록에 추가:

```python
cfg.build_repair_max_retries = exec_section.get(
    "build_repair_max_retries", cfg.build_repair_max_retries
)
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_codex_harness.py::test_codex_exec_config_loads_build_repair_max_retries tests/test_codex_harness.py::test_codex_exec_config_default_build_repair_max_retries -v`
Expected: PASS

- [ ] **Step 5: `config.toml` 업데이트**

`config.toml`의 `[codex.exec]` 섹션에 추가:

```toml
build_repair_max_retries = 3
```

- [ ] **Step 6: Commit**

```bash
git add src/cowork_pilot/codex/config.py config.toml tests/test_codex_harness.py
git commit -m "feat: add build_repair_max_retries to CodexExecConfig"
```

### Task 3: build-repair 전용 prompt builder

**Files:**
- Modify: `src/cowork_pilot/codex/harness.py` (새 함수 `_build_repair_prompt`)
- Test: `tests/test_codex_harness.py`

- [ ] **Step 1: prompt 테스트 작성**

```python
def test_build_repair_prompt_contains_required_sections(tmp_path):
    """build-repair prompt에는 원래 session prompt, 에러 로그, 수리 지시,
    [BUILD] 실행 금지가 포함되어야 한다.
    code-review/chunk-complete 스킬 레퍼런스는 포함하면 안 된다."""
    from cowork_pilot.codex.harness import _build_repair_prompt

    plan_path = tmp_path / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    prompt = _build_repair_prompt(
        chunk,
        str(tmp_path),
        "Error: Cannot find module './App'\nnpm ERR! code ELIFECYCLE",
    )

    # 필수 포함
    assert "Build Repair Mode" in prompt
    assert "프로젝트 설정을 완료하라" in prompt  # original session prompt
    assert "Cannot find module './App'" in prompt  # error log
    assert "최소 수정" in prompt
    assert "비빌드" in prompt  # non-build criteria 유지 지시
    assert "[BUILD] 항목은 직접 실행하지 말 것" in prompt

    # 포함하면 안 됨
    assert "code-review" not in prompt.lower() or "Skill Reference: code-review" not in prompt
    assert "chunk-complete" not in prompt.lower() or "Skill Reference: chunk-complete" not in prompt
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_codex_harness.py::test_build_repair_prompt_contains_required_sections -v`
Expected: FAIL — `_build_repair_prompt` 없음

- [ ] **Step 3: `_build_repair_prompt` 구현**

`src/cowork_pilot/codex/harness.py`에 추가:

```python
def _build_repair_prompt(chunk: Chunk, project_dir: str, build_error_log: str) -> str:
    """Build a focused prompt for build-repair retry.

    Includes the original session prompt for context, the build error log,
    and strict instructions to preserve existing implementation while making
    minimal fixes.  Does NOT include code-review or chunk-complete skill
    references — this is a focused fix, not a full implementation pass.
    """
    header = (
        f"You are working on: Chunk {chunk.number} — {chunk.name}\n"
        f"Project directory: {project_dir}\n"
        f"\n"
        f"## Build Repair Mode\n"
        f"\n"
        f"이 chunk의 구현은 완료되었으나 로컬 빌드가 실패했다.\n"
        f"비빌드 Completion Criteria는 이미 통과한 상태이므로 유지할 것.\n"
        f"기존 구현 의도를 보존하고 최소 수정으로 빌드 오류만 해결할 것.\n"
        f"\n"
    )
    original = (
        f"### Original Session Prompt (맥락 참고용)\n"
        f"{chunk.session_prompt}\n"
        f"\n"
    )
    error = (
        f"### Build Error Log\n"
        f"```\n"
        f"{build_error_log}\n"
        f"```\n"
        f"\n"
    )
    footer = (
        f"수정 후 [BUILD] 항목은 직접 실행하지 말 것 — 로컬 harness가 자동으로 실행한다.\n"
        f"exec-plan 파일의 체크박스를 변경하지 말 것.\n"
    )
    return header + original + error + footer
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_codex_harness.py::test_build_repair_prompt_contains_required_sections -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cowork_pilot/codex/harness.py tests/test_codex_harness.py
git commit -m "feat: add _build_repair_prompt for build-repair retry"
```

---

## Chunk 3: build-repair loop + harness 통합

### Task 4: `_run_build_repair_loop` 구현

**Files:**
- Modify: `src/cowork_pilot/codex/harness.py` (새 async 함수 `_run_build_repair_loop`)
- Test: `tests/test_codex_harness.py`

- [ ] **Step 1: repair loop 테스트 — 1회 만에 성공**

```python
def test_build_repair_loop_succeeds_on_first_attempt(tmp_path, monkeypatch):
    """build-repair 1회차에서 빌드 통과 → COMPLETED 반환."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    repair_call_count = 0

    async def fake_run_chunk_with_retry(*args, **kwargs):
        nonlocal repair_call_count
        repair_call_count += 1
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    # After repair, build passes → all criteria checked
    verify_calls = [0]
    def fake_verify(plan_path, chunk, project_dir, build_timeout=600.0):
        verify_calls[0] += 1
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR! code ELIFECYCLE",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert repair_call_count == 1
    assert verify_calls[0] == 1
```

- [ ] **Step 2: repair loop 테스트 — 2회째 성공**

```python
def test_build_repair_loop_succeeds_on_second_attempt(tmp_path, monkeypatch):
    """1회차 빌드 여전히 실패, 2회차에 통과 → COMPLETED."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )

    verify_calls = [0]
    def fake_verify(plan_path, chunk, project_dir, build_timeout=600.0):
        verify_calls[0] += 1
        if verify_calls[0] == 1:
            return ("BUILD_FAILED", "still failing")
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR! initial error",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert verify_calls[0] == 2
```

- [ ] **Step 3: repair loop 테스트 — 전부 실패 → BUILD_FAILED**

```python
def test_build_repair_loop_exhausts_retries(tmp_path, monkeypatch):
    """모든 repair 시도 실패 → BUILD_FAILED 반환."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        lambda *args, **kwargs: ("BUILD_FAILED", "persistent error"),
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR!",
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    assert status == "BUILD_FAILED"
    assert "persistent error" in detail
```

- [ ] **Step 4: repair loop 테스트 — codex exec 자체 실패**

```python
def test_build_repair_loop_handles_codex_exec_failure(tmp_path, monkeypatch):
    """codex exec 자체가 실패하면 해당 attempt를 소모하고 다음으로."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    call_count = [0]
    async def fake_run_chunk_with_retry(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ChunkResult(
                chunk_number=1,
                chunk_name="Setup",
                status=ChunkRunStatus.FAILED,
                returncode=1,
                duration_seconds=1.0,
            )
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )

    verify_calls = [0]
    def fake_verify(*args, **kwargs):
        verify_calls[0] += 1
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR!",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert call_count[0] == 2  # 1st failed, 2nd succeeded
    assert verify_calls[0] == 1  # only called after successful codex exec
```

- [ ] **Step 5: 테스트 실행 — 전부 실패 확인**

Run: `pytest tests/test_codex_harness.py -k "build_repair_loop" -v`
Expected: FAIL — `_run_build_repair_loop` 없음

- [ ] **Step 6: `_run_build_repair_loop` 구현**

`src/cowork_pilot/codex/harness.py`에 추가:

```python
async def _run_build_repair_loop(
    plan_path: Path,
    chunk: Chunk,
    project_dir: str,
    build_error_log: str,
    exec_config: CodexExecConfig,
) -> tuple[str, str]:
    """Run build-repair retry loop.

    Sends a focused repair prompt to codex, then re-runs local build
    verification.  Repeats up to ``exec_config.build_repair_max_retries``
    times.  Each iteration uses the latest build error log so codex sees
    fresh diagnostics.

    Returns:
        (status, detail) — same contract as _verify_and_update_chunk.
    """
    max_attempts = exec_config.build_repair_max_retries

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Build repair attempt %d/%d for chunk %d",
            attempt, max_attempts, chunk.number,
        )
        print(
            f"  🔧 Build repair attempt {attempt}/{max_attempts}",
            file=sys.stderr,
        )

        repair_prompt = _build_repair_prompt(chunk, project_dir, build_error_log)

        def _repair_builder(c: Chunk, p: str, _prompt=repair_prompt) -> str:
            return _prompt

        result = await run_chunk_with_retry(
            chunk,
            project_dir,
            max_retries=1,
            codex_command=exec_config.command,
            codex_extra_args=exec_config.extra_args or None,
            timeout_seconds=exec_config.build_timeout_seconds,
            stalled_output_timeout_seconds=exec_config.stalled_output_timeout_seconds,
            prompt_builder=_repair_builder,
        )

        _print_chunk_result(result)

        if result.status != ChunkRunStatus.SUCCESS:
            logger.warning(
                "Build repair attempt %d: codex exec failed (%s)",
                attempt, result.status.value,
            )
            print(
                f"  ✗ Repair codex exec failed ({result.status.value})",
                file=sys.stderr,
            )
            continue

        # Re-verify: run local builds again
        verify_status, verify_detail = _verify_and_update_chunk(
            plan_path, chunk, project_dir,
            build_timeout=exec_config.build_timeout_seconds,
        )

        if verify_status != "BUILD_FAILED":
            return (verify_status, verify_detail)

        # Still failing — update error log for next attempt
        build_error_log = verify_detail
        logger.warning(
            "Build repair attempt %d: build still failing",
            attempt,
        )
        print(
            f"  ✗ Build still failing after repair attempt {attempt}",
            file=sys.stderr,
        )

    return ("BUILD_FAILED", build_error_log)
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_codex_harness.py -k "build_repair_loop" -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/cowork_pilot/codex/harness.py tests/test_codex_harness.py
git commit -m "feat: add _run_build_repair_loop for automatic build-repair retry"
```

### Task 5: `run_codex_harness` 메인 루프 분기 수정

**Files:**
- Modify: `src/cowork_pilot/codex/harness.py:381-404`
- Modify: `tests/test_codex_harness.py`

- [ ] **Step 1: 통합 테스트 — BUILD_FAILED → repair → 성공**

```python
def test_harness_runs_build_repair_on_build_failed(tmp_path, monkeypatch, capsys):
    """BUILD_FAILED 시 즉시 escalate하지 않고 build-repair loop 실행."""
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    run_calls = [0]
    async def fake_run_chunk_with_retry(*args, **kwargs):
        run_calls[0] += 1
        # On repair calls, check all checkboxes to simulate fix
        if run_calls[0] >= 2:
            text = plan_path.read_text(encoding="utf-8")
            text = text.replace("- [ ]", "- [x]")
            plan_path.write_text(text, encoding="utf-8")
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    build_calls = [0]
    def fake_build_criteria(*args, **kwargs):
        build_calls[0] += 1
        if build_calls[0] == 1:
            return ("FAILED", "npm run build exit 1")
        return ("PASSED", "")

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        fake_build_criteria,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda msg: escalations.append(msg),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *a, **kw: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    stderr = capsys.readouterr().err

    assert result is True  # plan completed
    assert "Build repair attempt" in stderr
    assert not escalations
    assert run_calls[0] >= 2  # initial + at least 1 repair
```

- [ ] **Step 2: 통합 테스트 — BUILD_FAILED → repair 전부 실패 → escalate**

```python
def test_harness_escalates_after_build_repair_exhausted(tmp_path, monkeypatch, capsys):
    """build-repair 모든 시도 실패 → escalate."""
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("FAILED", "persistent build error"),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda msg: escalations.append(msg),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *a, **kw: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    assert result is False
    assert any("build repair" in e.lower() or "BUILD_FAILED" in e for e in escalations)
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_codex_harness.py -k "harness_runs_build_repair or harness_escalates_after_build_repair" -v`
Expected: FAIL — 현재는 BUILD_FAILED에서 바로 escalate

- [ ] **Step 4: `run_codex_harness` 수정**

`src/cowork_pilot/codex/harness.py`의 메인 루프 (약 381~404행)를 수정:

```python
            if result.status == ChunkRunStatus.SUCCESS:
                # Verify + update checkboxes
                verify_status, verify_detail = _verify_and_update_chunk(
                    plan_path, chunk, project_dir,
                    build_timeout=exec_config.build_timeout_seconds,
                )
                if verify_status == "COMPLETED":
                    print(f"  ✓ Chunk {chunk.number} completed", file=sys.stderr)
                    if verify_detail:
                        print(f"    verify: {verify_detail}", file=sys.stderr)
                elif verify_status == "BUILD_FAILED":
                    # Enter build-repair loop
                    print(
                        f"  ⚠ Chunk {chunk.number}: build failed, entering repair loop",
                        file=sys.stderr,
                    )
                    if verify_detail:
                        print(f"    build error: {verify_detail[:200]}", file=sys.stderr)

                    repair_status, repair_detail = await _run_build_repair_loop(
                        plan_path=plan_path,
                        chunk=chunk,
                        project_dir=project_dir,
                        build_error_log=verify_detail,
                        exec_config=exec_config,
                    )
                    if repair_status == "COMPLETED":
                        print(
                            f"  ✓ Chunk {chunk.number} completed after build repair",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    repair: {repair_detail}", file=sys.stderr)
                    else:
                        print(
                            f"  ✗ Chunk {chunk.number}: build repair failed — {repair_status}",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    detail: {repair_detail[:200]}", file=sys.stderr)
                        _print_unchecked_criteria(plan_path, chunk.number)
                        notify_escalate(
                            f"Chunk {chunk.number} ({chunk.name}) build repair 실패 — "
                            f"{repair_status}: {repair_detail[:200]}"
                        )
                        all_chunks_ok = False
                        break
                else:
                    # INCOMPLETE — non-build criteria unchecked
                    print(
                        f"  ⚠ Chunk {chunk.number}: codex succeeded but verify={verify_status}",
                        file=sys.stderr,
                    )
                    if verify_detail:
                        print(f"    verify: {verify_detail}", file=sys.stderr)
                    _print_unchecked_criteria(plan_path, chunk.number)
                    notify_escalate(
                        f"Chunk {chunk.number} ({chunk.name}) verify 실패 — "
                        f"{verify_status}: {verify_detail}"
                    )
                    all_chunks_ok = False
                    break
```

- [ ] **Step 5: 기존 `test_harness_stops_on_build_failed_and_keeps_unchecked_criteria` 수정**

이 테스트는 BUILD_FAILED에서 바로 escalate를 기대했는데, 이제는 repair loop를 돌고 나서 escalate해야 한다. repair loop가 결국 실패하면 escalate하므로, mock을 조정:

```python
def test_harness_stops_on_build_failed_and_keeps_unchecked_criteria(
    tmp_path,
    monkeypatch,
    capsys,
):
    """BUILD_FAILED 후 repair loop도 실패하면 escalate + 체크박스 유지."""
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("FAILED", "npm run build exit 1"),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    stderr = capsys.readouterr().err
    after = plan_path.read_text(encoding="utf-8")

    assert result is False
    assert "- [ ] [BUILD] npm run lint" in after
    assert "- [ ] [BUILD] npm run build" in after
    assert escalations
    assert "Build repair attempt" in stderr
```

- [ ] **Step 6: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_codex_harness.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/cowork_pilot/codex/harness.py tests/test_codex_harness.py
git commit -m "feat: integrate build-repair loop into run_codex_harness main loop"
```

---

## Chunk 4: 최종 검증

- [ ] **Step 1: 전체 테스트 실행**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: dry-run으로 기존 기능 확인**

```bash
cd /path/to/project && python -m cowork_pilot.codex.main --dry-run
```
Expected: 기존 harness dry-run이 에러 없이 plan preview 출력
