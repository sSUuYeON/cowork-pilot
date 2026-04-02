# Local Build Runner Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completion Criteria의 `[BUILD]` 태그 항목을 로컬 머신에서 실행하여 VM 빌드를 대체한다.

**Architecture:** `plan_parser`가 `[BUILD]` 태그를 파싱하고, `completion_detector`가 로컬에서 `subprocess.run`으로 빌드를 실행하며, `session_manager`가 빌드 결과에 따라 피드백/완료 흐름을 제어한다. 기존 idle 감지 → 검증 → 피드백 루프를 그대로 활용한다.

**Tech Stack:** Python 3.10+, subprocess, pytest, dataclasses

**Spec:** `docs/specs/2026-04-02-local-build-runner-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/cowork_pilot/plan_parser.py` | Modify | `CompletionCriterion`에 `build_command` 필드 추가, `[BUILD]` 태그 파싱 |
| `src/cowork_pilot/completion_detector.py` | Modify | `run_local_build()`, `run_build_criteria()` 함수 추가 |
| `src/cowork_pilot/session_manager.py` | Modify | `build_session_prompt()` VM빌드금지 주입, `process_chunk()` 빌드 스텝 삽입 |
| `src/cowork_pilot/config.py` | Modify | `HarnessConfig`에 `build_timeout_seconds` 추가 |
| `config.toml` | Modify | `build_timeout_seconds` 항목 추가 |
| `tests/test_plan_parser.py` | Modify | `[BUILD]` 파싱 테스트 추가 |
| `tests/test_completion_detector.py` | Modify | 로컬 빌드 실행 테스트 추가 |
| `tests/test_session_manager.py` | Modify | 빌드 통합 흐름 테스트 추가 |
| `tests/fixtures/sample_exec_plan_build.md` | Create | `[BUILD]` 태그가 포함된 테스트 fixture |

---

## Chunk 1: plan_parser — [BUILD] 태그 파싱

### Task 1: CompletionCriterion에 build_command 필드 추가 + 파싱 로직

**Files:**
- Modify: `src/cowork_pilot/plan_parser.py:17-20` (CompletionCriterion 데이터클래스)
- Modify: `src/cowork_pilot/plan_parser.py:46-49` (regex patterns)
- Modify: `src/cowork_pilot/plan_parser.py:109-125` (_parse_completion_criteria)
- Create: `tests/fixtures/sample_exec_plan_build.md`
- Modify: `tests/test_plan_parser.py`

- [ ] **Step 1: 테스트 fixture 생성**

`tests/fixtures/sample_exec_plan_build.md` 파일을 생성한다:

```markdown
# Build Test Plan

## Metadata
- project_dir: /Users/test/build-project
- spec: docs/specs/sample.md
- created: 2026-04-02
- status: pending

---

## Chunk 1: Setup

### Completion Criteria
- [ ] vercel.json 파일 존재
- [ ] [BUILD] npm run lint
- [ ] [BUILD] npm run build

### Tasks
- Task 1: Vercel 설정
- Task 2: Lint 설정

### Session Prompt
```
프로젝트 설정을 완료하라.
```

---

## Chunk 2: No Build

### Completion Criteria
- [ ] README.md 파일 존재
- [x] [BUILD] npm run test

### Tasks
- Task 3: 문서 작성

### Session Prompt
```
문서를 작성하라.
```
```

- [ ] **Step 2: [BUILD] 파싱 실패 테스트 작성**

`tests/test_plan_parser.py` 파일 끝에 추가:

```python
class TestBuildTagParsing:
    """Tests for [BUILD] tag parsing in CompletionCriterion."""

    SAMPLE_BUILD_PLAN = Path(__file__).parent / "fixtures" / "sample_exec_plan_build.md"

    def test_build_command_parsed_from_tag(self):
        plan = parse_exec_plan(self.SAMPLE_BUILD_PLAN)
        chunk1 = plan.chunks[0]
        # 첫 번째 criterion: 일반 항목 (build_command 없음)
        assert chunk1.completion_criteria[0].build_command == ""
        assert chunk1.completion_criteria[0].description == "vercel.json 파일 존재"
        # 두 번째: [BUILD] npm run lint
        assert chunk1.completion_criteria[1].build_command == "npm run lint"
        assert chunk1.completion_criteria[1].description == "[BUILD] npm run lint"
        # 세 번째: [BUILD] npm run build
        assert chunk1.completion_criteria[2].build_command == "npm run build"

    def test_build_command_empty_for_non_build(self):
        plan = parse_exec_plan(self.SAMPLE_BUILD_PLAN)
        chunk2 = plan.chunks[1]
        # README 항목: 일반
        assert chunk2.completion_criteria[0].build_command == ""

    def test_checked_build_preserves_command(self):
        plan = parse_exec_plan(self.SAMPLE_BUILD_PLAN)
        chunk2 = plan.chunks[1]
        # [x] [BUILD] npm run test — 체크되었지만 build_command는 파싱됨
        assert chunk2.completion_criteria[1].build_command == "npm run test"
        assert chunk2.completion_criteria[1].checked is True

    def test_build_command_with_complex_command(self):
        """[BUILD] 뒤에 && 등 복잡한 명령이 와도 전체가 캡처된다."""
        criterion = CompletionCriterion(
            description="[BUILD] npm run lint && npm run build",
            checked=False,
            build_command="npm run lint && npm run build",
        )
        assert criterion.build_command == "npm run lint && npm run build"
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_plan_parser.py::TestBuildTagParsing -v`
Expected: FAIL — `CompletionCriterion` 에 `build_command` 필드가 없으므로 `TypeError`

