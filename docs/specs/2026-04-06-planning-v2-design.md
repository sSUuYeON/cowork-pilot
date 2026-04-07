# Planning V2 — Design Spec

**Date**: 2026-04-06
**Status**: Draft
**Author**: Yeonsu + Codex

---

## 1. 목표

이 문서는 **현재 기준의 docs-orchestrator planning 경로**, 즉 Claude Desktop / Cowork interactive planning 흐름을 개선하는 설계다. 현재 Codex CLI는 exec-plan Chunk 실행 경로가 중심이며, **Codex CLI planning mode 자체는 이 문서의 직접 구현 범위에 포함되지 않는다**. 이 문서는 이후 Codex CLI planning mode를 설계할 때 재사용할 기준 문서로도 사용한다.

현재 docs-orchestrator planning의 핵심 문제는 세 가지다.

1. **기획 누락**: 랜딩, 대시보드, 설정, 프로필, 로그인 후 리디렉션, 롤별 진입점, 페이지 간 이동 같은 "당연한 제품 골격"이 자주 빠진다.
2. **Phase 5 과분해**: plan 수와 chunk 수가 실제 프로젝트 경계보다 템플릿 습관에 끌린다. 결과적으로 `11개 plan / 50개 chunk` 같은 과잉 분해 경향이 생긴다.
3. **후반 품질 저하**: 대규모 프로젝트에서 뒤 plan일수록 detail 품질이 낮아지거나 날림이 된다.

Planning V2의 목표는 다음과 같다.

- 초기 planning에서 제품 뼈대를 더 많이 확정한다.
- 이후 구현은 AI가 사람 개입 없이 가능한 만큼 계속 진행한다.
- Phase 5를 재설계해 "전체 outline은 잡되, 모든 plan을 동일 강도로 즉시 상세화하지 않는 구조"로 바꾼다.
- 기존 Phase 0~4와 테스트 자산은 최대한 유지하고, 문제가 집중된 지점만 선택적으로 재구성한다.

---

## 2. 비목표

- docs-orchestrator 전체 rewrite는 하지 않는다.
- `superpowers`를 직접 연동하지 않는다. 철학은 참고하되 auto mode는 cowork-pilot 고유 경로로 유지한다.
- 새로운 planning 시스템을 만들기 위해 산출물 파일을 무분별하게 늘리지 않는다.
- Codex auto mode에서 "실제 스킬 실행"을 전제로 설계하지 않는다. review/completion은 하네스 내장 workflow로 본다.
- Codex CLI planning mode 구현은 이번 문서의 직접 범위가 아니다. 현재 문서는 Claude Desktop / Cowork planning 경로를 먼저 정리한다.

---

## 3. 핵심 의사결정 요약

### 3.1 유지할 것

- `Phase 0~4` 전체 흐름은 유지한다.
- `gap-report -> docs 생성 -> quality review -> exec-plan`이라는 큰 파이프라인은 유지한다.
- `exec-plan-outline.md` 파일은 유지한다.

### 3.2 바꿀 것

- `Phase 2`를 단순 gap analysis가 아니라 **Scope Completion** 단계로 강화한다.
- `Phase 5`를 **outline -> self-review -> detail batch -> self-review** 구조로 바꾼다.
- `phase_5_detail:{plan_name}` 식의 무제한 per-plan fan-out을 없애고, **batch 단위 detail 세션**으로 바꾼다.
- `exec-plan-outline.md`에 `rough_size`, `dependency`, `confidence`, `lock_status`, `detail_batch` 메타데이터를 추가한다.

### 3.3 Planning 질문 정책

Planning V2는 질문을 두 시점으로 분리한다.

- **초기 질문 (`initial`)**
  - 프로젝트 뼈대를 확정하기 위한 질문
  - 예: 롤, 핵심 플로우, 리디렉션, 정책, 공개/비공개 페이지
- **wave 질문 (`wave`)**
  - 재계획 중 새 충돌이나 unlock 실패가 생겼을 때의 예외 질문

