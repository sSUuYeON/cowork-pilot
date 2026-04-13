# Docs-Orchestrator Codex Phase 5 Shared Outline — Design Spec

> 작성일: 2026-04-14
> 상태: Draft
> 범위: `docs-orchestrator`의 Codex 실행 경로에만 적용되는 Phase 5 재설계

---

## 1. 목표

이 문서는 `docs-orchestrator`의 Phase 5를 다음 기준으로 재설계한다.

1. 최종 canonical outline 산출물은 항상 `docs/generated/exec-plan-outline.md` 한 파일이다.
2. outline 포맷은 기존과 동일하게 유지한다.
   - `## exec-plan 개요` 표
   - `## 01-xxx.md 상세` 섹션
   - 각 상세 섹션 아래 `Chunk / Completion Criteria / Tasks / Session Prompt(비워둠)`
3. outline은 one-shot 생성이 아니라 여러 세션이 점진적으로 보강한다.
4. 각 세션은 전체 spec/design-doc 본문을 다 읽지 않고, 담당 unit에 관련된 본문만 읽는다.
5. outline 품질 기준은 단순 spec coverage가 아니라 UI/E2E coverage다.
6. 첫 롤아웃은 Codex backend에만 적용하고, Claude 경로는 유지한다.

---

## 2. 비목표

- 기존 Claude 기반 Phase 5 동작을 이번 변경에 맞춰 같이 바꾸지 않는다.
- `feature-outlines/*.md`를 canonical 산출물로 되살리지 않는다.
- Phase 5 detail 단계의 최종 산출물 위치(`docs/exec-plans/planning/*.md`)는 이번 문서의 직접 변경 범위가 아니다.
- outline 포맷을 planning V2 metadata 테이블 형식으로 다시 확장하지 않는다.
- 모든 feature를 반드시 `1 feature = 1 plan`으로 강제하지 않는다.

---

## 3. 현재 코드 기준 확인된 사실

### 3.1 현재 Phase 5는 one-shot outline이다

- `src/cowork_pilot/docs_orchestrator.py`의 `_run_phase_5_outline()`는 단일 step `phase_5_outline`만 실행한다.
- `_determine_next_step()`는 `phase_5_outline` 완료 후 곧바로 `phase_5_detail:{plan_name}`로 넘어간다.
- 따라서 현재 구조에는 outline을 여러 세션이 분할 보강하는 상태 전이가 없다.

### 3.2 현재 outline prompt는 index-only 규칙이다

- `src/cowork_pilot/orchestrator_templates/phase5_outline.j2`는 공통 파일만 읽도록 지시한다.
- 같은 템플릿의 품질 규칙에는 `product-spec 본문이나 design-doc 본문은 읽지 않는다`가 명시되어 있다.
- 이는 이번 요구사항과 정면으로 충돌한다.

### 3.3 현재 Codex/Claude는 같은 phase 템플릿을 공유한다

- `docs_orchestrator.py`는 phase별 prompt를 `build_session_prompt()`로 생성한다.
- Codex backend는 `build_codex_session_prompt()` wrapper를 사용할 수 있지만, phase 본문 템플릿 이름 자체는 공통이다.
- 따라서 Codex 전용 rollout을 하려면 template 자체를 완전히 분리하기보다, Phase 5 step 분기와 prompt 인자 구성을 backend 기준으로 갈라야 한다.

### 3.4 outline detail prompt에는 관련 spec 주입 여지가 있지만 배선이 덜 되어 있다

- `phase5_detail.j2`는 `relevant_specs` 목록을 읽도록 준비되어 있다.
- 그러나 현재 `_run_phase_5_detail()`는 `relevant_specs`를 실제로 넘기지 않는다.
- 즉 문서 단위 입력 축소라는 방향은 일부 암시되어 있지만, Phase 5 전체 모델에는 아직 반영되어 있지 않다.

---

## 4. 최종 설계 요약

Codex 경로에서만 Phase 5를 아래 상태 머신으로 바꾼다.

1. `phase_5_outline_unit:{unit_id}` 반복
2. `phase_5_outline_finalize`
3. `phase_5_detail:{plan_name}` 반복

여기서 핵심은 다음 두 가지다.

- outline 작성의 단일 source of truth는 항상 `docs/generated/exec-plan-outline.md`
- plan numbering과 최종 정렬/DONE marker 기록은 마지막 `phase_5_outline_finalize`가 담당

Claude 경로는 기존대로 유지한다.

