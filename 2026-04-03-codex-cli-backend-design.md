# Codex CLI Backend — Design Spec

**Date**: 2026-04-03
**Status**: Draft
**Author**: Skudy + Claude

---

## 1. 목표

기존 Claude Desktop 경로(판단: `claude -p`, 실행: AppleScript → Claude Desktop 앱)를 **한 글자도 건드리지 않고**, Codex CLI 전용 경로를 별도로 만든다.

- **판단**: CLI 에이전트 (`claude -p` 또는 `codex exec`)
- **실행 (interactive)**: AppleScript → Codex TUI 앱 (Terminal/iTerm)
- **실행 (exec-plan)**: `codex exec --dangerously-bypass-approvals-and-sandbox` subprocess

최종 사용자 경험은 "중간 개입 없는 자동 흐름"이어야 한다. planning → 문서 생성 → exec-plan 실행이 자동으로 이어진다.

---

## 2. 핵심 의사결정 요약

### 2.1 분리 원칙

- Claude Desktop 기존 흐름은 **절대 깨지면 안 된다**
- Codex CLI 전용 로직은 **별도 패키지** (`src/cowork_pilot/codex/`)
- 별도 커맨드: `cowork-pilot-codex` (pyproject.toml 엔트리포인트 추가)
- 공통 모듈 추출은 나중에 (A → C 점진적 전환 가능)

### 2.2 두 가지 실행 경로

| 구분 | Interactive | Exec-plan |
|------|-------------|-----------|
| 용도 | planning, 문서 생성, 대화 | Chunk 단위 코드 구현 |
| 실행 방식 | AppleScript로 Codex TUI 조작 | `codex exec --dangerously-bypass-approvals-and-sandbox` subprocess |
| 승인 | TUI 화면 감지 → 자동 응답 | 승인 없음 (bypass) |
| 세션 | Codex TUI interactive 세션 | 비대화형, 세션 없음 |

### 2.3 Phase 기반 모드 전환 (Codex 전용)

- `phase_1` = `Default` 모드 — 초기 대화, 컨텍스트 설정
- `phase_2` 진입 = `Plan` 모드 — 질문/기획
- `phase_2` 완료 = `Default` 모드 — 문서 writing
- 이후 = 계속 `Default`
- 모드 전환: `Shift+Tab`

### 2.4 Checklist 기반 전환

- Plan 모드에서 질문/기획 완료를 모델 출력으로 판단하지 않음
- Plan 모드는 파일 쓰기 금지이므로 Codex가 직접 체크 불가
- cowork-pilot이 JSONL 대화 컨텍스트를 CLI 에이전트에게 넘겨 체크리스트 충족 여부 판단
- idle 감지(`task_complete` 후 일정 시간 `task_started` 없음) 시점에 한 번 체크

### 2.5 교차 재개

- Claude Desktop ↔ Codex CLI 간 state 기반 resume
- `orchestrator_state.json` 파일 포맷을 공유
- 세션 이어받기가 아니라 파일/체크리스트 기준 재개

---

## 3. Codex JSONL 포맷 분석

### 3.1 기본 구조

모든 레코드: `{timestamp, type, payload}` 3키 구조.

**type 4종:**

| type | 용도 |
|------|------|
| `session_meta` | 세션 시작 메타 (source, originator, cli_version) |
| `event_msg` | 이벤트 알림 (task_started, task_complete, exec_command_end, token_count 등) |
| `response_item` | 모델 응답 (message, reasoning, function_call, function_call_output) |
| `turn_context` | 턴 컨텍스트 (collaboration_mode, approval_policy, model 등) |

### 3.2 세션 식별

- `session_meta.source == "cli"` → interactive 세션
- `session_meta.source == "exec"` → exec 실행 세션
- `session_meta.source == "vscode"` → 제외
- `session_meta.originator == "codex-tui"` → Codex TUI 확인

### 3.3 JSONL 경로

`~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl`

### 3.4 핵심 이벤트

