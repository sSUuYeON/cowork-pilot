---
name: docs-restructurer
description: "Cowork 대화에서 나온 자유 형식 문서들을 project-conventions.md 규격의 docs/ 구조로 자동 변환하는 스킬. 사용자가 Cowork에서 충분히 상의한 후 나온 결과물(설계 문서, 기능 명세, 데이터 모델 등)을 입력으로 받아 AGENTS.md, ARCHITECTURE.md, design-docs/, product-specs/, exec-plans를 자동 생성한다. 트리거: 'docs 재구성', 'docs/ 구조 만들어', '문서 포맷팅', '프로젝트 문서 변환', '설계 문서 정리', 'exec-plan 생성', 'restructure docs', 'generate project docs', 또는 자유 형식 문서를 project-conventions.md 형식으로 변환하려는 모든 요청에서 이 스킬을 사용하라."
---

# docs-restructurer

Cowork 대화에서 나온 자유 형식 문서들을 프로젝트의 `docs/` 규격 구조로 자동 변환한다.

## 이 스킬이 하는 일

사용자가 Cowork에서 충분히 상의하여 만든 설계 문서, 기능 명세, 데이터 모델 등의 자유 형식 결과물을 입력으로 받는다. 이 결과물에는 사용자의 의도, 맥락, 판단이 담겨 있어 품질이 높지만, 형식이 자유로워 자동화 도구가 바로 사용할 수 없다.

이 스킬은 그 자유 형식 문서들을 **5단계 파이프라인**으로 처리하여, 프로젝트의 `project-conventions.md` 규격에 맞는 완전한 `docs/` 구조 + exec-plans를 생성한다.

## 사용 시점

- Cowork에서 프로젝트 설계를 충분히 논의한 후, 결과물을 정리된 문서 구조로 변환하고 싶을 때
- 자유 형식의 마크다운 파일들을 표준 docs/ 구조로 재구성하고 싶을 때
- 설계 문서를 기반으로 구현 계획(exec-plan)을 자동 생성하고 싶을 때

## 전제 조건

1. **프로젝트 폴더 접근**: 대상 프로젝트 폴더가 마운트되어 있어야 한다. 없으면 사용자에게 폴더 마운트를 요청한다.
2. **입력 문서**: 자유 형식 마크다운 파일이 1개 이상 존재해야 한다. 마운트된 폴더, 세션 내 파일, 또는 사용자가 대화로 직접 설명한 내용 모두 입력으로 사용할 수 있다. 대화로 받은 경우 먼저 파일로 정리한다.
3. **project-conventions.md**: 프로젝트에 이 파일이 있으면 그 규격을 따른다. 없으면 이 스킬의 `references/output-formats.md`에 정의된 기본 규격을 사용한다.

---

## 5-Phase 워크플로

각 Phase는 **반드시 결과를 파일로 저장**한다. 다음 Phase에서는 해당 파일을 다시 읽어 맥락을 복원한다. 이는 세션이 길어져도 맥락이 흐려지지 않게 하기 위함이다.

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
입력 분석   갭 분석   문서 생성   품질 검토   exec-plan
```

각 Phase 완료 후 사용자에게 결과를 요약 보고하고, 다음 Phase를 진행해도 되는지 확인한다.

---

### Phase 1: 입력 읽기 & 구조 분석

**목표**: 입력 문서에서 어떤 정보가 있고, 무엇이 빠졌는지 파악한다.

**실행 단계:**

1. 마운트된 폴더를 탐색하여 마크다운 파일을 모두 수집한다. 세션 내에서 생성된 파일도 포함한다.

2. 각 파일의 내용을 읽고, 다음 **입력 매핑 테이블**에 따라 어떤 정보가 어떤 docs/ 파일로 변환될 수 있는지 분류한다:

| 입력에서 발견되는 정보 | 매핑되는 docs/ 파일 |
|----------------------|-------------------|
| 프로젝트 개요, 기술 스택, 설계 철학 | `AGENTS.md`, `ARCHITECTURE.md` |
| 데이터 모델 (엔티티, 관계, 스키마) | `docs/design-docs/data-model.md` |
| 운영 원칙, 기술 철학 | `docs/design-docs/core-beliefs.md` |
| 인증/보안 설계 | `docs/design-docs/auth.md`, `docs/SECURITY.md` |
| 배포 전략 | `docs/design-docs/deployment.md` |
| 페이지/기능별 상세 스펙 | `docs/product-specs/{페이지}.md` |
| 디자인 가이드라인 | `docs/DESIGN_GUIDE.md` |
| 비기능 요구사항 (성능, 접근성 등) | 해당 문서에 분산 배치 |

3. 프로젝트 타입을 추론한다: `web-app` / `api` / `cli` / `library` / `mobile`. 추론할 수 없으면 사용자에게 직접 질문한다.

4. 결과를 `docs/generated/analysis-report.md`에 저장한다:

```markdown
# 입력 분석 보고서

