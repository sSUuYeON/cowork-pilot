# 메타 에이전트 (Phase 3) — 설계 문서

> 프로젝트 브리프 → docs/ 자동 생성 → 구현 자동 실행까지의 완전 자동화 시스템
> 작성일: 2026-03-25
> 상태: Draft

---

## 1. 목표

사용자가 "이런 프로젝트 만들고 싶어"라고 말하면, 메타 에이전트가 대화를 통해 요구사항을 구체화하고, OpenAI 하네스 엔지니어링 스타일의 docs/ 구조를 자동 생성하며, 기존 Phase 2 하네스로 구현까지 자동 실행하는 시스템.

핵심 원칙:
- **AGENTS.md는 목차, docs/가 기록 시스템** — 거대한 단일 파일이 아닌 구조화된 문서 체계
- **구조는 코드가, 내용은 에이전트가** — 디렉토리/빈 템플릿은 결정적 코드가 생성, 내용은 Cowork 세션이 채움
- **기존 인프라 재사용** — Phase 1 자동응답 + Phase 2 하네스 위에 올라가는 레이어

Phase 2 하네스의 확장판이다. 하네스의 입력(exec-plan + docs/)을 자동 생성하는 것이 본질.

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                     메타 에이전트 (Phase 3)                    │
│                                                             │
│  [Step 0] 브리프 채우기 (Cowork 세션, 사용자 직접 응답)         │
│      ↓                                                      │
│  [Step 1] 스캐폴딩 (Python 코드, 결정적)                      │
│      ↓                                                      │
│  [Step 2] 내용 채우기 (Phase 2 하네스, 자동)                   │
│      ↓                                                      │
│  [Step 3] 검증 + 승인                                        │
│      ↓                                                      │
│  [Step 4] 구현 시작 (Phase 2 하네스, 자동)                     │
└─────────────────────────────────────────────────────────────┘
        ↕                    ↕                    ↕
   브리프 템플릿        Cowork 세션 (JSONL)    Phase 1 자동응답
   (정해진 형식)        (Phase 2 Watcher)      (Step 2~4에서 ON)
```

### 2.1 기존 Phase 1~2와의 관계

Phase 1: 이벤트 단위 자동응답 (질문 → 판단 → 입력)
Phase 2: Chunk 단위 자동실행 (exec-plan → 세션 열기 → 완료 감지)
Phase 3: 계획 단위 자동생성 (브리프 → docs/ 생성 → exec-plan 생성 → Phase 2 실행)

세 레이어가 동시에 동작한다:
- Phase 3이 세션을 열고 docs/를 생성
- Phase 2가 exec-plan의 Chunk를 실행
- Phase 1이 각 세션 안에서 질문에 자동 응답

### 2.2 Phase 1 자동응답 제어

`--mode meta`로 실행 시:
- Step 0 (브리프 채우기): Phase 1 자동응답 **OFF** — 사용자 의도를 담아야 하므로
- Step 2~4 (내용 채우기 + 구현): Phase 1 자동응답 **ON** — 에이전트가 자동 진행

구현 방식: 메타 에이전트가 브리프 세션의 JSONL 경로를 `ignored_sessions: set[Path]`에 등록.
Watcher가 해당 경로의 이벤트를 무시. 브리프 세션 종료 시 등록 해제.

---

## 3. 브리프 템플릿

모든 프로젝트가 거치는 표준 입력 포맷. 메타 에이전트가 Cowork 세션에서 AskUserQuestion으로 항목을 하나씩 질문하여 채운다. 사용자는 브리프 템플릿의 존재를 몰라도 됨 — 대화하면 자연스럽게 채워짐.

### 3.1 템플릿 구조

```markdown
# Project Brief

## 1. Overview
- name: ""                    # 프로젝트 이름 (필수)
- description: ""             # 1~3문장 요약 (필수)
- type: ""                    # web-app | cli | api | library | mobile | other (필수)

## 2. Tech Stack
- language: ""                # Python, TypeScript, Rust, Go 등 (필수)
- framework: ""               # Next.js, FastAPI, Tauri 등 (필수)
- database: ""                # PostgreSQL, SQLite, none 등
- styling: ""                 # Tailwind, CSS Modules, shadcn 등
- package_manager: ""         # npm, pnpm, pip, cargo 등

## 3. Pages / Features
각 항목은 하나의 페이지 또는 독립 기능 단위.

- page: ""
  description: ""
  key_elements: []            # 핵심 UI 요소나 기능 목록

(반복)

