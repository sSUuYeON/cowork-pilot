# Local Build Runner — 로컬 빌드/테스트 실행 기능

## 개요

Cowork 세션의 VM 대신 로컬 머신에서 빌드/테스트를 실행하여 harness 모드의 전체 작업 시간을 단축한다.

## 동기

현재 harness 모드에서 Claude는 VM의 Bash 도구로 빌드/테스트를 실행한다. VM 환경은 리소스가 제한적이고 플랫폼 오버헤드가 있어 대규모 프로젝트의 빌드 시간이 과도하게 길어진다. 로컬 머신의 풀 CPU/메모리를 활용하면 빌드 자체가 빠르고, Claude가 빌드 완료를 기다리며 세션을 점유하는 시간도 제거된다.

## 설계 결정

- **실행 방식**: `subprocess.run` 직접 실행 (claude CLI 위임 아님). 오버헤드 없이 빌드 명령을 바로 실행하고 stdout/stderr를 캡처한다.
- **에러 전달**: stderr 원문 그대로 (마지막 2000자). 정보 손실 없음.
- **명령 지정**: exec-plan의 Completion Criteria에 `[BUILD]` 태그로 명시. 기존 체크박스 포맷과 자연스럽게 호환.
- **타임아웃**: 600초 (10분) 기본값. `config.toml`에서 변경 가능.

## 현재 흐름

```
1. 세션 열림 → Claude가 코드 작성 + VM에서 빌드/테스트
2. JSONL 기록 멈춤 → 30초 idle 감지
3. process_chunk() → 체크박스 확인 → 다음 chunk
```

## 변경 후 흐름

```
1. 세션 열림 → Claude가 코드만 작성 (VM 빌드 금지 지시 자동 주입)
2. JSONL 기록 멈춤 → 30초 idle 감지
3. process_chunk() 호출
4. Completion Criteria에서 [BUILD] 태그 파싱
   - [BUILD] 항목 있고 미체크([ ]) → 로컬에서 subprocess.run 실행
     - 성공 → 해당 [BUILD] 체크박스 자동 체크([x])
     - 실패 → 에러 로그를 Cowork 세션에 피드백 → Claude가 수정 → 다시 idle → 재시도
   - [BUILD] 항목 없거나 이미 체크([x]) → 스킵
5. [BUILD] 통과 후 빌드 성공 피드백 전달
   → Claude가 /engineering:code-review + /chunk-complete:chunk-complete 실행
6. 다시 idle 감지 → 체크박스 전체 확인 → 다음 chunk
```

## exec-plan 포맷

### Completion Criteria 내 [BUILD] 태그

```markdown
### Completion Criteria
- [ ] vercel.json 파일 존재
- [ ] [BUILD] npm run lint
- [ ] [BUILD] npm run build
```

`[BUILD]` 태그가 붙은 항목은 harness가 로컬에서 실행할 명령어다. `[BUILD]` 뒤의 텍스트 전체가 `shell=True`로 실행된다.

`[BUILD]` 태그가 없는 항목은 기존과 동일하게 Cowork 세션 내에서 처리된다.

### 중복 실행 방지

이미 `[x]`로 체크된 `[BUILD]` 항목은 실행하지 않는다. 빌드 성공 시 즉시 `[x]`로 체크하므로, 다음 idle 사이클에서 다시 실행되지 않는다.

## 수정 파일

### 1. `plan_parser.py`

**변경 사항**: `CompletionCriterion` 데이터클래스에 `build_command` 필드 추가. `_parse_completion_criteria()`에서 `[BUILD]` 태그 파싱.

```python
# 변경 전
@dataclass
class CompletionCriterion:
    description: str
    checked: bool

# 변경 후
@dataclass
class CompletionCriterion:
    description: str
    checked: bool
    build_command: str = ""  # "[BUILD] npm run build" → "npm run build"
```

파싱 로직:
```python
_RE_BUILD_TAG = re.compile(r"^\[BUILD\]\s+(.+)$")

# _parse_completion_criteria() 내부:
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
```

