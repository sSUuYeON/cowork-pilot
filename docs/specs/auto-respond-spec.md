# Cowork Pilot — 설계 문서

> Cowork 자동 응답 에이전트 시스템
> 작성일: 2026-03-21
> 상태: Draft

---

## 1. 목표

Cowork가 작업 중 사용자에게 질문을 던지면 (옵션 선택, 확인 요청, 도구 승인, 자유 텍스트 입력 등), 사람이 직접 응답하지 않아도 **CLI 에이전트가 프로젝트 문서를 기반으로 판단하고 자동으로 응답**하는 시스템.

핵심은 단순한 auto-approve가 아니라, **프로젝트의 기획서, 아키텍처 문서, 판단 기준을 읽고 이해한 에이전트가 맥락에 맞는 판단을 내리는 것**이다.


## 2. 비전 (단계별)

### Phase 1: 자동응답 에이전트 (현재 스코프)
- Cowork의 질문에 자동 응답
- AskUserQuestion, 도구 승인, 자유 텍스트 입력 전부 대응

### Phase 2: 세션 관리 (다음)
- 작업 완료 감지
- 새 세션 자동 오픈
- 세션 간 작업 연속성 유지

### Phase 3: 메타 에이전트 (최종)
- CLI에서 "이 프로젝트 시작해" → Cowork에 지시
- 하네스 엔지니어링에 맞춰 기획서 작성
- Phase/Task별 자동 세션 전환
- 프로젝트를 끝까지 완전 자동화


## 3. 시스템 아키텍처

### 3.1 두 개의 레이어

```
레이어 1: 오케스트레이터 (Python, 결정적, 확정적)
  - 판단하지 않음
  - 이벤트 감지, 분류, 데이터 추출, CLI 호출, 응답 검증, AppleScript 입력

레이어 2: CLI 에이전트 (Claude CLI / Codex CLI, 판단)
  - 프로젝트 폴더를 열고 AGENTS.md + docs/ 읽음
  - 현재 상황 파악, 문서 기반 판단, 응답 생성
```

### 3.2 오케스트레이터 파이프라인

오케스트레이터는 4개의 독립 컴포넌트로 분리된다. 각각 하나의 일만 한다.

```
[Watcher] → [Dispatcher] → [Validator] → [Responder]
```

#### Watcher (감시)
- JSONL 파일을 tail -f로 감시
- 새 줄 추가 시 JSON 파싱
- 활성 세션의 JSONL 경로를 자동 탐지
- 세션 전환 시 새 JSONL로 자동 스위칭
- **지능 없음**: 파일 감시와 파싱만 수행

#### Dispatcher (분류 + CLI 호출)
- 이벤트 유형을 알고리즘으로 분류 (if/else, 규칙 기반)
  - AskUserQuestion: tool_use의 name이 "AskUserQuestion"
  - 도구 승인: tool_use가 있고 대응하는 tool_result 없음
  - 자유 텍스트: 기타 사용자 입력 대기 상태
- JSONL에서 최근 N개 메시지 추출 (알고리즘, JSON 파싱)
- 질문 + 옵션 + 최근 맥락을 조합하여 CLI 호출
- **지능 없음**: 분류와 데이터 추출은 전부 규칙 기반

#### Validator (검증)
- CLI 응답이 AppleScript에 넘길 수 있는 형식인지 검사 (알고리즘)
  - AskUserQuestion → 옵션 번호 또는 "Other: 텍스트"
  - 도구 승인 → "allow" 또는 "deny"
  - 자유 텍스트 → 비어있지 않은 문자열
- 형식 불일치 시 CLI에 재요청 (최대 N회)
- **지능 없음**: 형식 검증만 수행

#### Responder (입력)
- 검증된 응답을 AppleScript로 Cowork에 입력
- osascript로 Claude Desktop 앱 activate → keystroke/key code
- **전부 키보드만으로 처리 가능** — Accessibility API나 좌표 클릭 불필요
- 이벤트 유형별 입력 방식:
  - AskUserQuestion: 화살표 키(↑↓)로 옵션 이동 + `keystroke return` 선택. Other 선택 시 텍스트 입력 후 엔터.
  - 도구 승인: 허용 → `keystroke return` (Enter), 거부 → `key code 53` (Esc)
  - 자유 텍스트: `keystroke "텍스트"` + `keystroke return`
- **입력 후 검증 필수**: 입력 후 JSONL을 감시하여 대응하는 tool_result가 실제로 기록됐는지 확인. 기록되지 않으면 사일런트 실패로 간주하고 재시도 또는 경고.
- **지능 없음**: 입력만 수행

### 3.3 Watcher 상태 머신

JSONL 감지 시 오탐 방지를 위해 Watcher는 단순 패턴 매칭이 아닌 상태 머신으로 동작한다:

- Cowork가 tool_use를 연속으로 보내는 경우 → 마지막 tool_use 기준으로 판단
- tool_use 후 일정 시간(debounce) 대기 → 내부 처리 중인 것과 사용자 응답 대기를 구별
- 상태: `idle` → `tool_use_detected` → `debounce_wait` → `pending_response` → `responded`

### 3.4 CLI 에이전트 (판단)

CLI 에이전트(Claude CLI / Codex CLI)가 프로젝트 폴더에서 실행된다.
엔진 스위칭이 가능하다:

```bash
# Codex CLI (Spark 모델, 빠름)
codex -q "질문 내용" --context-file question.json

# Claude CLI (Sonnet/Opus, 깊은 추론)
claude -p "질문 내용"
```

CLI 에이전트는:
1. AGENTS.md를 읽고 프로젝트 구조를 파악한다
2. docs/의 기획서, 판단 기준, 규칙을 참고한다
3. Dispatcher가 넘긴 질문 + 옵션 + 맥락을 보고 판단한다
4. 정해진 형식으로 응답을 리턴한다

**에이전트 엔지니어링의 핵심은 이 CLI가 읽는 문서를 잘 설계하는 것이다.**


## 4. 운영 모드

자동전용 모드 하나만 운영한다. 단순하게.

- 시스템이 켜져 있으면 모든 질문에 자동 응답
- 사람은 개입하지 않음
- 켜고 끄는 것으로 제어


## 5. JSONL 구조 (감지 대상)

### 5.1 파일 위치

호스트 macOS:
```
~/Library/Application Support/Claude/local-agent-mode-sessions/
  {org-id}/{user-id}/local_{vm-id}/.claude/projects/
    -sessions-{session-name}/{session-id}.jsonl
```

VM 내부 (마운트):
```
/sessions/{session-name}/mnt/.claude/projects/
  -sessions-{session-name}/{session-id}.jsonl
```

양방향 bindfs 마운트 — 호스트에서 실시간 접근 가능.

### 5.2 레코드 타입

| 타입 | 설명 |
|------|------|
| queue-operation | 사용자 메시지 큐잉 (enqueue/dequeue) |
| user | 사용자 메시지 또는 tool_result |
| assistant | Claude 응답 (텍스트 + tool_use) |
| progress | 진행 상태 |
| last-prompt | 마지막 프롬프트 기록 |

### 5.3 감지 패턴

**"아직 답 안 한 질문" 판별:**
- assistant 레코드의 tool_use 블록에서 id 추출
- user 레코드의 tool_result에서 tool_use_id 매칭
- tool_use는 있는데 대응하는 tool_result가 없으면 = 답변 대기 중

**이벤트 분류 (알고리즘):**
```python
if tool_use.name == "AskUserQuestion":
    event_type = "question"
elif tool_use.name in TOOL_LIST and no_matching_result:
    event_type = "permission"
elif waiting_for_user_input:
    event_type = "free_text"
```


## 6. 프로젝트 폴더 구조 (하네스)

```
cowork-pilot/
  AGENTS.md                         # CLI 에이전트용 맵 (~100줄)
  ARCHITECTURE.md                   # 시스템 전체 구조

  docs/
    specs/
      auto-respond-spec.md          # 자동응답 시스템 기획서
    decision-criteria.md            # 질문 유형별 판단 기준
    golden-rules.md                 # 위반 불가 규칙
    exec-plans/
      active/
      completed/

  src/
    orchestrator/
      watcher.py                    # JSONL 감시
      dispatcher.py                 # 이벤트 분류 + CLI 호출
      validator.py                  # 응답 형식 검증
      responder.py                  # AppleScript 입력
      session_finder.py             # 활성 세션 탐지
      config.py                     # 모드, 엔진, 타임아웃 설정

  tests/
    fixtures/                       # 과거 JSONL 샘플
    test_watcher.py
    test_dispatcher.py
    test_validator.py
    test_responder.py

  scripts/
    lint_docs.py                    # 문서 최신 상태 검증
```


## 7. 에이전트 엔지니어링 (하네스)

### 7.1 원칙

OpenAI 하네스 엔지니어링 방식 적용:

- **AGENTS.md는 백과사전이 아니라 목차**: ~100줄. 프로젝트가 뭔지, 어디 뭐 있는지만.
- **docs/가 기록 시스템**: 모든 판단 기준, 규칙, 기획서는 여기에.
- **황금 규칙은 기계적으로 적용**: lint, 테스트로 인코딩.
- **문제 발견 → 문서화 → 규칙 인코딩**: 같은 실수 반복 방지.
- **에이전트 가독성 최적화**: CLI가 읽기 쉽게 문서 작성.

### 7.2 개발 방식

- 코드는 Codex CLI / Claude CLI가 작성
- 사람은 코드를 직접 쓰지 않음
- 사람의 역할: 기획서 작성, 문서 설계, 피드백 루프 구축, 결과 검증
- 문제 발견 시 → golden-rules.md에 기록 → lint/test로 인코딩 → 자동 적용

