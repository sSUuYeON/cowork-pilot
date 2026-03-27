**한국어** | [English](README.en.md)

# Cowork Pilot

기획서 하나로 프로젝트를 끝까지 만들어주는 E2E AI 자동화 시스템.

개발 기획서를 넣으면 Cowork(Claude Desktop의 에이전트 모드)가 코드를 작성하고, cowork-pilot이 그 과정에서 발생하는 모든 질문과 권한 요청에 자동으로 응답하며, 실행 계획을 Chunk 단위로 오케스트레이션하여 프로젝트 구현을 완주한다. 사람은 기획만 하고 나머지는 AI가 알아서 한다.

---

## 이 프로젝트가 하는 일

### Phase 1 — 자동 응답 (Watch 모드)

Cowork 세션의 JSONL 로그를 실시간으로 감시하다가 `AskUserQuestion`이나 도구 권한 요청이 발생하면:

1. **Watcher**가 JSONL 파일을 tail하며 `tool_use` 이벤트를 감지
2. **Dispatcher**가 프로젝트 문서(`golden-rules.md`, `decision-criteria.md`)와 최근 대화 컨텍스트를 읽어 CLI 에이전트에게 보낼 프롬프트를 생성
3. **CLI 에이전트**(`claude -p`)가 "옵션 번호", "allow/deny", 또는 "ESCALATE"를 반환
4. **Validator**가 응답 형식을 검증 (잘못된 형식이면 최대 3회 재시도)
5. **Responder**가 AppleScript로 Claude Desktop 앱에 키보드 입력 (화살표 키, Enter, Cmd+V 등)
6. **Post-verify**로 JSONL에 `tool_result`가 나타나는지 확인하여 응답이 실제로 전달되었는지 검증

위험한 요청(결제, 시크릿, 프로덕션 배포 등)은 자동으로 **ESCALATE** 처리되어 macOS 알림 + TTS로 사용자에게 알린다.

### Phase 2 — 실행 계획 오케스트레이션 (Harness 모드)

`docs/exec-plans/`에 작성된 실행 계획(exec-plan)을 Chunk 단위로 자동 실행한다:

1. `planning/`에서 `active/`로 실행 계획을 승격
2. 각 Chunk의 세션 프롬프트로 새 Cowork 세션을 열고 (AppleScript `Shift+Cmd+O`)
3. Phase 1 자동 응답을 동시에 돌리면서 Chunk 작업을 진행
4. 세션이 idle 상태가 되면 exec-plan의 체크박스(`[x]`)를 확인하여 완료 여부 판단
5. 미완료면 피드백을 보내 재시도, 재시도 초과하면 ESCALATE
6. 완료되면 다음 Chunk로 이동, 모든 Chunk 완료 시 `completed/`로 이동

### Phase 3 — 메타 에이전트 (Meta 모드)

프로젝트 설명 한 줄로부터 전체 프로젝트를 생성한다:

- **Step 0**: Cowork 세션에서 사용자와 대화하며 프로젝트 브리프 작성
- **Step 1**: 브리프 기반으로 프로젝트 디렉토리 + docs 템플릿 스캐폴딩
- **Step 2**: Harness로 docs 내용 자동 생성 (설계 문서, 스펙 등)
- **Step 3**: 사용자 검증/승인 (수동 또는 자동)
- **Step 4**: Harness로 구현 계획 순차 실행

---

## 추천 사용 플로우

전체 흐름은 **기획서 준비 → docs 구조 생성 → 자동 실행** 3단계다.

### Step 1: 개발 기획서 준비

cowork-pilot이 자동으로 프로젝트를 구현하려면, 먼저 **개발 기획서**(설계 문서, 기능 명세, 데이터 모델 등)가 필요하다. 두 가지 방법 중 하나로 준비한다:

- **방법 A — Cowork에서 대화하며 작성**: Claude Desktop의 Cowork 모드에서 프로젝트에 대해 충분히 대화하면서 기획 내용을 정리한다. 대화가 끝나면 결과물을 마크다운 파일로 저장한다.
- **방법 B — 기존 기획서 사용**: 이미 작성된 기획서(마크다운, 노션 export 등)가 있으면 그대로 사용한다.

