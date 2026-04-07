# Planning V2.1 — Revised Design Spec

**Date**: 2026-04-07
**Status**: Draft
**Author**: Yeonsu + Codex
**Revises**: `docs/specs/2026-04-06-planning-v2-design.md`

---

## 1. 목표

이 문서는 `2026-04-06-planning-v2-design.md`를 **보존한 상태로**, 1차 구현에 바로 들어갈 수 있도록
빠진 계약을 닫는 후속 설계다.

이번 리비전의 목적은 다섯 가지다.

1. `AI Decisions`를 단순 태그가 아니라 **사람도 읽기 쉽고, 후속 planning도 다시 활용할 수 있는 구조화된 기록**으로 바꾼다.
2. `Phase 5 review step`이 현재 완료 감지 구조에서 허위 완료되지 않도록 **전용 산출물 계약**을 추가한다.
3. `output-formats.md`를 변경 계획에 포함해, prompt와 reference가 같은 규약을 보도록 만든다.
4. `provisional` plan의 생명주기를 명시해, "남은 provisional이 있는데도 done" 같은 애매한 종료를 막는다.
5. batch cap 초과 시 어떻게 합치고, 무엇을 미루고, 어떤 plan을 `provisional`로 내릴지 **결정 규칙**을 명시한다.

이 문서는 현재 Claude Desktop / Cowork interactive planning 경로의 1차 구현 기준 문서다.
Codex CLI planning mode 자체는 여전히 직접 구현 범위가 아니다.

---

## 2. 비목표

- docs-orchestrator 전체 rewrite는 하지 않는다.
- 기존 `Phase 0~4`를 갈아엎지 않는다.
- `exec-plan` 최종 파서 규격 자체를 깨는 변경은 하지 않는다.
- `AI Decisions`를 위해 별도 JSON 산출물 파일을 추가하지 않는다.
- 첫 구현에서 다중 wave를 무한 반복하도록 만들지 않는다.

---

## 3. 핵심 의사결정 요약

### 3.1 유지할 것

- `Phase 0~4` 큰 흐름 유지
- `gap-report -> docs 생성 -> quality review -> exec-plan` 유지
- `docs/generated/exec-plan-outline.md` 유지
- 최종 `exec-plan` 파서 계약 유지

### 3.2 새로 추가할 것

- `## AI Decisions` 섹션을 gap-report에 추가
- `phase_5_outline_review`, `phase_5_detail_review` 전용 산출물 추가
- `phase_5_wave_replan:{wave_id}`와 `phase_5_blocked` 상태 추가
- outline 메타데이터에 `priority_class` 추가
- `skills/docs-orchestrator/references/output-formats.md` 개정 작업을 구현 범위에 포함

### 3.3 V2.1의 강한 기본값

- `AI Decisions`는 **섹션 추가 + `[AI_DECISION]` 태그 유지**
- `provisional` plan은 첫 구현에서 **부분 detail 금지**
- `done`은 **모든 plan이 locked + detailed 상태일 때만 허용**
- 남은 provisional이 있으면 `wave`를 한 번 더 시도하고, 그래도 남으면 `phase_5_blocked`로 종료

---

## 4. 아키텍처 개요

### 4.1 Phase 2 — Scope Completion + Structured Decisions

`Phase 2`는 단순 gap analysis가 아니라 다음 두 책임을 가진다.

1. 제품 골격 누락 탐지
2. AI가 대신 결정한 항목을 재활용 가능한 형식으로 기록

이를 위해 gap-report는 다음 섹션을 가진다.

- `## Coverage Summary`
- `## Product Completeness`
- `## Routing & Role Flow`
- `## AI Decisions`
- `## Open Questions`

### 4.2 Phase 5 — Revised state machine

V2.1의 상태 전이는 다음과 같다.

1. `phase_5_outline`
2. `phase_5_outline_review`
3. `phase_5_detail_batch:{batch_id}` 반복
4. `phase_5_detail_review`
5. provisional이 없으면 `done`
6. provisional이 있고 `wave` 잔여 횟수가 있으면 `phase_5_wave_replan:{wave_id}`
7. wave에서 새로 locked 된 plan에 대해 `phase_5_detail_batch:{batch_id}` 반복
8. 다시 `phase_5_detail_review`
9. 여전히 provisional이 남으면 `phase_5_blocked`

### 4.3 Review step 완료 계약

현재 orchestrator는 "기대 산출물 존재 + DONE marker"로 완료를 판정한다.
따라서 review step은 기존 파일 inline 수정만으로 끝내면 안 된다.