- [ ] **Step 4: CompletionCriterion에 build_command 필드 추가**

`src/cowork_pilot/plan_parser.py` 수정:

```python
# 기존 (line 17-20):
@dataclass
class CompletionCriterion:
    """A single checkbox item under ``### Completion Criteria``."""
    description: str    # e.g. "pytest tests/test_models.py 통과"
    checked: bool       # True if [x], False if [ ]

# 변경:
@dataclass
class CompletionCriterion:
    """A single checkbox item under ``### Completion Criteria``."""
    description: str    # e.g. "pytest tests/test_models.py 통과"
    checked: bool       # True if [x], False if [ ]
    build_command: str = ""  # "[BUILD] npm run build" → "npm run build"
```

- [ ] **Step 5: [BUILD] 태그 정규식 추가**

`src/cowork_pilot/plan_parser.py`의 regex patterns 섹션에 추가 (line 49 아래):

```python
_RE_BUILD_TAG = re.compile(r"^\[BUILD\]\s+(.+)$")
```

- [ ] **Step 6: _parse_completion_criteria() 수정**

`src/cowork_pilot/plan_parser.py`의 `_parse_completion_criteria()` 함수 수정:

```python
def _parse_completion_criteria(body: list[str]) -> list[CompletionCriterion]:
    """Parse ``- [ ]`` / ``- [x]`` lines under ``### Completion Criteria``."""
    criteria: list[CompletionCriterion] = []
    in_section = False
    for line in body:
        stripped = line.strip()
        if stripped == "### Completion Criteria":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("### ") or stripped == "---":
                break
            m = _RE_CHECKBOX.match(stripped)
            if m:
                checked = m.group(1) == "x"
                desc = m.group(2).strip()
                build_cmd = ""
                bm = _RE_BUILD_TAG.match(desc)
                if bm:
                    build_cmd = bm.group(1).strip()
                criteria.append(CompletionCriterion(
                    description=desc,
                    checked=checked,
                    build_command=build_cmd,
                ))
    return criteria
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_plan_parser.py::TestBuildTagParsing -v`
Expected: 4 PASSED

- [ ] **Step 8: 기존 테스트 깨지지 않았는지 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_plan_parser.py -v`
Expected: ALL PASSED (기존 테스트는 `build_command` 기본값 "" 사용)

- [ ] **Step 9: 기존 fixture 호환성 테스트 추가**

`tests/test_plan_parser.py`의 `TestBuildTagParsing` 클래스에 추가:

```python
    def test_existing_fixture_backward_compatible(self):
        """기존 fixture (no [BUILD])도 build_command='' 로 정상 파싱."""
        SAMPLE_PLAN = Path(__file__).parent / "fixtures" / "sample_exec_plan.md"
        plan = parse_exec_plan(SAMPLE_PLAN)
        for chunk in plan.chunks:
            for cr in chunk.completion_criteria:
                assert cr.build_command == ""
```

- [ ] **Step 10: update_checkboxes_by_description() 헬퍼 구현**

`src/cowork_pilot/plan_parser.py` 끝에 추가 (Chunk 2에서 사용할 의존성):

```python
def update_checkboxes_by_description(path: Path, chunk_number: int, description: str) -> None:
    """Update ``- [ ]`` → ``- [x]`` for a specific criterion matched by description.

    Safer than index-based update when the file may change during long operations.
    Re-parses the file to find the correct index, then delegates to update_checkboxes().
    """
    plan = parse_exec_plan(path)
    for chunk in plan.chunks:
        if chunk.number == chunk_number:
            for i, cr in enumerate(chunk.completion_criteria):
                if cr.description == description and not cr.checked:
                    update_checkboxes(path, chunk_number, criteria_indices=[i])
                    return
            break