형식은 자유다. 중요한 건 프로젝트의 기능, 기술 스택, 설계 방향이 담겨 있는 것.

### Step 2: docs 구조 생성 (`/docs-restructurer` 스킬)

기획서가 준비되면 Cowork 새 세션을 열고, 기획서 파일을 넣은 뒤 `/docs-restructurer` 스킬을 호출한다. 이 스킬이 자유 형식 기획서를 cowork-pilot이 이해하는 표준 `docs/` 구조로 변환해준다:

```
docs/
├── design-docs/       # 설계 문서 (데이터 모델, 인증, 아키텍처 등)
├── product-specs/     # 페이지/기능별 상세 스펙
├── exec-plans/        # 실행 계획 (Chunk 단위)
│   ├── planning/      # 대기 중인 계획들 (번호순)
│   ├── active/        # 현재 실행 중 (최대 1개)
│   └── completed/     # 완료된 계획
├── DESIGN_GUIDE.md
├── SECURITY.md
└── QUALITY_SCORE.md
```

여기서 핵심은 `exec-plans/` 안에 Chunk별 실행 계획이 자동 생성된다는 것이다. 각 Chunk에는 작업 목록, 완료 조건 체크박스, 세션 프롬프트가 포함된다.

> **참고**: `/docs-restructurer` 스킬은 5단계 파이프라인으로 동작하며, 각 단계가 끝날 때마다 결과를 보여주고 다음 단계를 진행해도 되는지 확인 질문을 한다. 또한 기획서에서 빠진 정보가 있으면 추가 질문을 할 수 있다. 완전 자동이 아니라 **사용자가 Cowork 화면을 보면서 질문에 답해줘야** 하는 반자동 과정이다.

### Step 3: 자동 실행 (`--mode harness`)

docs 구조가 생성되면 터미널에서 프로젝트 경로로 이동 후 harness 모드를 실행한다:

```bash
cd /path/to/your-project
cowork-pilot --mode harness
```

이 순간부터 cowork-pilot이 자동으로:
1. `planning/`에서 첫 번째 exec-plan을 `active/`로 승격
2. Chunk 1의 세션 프롬프트로 Cowork 세션을 열기
3. Cowork가 코드를 작성하는 동안 발생하는 질문/권한 요청에 자동 응답
4. Chunk 완료 → 다음 Chunk → 모든 Chunk 완료 → 다음 exec-plan... 반복
5. 모든 계획이 끝나면 macOS 알림으로 완료 통지

사용자는 터미널을 띄워놓고 다른 일을 하면 된다. 위험한 판단이 필요하면 ESCALATE 알림이 온다.

### 전체 흐름 요약

```
[사용자] 기획서 작성 (Cowork 대화 or 기존 문서)
    │
    ▼
[Cowork] /docs-restructurer 스킬로 docs/ 구조 생성
    │
    ▼
[터미널] cowork-pilot --mode harness
    │
    ▼
[자동] Chunk별 Cowork 세션 → 코드 작성 → 완료 검증 → 반복
    │
    ▼
[완료] 전체 프로젝트 구현 완료 알림
```

### 필요한 Cowork 스킬 (플러그인)

cowork-pilot이 열어주는 Cowork 세션은 아래 스킬들을 사용한다. 모두 설치되어 있어야 정상 동작한다.

**이 레포의 플러그인 (GitHub URL로 설치)**

이 레포 자체가 Cowork 플러그인이다. Claude Desktop에서 이 GitHub 레포 URL을 플러그인으로 등록하면 아래 3개 스킬이 자동으로 설치된다:

| 스킬 | 역할 |
|------|------|
| `/docs-restructurer` | 기획서 → docs/ 구조 변환 (Step 2에서 사용) |
| `/chunk-complete` | Chunk 완료 시 exec-plan 체크박스 업데이트 |
| `/vm-install` | VM에서 빌드/테스트용 툴체인 안전 설치 + 자동 정리 |

