# docs-restructurer 스킬 — 설계 문서

> Cowork 대화 결과물을 cowork-pilot의 docs/ 구조로 자동 변환하는 스킬
> 작성일: 2026-03-26
> 상태: Draft

---

## 1. 목표

### 해결하는 문제

현재 Phase 3 메타 모드는 Brief(얕은 정보) → 템플릿(GUIDE 주석) → Cowork 자동 채우기 파이프라인으로 문서를 생성한다. 이 방식의 근본적 한계: **프로젝트 맥락 없이 AI가 혼자 채우는 문서**는 실제 개발에 필요한 구체성이 부족하다.

반면 사용자가 Cowork에서 충분히 상의한 후 나온 결과물은 의도, 맥락, 판단이 담겨 품질이 높다. 문제는 이 결과물이 자유 형식이라 cowork-pilot의 하네스가 바로 사용할 수 없다는 것.

### 이 스킬이 하는 일

Cowork 대화에서 나온 자유 형식 문서들을 입력으로 받아, cowork-pilot의 `project-conventions.md` 규격에 맞는 완전한 `docs/` 구조 + exec-plans로 자동 변환한다.

### 기존 Phase 3과의 관계

기존 `--mode meta` (Step 0→1→2→3→4)는 **그대로 유지**한다. 사용자에게 두 가지 경로를 제공:

| 경로 | 방식 | 장점 | 단점 |
|------|------|------|------|
| **경로 A (기존 meta)** | Brief → 자동 스캐폴딩 → 자동 문서 채우기 → 자동 구현 | 빠름, 사람 개입 최소 | 문서 품질 낮음 |
| **경로 B (이 스킬)** | Cowork 대화 → 스킬로 docs/ 재구성 → harness로 구현 | 문서 품질 높음 | 사전 대화 시간 필요 |

경로 B 완료 후 `cowork-pilot --mode harness`로 exec-plan을 실행하면 된다.

---

## 2. 아키텍처

### 실행 환경

이 스킬은 **Cowork 세션 안에서** 실행된다. 별도의 Python 코드가 아니라 SKILL.md 파일 하나로, Cowork AI에게 단계별 지시를 내리는 방식이다.

### 전체 흐름

```
사용자의 자유 형식 문서 (마운트된 폴더 또는 세션 내 파일)
    ↓
[Phase 1] 입력 읽기 & 구조 분석
    → 어떤 정보가 있고 뭐가 빠졌는지 파악
    → 결과: docs/generated/analysis-report.md 저장
    → 사용자 확인 (cowork-pilot 자동 승인)
    ↓
[Phase 2] 갭 분석 + 점수 평가
    → 체크리스트 기반으로 각 항목 점수 매기기
    → 부족한 부분 → 사용자에게 AskUserQuestion (ESCALATE → 사람이 답변)
    → 결과: docs/generated/gap-report.md 저장
    ↓
[Phase 3] docs/ 구조 생성 (포맷팅)
    → project-conventions.md 규격에 맞게 변환
    → AGENTS.md, ARCHITECTURE.md, design-docs/, product-specs/ 생성
    → 사용자 확인 (cowork-pilot 자동 승인)
    ↓
[Phase 4] 품질 검토 + 점수 재평가
    → 생성된 문서 전체를 검토 기준으로 검증
    → 문서 간 모순, 모호한 표현, 빠진 항목 체크
    → 보강 필요하면 수정 또는 사용자에게 질문
    → 결과: docs/QUALITY_SCORE.md 업데이트
    ↓
[Phase 5] exec-plans 생성
    → 설계 문서 + 스펙을 기반으로 구현 계획 작성
    → docs/exec-plans/planning/에 배치
    → 사용자 최종 확인 (ESCALATE → 사람이 확인)
    ↓
확정. `cowork-pilot --mode harness`로 실행 가능.
```

### 맥락 보존 전략

세션이 길어지면 AI의 대화 기억이 흐려진다. 이를 방지하기 위해 **각 Phase의 결과를 반드시 파일로 저장**하고, 다음 Phase에서는 파일을 다시 읽어 맥락을 복원한다.

| Phase | 출력 파일 | 다음 Phase에서 읽음 |
|-------|-----------|-------------------|
| 1 | `docs/generated/analysis-report.md` | Phase 2, 3 |
| 2 | `docs/generated/gap-report.md` | Phase 3, 4 |
| 3 | `docs/` 전체 구조 | Phase 4, 5 |
| 4 | `docs/QUALITY_SCORE.md` | Phase 5 |
| 5 | `docs/exec-plans/planning/*.md` | harness 실행 |

