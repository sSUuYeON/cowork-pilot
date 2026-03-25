# Cowork Pilot — 프로젝트 컨벤션

> cowork-pilot이 자동 실행하는 모든 프로젝트가 따라야 할 표준 구조와 형식.
> 하네스 오케스트레이터는 이 컨벤션에 맞춰 문서를 파싱하고, Cowork 세션은 이 컨벤션에 맞춰 문서를 참조한다.
> 작성일: 2026-03-24

---

## 1. 프로젝트 폴더 구조

모든 대상 프로젝트는 다음 구조를 따른다:

```
프로젝트-루트/
  AGENTS.md                     ← Cowork 세션의 진입점 (필수)
  docs/
    specs/                      ← 개발 기획서 (설계 문서)
      {날짜}-{이름}.md           ← 예: 2026-03-24-auth-system-design.md
    exec-plans/
      planning/                 ← 대기 중인 구현 계획 (번호순 실행)
        {NN}-{이름}.md           ← 예: 02-frontend.md, 03-backend.md
      active/                   ← 현재 진행 중인 구현 계획 (최대 1개)
        {NN}-{이름}.md           ← 예: 01-docs-setup.md
      completed/                ← 완료된 구현 계획 (하네스가 자동 이동)
    golden-rules.md             ← (선택) 프로젝트별 절대 규칙
    decision-criteria.md        ← (선택) 프로젝트별 판단 기준
  src/                          ← 소스 코드 (언어/프레임워크에 따라 다름)
  tests/                        ← 테스트 코드
  config.toml                   ← (선택) cowork-pilot 설정 오버라이드
```

### 1.1 필수 vs 선택

| 항목 | 필수 여부 | 설명 |
|------|-----------|------|
| `AGENTS.md` | **필수** | 없으면 Cowork 세션이 맥락을 잡을 수 없음 |
| `docs/specs/` | **필수** | 최소 1개의 설계 문서가 있어야 함 |
| `docs/exec-plans/planning/` | 선택 | 대기 중인 구현 계획 (번호순 자동 승격) |
| `docs/exec-plans/active/` | **필수** | 하네스가 읽는 실행 계획 위치 (최대 1개) |
| `docs/exec-plans/completed/` | 자동 생성 | 하네스가 완료 시 자동 이동 |
| `docs/golden-rules.md` | 선택 | Phase 1 자동응답에서 참조 |
| `docs/decision-criteria.md` | 선택 | Phase 1 자동응답에서 참조 |
| `config.toml` | 선택 | 없으면 cowork-pilot 기본값 사용 |


## 2. AGENTS.md 형식

AGENTS.md는 Cowork 세션이 프로젝트에 진입할 때 가장 먼저 읽는 파일이다. 프로젝트의 맥락, 구조, 규칙을 간결하게 전달한다.

### 2.1 필수 섹션

```markdown
# {프로젝트 이름}

{1~2문장 프로젝트 요약}

## Directory Map

- `src/` — {소스 코드 설명}
- `docs/specs/` — 설계 문서
- `docs/exec-plans/active/` — 현재 진행 중인 실행 계획
- `tests/` — 테스트
- {기타 주요 경로}

## When Making Changes

1. {프로젝트별 변경 규칙}
2. 변경 후 반드시 `{테스트 명령}` 실행
3. 기존 패턴을 따를 것

## Conventions

- {언어/프레임워크 컨벤션}
- {코딩 스타일 규칙}
```

### 2.2 선택 섹션

```markdown
## Key Design Decisions

{아키텍처적으로 중요한 결정 사항. 새로운 세션이 맥락 없이 잘못된 방향으로 가는 걸 방지}

## Project Conventions

`docs/project-conventions.md` 참조 — 폴더 구조, 문서 형식 표준 정의.

## Exec-Plan Execution Notes

{하네스가 이 프로젝트를 실행할 때 알아야 할 특이사항}
- 예: "프론트엔드 빌드 전에 반드시 `npm install` 필요"
- 예: "DB 마이그레이션은 수동으로만 실행할 것"
```

