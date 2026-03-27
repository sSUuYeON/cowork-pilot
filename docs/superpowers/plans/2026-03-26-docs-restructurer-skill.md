# docs-restructurer 스킬 구현 계획

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cowork 대화 결과물을 project-conventions.md 규격의 docs/ 구조로 자동 변환하는 Cowork 스킬을 생성한다.

**Architecture:** SKILL.md 하나 + references/ 디렉토리(3개 참조 파일)로 구성. SKILL.md는 5-Phase 워크플로를 정의하고, 상세 체크리스트/출력 포맷/품질 기준은 references/에 분리하여 500줄 제한을 준수한다. 스킬은 Cowork 세션에서 실행되며, 각 Phase 결과를 파일로 저장해 맥락을 보존한다.

**Tech Stack:** Markdown (SKILL.md + references), YAML frontmatter

**Spec:** `docs/specs/2026-03-26-docs-restructurer-skill-design.md`

---

## File Structure

```
skills/docs-restructurer/
├── SKILL.md                          ← 메인 스킬 파일 (~400줄)
│   ├── YAML frontmatter              ← name, description
│   ├── Overview                      ← 스킬 목적, 사용 시점
│   ├── Prerequisites                 ← 입력 요구사항
│   ├── Phase 1~5 워크플로            ← 단계별 지시 (핵심)
│   ├── Context Preservation          ← 맥락 보존 전략
│   └── Error Handling                ← 에러 시 행동
└── references/
    ├── checklists.md                 ← Phase 2 갭 분석 체크리스트 + 점수 체계
    ├── output-formats.md             ← Phase 3 문서별 출력 구조 (product-spec, AGENTS.md 등)
    └── quality-criteria.md           ← Phase 4 품질 검토 기준 + 점수 산출
```

**각 파일의 책임:**

| 파일 | 역할 | 읽는 시점 |
|------|------|-----------|
| `SKILL.md` | 전체 워크플로 오케스트레이션, Phase별 지시 | 스킬 트리거 시 자동 |
| `references/checklists.md` | product-spec 체크리스트(8항목), web-app 추가(3항목), 아키텍처(4항목), 점수 체계 | Phase 2 시작 시 |
| `references/output-formats.md` | product-spec 섹션 구조(공통 8 + web-app 3 + api 2), AGENTS.md 형식, ARCHITECTURE.md 형식, 기타 docs/ 파일 구조 | Phase 3 시작 시 |
| `references/quality-criteria.md` | 문서 간 정합성, 표현 품질, 구조 완전성 기준, QUALITY_SCORE.md 템플릿 | Phase 4 시작 시 |

---

## Chunk 1: SKILL.md 프론트매터 + 개요 + Phase 1

### Task 1: Create directory structure and SKILL.md frontmatter + overview