### 2. `completion_detector.py`

**변경 사항**: `run_local_build()` 함수 추가. `process_chunk()` 전에 호출되는 `run_build_criteria()` 함수 추가.

```python
def run_local_build(
    command: str,
    project_dir: str,
    timeout: float = 600.0,
) -> tuple[bool, str, str]:
    """로컬에서 빌드 명령을 실행한다.

    Returns:
        (success, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (
            result.returncode == 0,
            result.stdout,
            result.stderr,
        )
    except subprocess.TimeoutExpired:
        return (False, "", f"Build timed out after {timeout}s")
    except OSError as exc:
        return (False, "", f"Build failed to start: {exc}")


def run_build_criteria(
    chunk: Chunk,
    project_dir: str,
    plan_path: Path,
    timeout: float = 600.0,
) -> tuple[str, str]:
    """Chunk의 [BUILD] 태그 항목을 로컬에서 실행한다.

    Returns:
        ("PASSED", "") — 모든 빌드 성공 (또는 [BUILD] 없음)
        ("FAILED", "에러 로그") — 빌드 실패
    """
    build_criteria = [
        (i, c) for i, c in enumerate(chunk.completion_criteria)
        if c.build_command and not c.checked
    ]

    if not build_criteria:
        return ("PASSED", "")

    for idx, criterion in build_criteria:
        print(f"  [build] Running: {criterion.build_command}", file=sys.stderr)
        success, stdout, stderr = run_local_build(
            criterion.build_command,
            project_dir,
            timeout=timeout,
        )

        if success:
            print(f"  [build] ✓ {criterion.build_command}", file=sys.stderr)
            # 체크박스를 [x]로 업데이트
            update_checkboxes(plan_path, chunk.number, criteria_indices=[idx])
        else:
            error_log = stderr[-2000:] if stderr else stdout[-2000:]
            print(f"  [build] ✗ {criterion.build_command}", file=sys.stderr)
            return ("FAILED", f"빌드 실패: {criterion.build_command}\n{error_log}")

    return ("PASSED", "")
```

### 3. `session_manager.py`

**변경 사항**:
- `build_session_prompt()`에서 `[BUILD]` 태그가 있는 chunk의 프롬프트에 VM 빌드 금지 지시 자동 주입
- `process_chunk()`에서 체크박스 확인 전에 `run_build_criteria()` 호출

#### `build_session_prompt()` 변경

```python
LOCAL_BUILD_NOTICE = """\

⚠️ 이 Chunk의 Completion Criteria에 [BUILD] 태그 항목이 있다.
[BUILD] 태그가 붙은 빌드/테스트 명령은 VM에서 실행하지 마라.
로컬 harness가 자동으로 실행한다.
빌드/테스트를 제외한 나머지 작업(코드 작성, 파일 생성 등)만 수행해라."""


def _chunk_has_build_criteria(chunk: Chunk) -> bool:
    """Check if chunk has any unchecked [BUILD] criteria."""
    return any(c.build_command and not c.checked for c in chunk.completion_criteria)


def build_session_prompt(chunk, review_config=None):
    prompt = chunk.session_prompt

    # [BUILD] 태그가 있으면 VM 빌드 금지 지시 주입
    if _chunk_has_build_criteria(chunk):
        prompt += LOCAL_BUILD_NOTICE

    if review_config and review_config.enabled:
        if chunk.number not in review_config.skip_chunks:
            prompt += REVIEW_INSTRUCTIONS

    return prompt
```

#### `process_chunk()` 변경