### 2.3 작성 규칙

- **간결하게**: 200줄 이하 권장. Cowork 세션의 컨텍스트를 아낀다
- **경로는 프로젝트 루트 기준 상대 경로**: `src/models.py`, `docs/specs/design.md` (절대 경로 사용 금지 — exec-plan의 `project_dir`만 절대 경로)
- **핵심만**: Cowork가 "이 프로젝트에서 뭘 어떻게 해야 하는지" 파악할 수 있으면 됨
- **한글/영어 혼용 가능**: 프로젝트 언어에 맞춤
- **최소 유효 파일**: `# {이름}`, `## Directory Map`, `## When Making Changes` 3개 섹션만 있어도 유효


## 3. 개발 기획서 (Spec) 형식

기획서는 `docs/specs/` 아래에 위치하며, 프로젝트의 설계 의도를 기술한다.

### 3.1 파일명 규칙

```
{YYYY-MM-DD}-{이름}.md
```

예시: `2026-03-24-auth-system-design.md`, `2026-03-25-payment-integration.md`

### 3.2 필수 섹션

```markdown
# {기능/시스템 이름} — 설계 문서

> {1줄 요약}
> 작성일: {YYYY-MM-DD}
> 상태: Draft | Review | Approved | Implemented

---

## 1. 목표

{이 기능/시스템이 왜 필요한지, 무엇을 달성하려는지}

## 2. 아키텍처

{시스템 구조, 컴포넌트 관계, 데이터 흐름}
{다이어그램 권장 (ASCII art 또는 Mermaid)}

## 3. 기술적 세부사항

{구현에 필요한 구체적 내용: API 설계, 데이터 모델, 알고리즘 등}

## 4. 에러 처리

{예상 실패 시나리오와 대응}

## 5. 미결정 사항

- [ ] {아직 결정되지 않은 것들}
```

### 3.3 선택 섹션

필요에 따라 추가:

- **기술 스택**: 사용할 언어, 프레임워크, 라이브러리
- **제약 조건**: 성능 요구사항, 호환성, 보안
- **마이그레이션 계획**: 기존 시스템에서의 전환 전략
- **외부 의존성**: API, 서드파티 서비스

### 3.4 작성 규칙

- **구현 가능한 수준의 구체성**: "잘 만들자"가 아니라 "이 함수가 이 인터페이스를 가진다"
- **상태 필드 관리**: Draft → Review → Approved → Implemented (하네스가 참조)
- **미결정 사항은 체크박스로**: 구현 전에 해결해야 할 것들을 명시


## 4. 구현 계획 (exec-plan) 형식

exec-plan은 `docs/exec-plans/active/` 아래에 위치하며, 하네스 오케스트레이터가 직접 파싱하여 자동 실행한다. **형식이 정확해야 한다.**

### 4.1 파일명 규칙

```
{이름}.md
```

예시: `auth-system.md`, `phase-2-implementation.md`

### 4.2 전체 구조

```markdown
# {구현 계획 제목}

## Metadata
- project_dir: {프로젝트 루트 절대 경로}
- spec: {참조하는 설계 문서 상대 경로}
- created: {YYYY-MM-DD}
- status: pending | in_progress | completed

---

## Chunk 1: {Chunk 이름}

### Completion Criteria
- [ ] {기계적으로 검증 가능한 완료 조건 1}
- [ ] {기계적으로 검증 가능한 완료 조건 2}

### Tasks
- Task 1: {태스크 이름}
- Task 2: {태스크 이름}

### Session Prompt
```
{Cowork 세션에 보내는 실제 프롬프트 텍스트}
```

---

## Chunk 2: {Chunk 이름}
{같은 구조 반복}
```

### 4.3 Metadata 필드