**Files:**
- Create: `skills/docs-restructurer/SKILL.md`
- Create: `skills/docs-restructurer/references/` (directory)

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p skills/docs-restructurer/references
```

- [ ] **Step 2: Write SKILL.md frontmatter + Overview + Prerequisites**

YAML frontmatter:
```yaml
---
name: docs-restructurer
description: "Cowork 대화에서 나온 자유 형식 문서들을 project-conventions.md 규격의 docs/ 구조로 자동 변환하는 스킬. 사용자가 Cowork에서 충분히 상의한 후 나온 결과물(설계 문서, 기능 명세, 데이터 모델 등)을 입력으로 받아 AGENTS.md, ARCHITECTURE.md, design-docs/, product-specs/, exec-plans를 자동 생성한다. 트리거: 'docs 재구성', 'docs/ 구조 만들어', '문서 포맷팅', '프로젝트 문서 변환', '설계 문서 정리', 'exec-plan 생성', 또는 자유 형식 문서를 project-conventions.md 형식으로 변환하려는 모든 요청."
---
```

Overview section — 스킬이 하는 일:
- Cowork 대화 결과물(자유 형식) → docs/ 규격 변환
- 5-Phase 파이프라인: 입력 분석 → 갭 분석 → 문서 생성 → 품질 검토 → exec-plan 생성
- 각 Phase 결과를 파일로 저장하여 맥락 보존
- 부족한 정보는 사용자에게 AskUserQuestion

Prerequisites section:
- 프로젝트 폴더가 마운트되어 있어야 함 (없으면 request_cowork_directory)
- 자유 형식 문서가 1개 이상 존재해야 함
- project-conventions.md가 프로젝트에 없으면 스킬이 자체 규격 사용

- [ ] **Step 3: Write Phase 1 instructions**

Phase 1: 입력 읽기 & 구조 분석
- 마운트된 폴더 탐색 → 마크다운 파일 수집
- 각 파일에서 추출 가능한 정보 카테고리 분류 (입력 매핑 테이블 참조)
- 입력 매핑 테이블 (spec 3.1의 테이블을 SKILL.md에 인라인):

| 정보 | 매핑되는 docs/ 파일 |
|------|-------------------|
| 프로젝트 개요, 기술 스택, 설계 철학 | AGENTS.md, ARCHITECTURE.md |
| 데이터 모델 | docs/design-docs/data-model.md |
| 운영 원칙, 기술 철학 | docs/design-docs/core-beliefs.md |
| 인증/보안 설계 | docs/design-docs/auth.md, docs/SECURITY.md |
| 배포 전략 | docs/design-docs/deployment.md |
| 페이지/기능별 상세 스펙 | docs/product-specs/{페이지}.md |
| 디자인 가이드 | docs/DESIGN_GUIDE.md |

- 프로젝트 타입 추론 (web-app / api / cli / library / mobile)
- 결과를 `docs/generated/analysis-report.md`에 저장
- analysis-report.md 구조:
  ```markdown
  # 입력 분석 보고서
  ## 프로젝트 타입: {추론된 타입}
  ## 발견된 정보
  | 카테고리 | 출처 파일 | 요약 |
  ## 매핑 계획
  | 입력 정보 | 대상 docs/ 파일 | 상태 |
  ## 누락 항목
  - {발견되지 않은 정보 목록}
  ```
- 사용자에게 분석 결과 요약 보고

- [ ] **Step 4: Verify SKILL.md has valid YAML frontmatter**

```bash
head -10 skills/docs-restructurer/SKILL.md
```

Expected: `---` 으로 시작하는 유효한 YAML frontmatter

- [ ] **Step 5: Commit**

```bash
git add skills/docs-restructurer/SKILL.md
git commit -m "feat(skill): add docs-restructurer SKILL.md with frontmatter + Phase 1"
```

---

## Chunk 2: Phase 2 (갭 분석) + references/checklists.md

### Task 1: Write Phase 2 instructions in SKILL.md
### Task 2: Create references/checklists.md

**Files:**
- Modify: `skills/docs-restructurer/SKILL.md`
- Create: `skills/docs-restructurer/references/checklists.md`

- [ ] **Step 1: Write references/checklists.md**

파일 구조:
```markdown
# 갭 분석 체크리스트

## 점수 체계
- 충족 (3점): 구체적이고 측정 가능하게 정의됨
- 부분 충족 (2점): 정보는 있으나 모호하거나 불완전
- 미충족 (1점): 해당 정보 없음
- 해당 없음 (N/A): 프로젝트 특성상 불필요

## product-spec 체크리스트 (모든 타입)
| # | 항목 | 기준 | 충족 예시 | 미충족 예시 |
{spec 3.3의 8개 항목 + 구체적 예시 추가}

## web-app 추가 체크리스트
| # | 항목 | 기준 | 충족 예시 | 미충족 예시 |
{spec 3.3의 3개 항목}

## api/library 추가 체크리스트
{엔드포인트 상세, SDK 인터페이스}

## 아키텍처 체크리스트
| # | 항목 | 기준 | 충족 예시 | 미충족 예시 |
{spec 3.3의 4개 항목}

## 미충족/부분 충족 시 행동
- 미충족 (1점): AskUserQuestion으로 질문 (선택지 제시)
- 부분 충족 (2점): 구체화 방향 제안 후 사용자 확인
- 모든 항목 충족/N/A: 다음 Phase 자동 진행