Wave 질문은 두 모드를 지원한다.

- `ask-human`
  - wave에서 판단이 막히면 사람에게 질문
- `ai-decide`
  - wave 질문도 AI가 자체 판단하고 재계획

초기 질문은 많이, 이후 wave 질문은 최소화하는 것이 기본 방향이다.

### 3.4 Planning depth

- `full-project`
  - 초기 planning에서 전체 프로젝트 outline을 한 번에 생성
  - 단, 모든 plan을 즉시 같은 깊이로 detail하지는 않음
- `master+wave`
  - master outline만 먼저 고정하고 detail은 앞 wave 중심으로 진행

V2의 첫 구현 목표는 `full-project`를 더 똑똑하게 만드는 것이다.

---

## 4. 아키텍처 개요

### 4.1 현재 구조

현재 docs-orchestrator는 대략 다음 흐름이다.

- Phase 0: setup
- Phase 1: source analysis
- Phase 2: gap analysis
- Phase 3: docs generation
- Phase 4: quality/consistency review
- Phase 5: outline 1회 + plan별 detail 세션 반복

문제는 마지막 단계다. 현재 `Phase 5-detail`은 outline에 있는 plan 수만큼 세션이 늘어난다.

### 4.2 V2 구조

Planning V2에서 실제 상태 전이 구조는 다음과 같다.

1. `phase_5_outline`
2. `phase_5_outline_review`
3. `phase_5_detail_batch:{batch_id}` 반복
4. `phase_5_detail_review`

여기서 핵심은 `batch_id` 기반이다. detail 세션 수는 plan 수가 아니라 **batch 수**에 비례한다.

### 4.3 Phase 5 세션 상한

V2는 다음 상한을 둔다.

- `phase_5_outline`: 1세션
- `phase_5_outline_review`: 1세션
- `phase_5_detail_batch:*`: 기본 2세션, hard cap 3세션
- `phase_5_detail_review`: 1세션

즉 기본적으로 **총 4세션**, 많아도 **총 5세션** 안에서 끝내는 것을 목표로 한다.

---

## 5. Phase 2 — Scope Completion 강화

### 5.1 삽입 위치

Product completeness 체크는 `Phase 2`에 넣는다.

이유:

- 이 단계의 본질이 "빠진 요구사항을 찾고 보완하는 것"이기 때문
- docs를 다 쓴 뒤에 잡으면 이미 후행 문서와 plan이 왜곡된다
- 사람이 답할 질문도 이 단계에 몰아주는 편이 이후 자동 진행에 유리하다

역할 분담:

- `Phase 2`: 탐지 + 보완 결정
- `Phase 3`: 문서화
- `Phase 4`: 누락/충돌 재검사

### 5.2 새 체크리스트 범주

`checklists.md`에 다음 범주를 추가한다.

1. **Page Inventory**
   - 메인 랜딩
   - 로그인/회원가입
   - 대시보드
   - 설정
   - 프로필
   - 관리자/운영 페이지
2. **Routing & Redirect**
   - 로그인 전 기본 진입점
   - 로그인 후 리디렉션
   - 권한 부족 시 이동
   - 온보딩 후 이동
3. **Role Entry Point**
   - 역할별 홈 화면
   - 역할별 네비게이션 차이
4. **User Flow Coverage**
   - 해피 패스
   - 오류 패스
   - 취소/되돌리기 플로우
5. **State Coverage**
   - loading
   - empty
   - error
   - forbidden / not-found
6. **Global Product Skeleton**
   - 공통 레이아웃
   - 글로벌 navigation
   - 알림/프로필 드롭다운 등 공통 진입점

### 5.3 gap-report 출력 구조 변경

각 기능별 gap-report 또는 bundle gap-report에는 다음 섹션을 포함한다.

- `## Coverage Summary`
- `## Product Completeness`
- `## Routing & Role Flow`
- `## AI Decisions`
- `## Open Questions`

`AI Decisions`는 별도 파일로 분리하지 않고 gap-report 내부에 기록한다.

### 5.4 질문 정책