| 필드 | 필수 | 설명 |
|------|------|------|
| `project_dir` | **필수** | 프로젝트 루트 **절대 경로**. CLI 검증 시 이 경로에서 명령 실행. 문서 전체에서 유일하게 절대 경로를 사용하는 필드 |
| `spec` | 선택 | 참조하는 설계 문서 **상대 경로** (프로젝트 루트 기준). 예: `docs/specs/2026-03-24-design.md` |
| `created` | 선택 | 생성 날짜 (YYYY-MM-DD) |
| `status` | **필수** | `pending` → `in_progress` → `completed` (하네스가 자동 업데이트) |

### 4.4 Chunk 규칙

**구조 (파서가 의존하는 정확한 형식):**
- `## Chunk N: {이름}` 헤더로 시작 (N은 1부터 순차, 콜론 필수, `## Chunk 1: Foundation` 형태)
- 정규식: `^## Chunk (\d+): (.+)$`
- 반드시 `### Completion Criteria`, `### Tasks`, `### Session Prompt` 3개의 하위 섹션 포함
- 하위 섹션은 **이 순서대로** 나타나야 함 (파서가 순서에 의존)
- 추가 하위 섹션(`### Notes` 등)은 `### Session Prompt` 뒤에 넣을 수 있으나 파서는 무시
- Chunk 사이는 `---` 구분선으로 분리

**Completion Criteria 작성 규칙:**
- 반드시 `- [ ]` 체크박스 형식 (정규식: `^- \[([ x])\] (.+)$`)
- 앞에 공백 들여쓰기 없음 (줄 시작이 `- [`)
- `* [ ]`, `+ [ ]` 등 다른 리스트 마커는 파서가 인식하지 않음
- **기계적으로 검증 가능한 조건만** 허용:
  - `pytest tests/test_X.py 통과` (exit code 0)
  - `src/X.py 파일 존재` (파일 시스템 확인)
  - `localhost:3000 응답 status 200` (curl 확인)
  - `npm run build 성공` (exit code 0)
  - `git diff --name-only에 X.py 포함` (변경 파일 확인)
- **금지**: 주관적 판단이 필요한 조건
  - ~~"코드가 깔끔한지 확인"~~
  - ~~"UI가 보기 좋은지 확인"~~
  - ~~"성능이 충분한지 확인"~~ (구체적 수치가 있으면 OK: "응답 시간 < 200ms")

**Tasks:**
- Chunk 안에서 수행할 작업 목록 (순서대로)
- 하네스가 직접 파싱하지는 않음 — Cowork 세션이 Session Prompt를 통해 참조
- 사람이 진행 상황을 파악하기 위한 용도