## 중단 기준
- 미충족 항목이 전체의 50% 이상: 경고 메시지 표시 후 사용자에게 선택지 제공
```

- [ ] **Step 2: Write Phase 2 instructions in SKILL.md**

Phase 2: 갭 분석 + 점수 평가
- `references/checklists.md` 읽기 지시
- `docs/generated/analysis-report.md` 다시 읽기 (맥락 복원)
- 각 페이지/기능별로 product-spec 체크리스트 적용
- 아키텍처 체크리스트 적용
- 프로젝트 타입별 추가 체크리스트 적용
- 미충족/부분 충족 항목에 대해 AskUserQuestion 호출
  - 미충족: 선택지 + "어떻게 할까?" 형태
  - 부분 충족: "이렇게 구체화하면 될까?" 형태
- gap-report.md 구조:
  ```markdown
  # 갭 분석 보고서
  ## 종합 점수: {평균 점수} / 3.0
  ## 페이지별 점수
  | 페이지 | 평균 점수 | 미충족 항목 |
  ## 아키텍처 점수
  | 항목 | 점수 | 비고 |
  ## 보강된 내용 (사용자 응답)
  {AskUserQuestion으로 받은 정보}
  ```
- 결과를 `docs/generated/gap-report.md`에 저장
- 사용자에게 점수 요약 보고

- [ ] **Step 3: Verify checklists.md is complete**

```bash
grep -c "^|" skills/docs-restructurer/references/checklists.md
```

Expected: 최소 15줄 이상의 테이블 행 (체크리스트 항목들)

- [ ] **Step 4: Commit**

```bash
git add skills/docs-restructurer/SKILL.md skills/docs-restructurer/references/checklists.md
git commit -m "feat(skill): add Phase 2 gap analysis + checklists reference"
```

---

## Chunk 3: Phase 3 (docs/ 구조 생성) + references/output-formats.md

### Task 1: Write references/output-formats.md
### Task 2: Write Phase 3 instructions in SKILL.md

**Files:**
- Modify: `skills/docs-restructurer/SKILL.md`
- Create: `skills/docs-restructurer/references/output-formats.md`

- [ ] **Step 1: Write references/output-formats.md**

파일 구조:
```markdown
# 문서 출력 포맷

## 1. AGENTS.md 형식
{project-conventions.md 2절의 필수/선택 섹션 형식}
- Directory Map, When Making Changes, Conventions 필수
- Key Design Decisions, Exec-Plan Execution Notes 선택

## 2. ARCHITECTURE.md 형식
- 5-section 구조: 개요, 기술 스택, 디렉토리 구조, 핵심 시나리오 데이터 흐름, 설계 원칙

## 3. product-spec 형식

### 공통 섹션 (모든 타입)
1. Problem & Appetite
2. 유저 플로우 (step-by-step 형식 예시 포함)
3. 핵심 요소 (동작/상태/예외/데이터 의존성)
4. 데이터 & API (TypeScript 인터페이스 예시)
5. 에러 처리 (테이블: 에러 조건 | 사용자 메시지 | 복구 동작)
6. 성능 요구사항 (측정 가능한 수치)
7. 의존성 (의존하는 것 / 의존되는 것)
8. Rabbit Holes & Non-Goals

### web-app / mobile 추가
9. UI 구성 (ASCII 와이어프레임 + 컴포넌트 트리 + 상태별 화면)
10. 상태 관리 (state shape, hooks, local vs server)
11. 접근성 (키보드, ARIA, 포커스)

### api / library 추가
9. 엔드포인트 상세
10. SDK / 공개 인터페이스

## 4. design-docs/ 형식
### core-beliefs.md — DO/DON'T 패턴
### data-model.md — 엔티티 테이블 + Mermaid ERD
### auth.md — Mermaid 인증 흐름 + 컴포넌트 구조
### deployment.md — 환경 구성 + CI/CD 파이프라인

## 5. 기타 파일
### DESIGN_GUIDE.md — 디자인 시스템/가이드라인
### SECURITY.md — 보안 설계
### QUALITY_SCORE.md — 품질 점수 (Phase 4에서 채움)