### 7.3 핵심 문서

#### AGENTS.md
- 프로젝트 개요
- 디렉토리 맵
- 작업 시 참고할 문서 경로
- 코딩 컨벤션

#### decision-criteria.md
- AskUserQuestion 대응: 선택지가 있으면 프로젝트 스펙 기반으로 선택
- 도구 승인 대응: golden-rules에 위반되지 않으면 허용
- 자유 텍스트 대응: exec-plans/active/ 참고해서 다음 지시

#### golden-rules.md
- 절대 삭제 명령 자동 승인하지 않기
- 외부 API 키/시크릿 관련 도구 자동 승인하지 않기
- **블랙리스트 질문은 무조건 사람에게 넘기기** (CLI가 자기 확신도를 정확히 판단 못하므로, 특정 카테고리는 자동 응답하지 않음)
  - 결제/과금 관련
  - 외부 서비스 계정 생성/삭제
  - 프로덕션 배포 승인
  - (프로젝트별로 추가)
- (프로젝트 진행하면서 계속 추가)


## 8. 기술 스택

| 컴포넌트 | 기술 | 이유 |
|----------|------|------|
| 오케스트레이터 | Python 3.11+ | JSON 파싱, 프로세스 관리, 간단 |
| CLI 에이전트 | Claude CLI + Codex CLI | 엔진 스위칭, 기존 구독 활용 |
| 입력 자동화 | AppleScript (osascript) | macOS 네이티브, 안정적, 간단 |
| JSONL 감시 | Python watchdog 또는 tail -f | 실시간 파일 감시 |
| 테스트 | pytest | 과거 JSONL fixtures로 검증 |


## 9. 로깅

golden-rules 피드백 루프를 돌리려면 구조화된 로그가 필수다. 모든 컴포넌트가 구조화된 로그를 남긴다:

```json
{
  "timestamp": "2026-03-21T10:30:00Z",
  "component": "dispatcher",
  "event_type": "ask_user_question",
  "question": "어떤 DB를 쓸까요?",
  "options": ["PostgreSQL", "SQLite", "MySQL"],
  "context_lines": 15,
  "engine": "codex",
  "cli_response": "1",
  "validator_result": "pass",
  "responder_action": "keystroke_arrow_down_0_enter",
  "post_verify": "tool_result_confirmed"
}
```

이 로그를 기반으로:
- 오판단 패턴 발견 → golden-rules에 추가
- 자주 실패하는 이벤트 유형 파악 → 프롬프트 개선
- Responder 사일런트 실패 감지 → 디버깅


## 10. 기술적 제약 및 리스크

| 제약 | 영향 | 대응 |
|------|------|------|
| Cowork 보안 모델 우회 | AppleScript로 사용자 입력 시뮬레이션 | 자동전용 모드에서만 전체 자동화, golden-rules로 위험 도구 차단 |
| JSONL 경로가 세션마다 다름 | session_finder가 동적으로 탐지 필요 | 최근 수정 시간 기준으로 활성 JSONL 탐지 |
| CLI 응답 형식 불일치 | AppleScript 입력 실패 | Validator에서 형식 검증 + 재요청 (최대 3회) |
| 앱 포커스 문제 | AppleScript가 다른 앱에 입력 | osascript로 Claude Desktop activate 후 입력 |
| LLM 판단 오류 | 잘못된 선택 | golden-rules로 위험 행동 차단, 로그 기록, 나중에 롤백 방법 설계 |
| Cowork 업데이트로 JSONL 포맷 변경 | 파서 깨짐 | 파서 테스트 fixtures 유지, 포맷 변경 시 빠르게 감지 |


## 10. 미결정 사항 (Phase 1 범위)

- [x] AskUserQuestion의 Cowork UI 실제 인터랙션 방식 → **화살표 키(↑↓) + Enter로 선택. 전부 키보드로 가능.**
- [x] AppleScript로 Cowork에 입력할 때의 정확한 시퀀스 → **앱 activate → keystroke/key code. 도구 승인은 Enter/Esc, 질문은 화살표+Enter, 자유 텍스트는 타이핑+Enter.**
- [x] Claude CLI의 비대화형 모드 → **`claude -p "프롬프트"` 원샷 실행. `--output-format json` 가능. 프로젝트 폴더에서 실행하면 AGENTS.md 자동 인식.**
- [x] Codex CLI의 프로젝트 폴더 지정 + 원샷 방식 → **`codex exec "프롬프트"` 비대화형. `--json`으로 JSONL 스트림. `--full-auto`로 승인 없이 실행. 프로젝트 폴더에서 실행하면 컨텍스트 자동 인식.**

---

> 이 문서는 하네스 엔지니어링 방식에 따라 Codex/Claude CLI가 읽고 이해할 수 있도록 작성됨.
> 프로젝트 진행하면서 발견한 문제와 규칙은 지속적으로 이 문서와 golden-rules.md에 반영한다.
