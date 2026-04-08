# Planning Runtime Handoff — Design Spec

**Status:** Proposed
**Date:** 2026-04-08
**Author:** User + Codex

## 1. Overview

본 문서는 `Planning Engine V3`의 10단계 planning core 위에서 실제 Codex CLI 세션을 어떻게 운영할지 정의한다.

핵심 목표는 다음과 같다.

- `exec` 자동 실행과 `cli` 상호작용 실행을 같은 planning run 안에서 연결한다.
- 질문이 필요한 경우 자연어 질문 감지가 아니라 `structured marker protocol`을 사용한다.
- 세션 경계는 토큰 고갈 시점이 아니라 미리 정의된 `stage session profile`에 따라 결정한다.
- 질문은 항상 현재 stage 세션을 `resume`해서 처리하고, 해결 후 다시 자동 실행으로 복귀할 수 있게 한다.

이 문서는 `docs/superpowers/specs/2026-04-07-planning-engine-v3-design.md`를 대체하지 않는다. 대신 그 위에서 planning run을 실제로 구동하는 런타임 계약을 정의한다.

## 2. Relationship to Planning Engine V3

유지되는 것은 `Planning Engine V3`의 기본 10단계다.

1. `Project Classification`
2. `Core Docs Check`
3. `Adaptive Docs Selection`
4. `Core Docs Presence Review`
5. `Product Completeness Review`
6. `Scope Structuring`
7. `Work Sizing`
8. `Plan Packing`
9. `Plan Review`
10. `Exec-Plan Authoring`

본 문서는 위 10단계를 바꾸지 않는다. 바꾸는 것은 다음뿐이다.

- 각 단계 안에서 질문/가정/승인을 어떻게 표현할지
- `exec -> interactive CLI resume -> exec resume` handoff를 어떻게 관리할지
- 각 단계를 몇 개 세션으로 나눌지

즉, planning의 뼈대는 V3가 정의하고, 세션/질문/자동응답의 런타임은 본 문서가 정의한다.

## 3. Execution Surfaces

V1에서 고려하는 실행 표면은 두 개다.

- `source=exec`
  - 백그라운드 non-interactive 실행
  - 사용자 입력 직접 수신 불가
  - 자동 진행과 최종 결과 수집에 적합
- `source=cli`
  - interactive CLI 실행
  - 사용자 입력 수신 가능
  - 질문/승인/예외 처리에 적합

`Codex Desktop`은 나중에 고려한다.

## 4. Core Runtime Principles

### 4.1 Default Mode + Structured Marker Protocol

질문이 필요한지 알아내기 위해 자연어를 추론하지 않는다.

대신 agent는 `default mode`에서 다음 중 하나가 필요할 때 반드시 구조화 마커를 출력한다.

- 입력 필요
- 가정 기록
- 승인 필요
- 단계 완료
- 인간 개입 필요

### 4.2 No Mid-Stream Parsing

부분 출력은 읽지 않는다.

- `assistant turn 완료 후`에만 파싱한다
- `최종 완료 응답`만 본다
- `그 turn의 메시지 tail에 붙은 마지막 contiguous top-level event bundle`만 유효하다

이 규칙은 생각 중에 예시로 마커를 언급하거나, 중간 토큰에 불완전한 마커가 나와도 오작동하지 않게 하기 위한 것이다.

### 4.3 Session Boundaries Are Pre-Planned

세션은 컨텍스트가 다 차서 끊지 않는다.

- 세션 범위는 stage 또는 substage 단위로 미리 정의한다
- 질문이 생기면 해당 세션을 `resume`한다
- 다음 세션은 계획된 stage 경계에서만 연다

즉, 세션은 `정해진 작업 단위`를 담는 그릇이고, 질문은 그 그릇 안에서 해결한다.

## 5. External Mode Model

외부에 노출되는 decision mode는 3개로 유지한다.

- `interactive`
- `hybrid`
- `auto`

추가 모드를 외부에 늘리지 않는다.

## 6. Internal Policy Knobs

실제 동작 차이는 mode 이름이 아니라 내부 정책으로 제어한다.

- `question_strategy`
- `assumption_scope`
- `approval_policy`
- `phase_strategy`