## 6. exec-plan 형식
{project-conventions.md 4절의 정확한 형식}
- Metadata 필수 필드: project_dir, status
- Chunk 헤더: ## Chunk N: {이름}
- 하위 섹션 순서: Completion Criteria → Tasks → Session Prompt
- Completion Criteria: - [ ] 형식, 기계적 검증 가능
```

- [ ] **Step 2: Write Phase 3 instructions in SKILL.md**

Phase 3: docs/ 구조 생성 (포맷팅)
- `references/output-formats.md` 읽기 지시
- `docs/generated/analysis-report.md`, `docs/generated/gap-report.md` 다시 읽기
- project-conventions.md가 프로젝트에 있으면 읽기 (없으면 output-formats.md 기준)
- 생성 순서:
  1. `docs/design-docs/` — core-beliefs.md, data-model.md, 조건부 파일들
  2. `docs/product-specs/` — 페이지/기능별 스펙 파일
  3. `docs/design-docs/index.md`, `docs/product-specs/index.md` — 색인
  4. `ARCHITECTURE.md`
  5. `AGENTS.md` — 모든 파일 생성 후 마지막에 (Directory Map 정확성)
  6. 기타: `DESIGN_GUIDE.md`, `SECURITY.md`, `QUALITY_SCORE.md`
- 프로젝트 타입에 따라 product-spec 섹션 조건부 적용
- GUIDE 주석 삽입하지 않음 (이 스킬은 실제 내용을 채움)
- 사용자에게 생성된 파일 목록 보고

- [ ] **Step 3: Verify output-formats.md covers all document types**

```bash
grep "^## " skills/docs-restructurer/references/output-formats.md
```

Expected: 최소 6개 섹션 (AGENTS.md, ARCHITECTURE.md, product-spec, design-docs, 기타, exec-plan)

- [ ] **Step 4: Commit**

```bash
git add skills/docs-restructurer/SKILL.md skills/docs-restructurer/references/output-formats.md
git commit -m "feat(skill): add Phase 3 docs generation + output-formats reference"
```

---

## Chunk 4: Phase 4 (품질 검토) + Phase 5 (exec-plan) + references/quality-criteria.md

### Task 1: Write references/quality-criteria.md
### Task 2: Write Phase 4 instructions in SKILL.md
### Task 3: Write Phase 5 instructions in SKILL.md

**Files:**
- Modify: `skills/docs-restructurer/SKILL.md`
- Create: `skills/docs-restructurer/references/quality-criteria.md`

- [ ] **Step 1: Write references/quality-criteria.md**

파일 구조:
```markdown
# 품질 검토 기준

## 1. 문서 간 정합성
- product-spec API ↔ data-model.md 엔티티 일치
- ARCHITECTURE.md 디렉토리 구조 ↔ AGENTS.md Directory Map 일치
- design-docs/ 간 모순 검출

## 2. 표현 품질
- 금지 표현 목록: "적절한", "필요시", "충분한", "TBD", "추후 작성", "TODO"
- 측정 가능한 수치 사용 여부 (px, ms, 개수 등)

## 3. 구조 완전성
- AGENTS.md Directory Map ↔ 실제 파일 구조 일치
- index.md 파일들 ↔ 실제 파일 일치
- GUIDE 주석 잔존 여부

## 4. 점수 산출 방법
- product-spec 평균: {각 스펙 체크리스트 점수 평균}
- 아키텍처 점수: {아키텍처 체크리스트 점수}
- 정합성: 통과/실패
- 표현 품질: 위반 건수

## 5. QUALITY_SCORE.md 템플릿
{실제 출력될 QUALITY_SCORE.md 형식}
```

- [ ] **Step 2: Write Phase 4 instructions in SKILL.md**

Phase 4: 품질 검토 + 점수 재평가
- `references/quality-criteria.md` 읽기 지시
- Phase 3에서 생성된 docs/ 전체 파일 목록 확인
- 검토 실행:
  1. 문서 간 정합성 체크 (교차 참조)
  2. 표현 품질 체크 (금지 표현 검색)
  3. 구조 완전성 체크 (파일 존재 확인)
  4. Phase 2 체크리스트 재적용 (점수 재평가)
- 문제 발견 시:
  - 자동 수정 가능한 것 → 즉시 수정
  - 정보 부족 → AskUserQuestion
  - 구조적 문제 → 자동 수정 후 사용자 보고
- QUALITY_SCORE.md 작성
- 사용자에게 품질 점수 요약 보고

- [ ] **Step 3: Write Phase 5 instructions in SKILL.md**

Phase 5: exec-plans 생성
- `references/output-formats.md`의 exec-plan 형식 섹션 다시 읽기
- 생성된 docs/ 전체 읽기 (맥락 복원)
- exec-plan 작성:
  1. 구현 순서 결정 (의존성 기반)
  2. Chunk 분할 (project-conventions.md 5절 크기 가이드라인: Task 2~5개, 파일 3~10개)
  3. 각 Chunk: Completion Criteria(기계적 검증), Tasks, Session Prompt
  4. Metadata: project_dir, spec, status: pending
- exec-plan 검증:
  - Chunk 헤더 정규식: `^## Chunk (\d+): (.+)$`
  - Completion Criteria: `^- \[([ x])\] (.+)$`
  - Session Prompt 비어있지 않음
  - 실패 시 자동 수정 후 재검증 (최대 3회)
