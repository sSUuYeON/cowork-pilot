# Ghost CTO Domain + Workflow Core — Design Spec

**Status:** Proposed
**Date:** 2026-04-07
**Author:** User + Codex

## 1. Overview

Ghost CTO는 개발기획서 중심 AI 자동 외주개발 플랫폼이다. 사용자는 초기 요구사항 또는 기존 개발기획서를 제출하고, Ghost CTO 운영은 AI 평가와 운영 검토를 거쳐 다음 개발기획서 초안을 만든다. 사용자가 그 초안을 승인하면 공식 버전이 확정되고, 그 공식 버전을 기준으로 planning과 개발 실행이 시작된다.

이 문서는 Ghost CTO의 첫 번째 핵심 설계 문서로서, 다음 범위를 정의한다.

- 초기 프로젝트 생성과 이후 변경 요청을 하나의 상태 머신으로 다루는 도메인 모델
- AI 평가, 운영 판단, 사용자 승인, 공식 버전 확정의 워크플로
- 공식 버전과 파생 실행 산출물(exec-plan)의 경계
- 사용자에게 보이는 버전 중심 UX와 칸반의 최소 노출 단위
- planning 엔진과 cowork-pilot이 따라야 할 상위 계약

이 문서는 planning 알고리즘 상세, 칸반 UI 상세, 실시간 채팅 전체 설계, 데이터베이스 스키마 상세를 다루지 않는다. 그 영역은 이후 하위 설계 문서에서 정의한다.

## 2. Scope and Non-Goals

### 2.1 Included

- 사용자 요구사항 제출
- 기존 개발기획서 업로드 후 Ghost CTO 표준 문서로 재구성
- 초기 생성(`V0 -> V1`)과 이후 변경 요청을 동일한 모델로 처리
- `Submission`, `ChangeRequest`, `BugReport`, `AI Evaluation`, `Operator Decision`, `Next Spec Draft`, `Official Spec Version` 정의
- 운영 승인과 사용자 승인 모두를 거친 공식 버전 확정 규칙
- 전체 문서 묶음 스냅샷 기반 버전 관리
- 공식 버전 이후 planning 시작 규칙
- `version -> exec-plan -> chunk` 칸반 노출 계약

### 2.2 Excluded

- exec-plan 규모 산정 알고리즘 상세
- Codex CLI planning mode 세부 설계
- TUI 화면 구성 상세
- 실시간 채팅 UX/권한/알림 상세
- DB 테이블, API endpoint, 이벤트 버스, 웹소켓 프로토콜 상세

## 3. Product Principles

### 3.1 Version-Centric Product

Ghost CTO의 정본은 항상 개발기획서 버전 스냅샷이다. 사용 편의를 위해 최신 통합 뷰를 제공할 수는 있지만, 정본은 `V1`, `V2`, `V3`처럼 타임스탬프와 승인 이력이 붙은 공식 버전이다.

### 3.2 Agreement Before Execution

개발 실행은 합의된 공식 문서 기준으로만 시작된다. draft 단계 문서나 내부 검토 상태를 기준으로 planning을 시작하지 않는다.

### 3.3 Auditability Over Convenience

변경은 덮어쓰지 않는다. 요청, 평가, 승인, draft 수정, version publication, replan은 모두 별도 기록으로 남아야 한다.

### 3.4 Stable User-Facing State

운영 내부 검토 상태는 사용자에게 그대로 노출하지 않는다. 사용자에게는 최종 확정에 가까운 안정된 상태만 보여준다. 내부에서 승인 가능했던 요청이 나중에 충돌해 보류되더라도, 사용자에게는 `해준다더니 갑자기 안 된다`처럼 보이지 않게 설계한다.

## 4. Roles

| Role | Description |
|------|-------------|
| `user` | 외주를 맡긴 사람. 요구사항 제출, draft 검토, 공식 버전 승인 주체 |
| `operator` | Ghost CTO 운영자. AI 평가 검토, 승인/거절/편성, draft 수정 주체 |
| `system_ai` | AI 시스템. 구조화된 평가서 생성, draft 생성, 충돌 재검토, planning 트리거 준비 |

V1에서는 이 세 역할만 정의한다. 개발자, 리뷰어, 별도 PM 역할은 이후 확장 대상으로 둔다.

## 5. Core Domain Model

