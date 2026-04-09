# Planning Stage-Oriented Session Orchestration — Design Spec

**Status:** Proposed
**Date:** 2026-04-09
**Author:** User + Codex

## 1. Overview

본 문서는 현재 `planning` 기본 경로의 one-shot 파이프라인을 대체할 stage-oriented orchestration을 정의한다.

핵심 목표는 다음과 같다.

- `docs-orchestrator`처럼 stage/substage 경계마다 새 Codex 세션을 열어 컨텍스트 압축을 피한다.
- 질문/승인 때문에 멈춘 경우에만 같은 stage 세션을 `resume`한다.
- 다음 stage는 항상 handoff 문서와 canonical docs만 읽고 새 세션에서 시작한다.
- `greenfield`와 `brownfield` 모두 명시적 입력 계약을 가지며, `brownfield`는 변경 요구를 구조화 문서로 정규화한다.
- runtime state와 handoff 문서를 source of truth로 두어 재시작, 상위 오케스트레이터 개입, GhostCTO 연계를 가능하게 한다.

본 문서는 `docs/superpowers/specs/2026-04-08-planning-runtime-handoff-design.md`의 런타임 계약을 활용하되, 그 위에 실제 stage orchestration 구조를 정의한다.

## 2. Design Principles

### 2.1 Session Boundaries Are Stage Boundaries

세션 경계는 토큰 고갈이나 컨텍스트 압축 시점이 아니라 `stage/substage`로 고정한다.

- AI-heavy stage 시작 시 새 `codex exec` 세션을 연다.
- stage 완료 후에는 같은 세션을 다음 stage로 재사용하지 않는다.
- 다음 AI-heavy stage는 무조건 새 세션에서 시작한다.

### 2.2 Resume Is Intra-Stage Only

`resume`은 예외적 handoff 수단이며, 같은 stage 내부 질문/승인 처리 용도로만 사용한다.

- `waiting_for_input`
- `waiting_for_approval`

위 두 상태에서만 기존 세션을 `resume`할 수 있다. stage가 완료되면 `resume`은 종료되고 다음 stage는 새 세션으로 넘어간다.

### 2.3 Documents, Not Sessions, Carry Context

세션은 실행 단위이고, 실제 컨텍스트 전달은 문서가 담당한다.

다음 stage는 repo 전체를 다시 읽지 않는다. 대신 다음 입력만 읽는다.

- input snapshot
- canonical docs
- 직전 stage handoff 문서
- 필요한 누적 decisions / answers / assumptions log

즉 세션은 버려도 문서는 버리지 않는다.

## 3. Execution Model

### 3.1 Mode Exposure

`project_mode`는 사용자에게 드러낸다.

- `--project-mode greenfield|brownfield`

자동 감지는 fallback으로만 남긴다.

- 사용자가 `--project-mode`를 명시하면 그 값을 사용한다.
- 명시가 없을 때만 자동 감지를 수행한다.
- 자동 감지 결과는 시작 로그에 명시적으로 출력한다.

### 3.2 Deterministic vs AI-Heavy Stages

모든 planning stage를 새 세션으로 열지 않는다. deterministic 단계는 로컬 Python에서 처리하고, 추론 중심 단계만 새 세션으로 연다.

로컬 Python 단계:

- input discovery
- project mode resolution
- document role mapping
- run bootstrap
- 상태 저장 / 파일 기록 / 검증
- 규칙형 sizing / packing

AI-heavy 단계:

- request normalization
- greenfield completeness review
- brownfield code observation extraction
- brownfield observation synthesis
- brownfield gap synthesis
- scope structuring
- plan review
- exec-plan authoring

이 구조는 비용과 latency를 줄이면서도, 추론이 긴 단계는 세션 분리로 안정화한다.

## 4. Input Contract

### 4.1 User-Facing Inputs

공통 입력:

- `--project-mode`
- `--request`
- `--request-file`

`brownfield` 추가 입력:

- `--change-request`
- `--change-request-file`

### 4.2 Input Priority

우선순위는 다음과 같다.