1. `phase_5_outline`
2. `phase_5_detail:{plan_name}` 반복

---

## 5. Outline Unit 모델

### 5.1 unit 정의

Phase 5 outline 세션의 최소 작업 단위는 `unit`이다.

지원 unit 종류:

- `feature` unit
  - 기본 단위
  - 각 `product-spec` 본문 1개를 기준으로 생성
- `domain` unit
  - 같은 도메인 안에서 여러 feature가 공유하는 흐름, 진입점, 정책, 설정, 전역 상태 수렴 경로가 있을 때만 추가
- `global` unit
  - 랜딩, 역할별 첫 진입, 전역 리디렉션, 앱 공통 navigation, invalid/closed/deleted 이후 수렴 경로 등 특정 feature 하나에 귀속시키면 책임이 흐려지는 항목을 담당

기본 원칙:

- `1 feature = 1 plan`은 절대 규칙이 아니다.
- 그러나 `1 feature = 1 plan 후보`처럼 취급한다.
- 명백히 같은 구현 흐름이 아니면 plan을 합치지 않는다.
- 애매하면 분리하고 dependency로 연결한다.

### 5.2 unit 생성 규칙

Codex 경로의 Phase 5는 다음 순서로 outline unit dispatch를 만든다.

1. `global` unit 1개를 먼저 추가한다.
2. `product-specs/index.md`에 나온 각 spec에 대해 `feature` unit 1개를 추가한다.
3. `analysis-report.md`와 `_overview.md` 존재 여부를 보고, 도메인 공통 맥락이 실제로 있는 도메인에 한해 `domain` unit을 추가한다.

중복 방지 규칙:

- `domain` unit은 feature 본문만으로 충분히 커버 가능한 경우 만들지 않는다.
- `global` unit은 항상 하나만 존재한다.

---

## 6. 세션별 입력 계약

모든 `phase_5_outline_unit:*` 세션은 아래 공통 파일을 항상 읽는다.

- `docs/generated/references/output-formats.md`
- `docs/design-docs/index.md`
- `docs/product-specs/index.md`
- `docs/ARCHITECTURE.md`
- `docs/QUALITY_SCORE.md`
- `docs/generated/analysis-report.md`
- 현재까지의 `docs/generated/exec-plan-outline.md`가 있으면 그 파일

그리고 unit 종류별로 추가 입력을 읽는다.

### 6.1 feature unit

- 담당 `product-spec` 본문 1개
- 해당 feature와 실제로 관련 있는 `design-doc` 본문
- 필요하면 같은 도메인의 `_overview.md`

### 6.2 domain unit

- 그 도메인의 관련 `product-spec` 본문들
- 도메인 공통 정책/흐름을 설명하는 관련 `design-doc` 본문
- 같은 도메인의 `_overview.md`가 있으면 반드시 읽음

### 6.3 global unit

- 랜딩, role entry, redirect, settings/admin shell, error/invalid/deleted convergence를 설명하는 관련 `design-doc` 본문
- 필요한 범위의 `product-spec` 본문 일부

입력 축소 원칙:

- 한 세션에서 모든 spec/design-doc 본문을 읽지 않는다.
- 관련성 없는 본문은 읽지 않는다.
- index는 목록/탐색용이고, 실제 outline 책임 결정은 본문 근거로 한다.

---

## 7. Shared Outline 수정 규칙

각 `phase_5_outline_unit:*` 세션은 `docs/generated/exec-plan-outline.md`를 직접 수정한다.

오케스트레이터의 완료 감지는 DONE marker를 전제로 하므로, 각 unit 세션도 현재 snapshot 파일의 마지막 줄에
`<!-- ORCHESTRATOR:DONE -->`를 유지해야 한다. finalize는 이 marker를 다시 확인하고 정규화된 최종 outline을 기록한다.

허용되는 수정:

1. 새 plan 후보 추가
2. 기존 plan의 범위 설명 보강
3. 기존 plan에 chunk 추가
4. 기존 chunk의 Completion Criteria 구체화
5. 기존 chunk의 Tasks 보강
6. dependency 보강
7. 전역 UX/redirect/예외 상태 책임을 새로운 독립 plan 또는 chunk로 드러내기

금지되는 수정:

1. 다른 unit이 이미 넣은 세부 구현 항목을 근거 없이 삭제
2. 단순 plan 수 축소를 위해 서로 다른 구현 책임을 억지로 병합
3. 세부 action/route/state를 요약해 뭉개기
4. `Session Prompt`를 채우기

