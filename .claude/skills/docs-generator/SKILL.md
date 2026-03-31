---
name: docs-generator
description: "docs-analyzer가 생성한 analysis-report.md, gap-report.md, domain-extracts/를 입력으로 받아, 지정된 도메인 범위의 docs/ 문서와 exec-plan을 생성하는 Phase 3~5 전용 스킬. 문서 하나를 쓸 때마다 양식을 재참조하고 즉시 검증하여, 대규모 프로젝트에서도 품질을 유지한다. 트리거: 'docs-generator', 'docs 생성', '문서 생성 Phase 3', 또는 docs-analyzer 완료 후 문서 생성을 시작하려는 모든 요청."
---

# docs-generator

`docs-analyzer`가 준비한 분석 결과를 바탕으로, 지정된 도메인 범위의 docs/ 문서와 exec-plan을 생성한다.

## 핵심 원리

**문서 하나를 쓸 때마다 양식 규칙을 다시 읽고, 즉시 검증한다.** 이것이 이 스킬의 존재 이유다.

컨텍스트가 길어지면 초반에 읽은 양식 규칙에 대한 주의력이 떨어진다. 바로 직전에 읽은 내용은 훨씬 더 정확하게 따른다. 매 문서마다 양식을 다시 읽으면 10번째 문서를 쓸 때도 1번째와 같은 수준의 품질을 유지할 수 있다.

## 사용 시점

- `docs-analyzer`가 완료되어 `analysis-report.md`, `gap-report.md`, `domain-extracts/`가 준비된 상태
- 사용자가 특정 그룹/도메인 범위를 지정하여 문서 생성을 요청할 때

## 전제 조건

1. **프로젝트 폴더 접근**: 대상 프로젝트 폴더가 마운트되어 있어야 한다
2. **분석 결과 파일 존재**: 아래 파일들이 `docs/generated/`에 있어야 한다:
   - `analysis-report.md` — 입력 분석 보고서 (도메인 분할 계획 포함)
   - `gap-report.md` — 갭 분석 보고서 (보강 내용 포함)
   - `domain-extracts/shared.md` — 공유 정보
   - `domain-extracts/{도메인}.md` — 해당 도메인 추출 내용
3. **project-conventions.md**: 있으면 그 규격을 따르고, 없으면 `references/output-formats.md` 기본 규격 사용

---

## 세션 시작 시 필수 작업

새 세션이 시작되면 반드시 아래 순서로 맥락을 복원한다:

1. `docs/generated/analysis-report.md`를 읽는다 — 프로젝트 개요, 설계 결정, 도메인 분할 계획 확인
2. `docs/generated/gap-report.md`를 읽는다 — 보강 내용, 사용자 설계 방향성 확인
3. `docs/generated/domain-extracts/shared.md`를 읽는다 — 공유 정보 확인
4. 지정된 도메인의 추출 파일을 읽는다 — `domain-extracts/{도메인}.md`
5. 사용자가 지정한 그룹/도메인 범위를 확인하고, 생성할 문서 목록을 확정한다

---

## Phase 3: docs/ 구조 생성 — 문서별 순차 생성

### 생성 순서

`analysis-report.md`의 도메인 분할 계획에서 지정된 그룹의 문서를 순서대로 생성한다:

- **그룹 A (설계 기반)**: core-beliefs.md → data-model.md → auth.md(조건부) → deployment.md(조건부) → index.md
- **그룹 B (제품 스펙)**: 해당 도메인의 각 페이지별 스펙 파일 → index.md
- **그룹 C (아키텍처 & 종합)**: ARCHITECTURE.md → DESIGN_GUIDE.md → SECURITY.md → QUALITY_SCORE.md(빈 템플릿)
- **그룹 D (진입점)**: AGENTS.md (반드시 마지막)

### 문서별 생성 루프

**각 문서를 생성할 때 아래 4단계를 반드시 따른다. 이것이 이 스킬의 핵심이다.**

```
┌─────────────────────────────────────────────────┐
│            문서별 생성 루프 (Document Loop)         │
│                                                 │
│  ① RE-READ: 양식 규칙 다시 읽기                    │
│       ↓                                         │
│  ② GENERATE: 해당 문서 1개 생성                    │
│       ↓                                         │
│  ③ VALIDATE: 즉시 자체 검증                        │
│       ↓                                         │
│  ④ SAVE: 파일 저장 + 진행 상황 기록                 │
│       ↓                                         │
│  다음 문서로 → ①로 돌아감                           │
└─────────────────────────────────────────────────┘
```