### 6.1 Default Policy Values

기본값은 다음과 같다.

- `question_strategy = front_loaded`
- `assumption_scope = broad_product_design`
- `approval_policy = final_draft_only`
- `phase_strategy = question_heavy_then_auto`

추가 규칙:

- `interactive`는 `approval_policy = section_approval`를 기본 override로 둔다
- `hybrid`는 기본값을 그대로 사용한다
- `auto`는 질문 임계치를 더 높이고 blocking이 아닌 질문은 최대한 assumption으로 흡수한다

### 6.2 Meaning of Each Policy

`question_strategy = front_loaded`

- planning 초반 단계에서 질문을 집중시킨다
- 후반 단계는 원칙적으로 자동 처리한다
- 후반 질문은 `blocker` 또는 `high-risk`일 때만 허용한다

`assumption_scope = broad_product_design`

- AI는 페이지 구성, 기본 유저플로우, 역할별 기본 기능, 기본 권한 모델, 기본 아키텍처 방향까지 적극 설계할 수 있다
- 단, 다음은 assumption으로 확정하지 않는다
  - 비용이 바로 발생하는 실행 결정
  - 실제 외부 서비스 실연결
  - irreversible migration
  - 보안/compliance에 직접 영향을 주는 실행 결정

`approval_policy = final_draft_only`

- 중간 단계는 자동으로 진행한다
- 최종 draft spec 또는 planning 결과물에서만 사람 승인을 받는다

`phase_strategy = question_heavy_then_auto`

- 초기 단계는 질문과 설계 고정에 집중한다
- 후기 단계는 이미 고정된 문서를 바탕으로 자동 처리 비중을 높인다

## 7. Structured Marker Protocol

### 7.1 Marker Types

V1 marker 종류는 5개로 시작한다.

- `INPUT_REQUIRED`
- `ASSUMPTION_LOG`
- `APPROVAL_REQUIRED`
- `STAGE_COMPLETE`
- `NEEDS_HUMAN`

### 7.2 Wire Format

마커 형식은 `custom tag + YAML body`다.

```text
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-login-redirect-001
reason: Default redirect decision blocks downstream flows.
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
  - onboarding
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
```

V1은 `한 turn = 정확히 하나의 marker`로 제한하지 않는다.

- 기본 원칙은 `ordered event bundle` 허용이다
- 한 turn 안에서 여러 marker가 필요하면, 메시지 tail에 연속된 top-level marker bundle을 둘 수 있다
- 대표 허용 조합은 `ASSUMPTION_LOG -> STAGE_COMPLETE`다
- 반대로 marker 사이에 일반 설명 텍스트가 끼어들거나 순서가 뒤집히면 bundle 전체를 무효로 본다

### 7.3 Recognition Rules

마커는 다음 규칙을 모두 만족할 때만 유효하다.

- `assistant turn 완료 후`에만 파싱
- `메시지 tail의 마지막 contiguous top-level ordered marker bundle`만 유효
- 코드블록 안 marker는 무시
- begin/end tag가 모두 있어야 함
- 필수 필드가 없으면 무효
- bundle 안 marker 순서는 실제 event 순서를 반영해야 함
- bundle 앞쪽의 일반 설명 텍스트는 허용되지만, bundle 내부에 일반 설명 텍스트가 끼어들면 무효

V1 기본 허용 bundle:

- `ASSUMPTION_LOG -> STAGE_COMPLETE`
- `ASSUMPTION_LOG -> APPROVAL_REQUIRED`
- `ASSUMPTION_LOG -> NEEDS_HUMAN`

### 7.4 Required Fields

공통 필수 필드:

- `type`
- `stage`
- `event_id`
- `reason`

`INPUT_REQUIRED` 필수 필드:

- `question`
- `options`
- `recommended`
- `blocking`

`ASSUMPTION_LOG` 필수 필드:

- `assumption`
- `confidence`
- `impact`

`APPROVAL_REQUIRED` 필수 필드:

- `subject`
- `proposed_decision`
- `blocking`

`STAGE_COMPLETE` 필수 필드:

- `summary`
- `outputs`

`NEEDS_HUMAN` 필수 필드:

- `issue`
- `why_ai_stopped`
- `suggested_next_action`

## 8. Marker Semantics by Source

### 8.1 `source=exec`

`exec`에서는 사용자 입력을 받을 수 없다.

따라서:

- `INPUT_REQUIRED(blocking=true)`가 나오면 run을 `waiting_for_input`으로 전환한다
- `INPUT_REQUIRED(blocking=false)`가 나오면 질문을 queue에 기록하고 현재 stage는 assumption 기반으로 계속 진행할 수 있다
- `APPROVAL_REQUIRED(blocking=true)`가 나오면 run을 `waiting_for_approval`로 전환한다
- `NEEDS_HUMAN`이 나오면 즉시 `escalated`로 전환한다

추가 규칙:

- `blocking=false INPUT_REQUIRED`를 assumption으로 흘려보냈다가, 이후 stage 또는 review에서 그 assumption이 틀렸다고 판명될 수 있다
- 이 경우 V1도 silent overwrite를 허용하지 않는다
- 최소 `assumption invalidated` 기록을 남기고, run은 `waiting_for_human`으로 전환해야 한다
- 이때 reason은 다음 중 하나로 남긴다
  - `stage_reopen_required`
  - `replan_required`
- full automatic replan은 later optimization으로 미뤄도 되지만, 현재 run을 계속 진행시키지는 않는다
- owner는 V1에서 `상위 orchestrator 또는 사람 운영자`다
- runtime의 책임은 invalidation 감지, 기록, `waiting_for_human` 전환, affected stage 표시까지다

### 8.2 `source=cli`

`cli`에서는 interactive 응답이 가능하다.

따라서:

- `INPUT_REQUIRED`는 interactive answer loop로 이어진다
- `APPROVAL_REQUIRED`는 사용자 승인 프롬프트로 이어진다
- `ASSUMPTION_LOG`는 문서화 후 계속 진행한다

## 9. Handoff Model

### 9.1 Basic Flow

기본 handoff는 다음 순서를 따른다.

1. `exec` stage session 실행
2. blocking marker 감지
3. run state를 `waiting_for_input` 또는 `waiting_for_approval`로 고정
4. 같은 `resume_handle`을 `codex resume --include-non-interactive <resume_handle>`로 interactive CLI에서 연다
5. 질문/승인 해결
6. 같은 `resume_handle`을 `codex exec resume <resume_handle> ...`로 다시 non-interactive 실행에 복귀시킨다

즉, 질문 때문에 새 대화가 생기는 것이 아니라, 같은 세션을 표면만 바꿔 이어간다.

### 9.1.1 Resume Handle Contract

runtime state는 surface-specific 식별자를 직접 노출하지 않고 다음 추상 필드를 저장한다.

- `resume_handle`
- `resume_handle_kind`
- `surface`
- `stage`
- `substage`

V1 Codex 구현 기본값:

- `resume_handle_kind = codex_thread_id`
- `resume_handle = <thread_id>`

즉 현재 구현 현실은 `thread_id`가 사실상 resume key로 동작하지만, runtime 계약은 `resume_handle` 추상화 위에 쌓인다.

### 9.2 What Is Resumed vs What Is Reopened

질문 해결은 항상 `resume`이다.

- 같은 stage 안에서 질문이 발생하면 현재 stage 세션을 그대로 이어간다
- 질문 응답을 위해 새로운 planning stage 세션을 만들지 않는다

새 세션은 stage 또는 substage 전환에서만 연다.

### 9.3 No Implicit Mid-Phase Surface Switch

중간에 surface를 즉석에서 갈아끼우는 방식으로 보지 않는다.

정확한 의미는:

- `exec` run은 일단 멈춘다
- interactive CLI가 같은 세션을 resume한다
- 입력 해결 후 다시 `exec resume`으로 이어간다

즉, 구현 관점에서는 handoff이고, 사용자 경험 관점에서는 같은 대화가 이어지는 것이다.

## 10. Run State Machine

Planning run의 최소 상태는 다음과 같다.

- `pending`
- `running_exec`
- `running_cli`
- `waiting_for_input`
- `waiting_for_approval`
- `waiting_for_human`
- `completed`
- `failed`
- `escalated`