`Session Prompt`는 outline 단계에서 항상 아래 literal 값을 유지한다.

- `Session Prompt: (다음 세션에서 작성)`

---

## 8. Finalize 단계 계약

`phase_5_outline_finalize`는 outline 작성 세션이 모두 끝난 후 한 번 실행한다.

역할:

1. `exec-plan-outline.md` 전체를 다시 읽는다.
2. plan 후보를 최종 정렬한다.
3. plan 번호를 `01-...`, `02-...` 형식으로 재배치한다.
4. `## exec-plan 개요` 표와 plan별 상세 섹션의 파일명을 동기화한다.
5. dependency 번호를 재배치 후 번호 기준으로 정리한다.
6. 중복 섹션을 합치되, 세부 내용은 더 구체적인 쪽을 보존한다.
7. outline 마지막 줄에 `<!-- ORCHESTRATOR:DONE -->`를 기록한다.

Finalize의 비역할:

- 새 product/spec 본문을 대량 재독해하는 one-shot 회귀
- outline 세부사항 재압축
- feature 책임 삭제

Finalize는 정리와 정규화 단계이지, 재기획 단계가 아니다.

---

## 9. Quality 기준

outline 품질 기준은 `UI/E2E coverage`다. 다음 항목이 outline 어딘가의 plan/chunk 책임으로 드러나야 한다.

1. 랜딩 페이지
2. 역할별 첫 진입 화면
3. 전역 리디렉션 규칙
4. 설정/관리성 화면
5. 삭제 후 수렴 경로
6. 종료 후 수렴 경로
7. invalid 상태 후 수렴 경로
8. 화면에 보이는 버튼, 링크, 폼 액션
9. offline 상태
10. empty 상태
11. error 상태
12. invalid 상태
13. closed 상태
14. deleted 상태
15. 모든 라우트와 리디렉션 책임

완료 판정 규칙:

- outline에 등장하는 각 화면/행동/상태는 적어도 하나의 plan 또는 chunk 책임에 매핑되어야 한다.
- "보이는 기능은 있는데 구현 책임이 outline에 없다"는 상태가 남으면 finalize는 실패다.
- detail 단계는 outline 세부사항을 확장하는 단계이지, 누락된 제품 축을 새로 발명하는 단계가 아니다.

---

## 10. Codex 전용 rollout 전략

첫 구현은 Codex backend에서만 새 Phase 5를 활성화한다.

원칙:

1. canonical 파일 경로는 공통으로 유지한다.
2. outline markdown 포맷도 공통으로 유지한다.
3. 상태 전이 분기만 engine 기준으로 다르게 둔다.

구체 규칙:

- `orch_config.engine == "codex"`일 때만 outline unit fan-out + finalize 경로를 사용한다.
- 그 외 엔진은 기존 `phase_5_outline` 단일 세션 경로를 유지한다.

이유:

- rollout risk를 Codex 경로로 제한할 수 있다.
- Claude 회귀를 즉시 피할 수 있다.
- 이후 안정화가 끝나면 공통 Phase 5 모델로 승격할 수 있다.

---

## 11. 코드 변경 설계

### 11.1 `src/cowork_pilot/docs_orchestrator.py`

변경:

- `phase_5_outline` 단일 step 외에 Codex 전용 step family를 추가한다.
  - `phase_5_outline_unit:{unit_id}`
  - `phase_5_outline_finalize`
- `_determine_next_step()`에서 engine이 `codex`인 경우 위 step family를 사용한다.
- outline unit 생성 helper를 추가한다.
- unit별 prompt 인자를 계산하는 helper를 추가한다.

### 11.2 `src/cowork_pilot/orchestrator_templates/phase5_outline.j2`

변경:

- 기존 one-shot 전용 지시를 제거한다.
- "공통 파일 + 담당 본문 + 기존 shared outline"을 읽는 unit 세션 계약으로 바꾼다.
- `global/domain/feature` unit 유형을 prompt 인자로 주입받는다.
- `Session Prompt`를 비워 두라고 명시한다.
- UI/E2E coverage 체크리스트를 prompt에 포함한다.

주의:

- 이 템플릿은 Claude 경로에서도 계속 쓰이므로, Codex 전용 지시는 Python 쪽에서 step/args 분기로 해결한다.
- Claude 호환을 깨지 않기 위해 템플릿은 "unit-aware"가 되되, 단일 실행에도 동작해야 한다.