## 4. Data Model
주요 엔티티와 관계. 완벽하지 않아도 됨 — 에이전트가 구체화.

- entity: ""
  fields: []
  relations: []

(반복)

## 5. Architecture Decisions
이미 정해진 아키텍처 결정. 없으면 비워도 됨.

- decision: ""
  rationale: ""

(반복)

## 6. Constraints
- auth: ""                    # 인증 방식 (Google OAuth, 패스워드, none 등)
- deployment: ""              # Vercel, Railway, self-hosted, none 등
- performance: ""             # 특별한 성능 요구사항
- accessibility: ""           # WCAG 레벨 등
- other: []                   # 기타 제약

## 7. Non-Goals
이 프로젝트에서 의도적으로 하지 않는 것.

- ""

(반복)

## 8. References
참고할 외부 자료, 디자인 시스템, 경쟁 제품 등.

- ref: ""
  url: ""
  notes: ""

(반복)
```

### 3.2 필수 vs 선택

| 구분 | 항목 | 동작 |
|------|------|------|
| **필수** | name, description, type, language, framework | AI가 반드시 물어보고, 사용자가 답해야 다음으로 넘어감 |
| **선택** | 그 외 전부 | AI가 물어보되, 사용자가 "몰라" 또는 "알아서 해"라고 하면 AI가 설계 단계에서 결정 |

### 3.3 브리프 채우기 흐름

1. 사용자: `cowork-pilot --mode meta "할 일 관리 앱 만들고 싶어"`
2. cowork-pilot이 Cowork 세션을 열고 브리프 채우기 프롬프트 전송
3. Cowork가 AskUserQuestion으로 항목을 순서대로 질문
4. 사용자가 직접 응답 (Phase 1 자동응답 OFF)
5. 필수 항목 다 채워지면 세션 종료
6. 채워진 브리프를 `{project_dir}/docs/project-brief.md`로 저장

### 3.4 브리프 채우기 종료 조건

- 필수 항목 5개 전부 채워짐
- 선택 항목은 사용자가 스킵하거나 답하면 다음으로
- 마지막에 "이대로 진행할까요?" 확인 질문 → 승인 시 종료

---

## 4. 스캐폴딩 (Step 1)

채워진 브리프를 파싱하여 프로젝트 디렉토리와 docs/ 구조를 결정적으로 생성하는 Python 코드. 에이전트 없이 순수 코드로만 동작.

### 4.1 생성되는 구조

```
프로젝트-루트/
  AGENTS.md                          ← 목차 (~100줄), 브리프 기반 초안
  ARCHITECTURE.md                    ← 빈 템플릿 (에이전트가 내용 채움)

  docs/
    project-brief.md                 ← 채워진 브리프 원본 보존
    design-docs/
      index.md                       ← 설계 문서 색인 (빈 템플릿)
      core-beliefs.md                ← 에이전트 운영 원칙 (빈 템플릿)
      data-model.md                  ← 엔티티/관계/스키마 (빈 템플릿)
      {도메인}.md                     ← 브리프 내용에 따라 동적 생성 (auth.md 등)

    product-specs/
      index.md                       ← 제품 스펙 색인 (빈 템플릿)
      {페이지이름}.md                  ← 브리프 Pages/Features에서 1:1 생성

    exec-plans/
      planning/                      ← 대기 중인 구현 계획 (번호순 자동 승격)
      active/                        ← Step 1에서 01-docs-setup.md 자동 생성
      completed/

    references/                      ← 비어있음 (필요 시 추가)

    generated/                       ← 비어있음 (구현 후 자동 추출)

    DESIGN_GUIDE.md                  ← 빈 템플릿 (디자인 시스템/가이드라인/레퍼런스)
    QUALITY_SCORE.md                 ← 빈 템플릿
    SECURITY.md                      ← 빈 템플릿

  src/                               ← 빈 디렉토리 (프레임워크에 따라 초기 구조 가능)
  tests/                             ← 빈 디렉토리
```

### 4.2 동적 생성 규칙

| 브리프 항목 | 생성되는 파일 |
|------------|-------------|
| Pages/Features 각 항목 | `docs/product-specs/{페이지이름}.md` |
| Data Model의 엔티티들 | `docs/design-docs/data-model.md`에 섹션으로 포함 |
| auth 제약이 있으면 | `docs/design-docs/auth.md` 추가 |
| deployment 제약이 있으면 | `docs/design-docs/deployment.md` 추가 |
| References 각 항목 | `docs/references/{이름}-ref.md` 또는 `-llms.txt` |

### 4.3 AGENTS.md 초안 자동 생성

스캐폴딩 코드가 브리프를 기반으로 AGENTS.md 초안을 생성:

```markdown
# {브리프.name}