---

## 3. 기술적 세부사항

### 3.1 입력 형식

스킬이 받아들이는 입력:

- 마운트된 폴더 내 마크다운 파일들 (자유 형식)
- Cowork 세션 중 생성된 파일들
- 또는 사용자가 대화로 직접 설명한 내용 (이 경우 스킬이 먼저 파일로 정리)

입력에서 추출해야 하는 정보:

| 정보 | 매핑되는 docs/ 파일 |
|------|-------------------|
| 프로젝트 개요, 기술 스택, 설계 철학 | AGENTS.md, ARCHITECTURE.md |
| 데이터 모델 (엔티티, 관계, 스키마) | docs/design-docs/data-model.md |
| 운영 원칙, 기술 철학 | docs/design-docs/core-beliefs.md |
| 인증/보안 설계 | docs/design-docs/auth.md, docs/SECURITY.md |
| 배포 전략 | docs/design-docs/deployment.md |
| 페이지/기능별 상세 스펙 | docs/product-specs/{페이지}.md |
| 디자인 가이드 | docs/DESIGN_GUIDE.md |
| 비기능 요구사항 | 해당 문서에 분산 배치 |

### 3.2 product-spec 출력 구조

프로젝트 타입에 따라 조건부 섹션을 적용한다.

**공통 섹션 (모든 타입):**

1. **Problem & Appetite** — 이 기능이 해결하는 문제, 투자할 시간 예산
2. **유저 플로우** — step-by-step: 유저 액션 → 시스템 반응 → 화면 변화. 해피 패스 + 에러 패스
3. **핵심 요소** — 각 요소의 동작/상태/예외/데이터 의존성
4. **데이터 & API** — 각 함수/엔드포인트별 request/response 스키마 (TypeScript 인터페이스), 에러 코드
5. **에러 처리** — 에러 유형별 테이블: 에러 조건 | 사용자 메시지 | 복구 동작
6. **성능 요구사항** — 측정 가능한 수치: 로딩 시간 목표, 페이지네이션 기준, 번들 사이즈
7. **의존성** — 이 기능이 의존하는 것 / 이 기능에 의존하는 것
8. **Rabbit Holes & Non-Goals** — 빠지기 쉬운 함정, 명시적으로 하지 않을 것

**web-app / mobile 전용 (추가):**

9. **UI 구성** — ASCII 와이어프레임 + 컴포넌트 계층 트리 + 로딩/빈 상태/에러 상태 각각의 화면
10. **상태 관리** — state shape, 사용할 훅, 로컬 state vs 서버 state 구분
11. **접근성** — 키보드 네비게이션, ARIA 속성, 포커스 관리

**api / library 전용 (9~11 대체):**

9. **엔드포인트 상세** — HTTP 메서드, 경로, 인증, rate limit, request/response 스키마
10. **SDK / 공개 인터페이스** — public API surface, 버전 호환성

### 3.3 갭 분석 체크리스트

Phase 2에서 적용하는 체크리스트. 각 항목에 점수를 매긴다.

**점수 체계:**
- **충족 (3점)**: 해당 정보가 구체적이고 측정 가능하게 정의됨
- **부분 충족 (2점)**: 정보는 있으나 모호하거나 불완전
- **미충족 (1점)**: 해당 정보 없음
- **해당 없음 (N/A)**: 프로젝트 특성상 불필요

**product-spec 체크리스트:**

| # | 항목 | 기준 |
|---|------|------|
| 1 | 문제 정의 | 해결하는 문제가 구체적으로 서술되었는가 |
| 2 | 유저 플로우 | 모든 유저 액션에 대한 시스템 반응이 step-by-step으로 정의되었는가 |
| 3 | 에러 패스 | 해피 패스 외에 에러 시나리오가 유형별로 정의되었는가 |
| 4 | 데이터 스키마 | API/함수의 request/response 타입이 정의되었는가 |
| 5 | 에러 처리 | 에러 조건, 사용자 메시지, 복구 동작이 테이블로 정의되었는가 |
| 6 | 성능 기준 | 측정 가능한 수치가 최소 1개 이상 명시되었는가 |
| 7 | 의존성 | 다른 기능/모듈과의 의존 관계가 명시되었는가 |
| 8 | Non-Goals | 명시적으로 하지 않을 것이 정의되었는가 |