각 review step은 다음 전용 산출물을 반드시 생성한다.

- `phase_5_outline_review`
  - `docs/generated/phase5-outline-review.md`
- `phase_5_detail_review`
  - `docs/generated/phase5-detail-review.md`
- `phase_5_wave_replan:{wave_id}`
  - `docs/generated/phase5-wave-{wave_id}.md`
- `phase_5_blocked`
  - `docs/generated/phase5-blockers.md`

review step은 outline이나 plan 파일을 inline 수정할 수 있다. 다만 **완료 판정은 전용 review report 파일**로 한다.

---

## 5. 기술적 세부사항

### 5.1 AI Decisions 계약

V2.1에서 `AI Decisions`는 사람용 섹션이지만, 기존 파서 호환을 위해 각 항목의 첫 줄은 반드시
`[AI_DECISION]`으로 시작한다.

규칙:

- `[AI_DECISION]` 태그는 `## AI Decisions` 섹션에서만 사용한다.
- 각 decision은 1개 항목 = 1개 기록이다.
- 각 기록은 다음 필드를 반드시 가진다.

필수 필드:

- `decision`
- `rationale`
- `affects`
- `risk`
- `revisit_trigger`
- `confidence`

권장 필드:

- `lock_impact`
  - `keeps-locked`
  - `forces-provisional`
  - `unlock-candidate`

예시:

```md
## AI Decisions

- [AI_DECISION] 로그인 후 기본 리디렉션은 `/dashboard`로 둔다
  - Rationale: 공통 진입점이 먼저 필요하고 역할별 홈은 아직 미확정
  - Affects: auth, dashboard, routing
  - Risk: 역할별 홈 요구가 확정되면 변경 필요
  - Revisit Trigger: role entry point 정책 확정 시
  - Confidence: 0.62
  - Lock Impact: forces-provisional
```

이 방식의 목적은 두 가지다.

- 사람은 `## AI Decisions`만 읽어도 가정과 위험을 빠르게 파악할 수 있다.
- 기존 `generate_gap_summary()`와 테스트는 계속 `[AI_DECISION]` 태그 수를 세어 backward compatible 하게 동작한다.

### 5.2 Phase 2 체크리스트 강화

`checklists.md`에는 기존 completeness 범주 외에 다음 평가 의도를 분명히 넣는다.

- 제품 골격 누락 탐지용 항목
- 사람이 답해야 하는 정책 항목
- AI가 가정해도 되는 항목
- 가정 시 `AI Decisions`에 반드시 남겨야 하는 항목

즉 체크리스트는 "무엇이 빠졌는가"만 보지 않고, "빠졌을 때 어디에 기록되어야 하는가"까지 지시해야 한다.

### 5.3 Phase 5 outline metadata

`exec-plan-outline.md`의 plan table은 다음 필드를 가진다.

| # | 파일명 | 범위 | rough_size | dependency | confidence | priority_class | lock_status | detail_batch | notes |
|---|--------|------|------------|------------|------------|----------------|-------------|--------------|-------|
| 1 | 01-foundation.md | scaffold, auth shell, base data model | M | - | 0.88 | P0 | locked | 01 | 초기 구현 가능 |
| 2 | 02-dashboard.md | role dashboard, redirects, nav | L | 01 | 0.58 | P1 | provisional | - | role policy 의존 |

필드 의미:

- `rough_size`: `S | M | L`
- `dependency`: 선행 plan 번호 목록
- `confidence`: 0.0~1.0
- `priority_class`: `P0 | P1 | P2`
- `lock_status`: `locked | provisional`
- `detail_batch`: 배정된 batch id, 미배정이면 `-`

`priority_class` 정의:

- `P0`: foundation, auth shell, routing shell, base data model, role entry, 공통 layout
- `P1`: 핵심 사용자 플로우, 주요 dashboard, 핵심 CRUD
- `P2`: admin, analytics, optional integration, polish, 후순위 운영 기능

`confidence`와 `priority_class`는 다른 값이다.
중요하지만 불확실한 plan은 `P0 + low confidence`일 수 있다.

### 5.4 Phase 5 입력 강화

outline/wave 재계획은 index만 읽고 끝내지 않는다.
다음 입력을 읽도록 prompt를 강화한다.

- `docs/generated/gap-reports/_summary.md`
- AI 결정 수가 많거나 `Open Questions`가 있는 gap-report
- `docs/QUALITY_SCORE.md`
- 필요한 경우 role/routing 관련 product-spec 본문 일부