> 생성일: {YYYY-MM-DD}
> 프로젝트 타입: {추론된 타입}

## 입력 파일 목록

| 파일 | 주요 내용 요약 |
|------|--------------|
| {파일명} | {1줄 요약} |

## 정보 매핑 계획

| 카테고리 | 출처 파일 | 대상 docs/ 파일 | 정보 충분도 |
|---------|---------|----------------|------------|
| {카테고리} | {출처} | {대상} | 충분 / 부분 / 없음 |

## 누락 항목

- {발견되지 않은 정보 목록}
```

5. 사용자에게 분석 결과를 요약 보고한다. 누락 항목이 있으면 미리 알린다.

---

### Phase 2: 갭 분석 + 점수 평가

**목표**: 체크리스트 기반으로 각 항목에 점수를 매기고, 부족한 부분을 보강한다.

**사전 작업:**
- `references/checklists.md`를 읽는다 — 체크리스트와 점수 체계가 정의되어 있다.
- `docs/generated/analysis-report.md`를 다시 읽는다 — Phase 1의 맥락을 복원한다.

**실행 단계:**

1. **product-spec 체크리스트 적용**: 각 페이지/기능별로 `references/checklists.md`의 "product-spec 체크리스트"를 적용한다. 각 항목에 점수(3/2/1/N/A)를 매긴다.

2. **프로젝트 타입별 추가 체크리스트 적용**: 프로젝트 타입이 `web-app`이면 "web-app 추가 체크리스트"도 적용. `api`/`library`이면 해당 체크리스트 적용.

3. **아키텍처 체크리스트 적용**: 프로젝트 전체에 대해 아키텍처 체크리스트를 적용한다.

4. **미충족/부분 충족 항목 처리**:
   - **미충족 (1점)**: 사용자에게 AskUserQuestion으로 질문한다. 구체적 선택지를 제시하고 "어떻게 할까?" 형태로 묻는다.
   - **부분 충족 (2점)**: 구체화 방향을 제안하고 "이렇게 구체화하면 될까?" 형태로 확인한다.
   - **충족 (3점) 또는 N/A**: 별도 조치 없이 통과.

5. **중단 기준**: 미충족 항목이 전체의 50% 이상이면 경고를 표시한다:
   > "입력 문서에 정보가 너무 부족합니다. 선택지: (1) Cowork에서 더 상의한 후 다시 시도 (2) 부족한 항목을 지금 여기서 채우기 (3) 부족한 채로 진행 (품질 저하 감수)"

6. 결과를 `docs/generated/gap-report.md`에 저장한다:

```markdown
# 갭 분석 보고서

> 생성일: {YYYY-MM-DD}

## 종합 점수: {평균} / 3.0

## 페이지별 product-spec 점수

| 페이지 | 문제정의 | 유저플로우 | 에러패스 | 데이터 | 에러처리 | 성능 | 의존성 | Non-Goals | 평균 |
|--------|---------|----------|---------|-------|---------|------|-------|----------|------|
| {페이지} | {점수} | ... | | | | | | | {평균} |

## 아키텍처 점수

| 항목 | 점수 | 비고 |
|------|------|------|
| {항목} | {점수} | {설명} |

## 보강된 내용