**사용자 입력 요청 (`request_user_input`):**
```json
{
  "type": "response_item",
  "payload": {
    "type": "function_call",
    "name": "request_user_input",
    "arguments": {
      "questions": [{
        "header": "...",
        "id": "...",
        "question": "...",
        "options": [
          {"label": "...", "description": "..."},
          ...
        ]
      }]
    },
    "call_id": "call_xxx"
  }
}
```

응답:
```json
{
  "type": "response_item",
  "payload": {
    "type": "function_call_output",
    "call_id": "call_xxx",
    "output": "{\"answers\":{\"id\":{\"answers\":[\"선택값\"]}}}"
  }
}
```

**승인 대기:**
- JSONL에 별도 승인 이벤트 없음
- `function_call` (exec_command 등) 기록 후 `function_call_output` / `exec_command_end`가 안 오면 승인 대기 가능성
- TUI 화면을 읽어서 "Would you like to run the following command?" 패턴으로 확정
- 승인 UI: 3개 선택지 (y: proceed, p: don't ask again, esc: deny), 방향키+Enter로 조작

**턴 구분:**
- `event_msg.type == "task_started"` → 새 턴 시작
- `event_msg.type == "task_complete"` → 턴 종료 (+ `last_agent_message`)

**모드 감지:**
- `turn_context.collaboration_mode.mode == "default" | "plan"`

**Idle 감지:**
- `task_complete` 이벤트 후 일정 시간(config 가능) 내 `task_started`가 안 오면 idle

---

## 4. 디렉토리 구조

```
src/cowork_pilot/
├── __init__.py              # 기존 (수정 안 함)
├── main.py                  # 기존 (수정 안 함)
├── watcher.py               # 기존 (수정 안 함)
├── dispatcher.py            # 기존 (수정 안 함)
├── responder.py             # 기존 (수정 안 함)
├── ... (기존 모듈 전부 그대로)
│
├── codex/                   # ★ Codex CLI 전용 패키지
│   ├── __init__.py
│   ├── main.py              # CLI 진입점: cowork-pilot-codex
│   ├── watcher.py           # Codex JSONL 파서
│   ├── dispatcher.py        # CLI 에이전트 판단 엔진 호출
│   ├── responder.py         # AppleScript로 Codex TUI 조작
│   ├── session_manager.py   # Codex 세션 열기/감지
│   ├── mode_controller.py   # Plan↔Default 전환 + checklist 판단
│   ├── exec_runner.py       # codex exec 실행 (exec-plan용)
│   ├── completion_detector.py  # idle/완료 감지
│   ├── orchestrator.py      # Codex 전용 오케스트레이터
│   └── models.py            # Codex JSONL 이벤트 모델
```

**엔트리포인트 (pyproject.toml):**
```toml
[project.scripts]
cowork-pilot = "cowork_pilot.main:cli"
cowork-pilot-codex = "cowork_pilot.codex.main:cli"
```

---

## 5. 모듈 설계

### 5.1 `codex/models.py` — 이벤트 모델

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any

class CodexRecordType(str, Enum):
    SESSION_META = "session_meta"
    EVENT_MSG = "event_msg"
    RESPONSE_ITEM = "response_item"
    TURN_CONTEXT = "turn_context"

class CodexItemType(str, Enum):
    MESSAGE = "message"
    REASONING = "reasoning"
    FUNCTION_CALL = "function_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"
    WEB_SEARCH_CALL = "web_search_call"

class CodexEventType(str, Enum):
    """cowork-pilot이 처리해야 하는 이벤트 유형"""
    USER_INPUT_REQUEST = "user_input_request"  # request_user_input
    APPROVAL_PENDING = "approval_pending"       # TUI 승인 대기
    TASK_COMPLETE = "task_complete"              # 턴 종료
    MODE_CHANGE = "mode_change"                 # Plan↔Default

class CollaborationMode(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"

@dataclass
class CodexQuestion:
    header: str
    id: str
    question: str
    options: list[dict[str, str]]  # [{label, description}, ...]

@dataclass
class CodexEvent:
    event_type: CodexEventType
    timestamp: str
    call_id: str | None = None
    questions: list[CodexQuestion] | None = None   # USER_INPUT_REQUEST
    tool_name: str | None = None                    # APPROVAL_PENDING
    tool_args: dict | None = None                   # APPROVAL_PENDING
    mode: CollaborationMode | None = None           # MODE_CHANGE
    last_message: str | None = None                 # TASK_COMPLETE

@dataclass
class CodexResponse:
    action: str    # "select", "approve", "deny", "text", "escalate"
    value: Any     # 선택 인덱스, 텍스트 등
```

### 5.2 `codex/watcher.py` — JSONL 감시

기존 `watcher.py`의 `JSONLTail`과 같은 패턴이지만, Codex JSONL 포맷에 맞춘 파서.

**핵심 책임:**
- `~/.codex/sessions/YYYY/MM/DD/` 에서 최신 `rollout-*.jsonl` (`source == "cli"`) 감지
- JSONL tail 읽기 (offset 기반, 기존과 동일 패턴)
- 레코드 파싱 → `CodexEvent` 변환
- 감지 대상:
  - `response_item` + `function_call` + `name == "request_user_input"` → `USER_INPUT_REQUEST`
  - `turn_context` + `collaboration_mode.mode` 변경 → `MODE_CHANGE`
  - `event_msg` + `type == "task_complete"` → `TASK_COMPLETE`
- 승인 대기 감지:
  - `function_call` 후 N초 내 `function_call_output` 미도착 → TUI 확인 트리거
  - TUI 화면에서 "Would you like to run" 패턴 확인 → `APPROVAL_PENDING`

### 5.3 `codex/responder.py` — TUI 조작

AppleScript로 Terminal/iTerm 내의 Codex TUI를 조작.

**입력 유형 2가지:**

| 유형 | 방법 | 용도 |
|------|------|------|
| 선택형 | 방향키(↑↓) + Enter | `request_user_input`, 승인 프롬프트 |
| 텍스트형 | Cmd+V (붙여넣기) + Enter | 프롬프트 전송, slash command |

**TUI 화면 읽기:**

Terminal.app:
```applescript
tell application "Terminal"
    set termContent to contents of selected tab of front window
end tell
```

iTerm2:
```applescript
tell application "iTerm2"
    set termContent to contents of current session of current tab of current window
end tell
```

- 두 앱 모두 `contents` 속성으로 현재 화면 텍스트를 가져올 수 있음

**패턴 매칭 (외부 설정 기반):**

Codex CLI 버전 업데이트로 TUI 문구가 변경될 수 있으므로, 모든 패턴을 코드 하드코딩이 아닌 `config.toml`에서 관리한다.

```toml
[codex.tui_patterns]
# 승인 대기 감지 패턴 (정규식, 순서대로 매칭 시도)
approval_pending = [
    "Would you like to run the following command\\?",
    "Press enter to confirm or esc to cancel",
    "Run command\\?",                  # 향후 변경 대비 예비 패턴
]
# 명령어 추출 패턴
command_extract = "^\\$ (.+)$"
# 모드 표시 패턴
mode_indicator_plan = "\\[plan\\]"
mode_indicator_default = "\\[default\\]"
```

**패턴 매칭 방어 전략:**

1. **다중 패턴 매칭 (Cascading Match)**
   - `approval_pending` 리스트를 순서대로 시도, 하나라도 매칭되면 승인 대기 확정
   - 모든 패턴 실패 시 → 즉시 실패 처리하지 않고 `PATTERN_UNMATCHED` 상태로 전환

2. **Codex CLI 버전 감지 및 패턴 자동 갱신**
   - 세션 시작 시 `codex --version` 실행하여 버전 기록
   - `session_meta.cli_version` 필드도 병행 확인
   - 버전별 패턴 오버라이드 지원:
   ```toml
   [codex.tui_patterns_override."1.2.0"]
   approval_pending = ["Do you want to execute this command\\?"]
   ```

3. **Fallback 전략 (패턴 매칭 실패 시)**
   ```
   PATTERN_UNMATCHED 진입
     → 1차: approval_timeout_seconds 후 TUI 화면 재읽기 (패턴 재시도)
     → 2차: 1차 실패 시 idle_timeout_seconds 대기 후 JSONL 재확인
            (function_call_output 도착 여부로 상태 추론)
     → 3차: 2차에서도 판단 불가 시 ESCALATE (사용자 개입 요청)
   ```
   - 최대 재시도: 3회 (config `pattern_match_max_retries = 3`)
   - 각 재시도 간 간격: `pattern_retry_interval_seconds = 2` (config 가능)

4. **터미널 버퍼 안전장치**
   - `contents` 속성이 빈 문자열이거나 일정 길이 미만이면 → "읽기 실패"로 처리, 재시도
   - 터미널 화면 크기(행 수)를 AppleScript로 조회하여, 예상보다 짧은 출력은 불완전 읽기로 간주
   ```applescript
   -- Terminal.app 행 수 확인
   tell application "Terminal"
       set termRows to number of rows of selected tab of front window
   end tell
   ```

5. **패턴 매칭 로깅 및 모니터링**
   - 모든 패턴 매칭 시도를 `codex_tui_match.log`에 기록 (타임스탬프, 패턴, 결과)
   - `PATTERN_UNMATCHED` 발생 빈도가 임계치(`pattern_alert_threshold = 5` / 세션) 초과 시
     → 세션 시작 시 경고 로그 + 패턴 업데이트 권고 메시지 출력

**모드 전환:**
- `Shift+Tab` 키 전송으로 Plan↔Default 토글

### 5.4 `codex/dispatcher.py` — 판단 엔진

기존 `dispatcher.py`와 같은 패턴. CLI 에이전트에게 컨텍스트 + 이벤트를 넘기고 판단을 받음.

**입력:** 프로젝트 docs (golden-rules, decision-criteria) + JSONL 컨텍스트 + 이벤트 정보
**출력:** `CodexResponse` (select/approve/deny/text/escalate)

승인 프롬프트의 경우, TUI에서 읽은 명령어 + justification을 CLI 에이전트에게 넘겨서 y/p/esc 중 결정.

### 5.5 `codex/mode_controller.py` — 모드 전환 + Checklist

**상태 머신:**
```
PLANNING → CHECKING → WRITING
   ↑          |          ↑
   └──────────┘          |
   (미충족, 재시도 남음)  |
                         |
PLANNING → CHECKING → FORCE_WRITING
                      (재시도 소진 → 사용자 확인 후 강제 전환)

PLANNING → CHECKING → STALLED
                      (재시도 소진 + 사용자 미응답 → 자동 전환)
```

- `PLANNING`: Plan 모드에서 질문/기획 진행 중
- `CHECKING`: idle 감지 → CLI 에이전트에게 checklist 판단 요청 중 (1회만)
- `WRITING`: checklist 충족 → Default 모드로 전환, 문서 writing 진행
- `FORCE_WRITING`: 재시도 한도 도달 → 사용자에게 확인 요청 후 강제 전환
- `STALLED`: 사용자 응답 없이 `stall_timeout_seconds` 초과 → 자동 전환 (안전 탈출)

**Checklist 소스:**
- exec-plan 메타데이터 또는 `docs/planning-checklist.md`에 정의
- 예: `[ ] 아키텍처 결정`, `[ ] 데이터 모델 정의`, `[ ] API 설계 방향`

**판단 프로세스:**
1. idle 감지 (`task_complete` 후 N초 대기)
2. 상태를 `CHECKING`으로 전환 (중복 판단 방지)
3. JSONL 최근 대화 컨텍스트를 CLI 에이전트에게 전달
4. "체크리스트 항목 X가 충족됐는지?" 질문
5. 충족 → `WRITING` 전환 + `Shift+Tab` 전송
6. 미충족 → `PLANNING` 복귀, 다음 idle까지 대기 (**재시도 카운터 증가**)

**무한루프 방지 (Circuit Breaker):**

Checklist 판단이 계속 "미충족"을 반환하는 경우를 방지하기 위한 다단계 안전장치.

```toml
[codex.checklist]
max_check_attempts = 5              # 최대 판단 시도 횟수
escalate_after_attempts = 3         # N회 미충족 시 사용자 개입 요청
stall_timeout_seconds = 120         # 사용자 응답 없으면 자동 진행
force_advance_on_stall = true       # stall 시 자동 전환 여부
consecutive_same_result_limit = 3   # 동일 미충족 항목 N회 연속 시 조기 escalate
```

**동작 흐름:**

```
[1회차~3회차] 일반 판단
  미충족 → PLANNING 복귀, 다음 idle 대기
  (단, 동일 미충족 항목이 consecutive_same_result_limit 연속 반복 시 → 즉시 4단계로)

[4회차: escalate_after_attempts 도달]
  미충족 → 사용자에게 macOS 알림 + TUI에 메시지 전송:
    "체크리스트 항목 [X, Y]가 3회 연속 미충족입니다.
     계속 기획을 진행하시겠습니까? (y: 계속 / n: 현재 상태로 writing 전환)"
  → 사용자 응답 대기 (stall_timeout_seconds)
  → 사용자 "계속" 선택 시: 카운터 리셋, PLANNING 복귀
  → 사용자 "전환" 선택 시: FORCE_WRITING 전환
  → 사용자 무응답 (stall_timeout_seconds 초과):
     - force_advance_on_stall == true → STALLED → Default 모드 전환
     - force_advance_on_stall == false → PLANNING 유지, 로그 기록

[5회차: max_check_attempts 도달]
  무조건 FORCE_WRITING 전환 + 경고 로그:
    "WARNING: 체크리스트 판단 최대 횟수(5) 도달. 미충족 항목: [X, Y]. 강제 전환."
```

**오판 방지 보조 전략:**

1. **항목별 부분 충족 추적**
   - 전체 체크리스트를 한번에 판단하지 않고, 항목별로 개별 추적
   - 이미 충족된 항목은 재판단하지 않음 (판단 범위 축소)
   - `orchestrator_state.json`의 `checklist` 필드에 항목별 상태 기록
   ```python
   # 예: 3개 항목 중 2개 충족 → 나머지 1개만 판단
   checklist_state = {
       "architecture": True,    # 1회차에 충족 판정
       "data_model": True,      # 2회차에 충족 판정
       "api_design": False,     # 아직 미충족 → 이 항목만 재판단
   }
   ```

2. **판단 근거 기록 (Audit Trail)**
   - CLI 에이전트의 판단 결과를 근거(reasoning)와 함께 저장
   - 동일 항목이 반복 미충족되면, 이전 판단 근거를 다음 판단에 컨텍스트로 포함
   - 에이전트가 "이전에는 X 이유로 미충족이었는데, 그 이후 대화에서 변화가 있는지" 판단 가능
   ```python
   @dataclass
   class CheckResult:
       item_id: str
       fulfilled: bool
       reasoning: str           # 판단 근거
       evidence_turns: list[int]  # 근거가 된 JSONL 턴 번호
       checked_at: str          # 판단 시각
   ```

3. **JSONL 컨텍스트 윈도우 확장**
   - 1~2회차: 최근 N턴만 전달 (기본)
   - 3회차 이후: 컨텍스트 윈도우를 2배로 확장하여 더 넓은 대화 범위 참조
   - 반복 미충족이 "에이전트가 관련 대화를 못 봐서"인 경우 방지

**중복 판단 방지:**
- `CHECKING` 상태일 때는 추가 idle 트리거 무시
- 판단 결과 나올 때까지 1회만 CLI 호출

**모드 전환 검증:**
- `Shift+Tab` 전송 후 JSONL `turn_context.collaboration_mode.mode` 변경 확인
- 변경 안 되면 재시도 (최대 3회)

### 5.6 `codex/exec_runner.py` — exec-plan 실행 (우선순위 1)

가장 단순하고 독립적인 모듈.

```python
async def run_exec_plan(plan_path: str, project_dir: str) -> bool:
    """exec-plan의 각 Chunk를 codex exec로 순차 실행"""
    plan = parse_exec_plan(plan_path)  # 기존 plan_parser 활용 가능

    for chunk in plan.chunks:
        if chunk.status == "completed":
            continue

        result = await run_chunk(chunk, project_dir)

        if not result.success:
            # 재시도 or ESCALATE
            ...

        update_checkboxes(plan_path, chunk)

    return True

async def run_chunk(chunk, project_dir: str) -> ChunkResult:
    """단일 Chunk를 codex exec로 실행"""
    cmd = [
        "codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-p", chunk.session_prompt,
        "--cwd", project_dir,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=config.build_timeout_seconds,
    )

    return ChunkResult(
        success=proc.returncode == 0,
        stdout=stdout.decode(),
        stderr=stderr.decode(),
    )
```

### 5.7 `codex/completion_detector.py` — 완료/idle 감지

**idle 감지:**
- `task_complete` 이벤트 후 N초(`idle_timeout_seconds`) 내 `task_started` 없음 → idle

**승인 대기 감지 (TUI 트리거):**
- `function_call` 후 N초 내 `function_call_output` 없음 → TUI 화면 읽기
- "Would you like to run" 패턴 → 승인 대기 확정

### 5.8 `codex/session_manager.py` — 세션 관리

- `~/.codex/sessions/YYYY/MM/DD/`에서 최신 `cli` 세션 JSONL 찾기
- 새 세션 열기: AppleScript로 Terminal에서 `codex` 명령 실행 또는 `/new`
- 세션 프롬프트 전송: Cmd+V + Enter

### 5.9 `codex/orchestrator.py` — 전체 오케스트레이터

```
Phase 1 (interactive, Default)
  → 초기 대화/컨텍스트 설정
  ↓
Phase 2 (interactive, Plan)
  → 질문/기획
  → idle 시 checklist 판단 (CLI 에이전트)
  ↓ checklist 완료
Phase 2 (interactive, Default)
  → 문서 writing
  ↓
Phase 3 (exec)
  → codex exec로 exec-plan Chunk별 실행
  → 실패 시 재시도 or ESCALATE
  → 모든 Chunk 완료 → macOS 알림
```

---

## 6. 구현 우선순위

exec-plan 실행이 가장 독립적이고 단순하므로 먼저 구현.

| 순서 | 모듈 | 의존성 |
|------|------|--------|
| 1 | `exec_runner.py` + `models.py` + `main.py` | plan_parser (기존 모듈 참조 가능) |
| 2 | `watcher.py` + `completion_detector.py` | 없음 |
| 3 | `responder.py` | 없음 |
| 4 | `dispatcher.py` | watcher, responder |
| 5 | `session_manager.py` | responder |
| 6 | `mode_controller.py` | watcher, responder, dispatcher |
| 7 | `orchestrator.py` | 전부 |

---

## 7. 설정 (`config.toml` 확장)

```toml
[codex]
sessions_path = "~/.codex/sessions"
approval_timeout_seconds = 5      # function_call 후 TUI 확인까지 대기
idle_timeout_seconds = 30          # task_complete 후 idle 판단

[codex.exec]
command = "codex"
args = ["exec", "--dangerously-bypass-approvals-and-sandbox"]
build_timeout_seconds = 600

[codex.interactive]
terminal_app = "Terminal"          # 또는 "iTerm"
mode_switch_delay_seconds = 1.0    # Shift+Tab 후 안정화 대기

# ★ TUI 패턴 매칭 방어 설정
[codex.tui_patterns]
approval_pending = [
    "Would you like to run the following command\\?",
    "Press enter to confirm or esc to cancel",
    "Run command\\?",
]
command_extract = "^\\$ (.+)$"
mode_indicator_plan = "\\[plan\\]"
mode_indicator_default = "\\[default\\]"
pattern_match_max_retries = 3       # 패턴 매칭 실패 시 최대 재시도
pattern_retry_interval_seconds = 2  # 재시도 간격
pattern_alert_threshold = 5         # 세션 내 PATTERN_UNMATCHED 경고 임계치

# 버전별 패턴 오버라이드 (필요 시 추가)
# [codex.tui_patterns_override."1.2.0"]
# approval_pending = ["Do you want to execute this command\\?"]

# ★ Checklist 무한루프 방지 설정
[codex.checklist]
max_check_attempts = 5              # 최대 판단 시도 횟수 (초과 시 강제 전환)
escalate_after_attempts = 3         # N회 미충족 시 사용자 개입 요청
stall_timeout_seconds = 120         # 사용자 응답 대기 제한 시간
force_advance_on_stall = true       # stall 시 자동 전환 여부
consecutive_same_result_limit = 3   # 동일 항목 연속 미충족 시 조기 escalate
context_window_expand_after = 3     # N회차 이후 컨텍스트 윈도우 2배 확장
```

---

## 8. 교차 재개 (State-based Resume)

Claude Desktop과 Codex CLI는 같은 `orchestrator_state.json` 포맷을 사용한다.

```json
{
  "backend": "codex",
  "updated_at": "2026-04-03T12:00:00Z",
  "current": {
    "phase": 2,
    "step": "writing",
    "status": "running",
    "started_at": "2026-04-03T11:30:00Z"
  },
  "completed": [
    {
      "phase": 1,
      "step": "context_setup",
      "status": "completed",
      "completed_at": "2026-04-03T11:00:00Z",
      "backend": "codex"
    }
  ],
  "pending": [
    {"phase": 3, "step": "exec_plan_1"}
  ],
  "generated_files": [
    "docs/design-docs/architecture.md",
    "docs/product-specs/auth.md"
  ],
  "checklist": {
    "architecture": true,
    "data_model": true,
    "api_design": false
  },
  "session_history": [
    {
      "backend": "codex",
      "session_id": "019d4fdd-65d8-...",
      "phase": 1,
      "started_at": "2026-04-03T10:00:00Z",
      "ended_at": "2026-04-03T11:00:00Z"
    }
  ]
}
```

재개 시:
1. `orchestrator_state.json` 읽기
2. `current.phase` + `current.step` 확인
3. 해당 지점부터 시작 (세션은 새로 열림)
4. `generated_files`로 이미 만들어진 산출물 확인
5. `session_history`로 이전 작업 내역 참조

Claude Desktop → Codex 전환, 또는 반대 방향 모두 가능.

---

## 9. 에러 처리

### 9.1 exec_runner 에러

| 상황 | 처리 |
|------|------|
| `codex exec` 비정상 종료 (returncode != 0) | 최대 3회 재시도, 초과 시 ESCALATE |
| timeout 초과 | 프로세스 kill + ESCALATE |
| Chunk 일부 완료 | 체크박스 기준으로 미완료 항목만 재실행 |

### 9.2 TUI 조작 에러

| 상황 | 처리 |
|------|------|
| Terminal 윈도우 못 찾음 | 3회 재시도 (1초 간격), 실패 시 ESCALATE |
| AppleScript 실행 실패 | 로그 + ESCALATE |
| 모드 전환 후 확인 실패 | 최대 3회 재시도 |
| TUI 화면 읽기 실패 | 타이머 리셋, 다음 트리거까지 대기 |

### 9.3 승인 대기 타이밍 레이스

`function_call` 후 타이머 돌리는 중에 `function_call_output`이 도착할 수 있음.

- 처리: TUI 읽기 전 항상 JSONL을 먼저 재확인
- `function_call_output`이 이미 도착했으면 TUI 읽기 건너뜀
- 기존 Claude Desktop `has_tool_result_arrived()` 패턴과 동일

---

## 10. Claude Desktop과의 차이점 요약

| 항목 | Claude Desktop | Codex CLI |
|------|---------------|-----------|
| JSONL 포맷 | `{role, content, tool_use, ...}` | `{timestamp, type, payload}` |
| JSONL 경로 | `~/Library/Application Support/Claude/...` | `~/.codex/sessions/YYYY/MM/DD/` |
| 질문 이벤트 | `AskUserQuestion` tool_use | `request_user_input` function_call |
| 승인 감지 | JSONL에 기록됨 | JSONL에 안 찍힘 → TUI 화면 읽기 |
| 모드 전환 | 없음 (단일 모드) | `Shift+Tab` (Plan↔Default) |
| exec-plan 실행 | Cowork 세션 + AppleScript | `codex exec --dangerously-bypass...` subprocess |
| 앱 조작 | AppleScript → Claude Desktop | AppleScript → Terminal/iTerm (Codex TUI) |