{브리프.description}

## Directory Map

- `src/` — {브리프.language} + {브리프.framework} 소스 코드
- `docs/design-docs/` — 설계 문서 (index.md에서 색인)
- `docs/product-specs/` — 페이지/기능별 스펙 (index.md에서 색인)
- `docs/exec-plans/active/` — 현재 진행 중인 구현 계획
- `tests/` — 테스트

## When Making Changes

1. AGENTS.md를 읽고 프로젝트 구조를 파악
2. docs/design-docs/를 참고하여 설계 의도 확인
3. 변경 후 테스트 실행
4. 기존 패턴을 따를 것

## Conventions

- {브리프.language}, {브리프.framework}
- {브리프.styling} (해당 시)

## Writing Standards

이 프로젝트의 모든 docs/ 파일은 다음 규칙을 따른다.
(상세 내용은 docs/specs/2026-03-25-docs-content-guide-design.md §3 참조)
```

### 4.4 빈 템플릿 파일의 구조

각 빈 템플릿 파일은 project-conventions.md의 형식을 따르되 내용은 비어있음.
각 섹션에 `<!-- GUIDE: ... -->` HTML 주석으로 내용/형식/분량 가이드를 인라인 포함.
에이전트가 내용을 채운 후 GUIDE 주석을 삭제. (상세: docs/specs/2026-03-25-docs-content-guide-design.md §4 참조)

```markdown
# {제목}

> {1줄 요약}
> 작성일: {오늘 날짜}
> 상태: Draft

---

## 1. 목표
<!-- GUIDE:
- 내용: ...
- 형식: ...
- 분량: ...
-->

## 2. ...
<!-- GUIDE: ... -->
```

### 4.5 "docs 채우기 exec-plan" 자동 생성

스캐폴딩의 마지막 단계로, `docs/exec-plans/active/01-docs-setup.md`를 자동 생성.
이 exec-plan은 Phase 2 하네스가 빈 템플릿 파일들에 내용을 채워넣는 작업을 정의:

```markdown
# docs/ 구조 내용 채우기

## Metadata
- project_dir: {절대 경로}
- spec: docs/project-brief.md
- created: {오늘 날짜}
- status: pending

---

## Chunk 1: 아키텍처 기반 문서

### Completion Criteria
- [ ] ARCHITECTURE.md 파일이 비어있지 않음
- [ ] docs/design-docs/core-beliefs.md 파일이 비어있지 않음
- [ ] docs/design-docs/data-model.md 파일이 비어있지 않음

### Tasks
- Task 1: project-brief.md를 읽고 ARCHITECTURE.md 작성
- Task 2: core-beliefs.md 작성 (에이전트 운영 원칙, 기술 철학)
- Task 3: data-model.md 작성 (엔티티, 관계, 스키마 초안)

### Session Prompt
```
docs/project-brief.md를 읽고, ARCHITECTURE.md와 docs/design-docs/의
core-beliefs.md, data-model.md를 작성해.
AGENTS.md를 참고해서 프로젝트 구조를 파악하고,
docs/project-conventions.md의 형식을 따라 작성해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 2: 도메인별 설계 문서

### Completion Criteria
- [ ] docs/design-docs/ 아래 모든 .md 파일이 비어있지 않음
- [ ] docs/design-docs/index.md에 모든 문서가 색인됨

### Tasks
- Task 1: 브리프의 제약/결정에 따라 도메인별 설계 문서 작성 (auth.md 등)
- Task 2: index.md 업데이트

### Session Prompt
```
docs/exec-plans/active/01-docs-setup.md를 읽고 Chunk 2를 진행해.
docs/project-brief.md와 ARCHITECTURE.md를 참고해서
docs/design-docs/ 아래 빈 파일들에 내용을 채워.
index.md도 업데이트해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 3: 페이지/기능별 스펙

### Completion Criteria
- [ ] docs/product-specs/ 아래 모든 .md 파일이 비어있지 않음
- [ ] docs/product-specs/index.md에 모든 스펙이 색인됨

### Tasks
- Task 1: 각 페이지/기능별 스펙 작성
- Task 2: index.md 업데이트