{AskUserQuestion으로 받은 사용자 응답을 여기에 기록}
```

7. 사용자에게 점수 요약을 보고한다.

---

### Phase 3: docs/ 구조 생성 (포맷팅)

**목표**: 입력 문서의 내용을 `project-conventions.md` 규격에 맞는 docs/ 구조로 변환한다.

**사전 작업:**
- `references/output-formats.md`를 읽는다 — 각 문서의 정확한 출력 구조가 정의되어 있다.
- `docs/generated/analysis-report.md`와 `docs/generated/gap-report.md`를 다시 읽는다.
- 프로젝트에 `project-conventions.md`가 있으면 읽는다 (output-formats.md보다 우선).

**생성 순서** (의존성 기반):

1. `docs/design-docs/` 생성:
   - `core-beliefs.md` — 운영 원칙, 기술 철학
   - `data-model.md` — 엔티티, 관계, 스키마 (Mermaid ERD 포함)
   - 조건부 파일: `auth.md` (인증 정보가 있으면), `deployment.md` (배포 정보가 있으면)
   - `index.md` — 생성된 파일 색인

2. `docs/product-specs/` 생성:
   - 각 페이지/기능별 스펙 파일 — `references/output-formats.md`의 product-spec 형식을 따른다
   - 프로젝트 타입에 따라 섹션을 조건부 적용 (web-app: 11섹션, api: 10섹션, 기본: 8섹션)
   - `index.md` — 생성된 파일 색인

3. `ARCHITECTURE.md` 생성

4. 기타 파일 생성: `DESIGN_GUIDE.md`, `SECURITY.md`, `QUALITY_SCORE.md` (빈 템플릿, Phase 4에서 채움)

5. `AGENTS.md` 생성 — **반드시 마지막에** 생성한다. Directory Map이 실제 파일 구조를 정확히 반영해야 하기 때문이다.
   - AGENTS.md에는 반드시 다음 **"Chunk 완료 워크플로"** 섹션을 포함한다:

   ```markdown
   ## Chunk 완료 워크플로

   exec-plan의 Chunk 작업을 완료한 후 반드시 다음 순서를 따른다:

   1. `/engineering:code-review` 스킬을 사용하여 작성한 코드를 리뷰한다
   2. 리뷰에서 발견된 문제를 수정한다
   3. `/chunk-complete:chunk-complete` 스킬을 사용하여 Completion Criteria 체크박스를 마킹한다

   **이 순서를 건너뛰지 않는다.** code-review 없이 chunk-complete를 실행하지 않는다.
   ```

**핵심 규칙:**
- 입력 문서의 실제 내용을 변환한다. 자리표시자("TBD", "TODO")는 사용하지 않는다.
- GUIDE 주석(`<!-- GUIDE: ... -->`)을 삽입하지 않는다 — 이 스킬은 실제 내용을 채우는 것이 목적이다.
- 입력에 없는 정보는 Phase 2에서 사용자에게 받은 보강 내용을 사용한다.
- 그래도 정보가 없으면 해당 섹션에 "Phase 2에서 미확인. 추후 보강 필요." 표시를 남기되, 가능한 한 줄인다.

6. 사용자에게 생성된 파일 목록과 각 파일의 1줄 요약을 보고한다.

---

### Phase 4: 품질 검토 + 점수 재평가

**목표**: 생성된 docs/ 전체를 검증하고, 문제를 수정한다.

**사전 작업:**
- `references/quality-criteria.md`를 읽는다 — 검토 기준이 정의되어 있다.
- Phase 3에서 생성된 모든 docs/ 파일을 다시 읽는다.

**검토 항목:**

1. **문서 간 정합성**:
   - product-spec에서 정의한 API/데이터가 `data-model.md`의 엔티티와 일치하는가
   - `ARCHITECTURE.md`의 디렉토리 구조가 `AGENTS.md`의 Directory Map과 일치하는가
   - design-docs/ 간에 모순되는 정의가 없는가

2. **표현 품질**:
   - "적절한", "필요시", "충분한" 같은 모호한 표현이 없는가
   - "TBD", "추후 작성", "TODO" 단독 사용이 없는가
   - 측정 가능한 수치가 사용되었는가 (px, ms, 개수 등)

3. **구조 완전성**:
   - `AGENTS.md`의 Directory Map이 실제 생성된 파일과 일치하는가
   - `index.md` 파일들이 실제 파일 목록과 일치하는가

4. **체크리스트 재적용**: Phase 2의 체크리스트를 생성된 문서에 다시 적용하여 점수를 재평가한다.

**문제 발견 시:**
- 자동 수정 가능 (오타, 경로 불일치 등) → 즉시 수정
- 정보 부족 → AskUserQuestion으로 사용자에게 질문
- 모순 발견 → 어느 쪽이 맞는지 사용자에게 확인

**결과**: `docs/QUALITY_SCORE.md`를 작성한다. 사용자에게 품질 점수 요약을 보고한다.

---

### Phase 5: exec-plans 생성

**목표**: 설계 문서와 스펙을 기반으로 구현 계획을 작성한다.

**사전 작업:**
- `references/output-formats.md`의 "exec-plan 형식" 섹션을 다시 읽는다.
- 생성된 docs/ 전체를 다시 읽는다 (맥락 복원).
- `docs/QUALITY_SCORE.md`를 읽는다.

**실행 단계:**

1. **구현 순서 결정**: 의존성을 분석하여 어떤 기능/모듈을 먼저 구현할지 결정한다. 보통의 순서: 데이터 모델 → 인증 → 핵심 기능 → 부가 기능.

2. **exec-plan 분할**: 큰 프로젝트는 여러 exec-plan 파일로 나눈다. 각 exec-plan은 독립적으로 실행 가능한 단위.

3. **Chunk 분할**: 각 exec-plan 내에서 Chunk으로 나눈다. Chunk 크기 가이드라인:
   - Task: 2~5개
   - 예상 파일 변경: 3~10개
   - Completion Criteria: 2~5개

4. **Chunk 형식** — 반드시 정확히 이 형식을 따른다:
   ```
   ## Chunk N: {이름}

   ### Completion Criteria
   - [ ] {기계적으로 검증 가능한 조건}

   ### Tasks
   - Task 1: {태스크}

   ### Session Prompt
   ```{프롬프트}```
   ```

5. **Completion Criteria 규칙**: 기계적으로 검증 가능한 조건만 허용.
   - OK: `pytest tests/test_X.py 통과`, `src/X.py 파일 존재`, `npm run build 성공`
   - 금지: `코드가 깔끔한지`, `UI가 보기 좋은지`

6. **Session Prompt에 Chunk 완료 워크플로 포함**: 각 Chunk의 Session Prompt 끝에 반드시 다음 지시를 포함한다:
   > "모든 Task 완료 후, `/engineering:code-review`로 코드 리뷰를 실행하고, 리뷰 통과 후 `/chunk-complete:chunk-complete`로 Completion Criteria 체크박스를 마킹해."

7. **Session Prompt 파서 호환 규칙**: 파서는 Session Prompt를 "### Session Prompt" 아래 첫 번째 코드 블록(triple-backtick 쌍)으로 추출한다. 내부에 추가 코드 블록이 있으면 파서가 중간에서 블록이 끝났다고 판단하여 빈 프롬프트로 인식한다. 반드시 지킨다:
   - **중첩 코드 블록 금지**: Session Prompt 안에 triple-backtick 코드 블록(bash, json, typescript 등)을 절대 넣지 않는다. 코드 예시가 필요하면 인라인 코드(backtick)나 4칸 들여쓰기로 대체한다.
   - **Chunk 헤더 금지**: Session Prompt 안에 `## Chunk N:` 형태의 마크다운 헤더를 넣지 않는다. 파서가 이를 새로운 Chunk 경계로 오인한다.
   - **코드보다 지시**: Session Prompt는 "무엇을 만들어라"를 지시하는 것이지, 완성 코드를 담는 곳이 아니다. 파일 경로, 함수명, 타입명은 인라인 코드로 언급하고, 구체적 구현은 참조 문서 경로를 안내한다.

