# Cowork Pilot

**Claude Cowork 세션을 감시하고, 권한 요청과 질문에 자동으로 응답하는 자율 에이전트 시스템.**

Cowork Pilot은 Claude Desktop의 [Cowork 모드](https://claude.ai) 세션 로그(JSONL)를 실시간으로 읽어, 도구 승인 요청이나 질문이 발생하면 CLI 에이전트(Claude Code / Codex)에게 판단을 위임하고, 그 결과를 AppleScript로 Cowork UI에 자동 입력한다.

사람이 하나하나 "Allow" 버튼을 누르거나 선택지를 고르는 대신, 미리 정의된 안전 규칙(`golden-rules.md`)과 판단 기준(`decision-criteria.md`)에 따라 에이전트가 대신 결정한다. 위험한 요청은 자동으로 **ESCALATE**하여 사람에게 알림을 보낸다.

---

## 작동 방식

### 핵심 파이프라인

```
JSONL 세션 로그 감시 (Watcher)
        ↓
도구 승인/질문 이벤트 감지
        ↓
CLI 에이전트에 판단 요청 (Dispatcher)
  - golden-rules.md + decision-criteria.md 주입
  - 최근 대화 맥락 추출
        ↓
응답 형식 검증 (Validator)
        ↓
AppleScript로 Cowork UI에 입력 (Responder)
        ↓
입력 성공 여부 확인 (Post-verify)
```

**핵심 설계 원칙**: Python 코드는 "멍청한 오케스트레이터"다. 모든 지능은 CLI 에이전트와 docs/에 있는 규칙 문서에 있다. 규칙을 바꾸고 싶으면 코드가 아니라 문서를 수정하면 된다.

### 안전 장치

Cowork Pilot은 모든 요청에 대해 다음 안전 규칙을 적용한다:

- **ESCALATE 블랙리스트**: 결제, 계정 생성/삭제, 시크릿 입력, 프로덕션 배포, 되돌릴 수 없는 데이터 삭제, 권한 변경 → 자동 응답하지 않고 사람에게 넘김
- **자동 거부 목록**: `rm -rf`, `sudo`, `git push --force`, 원격 스크립트 실행 등 위험 명령 → 즉시 거부
- **MCP 도구 키워드 필터**: 도구 이름에 `delete`, `remove`, `destroy` 등 포함 시 → ESCALATE
- **ESCALATE 알림**: macOS 알림 + 터미널 벨 + TTS 음성 안내

---

## 3가지 실행 모드

### Phase 1: Watch 모드 (기본)

현재 활성화된 Cowork 세션을 감시하며, 발생하는 이벤트에 자동 응답한다.

```bash
cowork-pilot
cowork-pilot --mode watch
```

감시 대상 도구:
- `AskUserQuestion` — 선택지 질문
- `mcp__cowork__allow_cowork_file_delete` — 파일 삭제 권한
- `mcp__cowork__request_cowork_directory` — 디렉토리 접근 권한
- 기타 모든 도구 승인 다이얼로그

### Phase 2: Harness 모드

실행 계획(exec-plan)을 로드하여 Chunk 단위로 Cowork 세션을 자동 개설하고, 각 Chunk의 완료 기준을 검증한다.

```bash
cowork-pilot --mode harness
```

동작 순서:
1. `docs/exec-plans/active/`에서 실행 계획 로드
2. 미완료 Chunk 찾기
3. 해당 Chunk의 세션 프롬프트로 새 Cowork 세션 열기
4. Phase 1 Watch 모드로 세션 내 이벤트 자동 응답
5. 세션이 idle 상태가 되면 완료 기준 검증
6. 완료 시 체크박스 업데이트 후 다음 Chunk로
7. 미완료 시 피드백 전송 후 재시도 (최대 3회)

### Phase 3: Meta 모드

프로젝트 설명(brief)으로부터 전체 프로젝트를 스캐폴딩하고, Harness 모드로 넘긴다.

```bash
cowork-pilot --mode meta "TODO 앱 REST API 만들기"
```

동작 순서:
1. 프로젝트 브리프 수집 (AskUserQuestion 반복)
2. 디렉토리 구조 생성 + Jinja2 템플릿으로 문서 자동 생성
3. 설계 문서, AGENTS.md, ARCHITECTURE.md 등 생성
4. 초기 exec-plan 생성
5. Harness 모드로 자동 전환하여 실행

---

## 요구 사항

### 운영 체제

- **macOS 전용** — AppleScript(`osascript`)로 UI를 자동화하므로 macOS에서만 작동한다.

### 필수 소프트웨어

| 소프트웨어 | 버전 | 설치 방법 |
|-----------|------|----------|
| **Python** | 3.10 이상 | `brew install python@3.12` 또는 [python.org](https://www.python.org/downloads/) |
| **Claude Desktop** | 최신 | [claude.ai/download](https://claude.ai/download) 에서 다운로드 |
| **Claude Code CLI** | 최신 | `npm install -g @anthropic-ai/claude-code` ([문서](https://docs.anthropic.com/en/docs/claude-code)) |

### Claude Desktop 설정

1. Claude Desktop을 설치하고 로그인한다.
2. **Cowork 모드**를 활성화한다 (Settings → Desktop app → Cowork).
3. Cowork 세션을 하나 이상 열어본 적이 있어야 세션 디렉토리가 생성된다.

### Claude Code CLI 확인

```bash
claude --version   # Claude Code CLI가 설치되어 있는지 확인
```

설치가 안 되어 있으면:

```bash
npm install -g @anthropic-ai/claude-code
```

Codex 엔진을 사용하려면 Codex CLI도 설치한다:

```bash
npm install -g @openai/codex
```

---

## 설치

### 1. 저장소 클론

```bash
git clone https://github.com/<your-username>/cowork-pilot.git
cd cowork-pilot
```

### 2. 패키지 설치

```bash
pip install -e .
```

개발 환경 (테스트 포함):

```bash
pip install -e ".[dev]"
```

### 3. 설치 확인

```bash
cowork-pilot --help
```

---

## 설정

프로젝트 루트의 `config.toml`을 수정한다. 기본값이 대부분 합리적이므로, 보통은 수정 없이 사용 가능하다.

```toml
# ── 엔진 설정 ──
[engine]
default = "claude"              # "claude" 또는 "codex"

[engine.claude]
command = "claude"              # Claude Code CLI 경로
args = ["-p"]                   # -p: project mode

[engine.codex]
command = "codex"               # Codex CLI 경로
args = ["-q"]                   # -q: quiet mode

# ── Watcher 설정 ──
[watcher]
debounce_seconds = 2.0          # 이벤트 감지 후 실제 처리까지 대기 시간
poll_interval_seconds = 0.5     # JSONL 파일 폴링 주기

# ── Responder 설정 ──
[responder]
post_verify_timeout_seconds = 30.0  # 응답 입력 후 확인 대기 시간
max_retries = 3                     # CLI 응답 검증 재시도 횟수
activate_delay_seconds = 0.3        # AppleScript 실행 전 대기 시간

# ── 세션 경로 ──
[session]
base_path = "~/Library/Application Support/Claude/local-agent-mode-sessions"

# ── 로깅 ──
[logging]
path = "logs/cowork-pilot.jsonl"    # 구조화된 JSONL 로그 출력 경로
level = "INFO"                      # DEBUG, INFO, WARN, ERROR

# ── 코드 리뷰 ──
[review]
enabled = true                  # Chunk 완료 시 코드 리뷰 실행 여부
skip_chunks = []                # 리뷰 건너뛸 chunk 번호 (예: [1, 3])

# ── Harness 모드 설정 ──
[harness]
idle_timeout_seconds = 30       # 세션 idle 감지 타임아웃
completion_check_max_retries = 3    # 완료 기준 검증 재시도
incomplete_retry_max = 3            # 미완료 Chunk 재시도 횟수
exec_plans_dir = "docs/exec-plans"  # 실행 계획 디렉토리

[harness.session]
open_delay_seconds = 3.0        # 세션 열기 후 대기
prompt_delay_seconds = 1.0      # 프롬프트 입력 후 대기
detect_timeout_seconds = 10.0   # 세션 감지 타임아웃
detect_poll_interval = 1.0      # 세션 감지 폴링 주기
```

---

## 사용법

### 기본 사용 (Watch 모드)

Claude Desktop에서 Cowork 세션을 열고, 터미널에서:

```bash
cowork-pilot
```

이제 Cowork가 도구 승인이나 질문을 띄울 때마다 자동으로 응답한다.

### 엔진 변경

```bash
cowork-pilot --engine codex    # Codex 엔진 사용
cowork-pilot --engine claude   # Claude Code 엔진 사용 (기본값)
```

### 커스텀 설정 파일

```bash
cowork-pilot --config my-config.toml
```

### Harness 모드로 실행 계획 자동 수행

1. `docs/exec-plans/active/`에 실행 계획 마크다운을 넣는다.
2. 실행한다:

```bash
cowork-pilot --mode harness
```

### Meta 모드로 프로젝트 생성

```bash
cowork-pilot --mode meta "할일 관리 앱 — Next.js + Supabase"
```

---

## 프로젝트 구조

```
cowork-pilot/
├── src/cowork_pilot/
│   ├── main.py                  # CLI 진입점 + 메인 루프
│   ├── watcher.py               # JSONL 파일 tail + 상태 머신
│   ├── dispatcher.py            # 프롬프트 빌더 + CLI 호출
│   ├── validator.py             # 응답 형식 검증
│   ├── responder.py             # AppleScript 생성 + 실행
│   ├── models.py                # 데이터 클래스 (Event, Response 등)
│   ├── config.py                # TOML 설정 로더
│   ├── logger.py                # 구조화된 JSONL 로거
│   ├── session_finder.py        # 활성 Cowork 세션 탐색
│   ├── session_manager.py       # Chunk 생명주기 관리
│   ├── session_opener.py        # AppleScript로 세션 열기
│   ├── completion_detector.py   # Idle 감지 + 완료 검증
│   ├── plan_parser.py           # 실행 계획 마크다운 파서
│   ├── brief_parser.py          # 프로젝트 브리프 파서
│   ├── meta_runner.py           # Phase 3 오케스트레이션
│   ├── scaffolder.py            # 프로젝트 디렉토리 + 템플릿 생성
│   └── brief_templates/         # Jinja2 템플릿 (9개 .j2 파일)
│
├── docs/
│   ├── golden-rules.md          # 절대 규칙 + ESCALATE 블랙리스트
│   ├── decision-criteria.md     # 도구/질문별 판단 기준
│   ├── project-conventions.md   # 프로젝트 폴더 구조 컨벤션
│   ├── brief-template.md        # 브리프 마크다운 형식 정의
│   ├── specs/                   # 설계 문서 (날짜별)
│   └── exec-plans/              # 실행 계획
│       ├── planning/            # 대기 중 (번호순 자동 승격)
│       ├── active/              # 진행 중 (최대 1개)
│       └── completed/           # 완료됨
│
├── tests/                       # pytest 테스트 (19개 모듈)
│   ├── conftest.py
│   ├── fixtures/                # JSONL 테스트 데이터
│   └── test_*.py
│
├── config.toml                  # 런타임 설정
├── pyproject.toml               # 패키지 메타데이터
├── AGENTS.md                    # 에이전트용 프로젝트 요약
└── logs/                        # 런타임 로그 출력
```

---

## 아키텍처

### 모듈 간 흐름

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌────────────┐
│   Watcher    │───▶│  Dispatcher  │───▶│  Validator   │───▶│  Responder │
│              │    │              │    │              │    │            │
│ JSONL tail   │    │ 프롬프트 빌드 │    │ 형식 검증    │    │ AppleScript│
│ 상태 머신     │    │ CLI 호출     │    │ 재시도 로직   │    │ 키보드 입력 │
└─────────────┘    └──────────────┘    └─────────────┘    └────────────┘
                          │
                    ┌─────┴─────┐
                    │ golden-   │
                    │ rules.md  │
                    │ decision- │
                    │ criteria  │
                    └───────────┘
```

### 상태 머신 (Watcher)

```
IDLE ──(tool_use 감지)──▶ TOOL_USE_DETECTED
                                │
                       (debounce 대기)
                                │
                                ▼
                         DEBOUNCE_WAIT
                                │
                   ┌────────────┴────────────┐
                   │                         │
            (tool_result 도착)         (타임아웃)
                   │                         │
                   ▼                         ▼
                 IDLE              PENDING_RESPONSE
                                         │
                                   (응답 전송)
                                         │
                                         ▼
                                     RESPONDED
                                         │
                                   (확인 완료)
                                         │
                                         ▼
                                       IDLE
```

### 응답 형식

CLI 에이전트가 리턴하는 응답 형식:

| 이벤트 타입 | 응답 | 의미 |
|-----------|------|------|
| 도구 승인 (Permission) | `ALLOW` | 승인 |
| 도구 승인 (Permission) | `DENY` | 거부 |
| 도구 승인 (Permission) | `ESCALATE` | 사람에게 넘김 |
| 질문 (Question) | `SELECT 2` | 2번 옵션 선택 |
| 질문 (Question) | `OTHER 텍스트` | 자유 텍스트 입력 |
| 질문 (Question) | `ESCALATE` | 사람에게 넘김 |
| 자유 텍스트 (Free Text) | `TEXT 내용` | 텍스트 입력 |
| 자유 텍스트 (Free Text) | `ESCALATE` | 사람에게 넘김 |

---

## 판단 규칙 개요

### 자동 허용 (Auto-Allow) 도구

읽기 전용이거나 부작용 없는 도구: `Read`, `Glob`, `Grep`, `TodoWrite`, `WebSearch`

### 조건부 허용 도구

프로젝트 경로 내에서만 허용, golden-rules 검사 필요: `Write`, `Edit`, `Bash`, `Agent`, `WebFetch`

### 자동 거부 패턴

`rm -rf`, `sudo`, `git push --force`, `git reset --hard`, `chmod 777`, 원격 스크립트 실행 (`curl | bash`) 등

### ESCALATE 대상

결제/과금, 외부 계정 생성, 시크릿 입력, 프로덕션 배포, 되돌릴 수 없는 데이터 삭제, 권한/보안 변경

규칙의 상세 내용은 `docs/golden-rules.md`와 `docs/decision-criteria.md`를 참조.

---

## 실행 계획 (Exec-Plan) 형식

Harness 모드에서 사용하는 실행 계획은 마크다운으로 작성한다:

```markdown
# 프로젝트 이름 — 실행 계획

## Chunk 1: 기본 구조 세팅

### Tasks
- [ ] 디렉토리 구조 생성
- [ ] 패키지 초기화
- [ ] 설정 파일 작성

### Completion Criteria
- [ ] `src/` 디렉토리 존재
- [ ] `pytest` 통과

### Session Prompt
프로젝트 기본 구조를 세팅하라. ...

## Chunk 2: 핵심 기능 구현
...
```

실행 계획은 `docs/exec-plans/` 아래에서 관리된다:
- `planning/` → 대기 (번호순으로 자동 승격)
- `active/` → 진행 중 (최대 1개)
- `completed/` → 완료됨

---

## 테스트

```bash
# 전체 테스트
pytest

# 특정 모듈
pytest tests/test_watcher.py

# 상세 출력
pytest -v
```

19개 테스트 모듈이 파이프라인의 각 단계를 커버한다: watcher, dispatcher, validator, responder, config, models, plan_parser, brief_parser, session_finder, session_manager, session_opener, completion_detector, scaffolder, meta_runner, integration 등.

---

## 로그 확인

실행 중 발생하는 모든 이벤트는 구조화된 JSONL 형식으로 기록된다:

```bash
# 실시간 로그 확인
tail -f logs/cowork-pilot.jsonl | python -m json.tool

# ESCALATE된 이벤트만 필터
grep '"level":"WARN"' logs/cowork-pilot.jsonl
```

---

## 트러블슈팅

### "세션을 찾을 수 없습니다"

Claude Desktop에서 Cowork 세션이 활성화되어 있는지 확인한다. 세션을 한 번도 열어본 적이 없으면 세션 디렉토리 자체가 생성되지 않는다.

```bash
ls ~/Library/Application\ Support/Claude/local-agent-mode-sessions/
```

### AppleScript 권한 오류

macOS의 시스템 환경설정 → 개인 정보 보호 및 보안 → 접근성에서 터미널(또는 사용 중인 터미널 앱)에 접근성 권한을 부여한다.

### CLI 에이전트 타임아웃

`config.toml`에서 `post_verify_timeout_seconds`를 늘리거나, Claude Code CLI가 정상 작동하는지 확인한다:

```bash
echo "hello" | claude -p
```

---

## 설계 원칙

- **오케스트레이터는 멍청하다.** 모든 지능은 CLI 에이전트와 docs/의 규칙 문서에 있다. Python 코드는 기계적 파이프라인: 감시 → 디스패치 → 검증 → 응답.
- **파일 하나, 책임 하나.** 각 모듈은 파이프라인의 한 단계만 담당한다.
- **클래스보다 함수.** 파이프라인 단계는 순수 함수, 데이터만 dataclass.
- **의심되면 ESCALATE.** 위험한 선택보다 사람에게 넘기는 게 항상 낫다.
- **규칙은 코드가 아니라 문서.** golden-rules.md를 수정하면 코드 변경 없이 동작이 바뀐다.

---

## 기여

오판단을 발견하면:

1. `docs/golden-rules.md`에 새 규칙을 추가한다
2. `tests/`에 해당 케이스의 fixture를 추가한다
3. `docs/decision-criteria.md`도 함께 업데이트한다
4. `pytest`가 통과하는지 확인한다

---

## 라이선스

MIT