```python
def process_chunk(
    plan_path, chunk, harness_config, project_dir, retry_state,
    verify_fn=None, feedback_fn=None, build_fn=None,
) -> str:
    if verify_fn is None:
        verify_fn = run_chunk_verification
    if feedback_fn is None:
        feedback_fn = send_feedback
    if build_fn is None:
        from cowork_pilot.completion_detector import run_build_criteria
        build_fn = run_build_criteria

    # ── Step 1: [BUILD] 항목 로컬 실행 ──
    # plan_path를 다시 읽어서 최신 체크박스 상태 반영
    fresh_plan = parse_exec_plan(plan_path)
    fresh_chunk = None
    for c in fresh_plan.chunks:
        if c.number == chunk.number:
            fresh_chunk = c
            break

    if fresh_chunk is not None:
        build_status, build_detail = build_fn(
            fresh_chunk, project_dir, plan_path,
            timeout=harness_config.build_timeout_seconds,
        )

        if build_status == "FAILED":
            retry_state.incomplete_feedback_count += 1
            if retry_state.incomplete_feedback_count > harness_config.incomplete_retry_max:
                return "ESCALATE"
            # 빌드 성공 피드백 + code-review/chunk-complete 지시
            feedback_text = (
                f"로컬 빌드 실패:\n{build_detail}\n\n"
                f"코드를 수정하고 다시 idle 상태로 대기해라."
            )
            feedback_fn(feedback_text)
            return "INCOMPLETE"

        if build_status == "PASSED":
            # [BUILD] 항목이 있었고 모두 통과한 경우
            # 빌드 성공 피드백 + code-review/chunk-complete 지시
            has_build = any(c.build_command for c in fresh_chunk.completion_criteria)
            if has_build:
                unchecked_non_build = [
                    c for c in fresh_chunk.completion_criteria
                    if not c.build_command and not c.checked
                ]
                # 아직 code-review / chunk-complete가 안 된 상태
                # → 피드백을 보내서 Claude가 마저 하게 함
                feedback_text = (
                    "로컬 빌드/테스트 전체 통과 ✓\n\n"
                    "이제 /engineering:code-review → /chunk-complete:chunk-complete 순서로 진행해라."
                )
                feedback_fn(feedback_text)
                return "INCOMPLETE"  # Claude가 스킬 실행 후 다시 idle → 다시 검증

    # ── Step 2: 기존 체크박스 검증 (모든 [BUILD] 이미 체크 상태) ──
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
    else:
        retry_state.cli_failure_count += 1
        if retry_state.cli_failure_count > harness_config.completion_check_max_retries:
            return "ESCALATE"
        return "ERROR"
```

### 4. `config.py`

**변경 사항**: `HarnessConfig`에 `build_timeout_seconds` 필드 추가.

```python
@dataclass
class HarnessConfig:
    # ... 기존 필드 ...
    build_timeout_seconds: float = 600.0  # 로컬 빌드 타임아웃 (10분)
```

`load_harness_config()`에서 로딩:
```python
harness.build_timeout_seconds = h.get("build_timeout_seconds", harness.build_timeout_seconds)
```

### 5. `config.toml`

```toml
[harness]
idle_timeout_seconds = 30
completion_check_max_retries = 3
incomplete_retry_max = 3
exec_plans_dir = "docs/exec-plans"
build_timeout_seconds = 600  # 로컬 빌드 타임아웃 (초)
```

## 상세 시퀀스 다이어그램

```
Harness                    Local Shell              Cowork Session (Claude)
  │                            │                         │
  │ ── open_chunk_session() ──────────────────────────→ │ 코드 작성 시작
  │    (프롬프트에 VM빌드금지 주입됨)                      │ (빌드 안 함)
  │                            │                         │
  │ ← ── JSONL idle 30s ─────────────────────────────── │ 코드 작성 완료
  │                            │                         │
  │ ── run_build_criteria() ─→ │                         │
  │    subprocess.run(          │ npm run lint            │
  │      "npm run lint",       │ npm run build           │
  │      "npm run build")      │                         │
  │ ← ── (성공/실패) ───────── │                         │
  │                            │                         │
  │ [성공 시]                   │                         │
  │ ── update_checkboxes() ──→ │ (파일에 [x] 마킹)       │
  │ ── send_feedback() ──────────────────────────────→  │ code-review 실행
  │    "빌드 통과. code-review                           │ chunk-complete 실행
  │     + chunk-complete 해라"                           │
  │                            │                         │
  │ ← ── JSONL idle 30s ─────────────────────────────── │ 스킬 완료
  │                            │                         │
  │ ── run_chunk_verification()│                         │
  │    (모든 체크박스 [x] 확인) │                         │
  │ ── COMPLETED → 다음 chunk  │                         │
  │                            │                         │
  │ [실패 시]                   │                         │
  │ ── send_feedback() ──────────────────────────────→  │ 에러 보고 코드 수정
  │    "빌드 실패: {stderr}"                             │
  │                            │                         │
  │ ← ── JSONL idle 30s ─────────────────────────────── │ 수정 완료
  │ ── run_build_criteria() ─→ │ (재시도)                 │
  │    ...반복...               │                         │
```