### 11.3 `src/cowork_pilot/orchestrator_state.py`

변경:

- 새 step 이름에 대한 output file 계약을 추가한다.
- `phase_5_outline_unit:*`와 `phase_5_outline_finalize`는 둘 다 `docs/generated/exec-plan-outline.md`를 산출물로 본다.
- recovery 로직이 shared outline 파일 존재 + DONE marker 유무를 올바르게 해석하도록 유지한다.

### 11.4 `tests/test_docs_orchestrator.py`

추가 테스트:

1. Codex engine일 때 `phase_5_outline_unit:global`이 첫 Phase 5 step으로 선택됨
2. feature unit들이 순서대로 fan-out됨
3. 모든 unit 완료 후 `phase_5_outline_finalize`가 선택됨
4. finalize 완료 후 `phase_5_detail:{first_plan}`로 넘어감
5. Claude engine일 때 기존 `phase_5_outline` 경로 유지

### 11.5 `tests/test_orchestrator_prompts.py`

추가 테스트:

1. `phase5_outline` prompt가 unit-aware 입력 목록을 렌더링함
2. 공통 파일 목록이 항상 포함됨
3. `Session Prompt: (다음 세션에서 작성)` 규칙이 포함됨
4. UI/E2E coverage 관련 키워드가 prompt에 포함됨

---

## 12. 구현 세부 결정

### 12.1 unit 순서

기본 실행 순서:

1. `global`
2. `feature` units
3. `domain` units
4. `phase_5_outline_finalize`

이 순서의 목적:

- 전역 구조와 진입/수렴 경로를 먼저 outline에 심는다.
- feature별 plan 후보를 세부 본문 근거로 추가한다.
- 마지막에 domain unit이 feature 간 공통 흐름을 보강한다.

### 12.2 plan 병합 기준

plan은 아래 조건을 모두 만족할 때만 병합한다.

1. 같은 사용자 흐름 안에서 구현된다.
2. 같은 라우트/상태/액션 책임을 공유한다.
3. 분리하면 오히려 구현 경계가 흐려진다.

위 조건 중 하나라도 애매하면 분리한다.

### 12.3 finalize numbering 전략

Finalize는 human-friendly stable numbering을 목표로 한다.

정렬 우선순위:

1. 전역 foundation / entry / redirect / shell
2. 핵심 사용자 flow
3. 설정 / 관리 / 운영
4. 예외 상태 처리 / cleanup / closure flow

이 규칙은 plan 수를 최소화하기 위한 정렬이 아니라, 구현 책임이 자연스럽게 읽히게 하기 위한 정렬이다.

---

## 13. 위험과 대응

### 13.1 shared outline 동시성 위험

여러 세션이 같은 파일을 수정하므로, 서로 독립 실행하면 충돌 가능성이 있다.

대응:

- docs-orchestrator는 outline unit을 순차 실행한다.
- 병렬 fan-out은 하지 않는다.

### 13.2 unit별 읽기 범위 판단 실패

관련 design-doc를 잘못 고르면 누락이 생길 수 있다.

대응:

- `design-docs/index.md` 기반으로 관련 문서를 좁히되, finalize에서 coverage hole을 다시 본다.
- `_overview.md`가 있는 도메인은 domain unit에서 한 번 더 보강한다.

### 13.3 Codex/Claude 경로 괴리

Codex만 새 모델을 쓰면 Phase 5 동작이 엔진별로 달라진다.

대응:

- canonical 파일과 포맷은 공통으로 유지한다.
- 상태 전이만 분기해 나중에 Claude 쪽을 따라오게 할 수 있게 한다.

---

## 14. 승인 후 구현 순서

1. state machine에 Codex 전용 Phase 5 step family 추가
2. outline unit 생성/입력 해석 helper 추가
3. `phase5_outline.j2`를 unit-aware prompt로 개정
4. 상태 복구/output file 계약 업데이트
5. Codex/Claude 분기 테스트 추가
6. 기존 pytest 전체 실행

---

## 15. self-review

- Placeholder 없음
- `feature-outlines/*.md`를 canonical로 되돌리는 경로 없음
- Codex 전용 rollout 규칙과 공통 canonical 파일 규칙이 충돌하지 않음
- outline 품질 기준이 spec coverage가 아니라 UI/E2E coverage로 명시됨
- finalize가 one-shot 회귀가 아니라 정규화 단계임을 명시함