### 5.1 Submission

모든 외부 입력의 공통 상위 개념이다. Ghost CTO는 입력을 먼저 `Submission`으로 저장하고, 그 하위 타입에 따라 흐름을 분기한다.

공통 속성:

- `submission_id`
- `project_id`
- `submission_type`
- `author_user_id`
- `created_at`
- `target_version_id` (기본은 최신 공식 버전, 없으면 `V0`)
- `target_section_ref` (선택)
- `status_internal`
- `status_user_facing`
- `source_message_refs`

### 5.2 ChangeRequest

기능 추가, 기능 수정, 요구사항 취소, 기획 방향 변경을 다루는 submission subtype이다.

세부 분류 예시:

- `initial_creation`
- `feature_addition`
- `feature_modification`
- `cancellation`
- `scope_reduction`
- `scope_expansion`

초기 프로젝트 생성도 예외 흐름으로 분리하지 않는다. 공식 버전이 아직 없으면 `V0`를 빈 기준선으로 보고 첫 `ChangeRequest` 묶음을 통해 `V1`을 만든다.

### 5.3 BugReport

QA/버그 제보는 기능 변경과 성격이 다르므로 별도 `BugReport` subtype으로 관리한다. 기능 변경은 미래 상태를 바꾸는 제안이고, 버그 제보는 현재 상태가 기존 약속과 어긋났다는 신고이기 때문이다.

`BugReport`가 별도 모델이어야 하는 이유:

- 재현 가능성, 심각도, 중복 여부, 영향 버전 확인이 핵심이다.
- spec 변경 없이 수정 가능한 경우가 많다.
- 상태 체계가 `ChangeRequest`와 다르다.

원칙:

- `BugReport`는 별도 모델로 관리한다.
- spec/version 반영이 필요해지면 `ChangeRequest`와 연결될 수 있어야 한다.
- spec 변경이 필요 없는 단순 구현 결함은 새 spec version 없이 수정 실행할 수 있다.
- 다만 V1에서는 그 경우에도 사용자 확인을 거친 뒤 수정 대상으로 확정한다.

### 5.4 AI Evaluation

각 `Submission`에는 구조화된 AI 평가서가 붙는다. 단순 추천 플래그가 아니라 운영자가 판단 가능한 평가서여야 한다.

필수 평가 항목:

- 충돌 여부
- 영향받는 spec 섹션
- 반영 방식 제안
- 반영 시 리스크
- 예상 planning 영향
- 추가 확인 필요사항
- 거절 시 사유 초안
- 수용 가능 시 대안/타협안

### 5.5 Operator Decision

운영 판단은 AI 평가와 분리된 별도 기록이다. 운영자는 submission 단위로 다음 중 하나를 결정한다.

- `reject`
- `approve_for_pool`
- `hold`

여기서 `approve_for_pool`은 사용자에게 곧바로 “확정”으로 보이는 상태가 아니다. 이는 `다음 draft 후보로 편성할 수 있는 내부 승인`을 뜻한다.

### 5.6 Next Spec Draft

운영이 내부 승인한 변경들을 배치해 만든 다음 공식 버전 후보 문서 묶음이다.

속성:

- 동시에 하나만 존재한다.
- 사용자에게 보여지는 순간 고정된다.
- 그 이후 새로 승인된 요청은 현재 draft에 합치지 않고 다음 버전 후보로 넘긴다.
- 운영자는 사용자에게 보여주기 전 또는 반려 후 재작성 과정에서 draft를 수정할 수 있다.
- 운영 수정도 이력으로 남는다.

### 5.7 Official Spec Version

Ghost CTO의 정본이다. 공식 버전은 다음 조건을 모두 만족해야 한다.

- 운영 검토 완료
- 사용자 승인 완료
- 문서 묶음 스냅샷 저장 완료
- 승인 시각과 승인 주체 기록 완료

공식 버전은 개발기획서 본문만이 아니라 아키텍처/설계 문서를 포함한 전체 문서 묶음이다.

### 5.8 ExecPlanSet

`ExecPlanSet`은 공식 버전에서 파생되는 실행 산출물이다. 정본이 아니며, 같은 공식 버전에 대해 여러 번 생성될 수 있다.

원칙:

- 공식 버전 이후에만 생성된다.
- 같은 공식 버전에 대한 replan이 가능하다.
- 이전 plan도 이력으로 남긴다.
- 어떤 공식 버전을 기준으로 생성되었는지 항상 명시한다.

## 6. Versioning Model

### 6.1 Canonical Storage

정본은 항상 전체 문서 묶음 스냅샷이다.

각 공식 버전은 다음을 포함한다.

- 개발기획서 본문
- 아키텍처 문서
- 설계 문서
- 승인 메타데이터
- 생성 시각, 승인 시각, 승인자

### 6.2 Diff and Change Summary

전체 스냅샷이 정본이지만, 사용자와 운영자는 변경 내용을 보기 쉬워야 한다. 따라서 각 버전에는 별도의 변경 요약과 diff 뷰를 제공한다.

정리 원칙:

- 정본: 전체 스냅샷
- 보조 정보: 변경 문서 요약, diff, 포함된 submission 목록

### 6.3 Version-Centric UX

서비스 메인 경험은 `버전 타임라인/버전 목록` 중심으로 구성한다. 사용자는 최신 승인 버전 하나만 보는 것이 아니라, 버전별 합의 문서를 탐색하는 방식으로 시스템을 이해한다.

## 7. Workflow

### 7.1 Initial Project Creation (`V0 -> V1`)

1. 사용자가 텍스트 요구사항 또는 기존 개발기획서를 제출한다.
2. 기존 문서 업로드의 경우, 업로드 문서는 source material로 취급한다.
3. AI가 Ghost CTO 표준 개발기획서 구조로 재구성한다.
4. 운영이 검토/수정한다.
5. 사용자에게 `V1 draft`를 보여준다.
6. 사용자가 승인하면 `Official Spec Version V1`이 확정된다.

### 7.2 Change Request Flow

1. 사용자가 최신 공식 버전 또는 특정 버전/특정 섹션을 기준으로 submission을 보낸다.
2. AI가 구조화된 평가서를 생성한다.
3. 운영이 내부 승인/거절/보류를 판단한다.
4. 내부 승인된 항목은 draft 후보 pool에 쌓인다.
5. 운영이 일부를 선택해 `Next Spec Draft`를 생성한다.
6. 사용자가 draft를 승인하면 새로운 공식 버전이 된다.

### 7.3 Cancellation Flow

이미 spec에 반영된 내용을 없애고 싶을 때는 기존 요청 상태를 수정하지 않는다. 반드시 새 `ChangeRequest`를 생성해 취소 요청으로 남긴다. 그래야 무엇이 왜 사라졌는지 이력이 유지된다.

### 7.4 Rejection Flow

거절은 단순 종료가 아니라 별도 판단 이력으로 남는다. 거절 기록에는 다음이 포함되어야 한다.

- 거절 사유
- 가능한 대안
- 나중에 다시 검토 가능한 조건

### 7.5 Bug Report Flow

1. 사용자가 `BugReport`를 제출한다.
2. AI/운영이 재현성, 심각도, spec 근거, 변경 필요성을 평가한다.
3. spec 변경이 필요 없으면 사용자 확인 후 수정 대상으로 확정할 수 있다.
4. spec 변경이 필요하면 `ChangeRequest`와 연결하고 다음 draft 편성 대상으로 넘긴다.

## 8. Internal State vs User-Facing State

### 8.1 Internal Submission States

내부 상태 예시:

- `submitted`
- `ai_reviewed`
- `approve_for_pool`
- `hold`
- `queued_for_draft`
- `included_in_draft`
- `blocked_by_conflict`
- `needs_re-review`
- `rejected`
- `cancelled`

### 8.2 User-Facing States

사용자에게는 더 안정적인 상태만 보여준다.

- `received`
- `under_review`
- `planned_for_next_draft`
- `included_in_draft`
- `approved_in_version`
- `rejected`

내부에서 `approve_for_pool` 상태였던 항목이 나중에 draft 편성 시 충돌로 보류되더라도, 사용자에게는 “확정 취소”처럼 보이게 하지 않는다.

## 9. Conflict Handling

과거에 내부 승인된 요청도 실제 draft 편성 시점에는 다시 검증한다. 이유는 최신 공식 버전과 이후 승인된 다른 요청들이 누적되면서 새로운 충돌이 생길 수 있기 때문이다.

처리 원칙:

- 승인 이력은 유지한다.
- 충돌이 나면 자동 보류한다.
- 기본 처리 방식은 `자동 보류 + 운영 재검토`다.
- 사용자에게는 내부 충돌 상세를 기본적으로 노출하지 않는다.

이 방식은 사용자-facing 상태와 내부 운영 상태를 분리해야만 성립한다.

## 10. Draft Rules

### 10.1 Single Draft Rule

한 프로젝트에서 동시에 존재할 수 있는 `Next Spec Draft`는 하나뿐이다.

### 10.2 Draft Freeze Rule

사용자에게 보여진 draft는 고정된다. 그 이후에 새로 승인된 submission은 해당 draft에 끼워 넣지 않고 다음 버전 후보로 넘긴다.

### 10.3 Operator Editability

운영자는 draft를 수정할 수 있다. 단, 다음 이력이 남아야 한다.

- AI 초안 원본
- 운영 수정본
- 수정 시각
- 수정자

## 11. Planning Contract

### 11.1 Start Condition

planning은 공식 spec version 확정 이후에만 시작된다. draft 단계에서 preview plan을 생성하지 않는다.

### 11.2 Start Mode

planning 시작 방식은 설정 가능하게 둔다.

- V1 기본값: 운영자 수동 시작
- 이후 확장: 자동 시작 가능

초기에는 수동 시작을 기본으로 두고, 나중에 자동화 수준을 올릴 수 있게 하는 것이 안전하다.

### 11.3 Planning Input

planning 엔진은 다음 입력을 받을 수 있어야 한다.

- 최신 공식 버전 전체 문서 묶음
- 직전 공식 버전 대비 변경분
- 편성된 submission 목록

기본 원칙은 변경분 중심 계획이지만, 필요하면 항상 최신 공식 버전 전체 문맥을 함께 참조할 수 있어야 한다.

### 11.4 Planning Output

planning 엔진은 최소한 다음 메타데이터를 반환해야 한다.

- 기준 공식 버전
- 반영한 변경 범위
- 생성된 exec-plan 수
- chunk 분해 결과
- replan 여부
- 이전 plan과의 관계

## 12. Kanban Contract

사용자에게 기본적으로 노출하는 단위는 다음이다.

- `Spec Version`
- `Exec Plan`
- `Chunk`

기본 노출 정보:

- 상태
- 요약 설명

기본적으로 노출하지 않는 정보:

- 내부 충돌 상세
- 운영 판단 상세
- AI 평가 전문

칸반은 `version -> exec-plan -> chunk` 관계를 중심으로 보여준다.

## 13. Collaboration Surface (V1)

V1의 채팅/참조 기능은 최소 범위로 정의한다.

### 13.1 Message Recording

메시지는 기록되어야 하며, 특정 대상과 연결될 수 있어야 한다.

### 13.2 Taggable Targets

V1에서 태그 가능한 대상:

- `Spec Version`
- `Spec Section`
- `Submission`

`Exec Plan`, `Chunk`, 메시지 간 인용 등은 이후 확장 대상으로 둔다.

## 14. Existing Spec Upload Rule

사용자가 이미 작성된 개발기획서를 업로드한 경우에도 그 문서를 그대로 공식 `V1`로 삼지 않는다.

처리 원칙:

- 업로드 문서는 source material로 본다.
- AI가 Ghost CTO 표준 개발기획서로 재구성한다.
- 운영이 검토/수정한다.
- 사용자가 승인하면 비로소 공식 `V1`이 된다.

이렇게 해야 이후 모든 버전과 변경관리가 동일한 규칙 아래 놓인다.

## 15. Consequences for Future Planning Spec

이 설계가 고정되면 이후 planning 엔진 설계는 다음 전제를 따라야 한다.

- planning은 공식 버전의 하위 시스템이다.
- exec-plan은 정본 문서가 아니라 파생 계획이다.
- 같은 공식 버전에 대해 replan이 가능하다.
- 계획 규모 산정은 “대충 일정한 개수”가 아니라 공식 버전의 변경 범위와 영향도에 종속되어야 한다.
- Ghost CTO는 문서 중심 서비스이므로 planning도 version-aware해야 한다.

이 문서는 Ghost CTO의 상위 도메인 계약이며, 이후 planning 엔진 spec은 이 계약을 위반해서는 안 된다.