## 이중 실행 방지 메커니즘

1. `run_build_criteria()`는 `not c.checked`인 `[BUILD]` 항목만 실행
2. 빌드 성공 시 `update_checkboxes()`로 즉시 `[x]` 마킹 (파일에 기록)
3. 다음 idle 사이클에서 `fresh_plan`을 다시 파싱하면 해당 항목은 `checked=True`
4. 따라서 `run_build_criteria()`가 스킵 → 바로 Step 2 (체크박스 검증)로 진입

## 엣지 케이스 처리

### 빈 project_dir 검증

`run_build_criteria()`는 빌드 실행 전에 `project_dir`이 유효한 디렉토리인지 검증한다. 빈 문자열이거나 존재하지 않는 경로면 `("FAILED", "project_dir이 유효하지 않음: {project_dir}")` 을 즉시 반환한다.

```python
if not project_dir or not Path(project_dir).is_dir():
    return ("FAILED", f"project_dir이 유효하지 않음: {project_dir}")
```

### 빌드 중 exec-plan 파일 수정

장시간 빌드 중 Cowork 세션이 exec-plan 파일을 수정하면 체크박스 인덱스가 밀릴 수 있다. 이를 방지하기 위해 `update_checkboxes()`를 인덱스 기반이 아닌 description 매칭 기반으로 호출한다.

현재 `update_checkboxes()`는 `criteria_indices` (0-based 인덱스)를 받는데, 빌드 완료 후 파일을 다시 파싱해서 해당 description을 가진 항목의 인덱스를 재계산한 뒤 업데이트한다.

```python
# 빌드 성공 후 체크박스 업데이트
fresh = parse_exec_plan(plan_path)
for c in fresh.chunks:
    if c.number == chunk.number:
        for i, cr in enumerate(c.completion_criteria):
            if cr.description == criterion.description and not cr.checked:
                update_checkboxes(plan_path, chunk.number, criteria_indices=[i])
                break
        break
```

## 영향 범위

| 파일 | 변경 | 위험도 |
|------|------|--------|
| `plan_parser.py` | `CompletionCriterion`에 `build_command` 필드 추가, 파싱 로직 | 낮음 — 기존 필드에 영향 없음 |
| `completion_detector.py` | `run_local_build()`, `run_build_criteria()` 추가 | 낮음 — 새 함수만 추가 |
| `session_manager.py` | `build_session_prompt()` VM빌드금지 주입, `process_chunk()` 빌드 스텝 추가 | 중간 — 기존 흐름에 삽입 |
| `config.py` | `build_timeout_seconds` 필드 추가, 로딩 | 낮음 |
| `config.toml` | `build_timeout_seconds` 항목 추가 | 낮음 |

## 테스트 계획

1. **plan_parser 단위 테스트**: `[BUILD]` 태그 파싱, `build_command` 필드 정확성
2. **completion_detector 단위 테스트**: `run_local_build()` 성공/실패/타임아웃, `run_build_criteria()` 다중 빌드
3. **session_manager 단위 테스트**: `build_session_prompt()` VM빌드금지 주입, `process_chunk()` 빌드 통합 흐름
4. **통합 테스트**: 전체 시퀀스 (idle → 빌드 → 피드백 → code-review → chunk-complete → 다음 chunk)