`Phase 2`에서 빠진 항목을 만났을 때 처리 방식:

- `initial_question_policy = manual`
  - 중요 항목은 사람에게 질문
- `initial_question_policy = critical-only`
  - 핵심 정책/충돌만 질문, 나머지는 AI가 메움
- `initial_question_policy = never`
  - 전부 AI가 메움

AI가 메우는 경우에도 반드시 다음을 남긴다.

- 가정
- 근거
- 리스크
- 추후 뒤집힐 가능성

### 5.5 Phase 3/4로의 전파

`Phase 3` prompt는 기존처럼 gap-report를 RE-READ하되, 다음 섹션을 반드시 반영하도록 강화한다.

- `Product Completeness`
- `Routing & Role Flow`
- `AI Decisions`

`Phase 4`는 다음을 재검사한다.

- page inventory 누락
- role/flow 충돌
- redirect 불일치
- spec/architecture 사이의 충돌

---

## 6. Phase 5 — Outline V2

### 6.1 산출물 원칙

새 파일 `master-plan.md`를 추가하지 않는다.

대신 `docs/generated/exec-plan-outline.md`가 다음 두 역할을 모두 가진다.

1. 전체 master outline
2. plan별 detail 메타데이터

### 6.2 outline 메타데이터

`exec-plan-outline.md`의 plan 테이블을 다음처럼 확장한다.

| # | 파일명 | 범위 | rough_size | dependency | confidence | lock_status | detail_batch | notes |
|---|--------|------|------------|------------|------------|-------------|--------------|-------|
| 1 | 01-foundation.md | scaffold, auth shell, base data model | M | - | 0.86 | locked | 01 | 초기 구현 가능 |
| 2 | 02-dashboard.md | role dashboard, redirects, nav | L | 01 | 0.58 | provisional | - | auth 결과 의존 |

필드 의미:

- `rough_size`: `S | M | L`
- `dependency`: 선행 plan 번호 목록
- `confidence`: 0.0~1.0
- `lock_status`: `locked | provisional`
- `detail_batch`: detail 세션에서 어느 batch가 담당하는지

### 6.3 locked / provisional 판정 기준

`locked`:

- 선행 의존성이 없거나 이미 설계상 안정적
- 요구사항과 플로우가 비교적 명확
- 지금 detail해도 재작업 리스크가 낮음

`provisional`:

- 다른 plan 결과에 의해 구조가 크게 바뀔 수 있음
- 정책/플로우/권한 결정이 아직 유동적
- 지금 detail하면 추측 비중이 높음

### 6.4 Outline self-review

`phase_5_outline_review`는 outline을 다시 읽고 다음을 검토한다.

1. plan 수가 과한가
2. 너무 큰 plan이 있는가
3. 불필요하게 쪼개진 plan이 있는가
4. provisional이어야 할 plan이 locked로 잘못 분류되었는가
5. detail batch 수가 cap를 넘는가
6. outline이 실제 dependency 순서를 반영하는가

이 단계에서 plan table을 inline 수정한다.

### 6.5 detail batch 구조

`phase_5_detail:{plan_name}`를 다음으로 바꾼다.

- `phase_5_detail_batch:01`
- `phase_5_detail_batch:02`
- `phase_5_detail_batch:03` (필요 시만)

각 batch 세션은 **여러 plan 파일을 한 번에** 작성할 수 있다.

배치 규칙:

- `locked` plan만 batch에 포함
- dependency 순서 유지
- batch당 최대 plan 수는 config로 제한
- `L` 사이즈 plan은 단독 batch 허용
- provisional plan은 batch에 넣지 않음

### 6.6 detail batch prompt 원칙

detail batch prompt는 다음을 강제한다.

- 해당 batch에 속한 plan 목록을 명시
- 각 plan file을 planning 디렉토리에 실제로 저장
- Session Prompt는 chunk별로 작성
- Completion Criteria는 기계적 검증 가능해야 함
- 이미 outline에 있는 dependency / lock 정보를 훼손하지 말 것