```

- [ ] **Step 11: update_checkboxes_by_description 테스트**

`tests/test_plan_parser.py`에 추가:

```python
class TestUpdateCheckboxesByDescription:
    """Tests for description-based checkbox update."""

    def test_updates_matching_description(self, tmp_path):
        import shutil
        SAMPLE_BUILD_PLAN = Path(__file__).parent / "fixtures" / "sample_exec_plan_build.md"
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_BUILD_PLAN, dest)

        from cowork_pilot.plan_parser import update_checkboxes_by_description
        update_checkboxes_by_description(dest, 1, "[BUILD] npm run lint")

        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]
        assert chunk1.completion_criteria[0].checked is False  # 일반 항목
        assert chunk1.completion_criteria[1].checked is True   # [BUILD] lint → 체크됨
        assert chunk1.completion_criteria[2].checked is False  # [BUILD] build → 그대로

    def test_no_match_does_nothing(self, tmp_path):
        import shutil
        SAMPLE_BUILD_PLAN = Path(__file__).parent / "fixtures" / "sample_exec_plan_build.md"
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_BUILD_PLAN, dest)

        from cowork_pilot.plan_parser import update_checkboxes_by_description
        update_checkboxes_by_description(dest, 1, "존재하지 않는 항목")

        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]
        # 아무것도 변하지 않음
        assert chunk1.completion_criteria[0].checked is False
        assert chunk1.completion_criteria[1].checked is False
```

- [ ] **Step 12: 전체 plan_parser 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_plan_parser.py -v`
Expected: ALL PASSED

- [ ] **Step 13: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/plan_parser.py tests/test_plan_parser.py tests/fixtures/sample_exec_plan_build.md
git commit -m "feat(plan_parser): add [BUILD] tag parsing and update_checkboxes_by_description()"
```

---

## Chunk 2: completion_detector — 로컬 빌드 실행

### Task 2: run_local_build() 함수 추가

**Files:**
- Modify: `src/cowork_pilot/completion_detector.py`
- Modify: `tests/test_completion_detector.py`

- [ ] **Step 1: 테스트 작성 — 빌드 성공**

`tests/test_completion_detector.py` 끝에 추가:

```python
class TestRunLocalBuild:
    """Tests for run_local_build()."""

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        success, stdout, stderr = run_local_build("npm run build", "/tmp/project")
        assert success is True
        assert stdout == "OK\n"
        mock_run.assert_called_once_with(
            "npm run build",
            shell=True,
            cwd="/tmp/project",
            capture_output=True,
            text=True,
            timeout=600.0,
        )

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_failure_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: lint failed")
        success, stdout, stderr = run_local_build("npm run lint", "/tmp/project")
        assert success is False
        assert "lint failed" in stderr

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="build", timeout=600)
        success, stdout, stderr = run_local_build("cargo build", "/tmp/project", timeout=600.0)
        assert success is False
        assert "timed out" in stderr.lower()

    @patch("cowork_pilot.completion_detector.subprocess.run")
    def test_os_error(self, mock_run):
        mock_run.side_effect = OSError("No such command")
        success, stdout, stderr = run_local_build("nonexistent", "/tmp/project")
        assert success is False
        assert "No such command" in stderr
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_completion_detector.py::TestRunLocalBuild -v`
Expected: FAIL — `run_local_build` 가 import 안 됨

- [ ] **Step 3: run_local_build() 구현**

`src/cowork_pilot/completion_detector.py` 끝에 추가:

```python
# ── Local build execution ───────────────────────────────────────────