### 10.1 Required Transitions

- `pending -> running_exec`
- `running_exec -> waiting_for_input`
- `running_exec -> waiting_for_approval`
- `running_exec -> waiting_for_human`
- `waiting_for_input -> running_cli`
- `waiting_for_approval -> running_cli`
- `running_cli -> running_exec`
- `running_exec -> completed`
- `running_exec -> failed`
- `running_cli -> escalated`
- `running_exec -> waiting_for_human` when a later review invalidates a non-blocking assumption
- `completed -> waiting_for_human` when post-completion validation discovers `stage_reopen_required` or `replan_required`

### 10.2 Failure Policy

V1 기본값은 다음과 같다.

- 자동응답 실패 시 즉시 인간에게 넘긴다
- 파싱 실패나 invalid marker는 재시도보다 `NEEDS_HUMAN`에 가깝게 본다
- later optimization으로 기술적 재시도 횟수를 늘릴 수 있지만, V1 기본은 보수적으로 간다

추가 규칙:

- non-blocking assumption이 뒤늦게 invalidated 되면, V1은 silent overwrite를 금지한다
- 최소 `assumption invalidated` 기록과 `affected stage` 표시는 남겨야 한다
- 그 다음 동작은 `waiting_for_human` 전환이다
- reason은 `stage_reopen_required` 또는 `replan_required`로 남긴다
- V1에서 이 상황의 owner는 `상위 orchestrator 또는 사람 운영자`이며, runtime은 감지하고 멈추는 역할을 맡는다

## 11. Stage Session Profile Matrix

세션 경계는 stage별 `session profile`로 미리 정의한다. 컨텍스트가 다 찼기 때문에 세션을 자르는 방식은 금지한다.

### 11.1 Matrix

`Project Classification`

- `small`: 1 session
- `medium`: 2 planned sessions
  - `classification-input-audit`
  - `classification-synthesis`
- `large`: 2 planned sessions
  - `classification-input-audit`
  - `classification-synthesis`

`Brownfield Code Observation Extraction` (`brownfield_code_observation_extraction`)

- `small`: 1-2 planned sessions by lightweight slice
- `medium`: multiple planned sessions by domain/module bundle
- `large`: explicit planned sessions by code slice

`Brownfield Observation Synthesis` (`brownfield_observation_synthesis`)

- 기본 1 synthesis session

`Brownfield Gap Synthesis` (`brownfield_gap_synthesis`)

- 기본 1 synthesis session

`Core Docs Check`

- 기본 1 session

`Adaptive Docs Selection`

- 기본 1 session

`Core Docs Presence Review`

- 기본 1 session

`Product Completeness Review`

- `small`: 1 session
- `medium`: 2 planned sessions
  - `user-facing completeness`
  - `ops/nonfunctional completeness`
- `large`: 3 planned sessions
  - `pages-and-flows`
  - `roles-and-permissions`
  - `ops-integrations-nfr`

`Scope Structuring`

- `small`: 1 session
- `medium`: 2 planned sessions by domain group
- `large`: multiple planned sessions by work domain bundle

`Work Sizing`

- scope bundles를 그대로 따른다
- size reasoning은 same bundle에서 처리한다

`Plan Packing`

- 기본 1 synthesis session
- `large`에서 top-level plan families가 많으면 2-stage packing 허용
  - `packing-draft`
  - `packing-synthesis`

`Plan Review`

- 항상 최소 2 planned sessions
  - `coverage-and-sizing`
  - `executionability-and-overdesign`

`Exec-Plan Authoring`

- 기본 1 session
- `large`에서는 top-level plan group별 authoring 후 final synthesis 허용

### 11.2 Brownfield Artifact Ownership and Completion

`Brownfield Code Observation Extraction` (`brownfield_code_observation_extraction`)

- artifact owner: 각 extraction session
- completion artifact: `code-observations/<slice>.md`
- completion predicate: 파일 존재 + `<!-- ORCHESTRATOR:DONE -->` 마커 존재
- resume target: 현재 slice extraction session
- next consumer: `Brownfield Observation Synthesis`

`Brownfield Observation Synthesis` (`brownfield_observation_synthesis`)

