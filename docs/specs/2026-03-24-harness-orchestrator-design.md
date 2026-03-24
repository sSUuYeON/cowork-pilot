# Cowork Pilot — 하네스 오케스트레이터 설계 문서

> Chunk 단위 자동 실행 시스템 (Phase 2+3 통합)
> 작성일: 2026-03-24
> 상태: Draft

---

## 1. 목표

이미 작성된 구현 계획서(exec-plan)를 읽고, Chunk 단위로 Cowork 세션을 열어 자동 실행하고,
완료 조건을 검증한 뒤 다음 Chunk으로 넘어가는 시스템.

최종 비전: "이 프로젝트 시작해" → 기획서 작성 → 구현 계획 생성 → Chunk별 자동 코딩/테스트 → 프로젝트 완료.
단, 단계적으로 구현한다: 먼저 exec-plan 자동 실행부터, 그 다음 기획서 자동 생성.


## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                   하네스 오케스트레이터                      │
│                                                         │
│  exec-plan 파서 → Chunk 추출 → 세션 열기 → 감시 → 판단    │
│         ↑                                    ↓          │
│         └──── exec-plan 체크박스 업데이트 ←───┘          │
└─────────────────────────────────────────────────────────┘
        ↕                      ↕                    ↕
   exec-plan.md         Cowork 세션 (JSONL)    session_opener
   (프로젝트 폴더)        (Phase 1 Watcher)      (AppleScript)
```

### 2.1 기존 Phase 1과의 관계

Phase 1의 Watcher, Dispatcher, Validator, Responder는 그대로 유지.
하네스 오케스트레이터는 Phase 1 **위에** 새로운 레이어로 올라간다:

- Phase 1: "Cowork가 질문하면 자동 응답" (이벤트 단위)
- Phase 2+3: "Chunk 단위로 세션을 열고, 작업 완료를 판단하고, 다음으로 넘김" (태스크 단위)

둘은 동시에 동작한다:
- 하네스 오케스트레이터가 세션을 열고 감시
- Phase 1 오케스트레이터가 그 세션 안에서 질문에 자동 응답
- 하네스 오케스트레이터가 작업 완료를 감지하면 다음 세션으로


## 3. exec-plan 포맷

exec-plan의 상세 포맷, AGENTS.md 형식, 폴더 구조 표준은 `docs/project-conventions.md`에 정의되어 있다. 아래는 하네스 구현에 필요한 핵심 내용만 요약한 것이다.

### 3.1 파일 위치

```
프로젝트/
  docs/
    exec-plans/
      active/
        phase-2-implementation.md     ← 현재 진행 중인 계획
      completed/
        phase-1-implementation.md     ← 완료된 계획
```

### 3.2 exec-plan 구조

```markdown
# Phase 2 Implementation Plan

## Metadata
- project_dir: /path/to/project
- created: 2026-03-24
- status: in_progress

---

## Chunk 1: Foundation

### Completion Criteria
- [ ] pytest tests/test_models.py 통과
- [ ] pytest tests/test_config.py 통과
- [ ] src/models.py, src/config.py 파일 존재

### Tasks
- Task 1: Project Scaffold
- Task 2: Models
- Task 3: Config

### Session Prompt
```
exec-plans/active/phase-2-implementation.md를 읽고 Chunk 1을 진행해.
AGENTS.md와 docs/를 참고해서 Task 1~3을 순서대로 구현해.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 2: Watcher

### Completion Criteria
- [ ] pytest tests/test_watcher.py 통과
- [ ] localhost:3000에서 메인 페이지 렌더링 확인 (해당 시)

### Tasks
- Task 4: JSONL Parser
- Task 5: State Machine

### Session Prompt
```
exec-plans/active/phase-2-implementation.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, 다음 Chunk를 시작해.
```
```

### 3.3 핵심 규칙