### 6.7 detail self-review

`phase_5_detail_review`는 모든 생성된 plan 파일을 읽고 다음을 검토한다.

1. parser로 읽히는가
2. chunk 크기가 과도하지 않은가
3. Completion Criteria가 주관적이지 않은가
4. outline의 lock/dependency와 detail 내용이 충돌하지 않는가
5. provisional plan이 잘못 상세화되지 않았는가

### 6.8 provisional 승격 규칙

provisional plan은 다음 wave에서 다시 평가한다.

승격 경로:

1. 선행 dependency 완료
2. docs/구현 결과 재읽기
3. AI 재평가
4. `locked`로 승격되면 다음 batch detail 대상이 됨

여전히 lock 불가이면:

- `wave_question_mode = ask-human`
  - 사람에게 targeted 질문
- `wave_question_mode = ai-decide`
  - AI가 가정과 근거를 남기고 안전한 범위까지만 detail
  - 단, 제품 방향 충돌이 크면 escalation

---

## 7. Config 스키마

### 7.1 신규 필드

`DocsOrchestratorConfig`에 다음 필드를 추가한다.

```toml
[docs_orchestrator]
planning_profile = "autonomous"
initial_question_policy = "critical-only"   # manual | critical-only | never
wave_question_mode = "ai-decide"            # ask-human | ai-decide
plan_depth = "full-project"                 # full-project | master+wave
phase5_max_detail_sessions = 2              # default 2, hard cap 3
phase5_detail_batch_max_plans = 3
```

### 7.2 프리셋 정책

V2 첫 구현에서는 `planning_profile = "autonomous"`만 실제 동작 대상으로 삼는다.

의미:

- 초기 planning은 사람 질문을 가능한 적게 유지
- 누락은 AI_DECISION으로 메움
- wave 질문도 기본은 `ai-decide`
- 전체 프로젝트 outline은 처음에 생성

향후 확장:

- `manual`
- `hybrid`

### 7.3 backward compatibility

기존 `docs_mode = auto | manual`는 당장 제거하지 않는다.

전환 원칙:

- V2 필드가 없으면 기존 동작 유지
- V2 필드가 있으면 V2 우선

---

## 8. 파일별 변경 계획

| 파일 | 변경 내용 |
|------|-----------|
| `src/cowork_pilot/docs_orchestrator.py` | Phase 5 state machine을 outline review / detail batch / detail review 구조로 변경. Phase 2 prompt wiring도 completeness 강화에 맞춰 수정 |
| `src/cowork_pilot/orchestrator_state.py` | Phase 5 추정 로직과 expected output 계산 보강. batch step 지원 |
| `src/cowork_pilot/orchestrator_templates/phase2_manual.j2` | Product completeness, routing, AI_DECISION 지시 추가 |
| `src/cowork_pilot/orchestrator_templates/phase2_auto.j2` | Product completeness, routing, AI_DECISION 지시 추가 |
| `src/cowork_pilot/orchestrator_templates/phase3_product_spec.j2` | completeness / routing / AI_DECISION 섹션 RE-READ 강제 |
| `src/cowork_pilot/orchestrator_templates/phase3_design_docs.j2` | completeness / routing / AI_DECISION 섹션 RE-READ 강제 |
| `src/cowork_pilot/orchestrator_templates/phase4_rescore.j2` | completeness 누락과 routing 충돌 재검사 추가 |
| `src/cowork_pilot/orchestrator_templates/phase5_outline.j2` | lock_status, confidence, dependency, detail_batch 포함 outline 포맷으로 변경 |
| `src/cowork_pilot/orchestrator_templates/phase5_detail.j2` | per-plan detail이 아니라 batch detail prompt로 변경 |
| `skills/docs-orchestrator/references/checklists.md` | product completeness 체크리스트 추가 |
| `src/cowork_pilot/config.py` | 신규 planning V2 config 필드 추가 |
| `tests/test_docs_orchestrator.py` | 새 Phase 5 step, batch parsing, completeness prompt wiring 테스트 추가 |
| `tests/test_codex_harness.py` | code-review / chunk-complete 인라인 workflow가 실제로 먹히는지 검증 강화 |