8. **검증**: 생성된 exec-plan이 파서 규격에 맞는지 확인:
   - Chunk 헤더: `^## Chunk (\d+): (.+)$`
   - Completion Criteria: `^- \[([ x])\] (.+)$`
   - Session Prompt가 비어있지 않음
   - Session Prompt 코드 블록 안에 추가 triple-backtick이 없음 (중첩 코드 블록 검사)
   - Session Prompt 안에 `## Chunk` 헤더가 없음 (중복 Chunk 헤더 검사)
   - 실패 시 자동 수정 후 재검증 (최대 3회)

8. `docs/exec-plans/planning/`에 번호순으로 저장: `01-{이름}.md`, `02-{이름}.md`, ...

9. 사용자에게 exec-plan 요약을 보고하고 최종 확인을 요청한다.

---

## 맥락 보존

세션이 길어지면 대화 기억이 흐려진다. 이를 방지하기 위해 각 Phase는 반드시 결과를 파일로 저장하고, 다음 Phase에서는 파일을 다시 읽어 맥락을 복원한다.

| Phase | 출력 파일 | 읽는 Phase |
|-------|-----------|-----------|
| 1 | `docs/generated/analysis-report.md` | 2, 3 |
| 2 | `docs/generated/gap-report.md` | 3, 4 |
| 3 | `docs/` 전체 구조 | 4, 5 |
| 4 | `docs/QUALITY_SCORE.md` | 5 |
| 5 | `docs/exec-plans/planning/*.md` | 외부 하네스 |

**각 Phase 시작 시 반드시**: 위 테이블의 "읽는 Phase" 열에 해당하는 파일을 먼저 읽는다. 이전 대화에서 했던 작업을 "기억"에 의존하지 말고, 파일에서 읽어 확인한다.

---

## 에러 처리

### 입력 문서가 너무 얕은 경우

Phase 2 갭 분석에서 미충족 항목(1점)이 전체의 50% 이상이면:

> "입력 문서에 정보가 너무 부족합니다."

사용자에게 선택지를 제시한다:
1. Cowork에서 더 상의한 후 다시 시도
2. 부족한 항목을 지금 여기서 하나씩 채우기
3. 부족한 채로 진행 (품질 저하 감수)

### 프로젝트 타입 판별 실패

입력 문서에서 프로젝트 타입을 추론할 수 없으면 사용자에게 직접 질문한다:

> "이 프로젝트의 타입이 뭔가요?"

선택지: web-app / api / cli / library / mobile

### 파일 쓰기 실패

대상 프로젝트 디렉토리에 쓰기 권한이 없으면:

> "프로젝트 폴더에 쓰기 권한이 없습니다. 폴더를 마운트해주세요."

### exec-plan 형식 검증 실패

Phase 5에서 생성한 exec-plan이 파서 규격에 맞지 않으면 자동 수정 후 재검증한다. 최대 3회 시도. 3회 실패 시 사용자에게 알린다.