**① RE-READ (양식 규칙 다시 읽기)**

매 문서 생성 전에 반드시 아래 파일들을 **Read 도구로 다시 읽는다**:

- `references/output-formats.md` — 해당 문서 유형의 양식 섹션 (전체를 다 읽을 필요 없이 해당 섹션만)
- `docs/generated/gap-report.md` — 해당 문서에 관련된 보강 내용 확인
- `project-conventions.md` — 있으면 읽는다 (output-formats.md보다 우선)

이 단계를 건너뛰면 안 된다. "이미 읽었으니 기억하고 있다"는 생각은 틀렸다. 컨텍스트가 길어질수록 초반에 읽은 양식 세부사항을 정확히 재현하기 어렵다. **매번 다시 읽는 것이 이 스킬의 핵심 메커니즘**이다.

해당 도메인의 원본 내용이 필요한 경우, `domain-extracts/{도메인}.md`를 참조한다. 원본 기획서 전체를 읽지 않는다 — 도메인 추출 파일에 필요한 내용이 이미 담겨 있다.

**② GENERATE (문서 생성)**

해당 문서 1개만 집중해서 생성한다.

핵심 규칙:
- 입력 문서의 실제 내용을 변환한다. 자리표시자("TBD", "TODO")는 사용하지 않는다
- GUIDE 주석(`<!-- GUIDE: ... -->`)을 삽입하지 않는다
- gap-report.md의 보강 내용을 활용한다
- 그래도 정보가 없으면 "Phase 2에서 미확인. 추후 보강 필요." 표시 (최소화)

AGENTS.md 생성 시에는 반드시 "Chunk 완료 워크플로" 섹션을 포함한다:

```markdown
## Chunk 완료 워크플로

exec-plan의 Chunk 작업을 완료한 후 반드시 다음 순서를 따른다:

1. `/engineering:code-review` 스킬을 사용하여 작성한 코드를 리뷰한다
2. 리뷰에서 발견된 문제를 수정한다
3. `/chunk-complete:chunk-complete` 스킬을 사용하여 Completion Criteria 체크박스를 마킹한다

**이 순서를 건너뛰지 않는다.** code-review 없이 chunk-complete를 실행하지 않는다.
```

**③ VALIDATE (즉시 자체 검증)**

문서를 파일로 저장한 직후, 방금 쓴 파일을 **Read 도구로 다시 읽어** 아래를 확인한다:

- **양식 일치**: `output-formats.md`의 해당 문서 템플릿과 섹션 순서/필수 항목이 일치하는가
- **금지 표현 부재**: "적절한", "필요시", "충분한", "등등", "TBD", "추후 작성", "TODO" 단독 사용이 없는가
- **측정 가능성**: 성능/UI/데이터 영역에 수치가 최소 1개 이상 있는가
- **GUIDE 주석 부재**: `<!-- GUIDE: -->` 잔존 여부

문제 발견 시:
- 자동 수정 가능한 것 → 즉시 수정하고 다시 저장
- 정보 부족 → 해당 부분을 표시하고 Phase 4에서 처리

**④ SAVE (저장 + 진행 기록)**

검증을 통과한 문서를 최종 저장하고, `docs/generated/progress.md`에 진행 상황을 기록한다:

```markdown
# 생성 진행 상황

| # | 문서 | 상태 | 자체 검증 | 비고 |
|---|------|------|----------|------|
| 1 | core-beliefs.md | 완료 | 통과 | |
| 2 | data-model.md | 완료 | 통과 | ERD 포함 |
| 3 | auth.md | 완료 | 수정 후 통과 | 에러코드 누락 → 보강 |
| 4 | {페이지1}.md | 진행 중 | - | |
```

### 그룹 간 체크포인트

각 그룹 전환 시 사용자에게 진행 상황을 요약 보고한다:

> "그룹 A (design-docs/) 완료: core-beliefs.md, data-model.md, auth.md 생성. 모두 자체 검증 통과.
> 그룹 B (product-specs/) 진행하겠습니다."

---

## Phase 4: 품질 검토 — 크로스 검증 집중

> **개별 문서 검증은 Phase 3에서 이미 완료했으므로, 이 Phase는 문서 간 교차 검증에 집중한다.**

**사전 작업:**
- `references/quality-criteria.md`를 읽는다
- Phase 3에서 생성된 **모든** docs/ 파일을 다시 읽는다
- `docs/generated/progress.md`를 읽어 자체 검증에서 발견된 이슈를 확인한다