목적은 다음과 같다.

- `confidence`를 근거 있게 판단
- `provisional` 판정이 gap-report의 unresolved assumption과 연결되게 함
- wave 재계획이 실제 새 정보에 반응하게 함

### 5.5 output-formats.md 개정 범위

V2.1에서는 `output-formats.md` 변경을 **필수 구현 범위**로 본다.

이유:

- `phase5_outline`과 `phase5_detail` prompt가 실제로 이 reference를 다시 읽는다.
- 코드만 바꾸고 reference를 안 바꾸면 모델이 계속 구형 per-plan 상세 형식을 따를 수 있다.

`skills/docs-orchestrator/references/output-formats.md`에는 최소 다음 변경이 들어가야 한다.

1. `exec-plan-outline.md` V2 테이블 형식
2. `priority_class`, `lock_status`, `detail_batch` 의미
3. batch detail 작성 규칙
4. review report 형식
5. `provisional`은 final exec-plan 파일을 만들지 않는다는 규칙
6. final exec-plan parser compatibility 규칙은 기존처럼 유지

prompt read contract도 바꾼다.

- `phase5_outline.j2`
  - outline format subsection을 읽음
- `phase5_detail.j2` 또는 `phase5_detail_batch.j2`
  - final exec-plan parser subsection + batch rules를 읽음
- `phase5_outline_review.j2`
  - outline metadata rules + overflow resolution rules를 읽음
- `phase5_detail_review.j2`
  - final exec-plan parser rules + review report rules를 읽음

### 5.6 Batch formation 규칙

batch는 다음 규칙으로 만든다.

- `locked` plan만 batch 대상
- dependency 순서 유지
- `phase5_detail_batch_max_plans` 이하
- `rough_size = L`은 단독 batch 우선
- 동일 batch 안의 plan은 dependency frontier를 넘지 않아야 함

추천 기본값:

- `phase5_max_detail_sessions = 2`
- hard cap `3`
- `phase5_detail_batch_max_plans = 3`

### 5.7 Cap overflow 해소 규칙

outline review는 "cap를 넘는가"만 말하고 끝나면 안 된다.
반드시 아래 순서로 해소한다.

#### 1단계: batch 재패킹

가능한 한 dependency를 보존한 채 batch를 다시 묶는다.

- `S` 또는 `M` plan을 같은 batch에 최대치까지 채움
- `L`은 단독 batch 유지

#### 2단계: outline merge

여전히 cap를 넘으면, 다음 조건을 모두 만족하는 인접 `S` plan만 merge 후보로 본다.

- 둘 다 `locked`
- dependency 집합이 동일
- `priority_class`가 동일
- 둘 다 cross-cutting foundation plan이 아님

첫 구현에서는 `S + S`만 merge 허용한다.
`M` 또는 `L` merge는 범위를 키우므로 금지한다.

#### 3단계: provisional downgrade

여전히 cap를 넘으면 일부 locked plan을 provisional로 내린다.
downgrade 순서는 다음 우선순위를 따른다.

1. `priority_class`: `P2` 먼저, 그다음 `P1`, 마지막 `P0`
2. `confidence`: 낮은 값 먼저
3. `rough_size`: 큰 값 먼저 (`L > M > S`)
4. dependency depth: 깊은 값 먼저

추가 강제 규칙:

- `P0` plan은 제품 방향 미확정이나 외부 정책 충돌이 없는 한 provisional로 내리지 않는다.
- provisional로 내린 이유는 `phase5-outline-review.md`에 반드시 기록한다.
- `detail_batch`에서 빠진 plan은 `notes`에 `deferred-to-wave`를 남긴다.

#### 4단계: wave defer

cap 안으로 들어왔지만 provisional이 남았다면, 남은 plan은 다음 wave의 후보가 된다.

### 5.8 Provisional / wave 생명주기

`provisional` plan은 다음 상태 전이를 따른다.

1. outline에서 provisional로 분류
2. initial detail batch에서는 제외
3. `phase_5_detail_review` 후 wave 재평가 대상으로 이동
4. `phase_5_wave_replan:{wave_id}`에서 다음 입력을 읽고 재판정
   - 선행 locked plan 결과
   - 관련 docs 수정분
   - relevant gap-report
   - prior review report
5. `locked`로 승격되면 다음 batch detail 대상이 됨
6. 끝까지 lock 불가면 `phase_5_blocked`