### Session Prompt
```
docs/exec-plans/active/01-docs-setup.md를 읽고 Chunk 3를 진행해.
docs/project-brief.md, ARCHITECTURE.md, docs/design-docs/를 참고해서
docs/product-specs/ 아래 빈 파일들에 페이지/기능별 스펙을 작성해.
index.md도 업데이트해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 4: 구현 계획 (exec-plan) 생성

### Completion Criteria
- [ ] docs/exec-plans/planning/ 아래에 최소 1개 .md 파일 존재
- [ ] 모든 파일이 plan_parser.py로 파싱 성공 (형식 검증)
- [ ] 파일명이 {NN}-{이름}.md 형식 (예: 02-frontend.md, 03-backend.md)

### Tasks
- Task 1: 설계 문서 + 스펙을 기반으로 구현 exec-plan 작성
- Task 2: 프로젝트 규모에 따라 하나 또는 여러 파일로 분리
- Task 3: project-conventions.md 섹션 4의 형식을 정확히 따름

### Session Prompt
```
docs/exec-plans/active/01-docs-setup.md를 읽고 Chunk 4를 진행해.
ARCHITECTURE.md, docs/design-docs/, docs/product-specs/를 전부 읽고
이 프로젝트의 구현 계획(exec-plan)을 작성해.
docs/project-conventions.md 섹션 4의 형식을 정확히 따라.

파일 위치: docs/exec-plans/planning/
파일명 규칙: {NN}-{이름}.md (02부터 시작. 예: 02-frontend.md, 03-backend.md)
프로젝트 규모에 따라 하나로 합쳐도 되고 여러 파일로 분리해도 된다.
단, 파일명의 번호 순서가 실행 순서가 된다.
Chunk은 2~5개 Task, 2~5개 Completion Criteria로 구성.
완료 조건을 모두 만족시켜.
```

---

## Chunk 5: 크로스 링크 검증

### Completion Criteria
- [ ] AGENTS.md의 Directory Map이 실제 파일 구조와 일치
- [ ] docs/design-docs/index.md의 목록이 실제 파일과 일치
- [ ] docs/product-specs/index.md의 목록이 실제 파일과 일치
- [ ] QUALITY_SCORE.md 초기화됨
- [ ] grep -r "<!-- GUIDE:" docs/ 결과가 0건 (모든 GUIDE 주석 삭제됨)

### Tasks
- Task 1: AGENTS.md 최종 업데이트
- Task 2: index.md 파일들 검증
- Task 3: QUALITY_SCORE.md에 각 도메인 초기 등급 설정

### Session Prompt
```
docs/exec-plans/active/01-docs-setup.md를 읽고 Chunk 5를 진행해.
프로젝트 전체 파일 구조를 확인하고:
1. AGENTS.md의 Directory Map이 실제와 맞는지 검증, 불일치 시 수정
2. design-docs/index.md, product-specs/index.md가 실제 파일과 일치하는지 검증
3. QUALITY_SCORE.md에 각 도메인/레이어 초기 등급 설정
4. grep -r "<!-- GUIDE:" docs/ 실행 → 결과 0건이어야 함. 남아있으면 해당 파일 내용 보완 후 GUIDE 주석 삭제
완료 조건을 모두 만족시켜.
```
```

---

## 5. 워크플로우 상세

### Step 0: 브리프 채우기

| 항목 | 내용 |
|------|------|
| 실행 | `cowork-pilot --mode meta "프로젝트 설명"` |
| 동작 | Cowork 세션 열기 → AskUserQuestion으로 브리프 항목 순서대로 질문 |
| Phase 1 | **OFF** — `ignored_sessions`에 등록 |
| 종료 조건 | 필수 5개 항목 채워짐 + 사용자 승인 |
| 이어서 채우기 | 기존 `project-brief.md`가 있으면: 완성 시 스킵, 미완성 시 기존 내용 포함하여 이어서 진행 |
| 출력 | `{project_dir}/docs/project-brief.md` |

### Step 1: 스캐폴딩

| 항목 | 내용 |
|------|------|
| 실행 | Step 0 완료 직후 자동 |
| 동작 | Python 코드가 브리프 파싱 → 디렉토리 + 빈 템플릿 + docs-setup exec-plan 생성 (섹션 4.5 참조) |
| Phase 1 | 해당 없음 (코드 실행, Cowork 세션 없음) |
| 종료 조건 | 모든 파일 생성 성공 |
| 실패 시 | 생성된 파일/디렉토리 전부 삭제 후 에러 출력. 부분 생성 상태를 남기지 않음 |
| 출력 | 프로젝트 디렉토리 전체 구조 |

### Step 2: 내용 채우기