- **Completion Criteria는 기계적으로 검증 가능해야 한다**: "pytest 통과", "파일 존재", "localhost 스크린샷에서 X 확인" 등
- **Session Prompt는 Cowork에 보내는 실제 텍스트**: 오케스트레이터가 이 텍스트를 그대로 session_opener에 넘김
- **체크박스(`- [ ]` / `- [x]`)로 진행 상황 추적**: Cowork가 작업 완료 후 체크박스를 업데이트, 또는 오케스트레이터의 CLI가 검증 후 업데이트
- **첫 번째 Chunk에만 구체적 Session Prompt를 쓰고**, 이후 Chunk들은 범용 프롬프트 사용 가능 ("다음 미완료 Chunk 진행해")


## 4. 하네스 오케스트레이터 컴포넌트

### 4.1 exec-plan 파서 (`plan_parser.py`)

exec-plan md 파일을 파싱하여 구조화된 데이터로 변환.

```python
@dataclass
class CompletionCriterion:
    description: str    # "pytest tests/test_models.py 통과"
    checked: bool       # True if [x], False if [ ]

@dataclass
class Chunk:
    name: str                              # "Chunk 1: Foundation"
    number: int                            # 1
    tasks: list[str]                       # ["Task 1: Project Scaffold", ...]
    completion_criteria: list[CompletionCriterion]
    session_prompt: str                    # Cowork에 보낼 프롬프트
    status: str                            # "pending" | "in_progress" | "completed"

@dataclass
class ExecPlan:
    title: str
    project_dir: str
    chunks: list[Chunk]
    status: str                            # "pending" | "in_progress" | "completed"
```