**Session Prompt:**
- Cowork 세션에 보내는 실제 텍스트
- 코드 블록(``` 으로 감싸기) 안에 작성 권장
- 여러 코드 블록이 있으면 **첫 번째만** 사용됨
- 코드 블록이 없으면 `### Session Prompt` 아래 텍스트를 다음 `---` 또는 `##` 까지 수집
- 추출 결과가 빈 문자열이면 **파싱 에러** → 하네스가 ESCALATE (사람에게 알림)

**Chunk 완료 판정:**
- 모든 Completion Criteria가 `[x]`이면 해당 Chunk의 status = `completed`
- 하나라도 `[ ]`이면 status = `pending` 또는 `in_progress`
- 하네스는 1개의 Chunk에 대해 1개의 Cowork 세션을 연다 (세션당 Chunk 1:1)

### 4.5 Session Prompt 작성 가이드

좋은 Session Prompt는 Cowork 세션이 **AGENTS.md + exec-plan + 프로젝트 폴더**만으로 작업할 수 있게 해야 한다.

**첫 번째 Chunk:**
```
docs/exec-plans/active/{파일명}을 읽고 Chunk 1을 진행해.
AGENTS.md와 docs/specs/{스펙파일}을 참고해서 Task 1~N을 순서대로 구현해.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

**이후 Chunk (범용):**
```
docs/exec-plans/active/{파일명}을 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, 다음 Chunk를 시작해.
완료 조건을 모두 만족시켜.
```

**Session Prompt에 포함하면 좋은 것:**
- exec-plan 파일 경로 (Cowork가 바로 찾을 수 있게)
- 참조할 문서 경로 (AGENTS.md, spec 등)
- 완료 조건을 만족시키라는 지시

**Session Prompt에 넣으면 안 되는 것:**
- 코드 자체를 프롬프트에 포함 (길어지면 컨텍스트 낭비)
- 이미 exec-plan에 있는 정보를 중복 기술


## 5. Chunk 크기 가이드라인

Chunk은 "하나의 Cowork 세션이 처리할 수 있는 작업 묶음" 단위다.

### 5.1 권장 크기

| 기준 | 값 |
|------|-----|
| Task 개수 | 2~5개 |
| 예상 소요 시간 | 10~30분 |
| 파일 변경 수 | 3~10개 |
| Completion Criteria | 2~5개 |

### 5.2 Chunk이 너무 크면

- Cowork 세션이 컨텍스트 한도에 도달할 수 있음
- 작업 중간에 멈추면 재시작이 어려움
- Completion Criteria가 많아져 검증이 복잡해짐

→ **분할**: 논리적 단위로 나누되, 각 Chunk이 독립적으로 검증 가능하게

### 5.3 Chunk이 너무 작으면

- 세션 열기/닫기 오버헤드가 큼 (세션당 최소 3초 + 프롬프트 입력)
- 맥락 전환 비용 (새 세션은 프로젝트를 처음부터 파악해야 함)

→ **합치기**: 밀접하게 관련된 Task는 한 Chunk으로


## 6. 문서 간 참조 관계

```
AGENTS.md
  ├── 참조 → docs/specs/*.md (설계 문서)
  ├── 참조 → docs/exec-plans/active/*.md (실행 계획)
  └── 참조 → docs/golden-rules.md, decision-criteria.md

docs/specs/{설계문서}.md
  └── 독립적 (다른 문서에 의존하지 않음)

docs/exec-plans/active/{실행계획}.md
  ├── Metadata.spec → docs/specs/{설계문서}.md
  ├── Metadata.project_dir → 프로젝트 루트 절대 경로
  └── Session Prompt → AGENTS.md, exec-plan 자체를 참조하라고 지시
```

### 6.1 하네스 오케스트레이터가 읽는 파일

1. `docs/exec-plans/active/*.md` — 파싱하여 Chunk 추출
2. `config.toml` — 타이밍, 재시도 설정

### 6.2 Cowork 세션이 읽는 파일

1. `AGENTS.md` — 프로젝트 맥락 (Cowork가 자동으로 읽음)
2. exec-plan — Session Prompt에서 지시한 파일
3. 설계 문서 — Session Prompt에서 지시한 파일
4. 소스 코드/테스트 — 작업에 필요한 파일들


## 7. Phase 3: 메타 에이전트 docs/ 구조 표준

Phase 3 메타 에이전트는 "프로젝트 브리프"를 기반으로 docs/ 구조를 자동 생성하고, Phase 2 하네스로 내용 채우기 + 구현까지 자동 실행한다.

### 7.1 전체 흐름

```
입력: 프로젝트 설명 (사용자가 제공)
  ↓
[Step 0] 브리프 채우기 (Cowork 세션, 사용자 직접 응답, Phase 1 OFF)
  → AskUserQuestion으로 항목별 질문
  → 완료: docs/project-brief.md 생성
  ↓
[Step 1] 스캐폴딩 (Python 코드, 결정적, 에이전트 없음)
  → 브리프 파싱 → 디렉토리 + 빈 템플릿 + exec-plan 자동 생성
  ↓
[Step 2] 내용 채우기 (Phase 2 하네스, Phase 1 ON)
  → docs-setup.md exec-plan 실행
  → 빈 템플릿의 GUIDE 주석을 따라 내용 채움
  ↓
[Step 3] 검증 + 승인
  → auto 모드: 즉시 진행
  → manual 모드: macOS 알림 → 사용자 확인
  ↓
[Step 4] 구현 시작 (Phase 2 하네스, Phase 1 ON)
  → planning/에서 다음 exec-plan을 active/로 승격 후 실행
  → 여러 exec-plan을 번호순으로 자동 실행
```

### 7.2 생성되는 docs/ 구조

스캐폴더가 브리프를 기반으로 결정적으로 생성하는 구조:

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
      planning/                      ← Step 2 Chunk 4에서 구현 계획 자동 생성
      active/                        ← Step 1에서 01-docs-setup.md 자동 생성
      completed/

    references/                      ← 비어있음 (필요 시 추가)
    generated/                       ← 비어있음 (구현 후 자동 추출)

    DESIGN_GUIDE.md                  ← 빈 템플릿 (디자인 시스템/가이드라인)
    QUALITY_SCORE.md                 ← 빈 템플릿 (도메인별 품질 등급)
    SECURITY.md                      ← 빈 템플릿 (보안 설계)

  src/                               ← 빈 디렉토리
  tests/                             ← 빈 디렉토리
  config.toml                        ← cowork-pilot 설정
```

### 7.3 동적 생성 규칙

| 브리프 항목 | 생성되는 파일 |
|------------|-------------|
| Pages/Features 각 항목 | `docs/product-specs/{페이지이름}.md` |
| Data Model의 엔티티들 | `docs/design-docs/data-model.md`에 섹션으로 포함 |
| auth 제약이 있으면 | `docs/design-docs/auth.md` 추가 |
| deployment 제약이 있으면 | `docs/design-docs/deployment.md` 추가 |

### 7.4 빈 템플릿과 GUIDE 주석

각 빈 템플릿 파일은 섹션 헤더와 `<!-- GUIDE: ... -->` HTML 주석을 포함. 에이전트가 내용을 채운 후 반드시 GUIDE 주석을 삭제한다. 검증 시 `grep -r "<!-- GUIDE:" docs/` 결과가 0건이어야 완료.

GUIDE 주석 형식:
```markdown
## 1. 섹션 제목
<!-- GUIDE:
- 내용: 이 섹션에서 다뤄야 할 내용
- 형식: 산문/리스트/테이블/다이어그램 중 권장 형식
- 분량: 최소~최대 줄 수
- 참조: 참고할 다른 문서
-->
```

### 7.5 승인 모드

`config.toml`에서 설정:

```toml
[meta]
approval_mode = "manual"    # "manual" | "auto"
```

| 모드 | 동작 |
|------|------|
| `manual` (기본) | Step 3에서 macOS 알림 → 사용자가 확인 후 `docs/.meta-approved` 파일 생성 → 하네스 진행 |
| `auto` | Step 3 즉시 통과 → Step 4 자동 시작 |

### 7.6 Phase 1 자동응답 제어

`--mode meta`로 실행 시:
- Step 0 (브리프 채우기): Phase 1 자동응답 **OFF** — 사용자 의도를 담아야 하므로
- Step 2~4 (내용 채우기 + 구현): Phase 1 자동응답 **ON** — 에이전트가 자동 진행

구현 방식: 메타 에이전트가 브리프 세션의 JSONL 경로를 `ignored_sessions: set[Path]`에 등록. Watcher가 해당 경로의 이벤트를 무시.

---

> 이 문서는 cowork-pilot이 실행하는 모든 프로젝트의 표준을 정의한다.
> 하네스 오케스트레이터는 이 문서의 형식에 의존하여 파싱/실행하므로, 형식 변경 시 파서도 함께 업데이트해야 한다.