**web-app 추가 체크리스트:**

| # | 항목 | 기준 |
|---|------|------|
| 9 | UI 상태 | 로딩/빈/에러 상태의 화면이 각각 정의되었는가 |
| 10 | 상태 관리 | state shape와 데이터 흐름이 정의되었는가 |
| 11 | 접근성 | 키보드 네비게이션과 ARIA 기본 요구사항이 정의되었는가 |

**아키텍처 체크리스트:**

| # | 항목 | 기준 |
|---|------|------|
| 1 | 기술 선택 근거 | 각 기술에 대한 선택 이유와 버린 대안이 있는가 |
| 2 | 디렉토리 구조 | 실제 파일 경로로 구조가 명시되었는가 |
| 3 | 데이터 흐름 | 핵심 시나리오의 요청→응답 흐름이 다이어그램으로 있는가 |
| 4 | 데이터 모델 | 엔티티별 필드, 타입, 제약조건, 관계가 테이블로 있는가 |

**미충족/부분 충족 시 행동:**

- 미충족 (1점): 사용자에게 AskUserQuestion으로 질문. 선택지 제시 + "어떻게 할까?" 형태
- 부분 충족 (2점): 구체화 방향을 제안하고 사용자 확인. "이렇게 구체화하면 될까?"
- 모든 항목이 충족 (3점) 또는 해당 없음 (N/A): 다음 Phase 자동 진행

### 3.4 품질 검토 기준 (Phase 4)

Phase 4에서 생성된 전체 docs/를 검증하는 기준:

**문서 간 정합성:**
- product-spec에서 정의한 API가 data-model.md의 엔티티와 일치하는가
- ARCHITECTURE.md의 디렉토리 구조가 AGENTS.md의 Directory Map과 일치하는가
- design-docs/ 간에 모순되는 정의가 없는가

**표현 품질:**
- "적절한", "필요시", "충분한" 같은 모호한 표현이 없는가
- "TBD", "추후 작성", "TODO" 단독 사용이 없는가
- 측정 가능한 수치가 사용되었는가 (px, ms, 개수 등)

**구조 완전성:**
- AGENTS.md의 Directory Map이 실제 파일 구조와 일치하는가
- design-docs/index.md와 product-specs/index.md가 실제 파일과 일치하는가
- 모든 GUIDE 주석이 삭제되었는가

**점수 산출:**
- 각 product-spec의 체크리스트 점수 평균
- 아키텍처 체크리스트 점수
- 문서 간 정합성 통과/실패
- 이 결과를 QUALITY_SCORE.md에 기록

---

## 4. 에러 처리

### 입력 문서가 너무 얕은 경우

갭 분석에서 미충족 항목이 전체의 50% 이상이면 경고:
"입력 문서에 정보가 너무 부족합니다. Cowork에서 더 상의한 후 다시 시도하시거나, 기존 meta 모드를 사용해보세요."

### 프로젝트 타입 판별 실패

입력 문서에서 프로젝트 타입을 유추할 수 없으면 사용자에게 직접 질문:
"이 프로젝트의 타입이 뭔가요? (web-app / api / cli / library / mobile)"

### 파일 쓰기 실패

대상 프로젝트 디렉토리에 쓰기 권한이 없으면:
"프로젝트 폴더에 쓰기 권한이 없습니다. 폴더를 마운트해주세요." → request_cowork_directory 호출

### exec-plan 형식 검증

Phase 5에서 생성한 exec-plan이 plan_parser.py로 파싱되는지 검증:
- Chunk 헤더 정규식 매칭 확인
- Completion Criteria 체크박스 형식 확인
- Session Prompt 비어있지 않은지 확인
- 실패 시 자동 수정 후 재검증 (최대 3회)

---

## 5. 미결정 사항

- [ ] 스킬 이름 확정: `docs-restructurer` vs `project-setup` vs 다른 이름
- [ ] docs/generated/ 폴더를 중간 산출물 저장소로 쓸지, 다른 위치를 쓸지
- [ ] 갭 분석 체크리스트를 SKILL.md에 인라인할지, 별도 파일로 분리할지
- [ ] exec-plan 생성 시 청크 크기를 스킬이 자동 판단할지, 사용자에게 물어볼지