**별도 설치 필요 (Anthropic 공식 플러그인)**

| 스킬 | 설치 방법 |
|------|-----------|
| `/engineering:code-review` | Claude Desktop에서 `engineering` 플러그인 설치 (Anthropic 공식 제공) |

`/engineering:code-review`와 `/chunk-complete`는 harness가 Chunk 세션 프롬프트에 자동으로 주입하는 워크플로의 일부다. 코드 리뷰 → 수정 → 완료 처리 순서가 강제되므로 품질이 유지된다.

---

## 요구 사항

### 운영체제

**macOS 전용.** AppleScript(`osascript`), `pbcopy`, macOS 알림(`display notification`), `say` TTS를 사용한다.

### 필수 소프트웨어

| 소프트웨어 | 버전 | 용도 |
|-----------|------|------|
| **Python** | 3.10 이상 | 런타임 |
| **Claude Desktop** | Cowork 모드 지원 버전 | 자동 응답 대상 앱 |
| **Claude CLI** | 최신 | 질문 판단 엔진 |

Claude CLI는 `claude -p` 플래그로 stdin에서 프롬프트를 받아 stdout으로 답변을 출력하는 파이프 모드를 사용한다.

### macOS 권한

cowork-pilot은 AppleScript로 Claude Desktop에 키보드 입력(`keystroke`, `key code`)을 보낸다. 이 기능이 작동하려면 **손쉬운 사용(Accessibility) 권한**이 필요하다.

**시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용**에서 사용하는 터미널 앱(Terminal, iTerm2, Warp 등)을 추가하고 활성화해야 한다. 이 권한이 없으면 AppleScript `keystroke`/`key code` 명령이 무시되어 자동 응답이 전혀 작동하지 않는다.

처음 실행 시 macOS가 권한을 요청하는 팝업을 띄울 수 있다. 팝업이 안 뜨면 위 경로에서 직접 추가한다.

---

## 설치

```bash
# 저장소 클론
git clone https://github.com/<your-username>/cowork-pilot.git
cd cowork-pilot

# 패키지 설치 (editable mode)
pip install -e .

# 개발 의존성 포함 설치
pip install -e ".[dev]"
```

유일한 런타임 의존성은 `jinja2>=3.1`이다.

---

## 설정

`config.toml` 파일로 모든 설정을 관리한다. 프로젝트 루트에 위치한다.

```toml
[engine]
default = "claude"

[engine.claude]
command = "claude"
args = ["-p"]                # pipe mode (stdin → stdout)

[watcher]
debounce_seconds = 2.0       # 이벤트 감지 후 응답 전 대기 시간
poll_interval_seconds = 0.5  # JSONL 파일 폴링 간격

[responder]
post_verify_timeout_seconds = 30.0  # 응답 전달 후 검증 대기
max_retries = 3                     # CLI 응답 형식 재시도 횟수
activate_delay_seconds = 0.3        # AppleScript 앱 활성화 대기

[session]
base_path = "~/Library/Application Support/Claude/local-agent-mode-sessions"

[logging]
path = "logs/cowork-pilot.jsonl"
level = "INFO"

[harness]
idle_timeout_seconds = 30            # Chunk idle 감지 타임아웃
completion_check_max_retries = 3     # 완료 검증 재시도
incomplete_retry_max = 3             # 미완료 피드백 재시도
exec_plans_dir = "docs/exec-plans"

[harness.session]
open_delay_seconds = 3.0     # 새 세션 열기 후 대기
prompt_delay_seconds = 1.0   # 프롬프트 입력 전 대기
detect_timeout_seconds = 10.0
detect_poll_interval = 1.0
```

---

## 사용법

### Phase 1: 자동 응답 (Watch 모드)

Cowork 세션이 실행 중인 상태에서:

```bash
cowork-pilot
```

가장 최근 활성 JSONL 세션을 자동으로 찾아 감시를 시작한다. 세션이 바뀌면 자동으로 전환된다.