**파싱 규칙:**
- `## Chunk N:` 헤더로 Chunk 분리
- `### Completion Criteria` 아래의 `- [ ]` / `- [x]` 파싱
- `### Session Prompt` 아래의 프롬프트 텍스트 추출 규칙:
  1. 코드 블록(`` ``` ``으로 시작~끝)이 있으면 **첫 번째** 코드 블록의 내용만 사용 (fence 라인 제외, 내부 텍스트만). 코드 블록 밖의 텍스트(주석, 설명 등)는 무시
  2. 코드 블록이 없으면 `### Session Prompt` 다음 줄부터 `---`, `## `, 또는 파일 끝까지의 일반 텍스트를 수집 (앞뒤 공백 trim)
  3. 추출 결과가 빈 문자열이면 파싱 에러 → ESCALATE
- 모든 criteria가 `[x]`면 Chunk status = "completed"

### 4.2 작업 완료 감지기 (`completion_detector.py`)

Cowork 세션이 Chunk 작업을 끝냈는지 판단하는 컴포넌트.

**감지 방식: JSONL idle 타임아웃 + CLI 판단 조합**

JSONL에 "세션 종료" 시그널이 없으므로 (분석 완료), 두 단계로 판단:

1. **Idle 감지**: JSONL에 새 레코드가 N초(기본 120초, config.toml에서 조정 가능) 동안 없으면 "작업이 멈춤" 후보로 간주. 추가로 다음 조건 중 **하나 이상**이 충족되어야 트리거:
   - 조건 A: 마지막 레코드가 `type: "summary"` (Cowork JSONL에서 `last-prompt`이라 불리는 턴 요약 레코드). 이 레코드는 매 턴(user→assistant 사이클)이 끝날 때 Cowork가 기록하며, 이것이 마지막이면 턴이 완전히 종료된 것
   - 조건 B: 마지막 assistant 메시지의 `stop_reason == "end_turn"`이고, 해당 메시지의 content에 `tool_use` 블록이 없음 (도구 호출 대기 상태가 아닌 것)
   - 조건 A가 더 확실한 시그널이므로 우선 체크. 조건 B는 fallback

2. **CLI 검증**: idle 감지 후, CLI 에이전트(Codex 또는 Claude)에게 다음을 질문:
   - exec-plan의 현재 Chunk completion criteria를 하나씩 확인
   - 검증 방법은 criteria의 내용에 따라 CLI 에이전트가 판단:
     - "pytest 통과" → `pytest` 명령 실행하여 exit code 확인
     - "파일 존재" → `ls` 또는 `stat`으로 확인
     - "localhost:3000에서 X 확인" → `curl localhost:3000` 응답 확인 (또는 Cowork 세션 내에서 Chrome MCP로 스크린샷 — 하네스가 직접 하지 않음)
   - CLI 에이전트는 범용 도구(bash, 파일 읽기 등)를 사용하여 각 criterion을 기계적으로 검증
   - 기계적 검증이 불가능한 주관적 criteria는 exec-plan 작성 시 금지 (섹션 3.3 핵심 규칙 참조)
   - 모든 criteria 충족 → "COMPLETED" 리턴
   - 미충족 → "INCOMPLETE: [미충족 항목]" 리턴

**CLI 검증 프롬프트 템플릿:**
```
다음 exec-plan의 Chunk {N} 완료 조건을 검증해:

{completion_criteria 목록}

프로젝트 폴더: {project_dir}

각 조건을 확인하고, 모두 충족되면 "COMPLETED"를, 하나라도 미충족이면
"INCOMPLETE: {미충족 항목}"을 리턴해.
```

### 4.3 세션 관리자 (`session_manager.py`)

Chunk 라이프사이클을 관리하는 상위 제어 컴포넌트.

```
[시작] → exec-plan 파싱 → 다음 미완료 Chunk 찾기 → 세션 열기 (session_opener)
  → Phase 1 자동응답 + JSONL 감시 → idle 감지 → CLI 검증
  → COMPLETED → exec-plan 체크박스 업데이트 → 다음 Chunk → [반복]
  → INCOMPLETE → 세션에 "미완료 항목: X" 전송 → 계속 감시
  → 모든 Chunk 완료 → exec-plan을 completed/로 이동 → [종료]
```

**세션 관리 흐름:**

1. `exec-plans/active/` 에서 활성 계획 파일을 찾는다
2. 파싱하여 다음 미완료 Chunk를 식별한다
3. `session_opener.open_new_session(chunk.session_prompt)` 으로 Cowork 세션을 연다
4. 새로 생성된 세션의 JSONL을 감시한다 (기존 session_finder + watcher 재사용)
5. Phase 1 자동 응답 루프가 동시에 동작한다
6. idle 감지 → CLI 검증 → 결과에 따라 분기

**INCOMPLETE 시 대응 (피드백 메커니즘):**

INCOMPLETE가 리턴되면, 현재 Cowork 세션에 미완료 사유를 전달하여 작업을 계속하게 한다.

전달 방식: Phase 1의 FREE_TEXT 입력과 동일한 경로 사용
1. Phase 1 자동응답 루프를 **일시 정지** (harness_feedback_pending 플래그)
2. `set_clipboard()` + `build_type_prompt_script()`로 피드백 텍스트 입력
3. 입력 완료 후 Phase 1 루프 **재개**
4. 다시 idle 감시 루프로 돌아감

피드백 텍스트 템플릿:
```
아직 미완료 항목이 있어:
{미충족 항목 목록}
마저 진행해. 완료 조건을 다시 확인하고 모든 항목을 만족시켜.
```

재시도 로직:
- **CLI 검증 실패** (파싱 에러, 타임아웃 등): 최대 3회 재시도 후 ESCALATE
- **INCOMPLETE 피드백 사이클** (검증은 성공했으나 미충족): 최대 3회 피드백 전송 후 ESCALATE
- 두 카운터는 별도로 관리되며, **Chunk별로 초기화** (새 Chunk 시작 시 둘 다 0으로)
- INCOMPLETE 피드백 후 다음 idle 감지 때 CLI 검증 실패가 나면, CLI 실패 카운터만 증가
- ESCALATE = macOS 알림 (`osascript -e 'display notification ...'`) + 하네스 루프 일시 정지 (사람의 개입 대기)

### 4.4 AGENTS.md 업데이트

기존 AGENTS.md에 하네스 관련 경로를 추가:

```markdown
## Harness (자동 실행 시스템)

- `docs/exec-plans/active/` — 현재 진행 중인 구현 계획
- `docs/exec-plans/completed/` — 완료된 구현 계획
- exec-plan 포맷: Chunk별 Tasks + Completion Criteria + Session Prompt
- Chunk 완료 시 체크박스 `[x]`로 업데이트됨
```


## 5. 운영 흐름 (End-to-End)

### 5.1 구현 계획 실행 모드 (Phase 2 스코프)

```
사람: exec-plans/active/에 구현 계획 파일을 넣는다
사람: `cowork-pilot --mode harness` 실행
오케스트레이터:
  1. exec-plan 파싱
  2. Chunk 1 → Cowork 세션 열기 + 프롬프트 전송
  3. Phase 1 자동응답 동시 동작
  4. Chunk 1 완료 감지 → 체크박스 업데이트
  5. Chunk 2 → 새 Cowork 세션 열기 + 프롬프트 전송
  6. ... 반복 ...
  7. 모든 Chunk 완료 → exec-plan을 completed/로 이동
  8. macOS 알림: "구현 계획 실행 완료"
사람: 결과 확인
```

### 5.2 기획서부터 자동 생성 모드 (Phase 3 스코프, 나중에 추가)

```
사람: "이 프로젝트 만들어" + 프로젝트 설명
메타 에이전트:
  1. 기획서(spec) 자동 생성 → docs/specs/에 저장
  2. 구현 계획(exec-plan) 자동 생성 → exec-plans/active/에 저장
  3. Phase 2 실행 모드 시작
```


## 6. 기술적 세부사항

### 6.0 JSONL 레코드 스키마 (Phase 1 기존 분석 기반)

Cowork 세션의 JSONL 파일에는 다음 레코드 타입이 기록된다:

| type | 의미 | 주요 필드 |
|------|------|-----------|
| `user` | 사용자(또는 도구 결과) 메시지 | `message.content[]` (text, tool_result 등) |
| `assistant` | Claude 응답 | `message.content[]` (text, tool_use 등), `message.stop_reason` |
| `summary` | 턴 요약 (일명 "last-prompt") | 매 턴이 끝날 때 Cowork가 자동 기록. user 메시지 수와 1:1 대응 |

`summary` 레코드는 Cowork 내부에서 자동 생성되며, 하나의 user→assistant 턴이 완전히 끝난 후에만 나타난다. 따라서 마지막 레코드가 `summary`이면 "현재 진행 중인 작업이 없다"고 판단할 수 있다.

### 6.0.1 Phase 1 피드백에 사용하는 기존 함수

하네스 오케스트레이터가 INCOMPLETE 피드백을 전송할 때 사용하는 Phase 1 함수들:

```python
# responder.py에서 import
from cowork_pilot.responder import set_clipboard, execute_applescript

# session_opener.py에서 import
from cowork_pilot.session_opener import build_type_prompt_script

# 피드백 전송 순서:
# 1. set_clipboard(feedback_text)  → 클립보드에 텍스트 로드
# 2. script = build_type_prompt_script()  → Cmd+V + Enter 스크립트 생성
# 3. execute_applescript(script)  → 실행
```

이 함수들은 이미 Phase 1에서 검증된 것이므로 새로 만들 필요 없다.

### 6.1 Phase 1과의 동시 실행

하네스 오케스트레이터와 Phase 1 자동응답은 같은 프로세스에서 동작한다.

**공유 상태 (모두 단일 스레드 — 동시성 문제 없음):**

하네스 오케스트레이터와 Phase 1은 **같은 스레드의 같은 while 루프** 안에서 교대로 실행된다 (협력적 멀티태스킹). 별도 스레드/프로세스가 아니므로 lock이나 queue가 필요 없다.

- `current_jsonl_path`: 현재 감시 중인 JSONL 파일 경로 (session_finder가 업데이트)
- `last_record_time`: 마지막 JSONL 레코드 수신 시각 (idle 감지용, `time.monotonic()`)
- `harness_feedback_pending`: bool 플래그 — True일 때 Phase 1 자동응답을 건너뜀

**우선순위:**
- Phase 1 이벤트 처리가 항상 우선 (질문 응답 누락 방지)
- 하네스의 idle 감지 + completion 체크는 Phase 1 이벤트가 없을 때만 동작
- 하네스 피드백 전송 시에만 Phase 1을 건너뜀

**Pause/Resume 프로토콜:**
1. `harness_feedback_pending = True` 설정
2. 현재 루프 반복에서 `handle_events()` 건너뜀 (단일 스레드이므로 즉시 반영)
3. `set_clipboard()` + `execute_applescript()` 실행 (동기 호출, 완료까지 블록)
4. `harness_feedback_pending = False` 설정
5. 다음 루프 반복부터 Phase 1 정상 동작

Phase 1이 이미 AppleScript를 실행 중일 때 피드백을 보내는 상황은 발생하지 않는다 — 단일 스레드이므로 Phase 1의 `execute_applescript()`이 완료된 후에야 하네스 코드가 실행된다.

```
main.py의 run() 루프:
  while True:
    # Phase 1: 이벤트 감지 + 자동 응답 (피드백 전송 중이 아닐 때만)
    if not harness_feedback_pending:
      events = handle_events()
      if events:
        last_record_time = time.monotonic()

    # Phase 2+3: idle 감지 + Chunk 완료 판단
    if harness_mode:
      check_completion()  # 내부에서 필요 시 harness_feedback_pending 토글

    sleep(poll_interval)
```

### 6.2 Cowork 세션 전환 감지

새 세션을 열면 session_finder가 새 JSONL을 감지한다.
하네스 오케스트레이터는 이 전환을 추적하여:
- 이전 세션의 JSONL → 완료 판단 대상
- 새 세션의 JSONL → Phase 1 자동응답 대상

**세션 전환 타이밍 (race condition 방지):**

`session_opener.open_new_session()` 호출 후, 새 JSONL 파일이 실제 생성되기까지 시간차가 있다.

1. 세션 열기 전: 현재 JSONL 파일 목록을 스냅샷으로 저장 (`set(glob("*.jsonl"))`)
2. `open_new_session()` 호출 — 이 함수는 **동기(blocking)**: 내부에서 AppleScript를 실행하고, `session_load_delay`(기본 3초)를 포함한 전체 스크립트가 완료된 후 리턴
3. `open_new_session()`이 False 리턴 시: AppleScript 실패 → 재시도 3회 후 ESCALATE
4. True 리턴 후: `session_finder`를 다시 호출하여 스냅샷과 비교
5. 새 JSONL 파일이 나타날 때까지 최대 10초 폴링 (1초 간격, `config.toml`의 `session_detect_timeout` / `session_detect_poll_interval`로 조정 가능)
6. 새 파일 감지 즉시: 해당 파일을 `current_jsonl_path`로 설정, Phase 1 감시 대상도 전환
7. 10초 내 감지 실패 시: ESCALATE (세션은 열렸으나 JSONL 생성이 안 된 것으로 간주)

이렇게 하면 "아직 이전 세션 JSONL을 감시하는데 새 세션이 열린" 상황을 방지할 수 있다.

### 6.3 idle 감지 타이밍

```python
IDLE_TIMEOUT_SECONDS = 120      # 2분 idle → 작업 완료 후보

def is_idle_trigger(last_record, last_record_time, now) -> bool:
    """idle 타임아웃 + 턴 종료 조건이 모두 충족되면 True."""
    if (now - last_record_time) < IDLE_TIMEOUT_SECONDS:
        return False
    # 조건 A (우선): 마지막 레코드가 턴 요약(summary/last-prompt)
    if last_record.get("type") == "summary":
        return True
    # 조건 B (fallback): assistant end_turn + no tool_use
    if last_record.get("type") == "assistant":
        msg = last_record.get("message", {})
        if msg.get("stop_reason") == "end_turn":
            content = msg.get("content", [])
            has_tool_use = any(
                b.get("type") == "tool_use" for b in content
                if isinstance(b, dict)
            )
            if not has_tool_use:
                return True
    return False
```

왜 120초인가:
- Cowork가 큰 파일 쓰거나 복잡한 도구 체인 실행할 때 30~60초 걸릴 수 있음
- Phase 1 자동응답이 동작 중이면 idle이 아님 (새 레코드가 계속 추가)
- 실제로 작업이 끝나고 Cowork가 최종 메시지를 보낸 뒤 idle이 시작

### 6.4 exec-plan 체크박스 업데이트

CLI 검증이 COMPLETED를 리턴하면, 오케스트레이터가 exec-plan 파일의
해당 Chunk의 `- [ ]`를 `- [x]`로 직접 업데이트한다 (Python 문자열 치환).

### 6.5 에러 처리

| 상황 | 대응 |
|------|------|
| Cowork 세션이 rate limit에 걸림 | JSONL에 stop_sequence 감지 → 대기 후 재시도 |
| CLI 검증 자체 실패 (타임아웃, 파싱 에러) | CLI 재시도 3회 후 ESCALATE |
| 검증 성공이나 미충족 (INCOMPLETE) | 피드백 전송 3사이클 후 ESCALATE |
| AppleScript 실패 (세션 열기) | 재시도 3회, 실패 시 ESCALATE |
| exec-plan 파싱 실패 | 즉시 ESCALATE, 사람이 형식 확인 |
| 프로젝트 폴더 접근 불가 | 즉시 ESCALATE |


## 7. 새로 만들 파일

```
src/cowork_pilot/
  plan_parser.py          # exec-plan 파서 (md → 구조화 데이터)
  completion_detector.py  # idle 감지 + CLI 검증
  session_manager.py      # Chunk 라이프사이클 관리 (상위 제어)

tests/
  test_plan_parser.py
  test_completion_detector.py
  test_session_manager.py
  fixtures/
    sample_exec_plan.md   # 테스트용 exec-plan

docs/
  exec-plans/
    active/               # (디렉토리 생성)
    completed/            # (디렉토리 생성)
```

기존 파일 수정:
- `main.py` — harness 모드 추가 (`--mode harness` 플래그)
- `config.py` — harness 관련 설정을 `config.toml`에서 읽는 로직 추가 (기존 `load_config()` 확장)
- `config.toml` — `[harness]` 섹션 추가 (아래 섹션 8 참고)
- `AGENTS.md` — harness 경로 추가 (이미 프로젝트 루트에 존재하는 파일)


## 8. config.toml 추가 설정

```toml
[harness]
idle_timeout_seconds = 120
completion_check_max_retries = 3
incomplete_retry_max = 3
exec_plans_dir = "docs/exec-plans"

[harness.session]
open_delay_seconds = 3.0        # 새 세션 로드 대기 (session_opener의 session_load_delay)
prompt_delay_seconds = 1.0      # 프롬프트 전송 전 대기
detect_timeout_seconds = 10.0   # 새 JSONL 감지 대기 최대 시간
detect_poll_interval = 1.0      # 새 JSONL 감지 폴링 간격
```


## 9. 미결정 사항

- [ ] Cowork가 에러로 멈춘 경우(크래시, VM 재시작 등)의 복구 전략
- [ ] 여러 프로젝트의 exec-plan을 순차/병렬 실행하는 방식 (Phase 3 스코프)
- [ ] 기획서 자동 생성 시 CLI 에이전트의 프롬프트 설계 (Phase 3 스코프)
- [ ] exec-plan을 사람이 아닌 CLI 에이전트가 자동 생성하는 워크플로우 (Phase 3 스코프)

---

> 이 문서는 cowork-pilot의 Phase 2+3 하네스 오케스트레이터 설계를 기술한다.
> 먼저 Phase 2(exec-plan 자동 실행)를 구현하고, 그 위에 Phase 3(기획서 자동 생성)을 추가한다.