---

## 9. 구현 순서

### 9.1 Step 0 — Codex execution audit

먼저 다음을 확인한다.

- `_harness_prompt_builder()`가 review/complete 지시를 제대로 넣는가
- Codex가 실제로 이를 수행하는가
- verify 단계가 plan 상태를 올바르게 읽는가
- 실패 원인이 prompt wording인지, verify mismatch인지

완료 조건:

- 최소 1개의 대표 실패 케이스에 대해 root cause가 문서화됨

### 9.2 Step 1 — Phase 2 completeness 강화

목표:

- 당연한 페이지/플로우/리디렉션 누락을 Phase 2에서 잡는다

완료 조건:

- gap-report 프롬프트에 completeness 범주가 포함됨
- Phase 3 prompt가 이를 RE-READ함
- Phase 4가 completeness 누락을 재검사함

### 9.3 Step 2 — Phase 5 outline V2

목표:

- outline에 plan 메타데이터를 넣고 locked/provisional 판정을 가능하게 한다

완료 조건:

- outline parser가 새 메타데이터를 읽을 수 있음
- `_determine_next_step()`가 `phase_5_outline_review`를 지원함

### 9.4 Step 3 — detail batch 도입

목표:

- per-plan detail fan-out을 batch 단위로 치환

완료 조건:

- `phase_5_detail_batch:{id}` step 지원
- 기본 2세션, hard cap 3세션 이하 유지
- detail 세션 하나가 여러 plan file을 만들 수 있음

### 9.5 Step 4 — config + compatibility

목표:

- V2 config 필드 추가
- 기존 config와 충돌 없이 동작

완료 조건:

- config load 테스트 통과
- V2 필드가 없을 때 legacy path 유지

---

## 10. 리스크와 대응

### 10.1 Risk: Phase 5가 여전히 과도하게 커질 수 있음

대응:

- `phase5_max_detail_sessions` cap
- `rough_size = L` plan 단독 batch
- provisional 유지 허용

### 10.2 Risk: completeness 체크리스트가 또 다른 과설계가 될 수 있음

대응:

- 새 파일을 만들지 않고 gap-report와 existing docs에 흡수
- Phase 2에서만 탐지, Phase 3/4는 propagation과 recheck만 담당

### 10.3 Risk: auto mode에서 AI가 과도하게 추측할 수 있음

대응:

- `AI Decisions` 섹션 강제
- wave escalation mode 분리
- cross-cutting contradiction은 escalation

### 10.4 Risk: Codex review/completion이 계속 불안정할 수 있음

대응:

- 먼저 audit
- prompt-inline 전략을 공식 전략으로 인정
- 필요 시 verify와 prompt wording 동시 보정

---

## 11. Open Questions

- `planning_profile = autonomous`의 초기 질문 강도를 `critical-only`로 둘지, `manual`에 더 가깝게 둘지
- detail batch의 plan 수 상한을 2로 둘지 3으로 둘지
- provisional plan을 wave에서 "부분 detail"까지 허용할지, lock 전에는 outline-only로 둘지

현재 판단:

- 첫 구현은 `critical-only`, `phase5_max_detail_sessions = 2`, provisional은 "안전한 범위의 부분 detail 허용"으로 시작한다.

---

## 12. 결론

Planning V2는 새 planning 시스템을 갈아엎는 작업이 아니다. 기존 docs-orchestrator를 유지한 채,

- `Phase 2`를 Scope Completion으로 강화하고
- `Phase 5`를 lock-aware batch planning으로 재구성하고
- `Codex auto mode`는 스킬이 아니라 하네스 내장 workflow로 다루는

선택적 재설계다.

이 설계의 성공 기준은 세 가지다.

1. planning 초기에 제품 기본 골격 누락이 줄어든다
2. Phase 5 세션 수가 상한 안에서 제어된다
3. 후반 plan일수록 날림이 되는 현상이 줄어든다