def run_local_build(
    command: str,
    project_dir: str,
    timeout: float = 600.0,
) -> tuple[bool, str, str]:
    """Run a build command locally via subprocess.

    Returns (success, stdout, stderr).
    """
    import sys as _sys
    print(f"  [build] Running: {command} (cwd={project_dir})", file=_sys.stderr)
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            print(f"  [build] ✓ exit code 0", file=_sys.stderr)
        else:
            print(f"  [build] ✗ exit code {result.returncode}", file=_sys.stderr)
        return (result.returncode == 0, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        print(f"  [build] ✗ timed out after {timeout}s", file=_sys.stderr)
        return (False, "", f"Build timed out after {timeout}s")
    except OSError as exc:
        print(f"  [build] ✗ OS error: {exc}", file=_sys.stderr)
        return (False, "", f"Build failed to start: {exc}")
```

- [ ] **Step 4: import 추가**

`tests/test_completion_detector.py` 상단 import에 `run_local_build` 추가:

```python
from cowork_pilot.completion_detector import (
    is_idle_trigger,
    build_verification_prompt,
    call_verification_cli,
    parse_verification_result,
    build_feedback_text,
    send_feedback,
    run_local_build,
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_completion_detector.py::TestRunLocalBuild -v`
Expected: 4 PASSED

- [ ] **Step 6: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/completion_detector.py tests/test_completion_detector.py
git commit -m "feat(completion_detector): add run_local_build() for local builds"
```

### Task 3: run_build_criteria() 함수 추가

**Files:**
- Modify: `src/cowork_pilot/completion_detector.py`
- Modify: `tests/test_completion_detector.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_completion_detector.py` 끝에 추가:

```python
class TestRunBuildCriteria:
    """Tests for run_build_criteria()."""

    def _make_chunk(self, criteria):
        return Chunk(
            name="Test", number=1,
            completion_criteria=criteria,
            session_prompt="test",
        )

    @patch("cowork_pilot.completion_detector.run_local_build")
    def test_no_build_criteria_returns_passed(self, mock_build):
        """[BUILD] 태그 없으면 즉시 PASSED."""
        chunk = self._make_chunk([
            CompletionCriterion("파일 존재", False),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        mock_build.assert_not_called()

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_all_builds_pass(self, mock_update, mock_build):
        """모든 [BUILD] 성공 시 PASSED + 체크박스 업데이트."""
        mock_build.return_value = (True, "OK", "")
        chunk = self._make_chunk([
            CompletionCriterion("파일 존재", False),
            CompletionCriterion("[BUILD] npm run lint", False, build_command="npm run lint"),
            CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        assert mock_build.call_count == 2
        assert mock_update.call_count == 2

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_first_build_fails_stops_early(self, mock_update, mock_build):
        """첫 빌드 실패 시 즉시 FAILED 반환, 두 번째 빌드 실행 안 함."""
        mock_build.return_value = (False, "", "Error: lint failed")
        chunk = self._make_chunk([
            CompletionCriterion("[BUILD] npm run lint", False, build_command="npm run lint"),
            CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "FAILED"
        assert "npm run lint" in detail
        mock_build.assert_called_once()
        mock_update.assert_not_called()

    @patch("cowork_pilot.completion_detector.run_local_build")
    def test_checked_build_skipped(self, mock_build):
        """이미 [x]인 [BUILD] 항목은 스킵."""
        chunk = self._make_chunk([
            CompletionCriterion("[BUILD] npm run lint", True, build_command="npm run lint"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "PASSED"
        mock_build.assert_not_called()

    def test_invalid_project_dir(self):
        """project_dir이 유효하지 않으면 FAILED."""
        chunk = self._make_chunk([
            CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
        ])
        status, detail = run_build_criteria(chunk, "", Path("/tmp/plan.md"))
        assert status == "FAILED"
        assert "project_dir" in detail

    @patch("cowork_pilot.completion_detector.run_local_build")
    @patch("cowork_pilot.plan_parser.update_checkboxes_by_description")
    def test_stderr_truncated_to_2000(self, mock_update, mock_build):
        """에러 로그가 2000자로 잘린다."""
        long_err = "x" * 5000
        mock_build.return_value = (False, "", long_err)
        chunk = self._make_chunk([
            CompletionCriterion("[BUILD] cargo build", False, build_command="cargo build"),
        ])
        status, detail = run_build_criteria(chunk, "/tmp", Path("/tmp/plan.md"))
        assert status == "FAILED"
        # detail에 에러 로그 포함, 2000자 이내
        assert len(detail) < 2200  # command name + newline overhead
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_completion_detector.py::TestRunBuildCriteria -v`
Expected: FAIL — `run_build_criteria` import 안 됨

- [ ] **Step 3: run_build_criteria() 구현**

> Note: `update_checkboxes_by_description()`는 Chunk 1 Step 10에서 이미 구현됨.



`src/cowork_pilot/completion_detector.py` 끝에 추가:

```python
def run_build_criteria(
    chunk: Chunk,
    project_dir: str,
    plan_path: "Path",
    timeout: float = 600.0,
) -> tuple[str, str]:
    """Run [BUILD]-tagged criteria locally via subprocess.

    Returns:
        ("PASSED", "") — all builds passed (or no [BUILD] items)
        ("FAILED", "error detail") — a build failed
    """
    from pathlib import Path as _Path

    # Validate project_dir
    if not project_dir or not _Path(project_dir).is_dir():
        return ("FAILED", f"project_dir이 유효하지 않음: {project_dir}")

    build_criteria = [
        (i, c) for i, c in enumerate(chunk.completion_criteria)
        if c.build_command and not c.checked
    ]

    if not build_criteria:
        return ("PASSED", "")

    import sys as _sys
    from cowork_pilot.plan_parser import update_checkboxes_by_description

    for idx, criterion in build_criteria:
        print(f"  [build] Running: {criterion.build_command}", file=_sys.stderr)
        success, stdout, stderr = run_local_build(
            criterion.build_command,
            project_dir,
            timeout=timeout,
        )

        if success:
            print(f"  [build] ✓ {criterion.build_command}", file=_sys.stderr)
            update_checkboxes_by_description(plan_path, chunk.number, criterion.description)
        else:
            error_log = stderr[-2000:] if stderr else stdout[-2000:]
            print(f"  [build] ✗ {criterion.build_command}", file=_sys.stderr)
            return ("FAILED", f"빌드 실패: {criterion.build_command}\n{error_log}")

    return ("PASSED", "")
```

- [ ] **Step 5: import 추가**

`tests/test_completion_detector.py` 상단:

```python
from cowork_pilot.completion_detector import (
    # ... 기존 imports ...
    run_local_build,
    run_build_criteria,
)
from cowork_pilot.plan_parser import Chunk, CompletionCriterion
from pathlib import Path
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_completion_detector.py::TestRunBuildCriteria -v`
Expected: 6 PASSED

- [ ] **Step 7: 전체 completion_detector 테스트 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_completion_detector.py -v`
Expected: ALL PASSED

- [ ] **Step 8: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/plan_parser.py src/cowork_pilot/completion_detector.py tests/test_completion_detector.py
git commit -m "feat(completion_detector): add run_build_criteria() for local build execution"
```

---

## Chunk 3: config + session_manager — 통합

### Task 4: HarnessConfig에 build_timeout_seconds 추가

**Files:**
- Modify: `src/cowork_pilot/config.py:40-57` (HarnessConfig)
- Modify: `src/cowork_pilot/config.py:208-241` (load_harness_config)
- Modify: `config.toml`

- [ ] **Step 1: config.py 수정 — HarnessConfig에 필드 추가**

`src/cowork_pilot/config.py`의 `HarnessConfig` 데이터클래스에 추가:

```python
@dataclass
class HarnessConfig:
    """Harness-specific configuration (loaded from config.toml [harness])."""
    idle_timeout_seconds: float = 30.0
    completion_check_max_retries: int = 3
    incomplete_retry_max: int = 3
    exec_plans_dir: str = "docs/exec-plans"
    build_timeout_seconds: float = 600.0  # 로컬 빌드 타임아웃 (10분)

    # Session timing
    session_open_delay: float = 3.0
    # ... (나머지 동일)
```

- [ ] **Step 2: load_harness_config()에 로딩 추가**

`load_harness_config()` 함수 내부, `harness.exec_plans_dir` 할당 아래에 추가:

```python
harness.build_timeout_seconds = h.get("build_timeout_seconds", harness.build_timeout_seconds)
```

- [ ] **Step 3: config.toml에 항목 추가**

```toml
[harness]
idle_timeout_seconds = 30
completion_check_max_retries = 3
incomplete_retry_max = 3
exec_plans_dir = "docs/exec-plans"
build_timeout_seconds = 600
```

- [ ] **Step 4: 기존 config 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_config.py -v`
Expected: ALL PASSED

- [ ] **Step 5: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/config.py config.toml
git commit -m "feat(config): add build_timeout_seconds to HarnessConfig"
```

### Task 5: build_session_prompt() — VM 빌드 금지 주입

**Files:**
- Modify: `src/cowork_pilot/session_manager.py:33-73`
- Modify: `tests/test_session_manager.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_session_manager.py`의 `TestBuildSessionPrompt` 클래스에 추가:

```python
    def test_build_notice_injected_for_build_criteria(self):
        """[BUILD] 태그가 있는 chunk에 VM 빌드 금지 지시가 주입된다."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="코드를 작성하라.",
            completion_criteria=[
                CompletionCriterion("파일 존재", False),
                CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
            ],
        )
        result = build_session_prompt(chunk)
        assert "VM에서 실행하지 마라" in result
        assert "코드를 작성하라." in result

    def test_no_build_notice_without_build_criteria(self):
        """[BUILD] 태그 없으면 VM 빌드 금지 지시가 없다."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="코드를 작성하라.",
            completion_criteria=[
                CompletionCriterion("파일 존재", False),
            ],
        )
        result = build_session_prompt(chunk)
        assert "VM에서 실행하지 마라" not in result

    def test_no_build_notice_when_all_builds_checked(self):
        """모든 [BUILD]가 이미 [x]이면 VM 빌드 금지 지시가 없다."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="코드를 작성하라.",
            completion_criteria=[
                CompletionCriterion("[BUILD] npm run build", True, build_command="npm run build"),
            ],
        )
        result = build_session_prompt(chunk)
        assert "VM에서 실행하지 마라" not in result

    def test_build_notice_with_review_config(self):
        """[BUILD] + review 둘 다 있으면 둘 다 주입."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="코드를 작성하라.",
            completion_criteria=[
                CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
            ],
        )
        rc = ReviewConfig(enabled=True, skip_chunks=[])
        result = build_session_prompt(chunk, review_config=rc)
        assert "VM에서 실행하지 마라" in result
        assert "/engineering:code-review" in result
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_session_manager.py::TestBuildSessionPrompt::test_build_notice_injected_for_build_criteria -v`
Expected: FAIL — VM 빌드 금지 텍스트가 없음

- [ ] **Step 3: session_manager.py 수정**

`src/cowork_pilot/session_manager.py`에 추가/수정:

```python
LOCAL_BUILD_NOTICE = """\

⚠️ 이 Chunk의 Completion Criteria에 [BUILD] 태그 항목이 있다.
[BUILD] 태그가 붙은 빌드/테스트 명령은 VM에서 실행하지 마라.
로컬 harness가 자동으로 실행한다.
빌드/테스트를 제외한 나머지 작업(코드 작성, 파일 생성 등)만 수행해라."""


def _chunk_has_build_criteria(chunk: Chunk) -> bool:
    """Check if chunk has any unchecked [BUILD] criteria."""
    return any(
        c.build_command and not c.checked
        for c in chunk.completion_criteria
    )


def build_session_prompt(
    chunk: Chunk,
    review_config: ReviewConfig | None = None,
) -> str:
    prompt = chunk.session_prompt

    if _chunk_has_build_criteria(chunk):
        prompt += LOCAL_BUILD_NOTICE

    if review_config is None or not review_config.enabled:
        return prompt

    if chunk.number in review_config.skip_chunks:
        return prompt

    return prompt + REVIEW_INSTRUCTIONS
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_session_manager.py::TestBuildSessionPrompt -v`
Expected: ALL PASSED

- [ ] **Step 5: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/session_manager.py tests/test_session_manager.py
git commit -m "feat(session_manager): inject VM build notice for [BUILD] chunks"
```

### Task 6: process_chunk() — 빌드 스텝 삽입

**Files:**
- Modify: `src/cowork_pilot/session_manager.py:277-317` (process_chunk)
- Modify: `tests/test_session_manager.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_session_manager.py`의 `TestProcessChunk` 클래스에 추가:

```python
    def test_build_failure_sends_feedback(self):
        """[BUILD] 실패 시 피드백 전송 + INCOMPLETE 반환."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="test",
            completion_criteria=[
                CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
            ],
        )
        retry = ChunkRetryState()

        def mock_build(c, pd, pp, timeout=600.0):
            return ("FAILED", "Error: build failed")

        result = process_chunk(
            Path("/tmp/plan.md"), chunk, HarnessConfig(), "/tmp",
            retry, build_fn=mock_build, feedback_fn=lambda t: True,
        )
        assert result == "INCOMPLETE"
        assert retry.incomplete_feedback_count == 1

    def test_build_success_sends_review_feedback(self):
        """[BUILD] 성공 시 code-review 피드백 전송 + INCOMPLETE (Claude가 스킬 실행해야 하므로)."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="test",
            completion_criteria=[
                CompletionCriterion("파일 존재", False),
                CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
            ],
        )
        retry = ChunkRetryState()
        feedback_texts = []

        def mock_build(c, pd, pp, timeout=600.0):
            return ("PASSED", "")

        def mock_feedback(text):
            feedback_texts.append(text)
            return True

        result = process_chunk(
            Path("/tmp/plan.md"), chunk, HarnessConfig(), "/tmp",
            retry, build_fn=mock_build, feedback_fn=mock_feedback,
        )
        assert result == "INCOMPLETE"
        assert len(feedback_texts) == 1
        assert "통과" in feedback_texts[0]

    def test_no_build_criteria_falls_through_to_verify(self):
        """[BUILD] 없으면 기존 검증 로직으로 바로 진행."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="test",
            completion_criteria=[
                CompletionCriterion("파일 존재", True),
            ],
        )
        retry = ChunkRetryState()

        def mock_verify(c, hc, pd, plan_path=None):
            return ("COMPLETED", "")

        def mock_build(c, pd, pp, timeout=600.0):
            return ("PASSED", "")

        result = process_chunk(
            Path("/tmp/plan.md"), chunk, HarnessConfig(), "/tmp",
            retry, verify_fn=mock_verify, build_fn=mock_build,
        )
        assert result == "COMPLETED"

    def test_build_failure_escalates_after_max_retries(self):
        """빌드 실패가 max retries 초과 시 ESCALATE."""
        chunk = Chunk(
            name="Test", number=1,
            session_prompt="test",
            completion_criteria=[
                CompletionCriterion("[BUILD] npm run build", False, build_command="npm run build"),
            ],
        )
        retry = ChunkRetryState(incomplete_feedback_count=3)  # 이미 3회

        def mock_build(c, pd, pp, timeout=600.0):
            return ("FAILED", "error")

        result = process_chunk(
            Path("/tmp/plan.md"), chunk, HarnessConfig(), "/tmp",
            retry, build_fn=mock_build, feedback_fn=lambda t: True,
        )
        assert result == "ESCALATE"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_session_manager.py::TestProcessChunk::test_build_failure_sends_feedback -v`
Expected: FAIL — `build_fn` 파라미터가 없음

- [ ] **Step 3: process_chunk() 수정**

`src/cowork_pilot/session_manager.py`의 `process_chunk()` 함수 전체를 교체:

```python
def process_chunk(
    plan_path: Path,
    chunk: Chunk,
    harness_config: HarnessConfig,
    project_dir: str,
    retry_state: ChunkRetryState,
    # Callbacks for testing — allow injection of mock functions
    verify_fn=None,
    feedback_fn=None,
    build_fn=None,
) -> str:
    """Process the verification/feedback cycle for one chunk.

    Returns:
    - "COMPLETED" — chunk is done, checkboxes updated
    - "INCOMPLETE" — feedback sent (build fail or success → awaiting skills)
    - "ESCALATE" — retries exhausted, needs human intervention
    - "ERROR" — CLI verification failed
    """
    if verify_fn is None:
        verify_fn = run_chunk_verification
    if feedback_fn is None:
        feedback_fn = send_feedback
    if build_fn is None:
        from cowork_pilot.completion_detector import run_build_criteria
        build_fn = run_build_criteria

    # ── Step 1: Run [BUILD] criteria locally ──
    # Re-read plan to get fresh checkbox state
    try:
        fresh_plan = parse_exec_plan(plan_path)
    except (OSError, ValueError):
        fresh_plan = None

    fresh_chunk = None
    if fresh_plan:
        for c in fresh_plan.chunks:
            if c.number == chunk.number:
                fresh_chunk = c
                break

    if fresh_chunk is not None:
        # Check if there are unchecked [BUILD] items
        has_unchecked_builds = any(
            c.build_command and not c.checked
            for c in fresh_chunk.completion_criteria
        )

        if has_unchecked_builds:
            build_status, build_detail = build_fn(
                fresh_chunk, project_dir, plan_path,
                timeout=harness_config.build_timeout_seconds,
            )

            if build_status == "FAILED":
                retry_state.incomplete_feedback_count += 1
                if retry_state.incomplete_feedback_count > harness_config.incomplete_retry_max:
                    return "ESCALATE"
                feedback_text = (
                    f"로컬 빌드 실패:\n{build_detail}\n\n"
                    f"코드를 수정하고 다시 idle 상태로 대기해라."
                )
                feedback_fn(feedback_text)
                return "INCOMPLETE"

            # PASSED — all builds succeeded, checkboxes already marked [x]
            # Send feedback for Claude to run code-review + chunk-complete
            has_build_criteria = any(
                c.build_command for c in fresh_chunk.completion_criteria
            )
            if has_build_criteria:
                feedback_text = (
                    "로컬 빌드/테스트 전체 통과 ✓\n\n"
                    "이제 /engineering:code-review → /chunk-complete:chunk-complete 순서로 진행해라."
                )
                feedback_fn(feedback_text)
                return "INCOMPLETE"

    # ── Step 2: Standard checkbox verification ──
    status, detail = verify_fn(chunk, harness_config, project_dir, plan_path=plan_path)

    if status == "COMPLETED":
        handle_chunk_completion(plan_path, chunk)
        return "COMPLETED"

    elif status == "INCOMPLETE":
        retry_state.incomplete_feedback_count += 1
        if retry_state.incomplete_feedback_count > harness_config.incomplete_retry_max:
            return "ESCALATE"
        feedback_text = build_feedback_text(detail)
        feedback_fn(feedback_text)
        return "INCOMPLETE"

    else:  # ERROR
        retry_state.cli_failure_count += 1
        if retry_state.cli_failure_count > harness_config.completion_check_max_retries:
            return "ESCALATE"
        return "ERROR"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_session_manager.py::TestProcessChunk -v`
Expected: ALL PASSED (기존 + 신규)

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/ -v`
Expected: ALL PASSED

- [ ] **Step 6: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add src/cowork_pilot/session_manager.py tests/test_session_manager.py
git commit -m "feat(session_manager): integrate local build into process_chunk()"
```

---

## Chunk 4: 통합 테스트 + 검증

### Task 7: End-to-End 통합 테스트

**Files:**
- Create: `tests/test_local_build_integration.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
"""End-to-end integration tests for local build runner feature."""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowork_pilot.config import HarnessConfig, ReviewConfig
from cowork_pilot.plan_parser import CompletionCriterion, Chunk, parse_exec_plan, update_checkboxes_by_description
from cowork_pilot.completion_detector import run_build_criteria, run_local_build
from cowork_pilot.session_manager import (
    ChunkRetryState,
    build_session_prompt,
    process_chunk,
)

SAMPLE_BUILD_PLAN = Path(__file__).parent / "fixtures" / "sample_exec_plan_build.md"


class TestLocalBuildIntegration:
    """Full roundtrip: parse → build → update → re-parse."""

    def test_full_roundtrip(self, tmp_path):
        """Parse plan → run builds → checkboxes updated → re-parse shows completed."""
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_BUILD_PLAN, dest)

        # Parse
        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]
        assert chunk1.completion_criteria[1].build_command == "npm run lint"
        assert chunk1.completion_criteria[2].build_command == "npm run build"

        # Simulate successful builds
        with patch("cowork_pilot.completion_detector.run_local_build") as mock_build:
            mock_build.return_value = (True, "OK", "")
            status, detail = run_build_criteria(chunk1, str(tmp_path), dest)
            assert status == "PASSED"

        # Re-parse and verify checkboxes updated
        plan2 = parse_exec_plan(dest)
        chunk1_fresh = plan2.chunks[0]
        assert chunk1_fresh.completion_criteria[0].checked is False  # 일반 항목
        assert chunk1_fresh.completion_criteria[1].checked is True   # [BUILD] lint
        assert chunk1_fresh.completion_criteria[2].checked is True   # [BUILD] build

    def test_build_session_prompt_integration(self):
        """[BUILD] chunk에 VM 금지 + review 지시 모두 포함."""
        plan = parse_exec_plan(SAMPLE_BUILD_PLAN)
        chunk1 = plan.chunks[0]

        rc = ReviewConfig(enabled=True, skip_chunks=[])
        prompt = build_session_prompt(chunk1, review_config=rc)

        assert "VM에서 실행하지 마라" in prompt
        assert "/engineering:code-review" in prompt
        assert chunk1.session_prompt in prompt

    def test_process_chunk_build_then_verify(self, tmp_path):
        """process_chunk: 빌드 통과 → INCOMPLETE (스킬 대기) → 다시 호출 → COMPLETED."""
        dest = tmp_path / "plan.md"
        shutil.copy(SAMPLE_BUILD_PLAN, dest)

        plan = parse_exec_plan(dest)
        chunk1 = plan.chunks[0]
        retry = ChunkRetryState()
        hc = HarnessConfig(build_timeout_seconds=60.0)

        # 1st call: builds pass → INCOMPLETE (awaiting code-review)
        def mock_build_pass(c, pd, pp, timeout=600.0):
            return ("PASSED", "")

        result = process_chunk(
            dest, chunk1, hc, str(tmp_path), retry,
            build_fn=mock_build_pass,
            feedback_fn=lambda t: True,
        )
        assert result == "INCOMPLETE"

        # Simulate: Claude ran code-review + chunk-complete → all checkboxes now [x]
        # Manually check all boxes
        from cowork_pilot.plan_parser import update_checkboxes
        update_checkboxes(dest, 1)  # Check all criteria in chunk 1

        # 2nd call: all checked → COMPLETED
        def mock_verify_completed(c, hc, pd, plan_path=None):
            return ("COMPLETED", "")

        result2 = process_chunk(
            dest, chunk1, hc, str(tmp_path), retry,
            verify_fn=mock_verify_completed,
            build_fn=mock_build_pass,
            feedback_fn=lambda t: True,
        )
        assert result2 == "COMPLETED"
```

- [ ] **Step 2: 통합 테스트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/test_local_build_integration.py -v`
Expected: ALL PASSED

- [ ] **Step 3: 전체 테스트 스위트 통과 확인**

Run: `cd /sessions/loving-zealous-pascal/mnt/cowork-pilot && python -m pytest tests/ -v`
Expected: ALL PASSED

- [ ] **Step 4: 커밋**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add tests/test_local_build_integration.py
git commit -m "test: add end-to-end integration tests for local build runner"
```

- [ ] **Step 5: 최종 커밋 — 스펙 문서**

```bash
cd /sessions/loving-zealous-pascal/mnt/cowork-pilot
git add docs/specs/2026-04-02-local-build-runner-design.md docs/specs/2026-04-02-local-build-runner-plan.md
git commit -m "docs: add local build runner design spec and implementation plan"
```