| 항목 | 내용 |
|------|------|
| 실행 | Step 1 완료 직후 자동 |
| 동작 | Phase 2 하네스가 `docs-setup.md` exec-plan을 Chunk별 실행 |
| Phase 1 | **ON** — Cowork 질문에 자동 응답 |
| 종료 조건 | docs-setup.md의 모든 Chunk 완료 |
| 출력 | 내용이 채워진 docs/ 전체 + implementation.md exec-plan |

### Step 3: 검증 + 승인

| 항목 | 내용 |
|------|------|
| 실행 | Step 2 완료 직후 |
| 동작 | auto 모드: 자동 진행 / manual 모드: macOS 알림 → 사용자 확인 |
| 종료 조건 | 승인 완료 |
| 출력 | 없음 (통과/대기) |

config.toml 설정:
```toml
[meta]
approval_mode = "manual"     # "manual" | "auto"
```

### Step 4: 구현 시작

| 항목 | 내용 |
|------|------|
| 실행 | Step 3 승인 후 자동 |
| 동작 | planning/의 exec-plan들을 번호순으로 active/에 승격하여 Phase 2 하네스로 순차 실행 |
| Phase 1 | **ON** |
| 종료 조건 | planning/과 active/ 모두 비어있음 (모든 plan이 completed/로 이동) |
| 출력 | 완성된 프로젝트 |

---

## 6. 에러 처리

### 6.1 브리프 채우기 실패

| 시나리오 | 대응 |
|---------|------|
| 사용자가 세션 중단 | 부분적으로 채워진 브리프 저장. 재실행 시 기존 내용을 프롬프트에 포함하여 이어서 진행 |
| Cowork 세션 크래시 | ESCALATE — 사람에게 알림 |

### 6.2 스캐폴딩 실패

| 시나리오 | 대응 |
|---------|------|
| 브리프 파싱 에러 | 에러 메시지 출력 + 종료. 브리프 형식 문제 |
| 디렉토리 생성 실패 | 에러 메시지 출력 + 종료. 경로/권한 문제 |

### 6.3 내용 채우기 실패

기존 Phase 2 하네스의 에러 처리를 그대로 사용:
- Chunk 실패 → 재시도 (최대 N회)
- 재시도 초과 → ESCALATE
- exec-plan 형식 오류 → 피드백 전송 후 재시도

### 6.4 구현 exec-plan 형식 오류

Chunk 4에서 planning/에 생성된 exec-plan 파일들을 plan_parser.py로 파싱 검증.
실패 시 피드백 전송 → 재시도 (최대 2회) → ESCALATE.

---

## 7. 구현 범위 및 파일 목록

### 7.1 새로 만드는 파일

| 파일 | 역할 |
|------|------|
| `src/cowork_pilot/brief_parser.py` | 브리프 MD 파싱 → 구조화된 데이터 |
| `src/cowork_pilot/scaffolder.py` | 브리프 데이터 → 디렉토리 + 빈 템플릿 + exec-plan 생성 |
| `src/cowork_pilot/meta_runner.py` | Step 0~4 워크플로우 오케스트레이션 |
| `src/cowork_pilot/brief_templates/` | 빈 템플릿 파일들 디렉토리 (아래 상세) |
| `src/cowork_pilot/brief_templates/AGENTS.md.j2` | AGENTS.md Jinja2 템플릿 |
| `src/cowork_pilot/brief_templates/ARCHITECTURE.md.j2` | ARCHITECTURE.md 빈 템플릿 |
| `src/cowork_pilot/brief_templates/design-doc.md.j2` | design-docs/ 하위 파일 범용 템플릿 |
| `src/cowork_pilot/brief_templates/product-spec.md.j2` | product-specs/ 하위 파일 범용 템플릿 |
| `src/cowork_pilot/brief_templates/index.md.j2` | index.md 범용 템플릿 |
| `src/cowork_pilot/brief_templates/docs-setup-plan.md.j2` | "docs 채우기 exec-plan" 템플릿 |
| `src/cowork_pilot/brief_templates/QUALITY_SCORE.md.j2` | QUALITY_SCORE.md 템플릿 (등급 기준 GUIDE 포함) |
| `src/cowork_pilot/brief_templates/SECURITY.md.j2` | SECURITY.md 템플릿 (인증/데이터보호/위험 GUIDE 포함) |
| `src/cowork_pilot/brief_templates/DESIGN_GUIDE.md.j2` | DESIGN_GUIDE.md 템플릿 (디자인 시스템/레퍼런스 GUIDE 포함) |
| `tests/test_brief_parser.py` | 브리프 파싱 테스트 |
| `tests/test_scaffolder.py` | 스캐폴딩 테스트 |
| `tests/test_meta_runner.py` | 메타 러너 테스트 |
| `docs/brief-template.md` | 표준 브리프 템플릿 (섹션 3.1) |