```bash
# config 파일 지정
cowork-pilot --config my-config.toml
```

### Phase 2: 실행 계획 오케스트레이션 (Harness 모드)

```bash
cowork-pilot --mode harness
```

`docs/exec-plans/active/`에 있는 exec-plan 파일을 읽어 Chunk별로 Cowork 세션을 열고 실행한다. `active/`가 비어있으면 `planning/`에서 자동 승격한다.

### Phase 3: 메타 에이전트 (Meta 모드)

```bash
cowork-pilot --mode meta "할 일 관리 웹앱을 만들어줘"
```

프로젝트 설명을 인자로 전달하면 Cowork 대화를 통해 브리프를 채우고, 스캐폴딩하고, docs를 생성하고, 구현까지 자동으로 진행한다.

---

## 작동 원리

### 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                    cowork-pilot                      │
│                                                      │
│  ┌──────────┐   ┌────────────┐   ┌───────────────┐  │
│  │  Watcher  │──▶│ Dispatcher │──▶│  CLI Agent    │  │
│  │(JSONL Tail)│  │(Prompt Build)│  │(claude -p)   │  │
│  └──────────┘   └────────────┘   └───────┬───────┘  │
│       ▲                                   │          │
│       │              ┌────────────┐       ▼          │
│       │              │ Validator  │◀──(raw text)     │
│       │              └─────┬──────┘                  │
│       │                    │                         │
│       │              ┌─────▼──────┐                  │
│       │              │ Responder  │                  │
│       │              │(AppleScript)│                 │
│       │              └─────┬──────┘                  │
│       │                    │                         │
│       └────────────────────┘  (post-verify)          │
└─────────────────────────────────────────────────────┘
         ▲                           │
         │ JSONL read                │ AppleScript keystroke
         ▼                           ▼
┌─────────────────┐        ┌──────────────────┐
│  Cowork Session  │        │  Claude Desktop  │
│  (JSONL log)     │        │  (macOS app)     │
└─────────────────┘        └──────────────────┘
```

### 모듈 구조

```
src/cowork_pilot/
├── main.py                 # CLI 엔트리포인트, 메인 루프 (watch/harness/meta)
├── watcher.py              # JSONL tail + 상태 머신 (IDLE→DETECTED→DEBOUNCE→PENDING→RESPONDED)
├── dispatcher.py           # 프롬프트 생성, CLI 호출, 프로젝트 문서 로드
├── validator.py            # CLI 응답 형식 검증 (select/other/allow/deny/escalate)
├── responder.py            # AppleScript 생성·실행, macOS 알림, 클립보드, 응답 검증
├── models.py               # 데이터 클래스 (Event, Response, EventType, WatcherState)
├── config.py               # TOML 설정 로드 (Config, HarnessConfig, MetaConfig 등)
├── session_finder.py       # 가장 최근 활성 JSONL 세션 탐색
├── session_opener.py       # AppleScript로 새 Cowork 세션 열기 (Shift+Cmd+O)
├── session_manager.py      # Chunk 라이프사이클 관리, exec-plan 이동
├── plan_parser.py          # exec-plan 마크다운 파싱 (Chunk, Task, Criteria)
├── completion_detector.py  # idle 감지, Chunk 완료 검증, 피드백 전송
├── scaffolder.py           # 브리프 기반 프로젝트 디렉토리 + 템플릿 스캐폴딩
├── brief_parser.py         # project-brief.md 파싱
├── meta_runner.py          # 메타 에이전트 오케스트레이션 (Step 0~4)
├── logger.py               # 구조화된 JSONL 로거
└── brief_templates/        # Jinja2 프로젝트 템플릿 (.j2)
```

### 판단 기준 문서

CLI 에이전트가 판단할 때 사용하는 규칙은 `docs/`에 있다:

- `docs/golden-rules.md` — ESCALATE 블랙리스트 (결제, 시크릿, 프로덕션 배포 등 자동 응답 금지 카테고리)
- `docs/decision-criteria.md` — 도구별 허용/거부 기준 (Read=항상허용, Bash=조건부 등)

이 문서들은 Dispatcher가 매 요청마다 프롬프트에 직접 주입하므로, 규칙을 수정하면 즉시 반영된다.

### exec-plan 형식

```markdown
# Plan: 기능 구현