- `docs/exec-plans/planning/`에 저장
- 사용자에게 exec-plan 요약 보고 + 최종 확인 요청

- [ ] **Step 4: Verify quality-criteria.md is complete**

```bash
grep "^## " skills/docs-restructurer/references/quality-criteria.md
```

Expected: 최소 5개 섹션

- [ ] **Step 5: Commit**

```bash
git add skills/docs-restructurer/SKILL.md skills/docs-restructurer/references/quality-criteria.md
git commit -m "feat(skill): add Phase 4 quality review + Phase 5 exec-plan generation"
```

---

## Chunk 5: Error Handling + Context Preservation + Final Review

### Task 1: Write error handling section in SKILL.md
### Task 2: Write context preservation section in SKILL.md
### Task 3: Final line count and structure verification

**Files:**
- Modify: `skills/docs-restructurer/SKILL.md`

- [ ] **Step 1: Write Error Handling section**

에러 시나리오별 행동:
1. 입력 문서가 너무 얕은 경우 (미충족 50%+) → 경고 + 선택지 제시
2. 프로젝트 타입 판별 실패 → AskUserQuestion으로 직접 질문
3. 파일 쓰기 실패 → request_cowork_directory 호출 안내
4. exec-plan 형식 검증 실패 → 자동 수정 후 재검증 (최대 3회)

- [ ] **Step 2: Write Context Preservation section**

맥락 보존 규칙:
- 각 Phase 시작 시 이전 Phase 출력 파일 읽기 지시 (구체적 파일 경로)
- Phase → 출력 파일 → 다음 Phase에서 읽음 매핑 테이블

| Phase | 출력 파일 | 다음 Phase에서 읽음 |
|-------|-----------|-------------------|
| 1 | docs/generated/analysis-report.md | Phase 2, 3 |
| 2 | docs/generated/gap-report.md | Phase 3, 4 |
| 3 | docs/ 전체 구조 | Phase 4, 5 |
| 4 | docs/QUALITY_SCORE.md | Phase 5 |
| 5 | docs/exec-plans/planning/*.md | 하네스 실행 |

- [ ] **Step 3: Verify SKILL.md line count**

```bash
wc -l skills/docs-restructurer/SKILL.md
```

Expected: 300~500줄 (500줄 이하)

- [ ] **Step 4: Verify all references files exist**

```bash
ls -la skills/docs-restructurer/references/
```

Expected: checklists.md, output-formats.md, quality-criteria.md

- [ ] **Step 5: Verify SKILL.md YAML frontmatter is valid**

```bash
head -5 skills/docs-restructurer/SKILL.md | grep -c "^---"
```

Expected: 2 (opening and closing --- of frontmatter, within first 5 lines may show 1)

- [ ] **Step 6: Verify no orphan references in SKILL.md**

SKILL.md에서 references/ 파일을 참조하는 모든 경로가 실제 파일과 일치하는지 확인:

```bash
grep "references/" skills/docs-restructurer/SKILL.md
ls skills/docs-restructurer/references/
```

Expected: SKILL.md에서 참조하는 모든 파일이 references/에 존재

- [ ] **Step 7: Final commit**

```bash
git add skills/docs-restructurer/
git commit -m "feat(skill): complete docs-restructurer skill with error handling and context preservation"
```