첫 구현의 강한 규칙:

- provisional plan은 부분 detail 금지
- outline-only 상태로 남겨둘 수는 있으나 `done`으로 종료할 수는 없다

### 5.9 done / blocked 판정

`done` 조건:

- 모든 plan이 `locked`
- 모든 plan file이 생성됨
- 마지막 `phase_5_detail_review` 통과
- `phase5-detail-review.md`에 blocker 없음

`phase_5_blocked` 조건:

- `phase5_max_waves` 소진 후에도 provisional이 남음
- 또는 `ask-human`이 필요한 targeted 질문이 남음

`phase_5_blocked` 산출물에는 다음을 기록한다.

- 남은 provisional 목록
- 왜 lock이 안 되는지
- 필요한 질문 또는 추가 입력
- 다음 wave에서 무엇을 읽어야 하는지

---

## 6. Config 스키마

### 6.1 신규 필드

```toml
[docs_orchestrator]
planning_profile = "autonomous"
initial_question_policy = "critical-only"   # manual | critical-only | never
wave_question_mode = "ai-decide"            # ask-human | ai-decide
plan_depth = "full-project"                 # full-project | master+wave
phase5_max_detail_sessions = 2              # default 2, hard cap 3
phase5_detail_batch_max_plans = 3
phase5_max_waves = 1
```

### 6.2 기본 정책

V2.1 첫 구현 기본값:

- `planning_profile = "autonomous"`
- `initial_question_policy = "critical-only"`
- `wave_question_mode = "ai-decide"`
- `phase5_max_detail_sessions = 2`
- `phase5_detail_batch_max_plans = 3`
- `phase5_max_waves = 1`

### 6.3 backward compatibility

- V2.1 필드가 없으면 legacy 동작 유지
- V2.1 필드가 있으면 V2.1 state machine 우선
- `[AI_DECISION]` 태그 count 기반 summary는 그대로 유지

---

## 7. 파일별 변경 계획

| 파일 | 변경 내용 |
|------|-----------|
| `src/cowork_pilot/docs_orchestrator.py` | `phase_5_outline_review`, `phase_5_detail_batch`, `phase_5_detail_review`, `phase_5_wave_replan`, `phase_5_blocked` 상태 추가 |
| `src/cowork_pilot/orchestrator_state.py` | Phase 5 expected outputs, session estimate, blocked 상태 계산 보강 |
| `src/cowork_pilot/orchestrator_prompts.py` | 새 prompt template mapping 추가 |
| `src/cowork_pilot/orchestrator_templates/phase2_auto.j2` | structured `AI Decisions` 섹션 강제 |
| `src/cowork_pilot/orchestrator_templates/phase2_manual.j2` | structured `AI Decisions` 섹션 강제 |
| `src/cowork_pilot/orchestrator_templates/phase3_product_spec.j2` | `Product Completeness`, `Routing & Role Flow`, `AI Decisions` RE-READ 강화 |
| `src/cowork_pilot/orchestrator_templates/phase3_design_docs.j2` | completeness / routing / `AI Decisions` RE-READ 강화 |
| `src/cowork_pilot/orchestrator_templates/phase4_rescore.j2` | completeness 누락과 routing 충돌 재검사 강화 |
| `src/cowork_pilot/orchestrator_templates/phase5_outline.j2` | V2 outline metadata + review handoff 전제 반영 |
| `src/cowork_pilot/orchestrator_templates/phase5_outline_review.j2` | outline review 전용 prompt 추가 |
| `src/cowork_pilot/orchestrator_templates/phase5_detail.j2` 또는 `phase5_detail_batch.j2` | batch detail prompt로 전환 |
| `src/cowork_pilot/orchestrator_templates/phase5_detail_review.j2` | detail review 전용 prompt 추가 |
| `src/cowork_pilot/orchestrator_templates/phase5_wave_replan.j2` | wave 재계획 prompt 추가 |
| `skills/docs-orchestrator/references/checklists.md` | product completeness + AI decision recording guidance 추가 |
| `skills/docs-orchestrator/references/output-formats.md` | outline V2, batch rules, review report rules, parser compatibility 섹션 개정 |
| `src/cowork_pilot/config.py` | `phase5_max_waves` 포함 신규 config 필드 추가 |
| `tests/test_docs_orchestrator.py` | 새 state machine, review outputs, wave/block path 테스트 추가 |
| `tests/test_orchestrator_prompts.py` | 새 template read contract 테스트 추가 |
| `tests/test_orchestrator_state.py` | expected outputs, estimate, blocked state 테스트 추가 |
| `tests/test_config.py` | 신규 config load 테스트 추가 |