## Chunk 1: 데이터 모델

### Tasks
- User 모델 생성
- DB 마이그레이션

### Completion Criteria
- [ ] User 모델 파일 존재
- [ ] 마이그레이션 성공

### Session Prompt
User 모델을 생성하고 마이그레이션을 실행하세요...
```

Chunk가 완료되면 `[ ]`가 `[x]`로 업데이트되고, 모든 Chunk 완료 시 `completed/`로 이동한다.

---

## 프로젝트 구조

```
cowork-pilot/
├── .claude-plugin/            # Cowork 플러그인 매니페스트
│   └── plugin.json
├── skills/                    # Cowork 스킬 (플러그인으로 자동 배포)
│   ├── docs-restructurer/     # 기획서 → docs/ 구조 변환
│   ├── chunk-complete/        # exec-plan 체크박스 마킹
│   └── vm-install/            # VM 안전 설치 + 자동 정리
├── src/cowork_pilot/          # Python 오케스트레이터 소스 코드
├── tests/                     # pytest 테스트 + JSONL 픽스처
│   └── fixtures/              # 테스트용 JSONL 샘플
├── docs/
│   ├── golden-rules.md        # 자동 응답 절대 규칙
│   ├── decision-criteria.md   # 도구별 판단 기준
│   ├── specs/                 # 설계 스펙 문서
│   └── exec-plans/            # 실행 계획
│       ├── active/            # 현재 실행 중 (최대 1개)
│       ├── planning/          # 대기 중 (번호순 자동 승격)
│       └── completed/         # 완료된 계획
├── config.toml                # 런타임 설정
├── pyproject.toml             # 빌드 설정 (hatchling)
├── AGENTS.md                  # 프로젝트 개요 (에이전트 + 사람용)
└── logs/                      # 구조화된 JSONL 로그
```

---

## 테스트

```bash
pytest
```

모든 테스트는 JSONL 픽스처(`tests/fixtures/`)를 사용하며, 실제 CLI 호출이나 AppleScript 실행 없이 각 모듈의 로직을 독립적으로 검증한다.

---

## 실행 전 macOS 설정

cowork-pilot은 AppleScript로 Claude Desktop에 키보드 입력을 보내는 방식으로 동작한다. 화면이 꺼지거나 잠기면 키 입력이 전달되지 않으므로, 실행 전에 아래 설정을 반드시 확인해야 한다.

**시스템 설정 → 잠금 화면:**
- "배터리 사용 시 비활성 상태인 경우 디스플레이 끄기" → **안 함**
- "전원 어댑터 사용 시 비활성 상태인 경우 디스플레이 끄기" → **안 함**

**시스템 설정 → 화면 보호기:**
- 화면 보호기 시작 시간 → **안 함** (또는 충분히 긴 시간)

**실행 중 주의:**
- cowork-pilot이 돌아가는 동안에는 **맥을 건드리지 않는 것**이 좋다. 다른 앱으로 포커스를 옮기면 AppleScript가 Claude Desktop에 키 입력을 보내는 타이밍이 꼬일 수 있다.
- 장시간 자동 실행할 경우 맥을 전원에 연결해두는 것을 권장한다.

---

## 주의사항

- **macOS 전용**: AppleScript, `pbcopy`, `osascript`, `say` 등 macOS 고유 API에 의존한다.
- **Claude Desktop 필수**: Cowork 모드의 JSONL 세션 로그를 읽고, AppleScript로 앱에 키 입력을 보내는 구조이므로 Claude Desktop이 실행 중이어야 한다.
- **접근성 권한**: System Events를 통한 키보드 제어에 macOS 손쉬운 사용 권한이 필요하다.
- **Claude CLI**: `claude` 명령어가 `$PATH`에 있어야 한다.

---

## 라이선스

MIT