**검토 항목:**

1. **문서 간 정합성** (quality-criteria.md §1):
   - 데이터 정합성: product-spec의 API 타입 ↔ data-model.md 엔티티 필드
   - 구조 정합성: ARCHITECTURE.md 디렉토리 구조 ↔ AGENTS.md Directory Map
   - 참조 정합성: index.md 목록 ↔ 실제 파일 존재 여부
   - design-docs 간 모순 없음

2. **체크리스트 재적용**: Phase 2의 체크리스트를 **생성된 문서에** 다시 적용하여 점수를 재평가한다. 입력에 대한 평가가 아니라, 출력에 대한 평가다.

3. **표현 품질 전체 스캔**: 모든 문서를 대상으로 금지 표현 검사를 한 번 더 실행한다.

**문제 발견 시:**
- 자동 수정 가능 → 즉시 수정
- 정보 부족 → AskUserQuestion으로 사용자에게 질문
- 모순 발견 → 어느 쪽이 맞는지 사용자에게 확인

**결과**: `docs/QUALITY_SCORE.md`를 `references/quality-criteria.md`의 §5 템플릿에 따라 작성한다. 사용자에게 종합 등급과 상세 점수를 보고한다.

---

## Phase 5: exec-plans 생성 — exec-plan별 순차 생성

> **Phase 3과 같은 원리를 적용한다. exec-plan을 한꺼번에 생성하지 않고, 하나씩 생성하며 매번 양식을 재참조한다.**

**사전 작업:**
- `references/output-formats.md`의 "exec-plan 형식" 섹션을 읽는다
- 생성된 docs/ 전체를 다시 읽는다 (맥락 복원)
- `docs/QUALITY_SCORE.md`를 읽는다

**실행 단계:**

1. **구현 순서 결정**: 의존성 분석 → 보통의 순서: 데이터 모델 → 인증 → 핵심 기능 → 부가 기능

2. **exec-plan 분할 계획**: 먼저 **어떤 exec-plan 파일들이 필요한지 목록만** 확정한다. 아직 내용은 쓰지 않는다.

```markdown
## exec-plan 생성 계획

| # | 파일명 | 범위 | 의존성 |
|---|--------|------|--------|
| 1 | 01-project-setup.md | 프로젝트 초기화, 기본 설정 | 없음 |
| 2 | 02-data-layer.md | 데이터 모델, DB 설정 | 01 |
| 3 | 03-auth.md | 인증/인가 | 01, 02 |
| ... | ... | ... | ... |
```

3. **exec-plan별 순차 생성 루프**: Phase 3의 문서별 생성 루프와 같은 패턴을 따른다.

```
┌─────────────────────────────────────────────────┐
│          exec-plan별 생성 루프                     │
│                                                 │
│  ① RE-READ: output-formats.md의 exec-plan 섹션   │
│       ↓                                         │
│  ② GENERATE: 해당 exec-plan 1개 생성              │
│       ↓                                         │
│  ③ VALIDATE: 파서 규격 즉시 검증                   │
│       ↓                                         │
│  ④ SAVE: 파일 저장 + 진행 기록                     │
│       ↓                                         │
│  다음 exec-plan으로 → ①로 돌아감                   │
└─────────────────────────────────────────────────┘
```

**① RE-READ**: 매 exec-plan 생성 전에 `references/output-formats.md`의 §6 "exec-plan 형식" 섹션을 **Read 도구로 다시 읽는다**. 특히 파서 호환 규칙을 반드시 재확인한다.

**② GENERATE**: 해당 exec-plan 1개만 집중해서 생성한다.

Chunk 크기 가이드라인:
- Task: 2~5개
- 예상 파일 변경: 3~10개
- Completion Criteria: 2~5개