- artifact owner: synthesis session
- completion artifact: `implementation-observation-summary.md`
- completion predicate: 파일 존재 + `<!-- ORCHESTRATOR:DONE -->` 마커 존재
- resume target: synthesis session
- next consumer: `Brownfield Gap Synthesis`

`Brownfield Gap Synthesis` (`brownfield_gap_synthesis`)

- artifact owner: gap synthesis session
- completion artifact: `spec-implementation-gap.md`, `change-impact-gap.md`
- completion predicate: 두 파일 모두 존재 + 각 파일에 `<!-- ORCHESTRATOR:DONE -->` 마커 존재
- resume target: gap synthesis session
- next consumer: `Scope Structuring`

Brownfield pre-analysis 상태 흐름:

`classification-synthesis -> brownfield_code_observation_extraction[*] -> brownfield_observation_synthesis -> brownfield_gap_synthesis -> core_docs_check`

### 11.3 Bundle Logic

`docs-orchestrator`에서 가져올 아이디어:

- single session
- grouped session
- bundled session
- quality degradation 시 bundle 해제

하지만 줄 수 기반 분할은 기본 기준으로 쓰지 않는다.

대신 bundle 기준은 다음을 우선한다.

- 도메인 경계
- 역할 경계
- 운영 경계
- 외부 연동 경계
- review 독립성

## 12. Stage-Level Question Policy

각 stage는 질문 강도가 다르다.

질문이 많이 나올 수 있는 stage:

- `Project Classification`
- `Adaptive Docs Selection`
- `Product Completeness Review`
- `Scope Structuring`
- `Plan Review`

질문이 원칙적으로 적어야 하는 stage:

- `Core Docs Check`
- `Core Docs Presence Review`
- `Work Sizing`
- `Plan Packing`
- `Exec-Plan Authoring`

즉, `front_loaded`는 planning 초반과 구조 결정 단계에 질문을 집중시키는 전략이다.

## 13. Brainstorming Pattern Integration

`brainstorming`을 planning core의 대체물로 쓰지 않는다.

적용 방식은 다음과 같다.

- 10단계 workflow는 유지
- 질문 형식은 `brainstorming` 패턴을 참고
  - 한 번에 질문 1개
  - 선택지 우선
  - 추천안 + 이유 포함
  - 답변/가정 기록
- `Product Completeness Review`, `Scope Structuring`, Greenfield 초기 설계 채우기에는 stronger brainstorming pattern을 적용
- 나머지 단계는 `lite brainstorming`만 적용

즉, planning 뼈대는 V3, 질문 UX와 reasoning style은 brainstorming 참고라는 관계다.

## 14. Brownfield Delta Artifact Usage

Brownfield의 `spec-implementation-gap.md`는 기록용 문서가 아니라 다음 단계 입력이다.

흐름:

1. 기존 spec 읽기
2. 현재 코드/동작 읽기
3. `spec-implementation-gap.md` 생성
4. 차이를 분류
   - `spec outdated`
   - `implementation missing`
   - `intentional divergence`
   - `undocumented behavior`
5. `change-impact-gap.md` 생성
6. `Scope Structuring`이 이를 work item으로 번역
7. `Work Sizing`과 `Plan Review`가 이를 읽고 반영

즉, Brownfield planning은 문서와 현실의 어긋남을 묻어두지 않고 explicit artifact로 드러낸다.

## 15. Consequences

이 설계를 따르면 다음이 가능해진다.

- `exec` 자동 실행 중 질문이 나와도 interactive CLI로 안전하게 handoff 가능
- 같은 세션을 끊지 않고 `exec <-> cli` 왕복 가능
- 세션 경계가 토큰 고갈이 아니라 stage 설계에 의해 결정됨
- planning run이 질문, 가정, 승인, delta artifact를 명시적으로 기록함
- `brainstorming`과 `subagent-driven-development`의 장점을 V3에 내장할 수 있는 기반이 생김

이 설계는 아직 DB/UI 구현을 포함하지 않는다. V1 목표는 런타임 계약을 고정하고, 그 계약 위에 실제 cowork-pilot 오케스트레이터를 구현할 수 있게 만드는 것이다.