mode:

- `--project-mode`
- 없으면 자동 감지

raw request:

- `--request`
- `--request-file`
- `docs/planning/request.md`

`brownfield` change request:

- `--change-request`
- `--change-request-file`
- `docs/planning/change-request.md`

CLI가 항상 파일보다 우선한다.

### 4.3 Input Document Layers

사용자 편집용 canonical 파일:

- `docs/planning/request.md`
- `docs/planning/change-request.md`

run snapshot:

- `docs/generated/planning-runs/<run-id>/inputs/request.md`
- `docs/generated/planning-runs/<run-id>/inputs/change-request.md`

run은 항상 snapshot을 읽고, 원본 파일은 user-facing contract로 유지한다.

## 5. Greenfield and Brownfield Semantics

### 5.1 Greenfield

`greenfield`는 다음 중 하나에 해당한다.

- 빈 프로젝트
- 코드베이스가 아직 없고 요구사항 / source material 중심인 프로젝트

입력은 raw request 하나로 시작 가능하다. 시스템은 이를 기반으로 planning용 normalized brief를 만든다.

### 5.2 Brownfield

`brownfield`는 기존 구현 코드가 있는 프로젝트다. 그러나 기존 코드 존재만으로 planning을 시작하지 않는다. 반드시 “무엇을 바꾸려는가”가 필요하다.

따라서 `brownfield`는 다음 두 층의 입력을 가진다.

- raw request
- structured change request

### 5.3 Change Request Normalization

사용자는 자유문장 요구사항만 넣어도 된다. 시스템이 이를 구조화된 `change-request.md`로 정규화한다.

정규화된 문서는 최소 다음 섹션을 가진다.

- 변경 목표
- 배경
- in scope
- out of scope
- 영향받는 영역
- 제약사항
- 승인 기준

정보가 부족한 항목은 `unknown` 또는 `needs confirmation`으로 표기한다.

### 5.4 Missing Brownfield Change Request

`brownfield`인데 CLI 입력과 canonical file 모두 없으면 다음 동작을 한다.

1. `docs/planning/change-request.md` 템플릿 자동 생성
2. `waiting_for_input`으로 전환
3. 사용자가 파일을 채운 뒤 resume

즉 `brownfield`는 change request가 비어 있으면 그냥 진행하지 않는다.

## 6. Stage Graph

### 6.1 Shared Top-Level Flow

상위 흐름은 다음과 같다.

1. input discovery
2. mode resolution
3. request normalization
4. classification
5. docs / completeness related stages
6. scope
7. sizing
8. packing
9. review
10. exec-plan authoring

### 6.2 Brownfield Sub-Pipeline

`brownfield`는 중간에 다음 서브스테이지를 거친다.

1. code observation extraction
2. observation synthesis
3. gap synthesis

각 서브스테이지는 독립된 AI-heavy stage이며, 필요 시 size class에 따라 slice session으로 나뉜다.

### 6.3 Session Profile Usage

`session_profiles.py`는 문서용이 아니라 실제 orchestration 규칙으로 사용한다.

- small / medium / large별 전략 사용
- `single_session`
- `explicit_slice_sessions`
- `single_synthesis_session`

세션 개수는 런타임 중 임의로 늘리거나 줄이지 않는다. profile이 결정한다.

## 7. Stage Session Orchestration

각 AI-heavy stage는 항상 다음 순서를 따른다.

1. 새 `codex exec` 세션 오픈
2. stage-specific prompt + read set 주입
3. 질문/승인 발생 시 같은 세션을 `resume`
4. `STAGE_COMPLETE` 수신
5. stage outputs 저장
6. handoff 문서 작성
7. 세션 종료
8. 다음 stage는 새 세션에서 시작

질문/승인 없이는 같은 stage에서 한 번의 `exec`만으로 끝날 수 있다.

## 8. Runtime State and Persistence

run 루트는 계속 다음 경로를 사용한다.

- `docs/generated/planning-runs/<run-id>/`

필수 기록:

- `run-state.json`
- `runtime-events.ndjson`
- `inputs/request.md`
- `inputs/change-request.md`
- `question-queue.md`
- `answer-log.md`
- `approval-log.md`
- `assumptions.md`
- `assumption-invalidations.md`
- `stage-handoffs/<nn>-<stage>.md`

상태 전이:

- `running_exec`
- `running_cli`
- `waiting_for_input`
- `waiting_for_approval`
- `waiting_for_human`
- `failed`
- `completed`
- `escalated`

운영 규칙:

- `resume`은 `waiting_for_input` / `waiting_for_approval`에서만 허용
- `STAGE_COMPLETE` 수신 시 handoff 작성 후 다음 stage로 진행
- `waiting_for_human`이면 사용자가 input file 또는 approval을 보완한 뒤 재개
- 프로세스 중단 후에도 `run-state.json`과 마지막 handoff 문서로 재시작 가능

## 9. Prompt and Handoff Contract

### 9.1 Read Set

각 AI-heavy stage는 다음 문서만 읽는다.

- input snapshot
- canonical docs
- 직전 handoff
- 필요한 누적 answers / approvals / assumptions log

이 원칙으로 불필요한 context 재적재를 막는다.

### 9.2 Stage Outputs

stage는 marker protocol을 따른다.

- 질문 필요 시 `INPUT_REQUIRED`
- 승인 필요 시 `APPROVAL_REQUIRED`
- 가정 기록 시 `ASSUMPTION_LOG`
- 사람 개입 필요 시 `NEEDS_HUMAN`
- stage 종료 시 `STAGE_COMPLETE`

마지막 turn tail의 marker bundle만 유효하다.

### 9.3 Handoff Document

각 stage 종료 후 다음 경로를 쓴다.

- `docs/generated/planning-runs/<run-id>/stage-handoffs/<nn>-<stage>.md`

포함 내용:

- stage 목적
- 결정 사항
- unresolved questions
- assumptions
- generated outputs
- next stage required read set

다음 stage는 이 handoff를 기본 컨텍스트로 사용한다.

## 10. Relationship to Docs-Orchestrator

본 설계는 `docs-orchestrator`와 같은 철학을 가진다.

- 단계별 새 세션
- 단계 완료 후 상태 저장
- 재시작 복구
- 단계별 prompt
- 최종 산출물 검증

차이는 planning이 문서 생성 general workflow가 아니라 stage-complete marker 기반의 stricter runtime을 가진다는 점이다.

즉 planning은 `docs-orchestrator`를 대체하되, 더 강한 stage completion contract를 가진 specialized orchestrator가 된다.

## 11. Verification Requirements

최소 다음 회귀가 필요하다.

- stage 완료 후 다음 AI-heavy stage는 새 세션으로 열린다
- 질문/승인은 같은 stage에서만 `resume`된다
- `brownfield`에서 change request가 없으면 템플릿 생성 후 `waiting_for_input`으로 멈춘다
- handoff 문서만으로 다음 stage가 시작된다
- large brownfield extraction은 slice session으로 분할된다
- `docs/generated/planning-runs/<run-id>/` 아래 기록이 일관되게 남는다
- 최종 `docs/exec-plans/planning/exec-plan.md`가 생성된다

## 12. Implementation Direction

구현은 다음 순서로 진행한다.

1. `planning` 기본 경로를 stage graph orchestrator로 교체
2. `brownfield` change request input contract 추가
3. raw request -> normalized request / change request 정규화 단계 추가
4. `session_profiles.py`를 실제 세션 개방 규칙으로 연결
5. `stage_executor.py`를 stage runtime 표준 엔진으로 승격
6. handoff 문서 생성/소비 계약 추가
7. `docs_orchestrator` 수준의 복구/검증을 planning에 연결

## 13. Non-Goals

본 설계는 다음을 이번 범위에 포함하지 않는다.

- 모든 deterministic stage를 AI 세션화하는 것
- Codex Desktop 전용 실행 경로
- 자연어 질문 감지 기반 orchestration
- context exhaustion 기반 동적 세션 분할