Chunk 형식 — Session Prompt 코드 블록은 **반드시 plain triple-backtick(```` ``` ````)으로만** 열어야 한다:

````
## Chunk 1: 프로젝트 초기화

### Completion Criteria
- [ ] src/index.ts 파일 존재
- [ ] npm run build 성공

### Tasks
- Task 1: 프로젝트 디렉토리 생성
- Task 2: TypeScript 설정

### Session Prompt
```
프로젝트를 초기화하라. docs/ARCHITECTURE.md를 참고하여 설정한다.
- TypeScript strict mode 활성화
- path alias: @/* → src/*
모든 Task 완료 후, `/engineering:code-review`로 코드 리뷰를 실행하고, 리뷰 통과 후 `/chunk-complete:chunk-complete`로 Completion Criteria 체크박스를 마킹해.
```
````

Session Prompt 파서 호환 규칙 (어기면 harness ESCALATE 에러):
- **언어 식별자 금지**: plain ```` ``` ```` 만 사용
- **중첩 코드 블록 금지**: Session Prompt 안에 triple-backtick 넣지 않는다
- **Chunk 헤더 금지**: Session Prompt 안에 `## Chunk N:` 넣지 않는다
- **코드보다 지시**: 파일 경로, 함수명은 인라인 코드, 구현은 참조 문서 경로 안내

Completion Criteria: 기계적으로 검증 가능한 조건만.
- OK: `pytest tests/test_X.py 통과`, `src/X.py 파일 존재`
- 금지: `코드가 깔끔한지`, `UI가 보기 좋은지`

Session Prompt 끝에 반드시 Chunk 완료 워크플로:
> "모든 Task 완료 후, `/engineering:code-review`로 코드 리뷰를 실행하고, 리뷰 통과 후 `/chunk-complete:chunk-complete`로 Completion Criteria 체크박스를 마킹해."

**③ VALIDATE**: 방금 쓴 exec-plan 파일을 **Read 도구로 다시 읽어** 파서 규격 검증 (최대 3회 자동 수정):
- Chunk 헤더: `^## Chunk (\d+): (.+)$`
- Completion Criteria: `^- \[([ x])\] (.+)$`
- Session Prompt가 비어있지 않음
- Session Prompt 여는 코드 블록이 plain ```` ``` ````
- Session Prompt 안에 추가 triple-backtick 없음
- Session Prompt 안에 `## Chunk` 헤더 없음

**④ SAVE**: `docs/exec-plans/planning/`에 번호순 저장 + `progress.md` 기록.

4. 모든 exec-plan 생성 완료 후, 사용자에게 전체 요약을 보고하고 최종 확인을 요청한다.

---

## 맥락 보존 전략

이 스킬은 두 가지 수준의 맥락 보존을 사용한다.

### 수준 1: 세션 시작 시 파일 기반 맥락 복원

| 파일 | 역할 |
|------|------|
| `docs/generated/analysis-report.md` | 프로젝트 구조, 도메인 분할, 설계 결정 |
| `docs/generated/gap-report.md` | 보강 내용, 사용자 설계 방향성 |
| `docs/generated/domain-extracts/{도메인}.md` | 해당 도메인의 원본 내용 |
| `docs/generated/progress.md` | 이전까지의 진행 상황 |

### 수준 2: Phase 3, 5 내부 — 문서별/exec-plan별 양식 재참조

Phase 3에서 문서를 생성할 때마다:

| 시점 | 읽는 파일 | 이유 |
|------|-----------|------|
| 매 문서 생성 전 | `references/output-formats.md` (해당 섹션) | 양식 규칙 주의력 유지 |
| 매 문서 생성 전 | `docs/generated/gap-report.md` | 보강 내용 확인 |
| 매 문서 생성 후 | 방금 쓴 파일 자체 | 즉시 자체 검증 |

Phase 5에서 exec-plan을 생성할 때마다:

| 시점 | 읽는 파일 | 이유 |
|------|-----------|------|
| 매 exec-plan 생성 전 | `references/output-formats.md` §6 | 파서 규칙 주의력 유지 |
| 매 exec-plan 생성 후 | 방금 쓴 exec-plan 파일 자체 | 파서 규격 즉시 검증 |

**"이미 읽었으니 기억한다"는 생각을 해서는 안 된다.** 이 재참조 메커니즘이 대규모 프로젝트에서 품질을 유지하는 유일한 방법이다.

---

## 에러 처리

### 분석 파일 누락
`analysis-report.md` 또는 `gap-report.md`가 없으면 먼저 `docs-analyzer`를 실행하라고 안내한다.

### 자체 검증 반복 실패
Phase 3에서 한 문서의 자체 검증이 3회 연속 실패하면 사용자에게 알리고 판단을 요청한다:
> "{문서명}의 자체 검증이 반복 실패합니다. 주요 문제: {문제 요약}. (1) 문제를 무시하고 진행 (2) 해당 문서를 수동으로 수정 (3) 처음부터 다시 생성"

### exec-plan 형식 검증 실패
자동 수정 후 재검증 (최대 3회). 3회 실패 시 사용자에게 알린다.

### 파일 쓰기 실패
폴더 마운트 요청.