### 7.2 기존 파일 (수정 없이 재사용)

| 파일 | 역할 |
|------|------|
| `src/cowork_pilot/plan_parser.py` | exec-plan 파싱 — 이미 존재. implementation.md 형식 검증에 사용 |
| `src/cowork_pilot/session_manager.py` | Chunk 실행 관리 — Phase 2에서 그대로 재사용 |
| `src/cowork_pilot/session_opener.py` | Cowork 세션 열기 — Step 0 브리프 세션 + Step 2 내용 채우기에서 재사용 |

### 7.3 수정하는 파일

| 파일 | 변경 |
|------|------|
| `src/cowork_pilot/main.py` | `--mode meta` 추가. `cli()`에서 meta 모드일 때 `meta_runner.run_meta(config, meta_config)` 호출 |
| `src/cowork_pilot/config.py` | `MetaConfig` 데이터클래스 추가 (approval_mode 등). `load_meta_config()` 함수 추가 |
| `src/cowork_pilot/watcher.py` | `ignored_sessions: set[Path]` 파라미터 추가. `WatcherStateMachine`이 해당 경로 이벤트 무시 |
| `docs/project-conventions.md` | 섹션 7 업데이트 — docs/ 구조 표준을 이 스펙의 섹션 4.1로 교체. **이 업데이트는 구현 Chunk 1에서 가장 먼저 수행** |
| `AGENTS.md` | Phase 3 관련 디렉토리/파일 추가 |

### 7.4 meta_runner.py 진입점 상세

`meta_runner.run_meta(config, meta_config)` 함수가 전체 워크플로우를 오케스트레이션:

```python
def run_meta(config: Config, meta_config: MetaConfig) -> None:
    # Step 0: 브리프 채우기 (이어서 채우기 지원)
    # 기존 project-brief.md가 완전하면 스킵
    # 불완전하면 기존 내용을 프롬프트에 포함하여 이어서 진행
    if not brief_already_complete():
        brief_jsonl = open_brief_session(config, meta_config, existing_brief)
        ignored_sessions.add(brief_jsonl)  # Phase 1 자동응답 OFF
        wait_for_brief_completion(brief_jsonl, meta_config)
    brief = parse_brief(meta_config.project_dir / "docs" / "project-brief.md")

    # Step 1: 스캐폴딩 (멱등 — 이미 있으면 덮어쓰지 않음)
    scaffold_project(brief, meta_config)

    # Step 2: 내용 채우기 (Phase 2 하네스 재사용)
    ignored_sessions.clear()  # Phase 1 자동응답 ON
    run_harness(config, harness_config_from(meta_config))

    # Step 3: 검증 + 승인
    if meta_config.approval_mode == "manual":
        notify_and_wait_approval(meta_config)

    # Step 4: 구현 시작 — planning/의 모든 plan을 순차 실행
    while has_plans_in_planning_or_active():
        promote_next_plan()  # planning/ → active/
        run_harness(config, harness_config_from(meta_config))
        # plan 완료 → completed/로 이동 → 다음 반복
```

---

## 8. 결정 사항

| 항목 | 결정 |
|------|------|
| 브리프 입력 방식 | 구조화된 템플릿, AI가 대화로 채움 |
| docs/ 구조 모델 | OpenAI 스타일 전면 채택 |
| Phase 1 자동응답 제어 | `ignored_sessions` 방식 |

## 9. 미결정 사항

- [x] 브리프 이어서 채우기 — 기존 project-brief.md 감지 → 완전하면 스킵, 불완전하면 프롬프트에 포함하여 이어서 진행
- [ ] exec-plan Chunk 수가 많아질 때 분할 기준 — 프로젝트 규모에 따른 적응적 분할
- [ ] generated/ 폴더의 자동 추출 메커니즘 — 별도 Phase에서 구현할지, 가비지 컬렉션과 함께 할지

---

> 이 문서는 하네스 엔지니어링 방식에 따라 작성됨.
> Phase 3은 Phase 2 하네스의 입력을 자동 생성하는 확장 레이어다.
> 기존 인프라(Phase 1 자동응답 + Phase 2 하네스)를 최대한 재사용한다.