---

## 8. 구현 순서

### 8.1 Step 0 — Codex execution audit

기존 문서의 audit step은 유지한다.
review/completion 지시가 실제로 먹히는지 먼저 확인한다.

### 8.2 Step 1 — Phase 2 structured AI Decisions

목표:

- gap-report에 `AI Decisions` 섹션 도입
- `[AI_DECISION]` 태그 유지
- decision 기록이 이후 wave 입력으로 재사용 가능하게 함

완료 조건:

- phase2 prompt가 structured decision 형식을 강제
- summary parser 기존 테스트 통과
- gap-report 예시가 새 형식을 만족

### 8.3 Step 2 — references 개정

목표:

- `checklists.md`와 `output-formats.md`를 V2.1 규약에 맞춤

완료 조건:

- phase5 prompt가 읽는 reference가 구형 규약을 남기지 않음
- outline format, batch rules, review report format이 reference에 명시됨

### 8.4 Step 3 — Phase 5 state machine 개편

목표:

- review 전용 산출물 추가
- batch detail 반복 구조 도입

완료 조건:

- `phase_5_outline_review` 지원
- `phase_5_detail_review` 지원
- detail step 완료가 review report와 충돌하지 않음

### 8.5 Step 4 — overflow + wave lifecycle

목표:

- cap overflow 해소 규칙과 wave/block lifecycle 구현

완료 조건:

- locked plan overflow 시 deterministic downgrade/merge 수행
- provisional이 남으면 wave 또는 blocked로 이동
- provisional이 남은 채 `done`되지 않음

### 8.6 Step 5 — config + compatibility

목표:

- 신규 config 필드 추가
- legacy path 보존

완료 조건:

- config load 테스트 통과
- V2.1 필드 미설정 시 기존 동작 유지

---

## 9. 에러 처리와 리스크

### 9.1 Risk: review step 허위 완료

대응:

- review step마다 전용 report 파일 생성
- 완료 판정은 review report 기준

### 9.2 Risk: AI Decisions 과도한 추측

대응:

- 모든 결정에 `Rationale`, `Risk`, `Revisit Trigger`, `Confidence` 강제
- `Lock Impact`로 provisional 여부를 드러냄

### 9.3 Risk: reference drift

대응:

- `output-formats.md` 변경을 필수 작업으로 명시
- prompt read contract와 reference subsection을 같이 업데이트

### 9.4 Risk: provisional이 끝없이 남음

대응:

- `phase5_max_waves = 1`
- 끝까지 lock 불가하면 `phase_5_blocked`
- `done` 조건을 엄격히 유지

### 9.5 Risk: overflow 규칙이 foundation plan을 밀어냄

대응:

- `priority_class` 도입
- `P0` downgrade 금지 규칙 추가

---

## 10. 미결정 사항

- `priority_class`를 사람이 직접 쓰게 할지, outline prompt가 자동 추정하게 할지
- `phase5_max_waves`를 1로 고정할지, config로만 열어둘지
- `phase_5_blocked`에서 `ask-human` targeted question을 별도 step으로 분리할지

현재 기본 판단:

- `priority_class`는 outline prompt가 먼저 제안하고 review가 수정
- `phase5_max_waves = 1`
- `phase_5_blocked`는 report 생성 후 targeted question으로 이어질 수 있게 설계

---

## 11. 결론

V2.1은 Planning V2의 방향을 유지하되, 실제 구현에서 바로 문제가 될 계약 누락을 닫는 리비전이다.

핵심은 다섯 가지다.

1. `AI Decisions`를 구조화하되 `[AI_DECISION]` 태그는 유지한다.
2. review step은 전용 산출물로 완료를 판정한다.
3. `output-formats.md` 개정을 구현 범위에 포함한다.
4. cap overflow는 merge + downgrade + wave defer 규칙으로 해소한다.
5. provisional이 남은 채 `done`으로 끝나지 않게 한다.

이 문서의 성공 기준은 다음이다.

1. 제품 골격 누락이 Phase 2에서 더 일찍 드러난다.
2. Phase 5 세션 수는 cap 안에서 제어된다.
3. reference와 prompt가 같은 포맷을 읽는다.
4. 남은 provisional은 `done`이 아니라 `wave` 또는 `blocked`로 명확히 드러난다.
