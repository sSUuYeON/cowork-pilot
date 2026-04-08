# Planning Engine V3 — Design Spec

**Status:** Proposed
**Date:** 2026-04-07
**Author:** User + Codex

## 1. Overview

Planning Engine V3의 목적은 단순히 exec-plan outline을 생성하는 것이 아니라, 프로젝트 규모와 변경 영향에 맞는 고품질 planning을 수행하고, 그 결과로 자동 실행했을 때 품질 높은 웹서비스가 완성되도록 하는 것이다.

이 엔진은 기존 `docs-orchestrator`의 planning 역할을 사실상 대체하는 새 planning core를 정의한다. 단기적으로는 기존 `docs-orchestrator`가 이 core를 호출하는 adapter가 될 수 있지만, 설계 기준 자체는 새 엔진이 우선한다. 즉, 기준은 더 이상 "Phase 5에서 outline을 만든다"가 아니라, "프로젝트를 먼저 구조화하고 그 구조를 문서와 plan으로 고정한다"이다.

이 엔진은 처음부터 다음 두 사용 시나리오를 지원해야 한다.

- `Greenfield`: 초기 기획서/요구사항에서 시작해 docs/spec/plan/실행까지 가는 흐름
- `Brownfield`: 기존 서비스/문서/공식 버전이 있는 상태에서 추가 요구사항, 취소 요청, 버그 제보를 반영하는 흐름

또한 이 엔진은 특정 UI에 종속되지 않는다. Ghost CTO, Codex CLI, 기존 cowork-pilot는 모두 이 planning core를 호출하는 실행 표면(adapter)이 될 수 있어야 한다.

## 2. Goals

- 냅다 outline부터 생성하는 현재 구조를 폐기한다.
- 프로젝트 규모(`small / medium / large`)와 유형에 맞는 분해를 수행한다.
- 문서 존재 여부뿐 아니라 제품 완결성까지 검사한다.
- Greenfield와 Brownfield를 같은 planning core 위에서 다룬다.
- Brownfield에서 코드를 한 번에 직접 읽지 않고, 분할 관찰 -> 관찰 합성 -> gap synthesis 흐름으로 현재 구현을 파악한다.
- `Hybrid`를 기본 모드로 하고, `Interactive`와 `Auto`를 설정 가능하게 한다.
- 각 planning 단계가 intermediate docs를 남기고 다음 단계가 이를 읽게 한다.
- 기존 gap report 개념을 V3 내부의 review artifact로 흡수한다.
- 최종적으로 parser-friendly exec-plan을 생성한다.
- Codex CLI에서도 실행 가능한 planning 대상 계약을 가진다.

## 3. Non-Goals

- TUI 상세 UI 설계
- Codex CLI 호출 옵션 및 subprocess 세부 구현
- DB 스키마, 웹 API, 브라우저 실시간 동기화 구현
- review comment 포맷, GitHub 연동 세부 구현

## 4. Replacement Stance

Planning Engine V3는 `docs-orchestrator`의 planning 역할을 대체하는 새 설계다.

정확히는 다음과 같이 본다.

- 기존 `docs-orchestrator`는 문서 생성 오케스트레이터로서 일부 자산을 제공한다.
- 그러나 planning 품질 기준, 규모 산정 기준, intermediate docs 계약, Greenfield/Brownfield 분기, version-aware planning 관점은 새 엔진이 새로 정의한다.
- migration 단계에서는 `docs-orchestrator`가 V3 core를 호출하는 wrapper가 될 수 있다.
- 장기적으로 planning의 기준 문서는 본 설계 문서다.

즉, 이 설계는 단순 개량이 아니라 사실상 planning 역할의 기준 교체다.

## 5. Execution Surfaces

Planning Engine V3는 다음 실행 표면을 지원 대상으로 둔다.

| Surface | Role |
|--------|------|
| `Ghost CTO` | 공식 spec version 기준 planning, 변경관리, planning run 이력 관리 |
| `Codex CLI` | planning 세션 실행, intermediate docs 생성, review 단계 수행 |
| `cowork-pilot adapter` | 기존 docs-orchestrator 또는 harness가 planning core를 호출하는 호환 레이어 |

원칙:

- planning core는 UI/실행기와 분리된다.
- Codex CLI 실행 가능성은 나중의 옵션이 아니라 현재 설계 요구사항이다.
- 다만 Codex CLI 구체 구현은 별도 하위 설계에서 정의할 수 있다.

## 6. Mode Model

### 6.1 Project Modes

- `Greenfield`
  - 아직 공식 spec version이 없거나, 초기 기획서/요구사항에서 시작
  - 목표: 빠진 기획 없이 docs/spec/plan/실행 체인을 만든다

- `Brownfield`
  - 이미 서비스/문서/공식 spec version이 있음
  - 목표: 현재 상태를 읽고 변경 영향만큼만 정확히 확장한다

### 6.2 Decision Modes

기본 결정 방식은 `Hybrid`다.

- `Hybrid`
  - AI가 먼저 합리적 기본값을 채우고, 영향이 크거나 불확실한 항목만 질문
- `Interactive`
  - 주요 설계 항목을 사용자와 순차 확인
- `Auto`
  - 질문을 최소화하고 AI가 끝까지 진행

핵심 원칙:

- 기본 결정 방식은 `Hybrid`
- `Interactive`와 `Auto`는 설정 가능한 모드로 제공
- 목표는 “빵꾸 없이 묻는 모드”와 “알아서 끝까지 가는 모드”를 모두 지원하는 것

## 7. Planning Philosophy

### 7.1 Documents Over Session Memory

각 planning 단계는 intermediate doc를 남기고, 다음 단계는 그 문서를 입력으로 읽는다. context는 세션 기억이 아니라 문서 체인으로 이어진다.

이 원칙은 컨텍스트 한계 때문만이 아니라 다음 이유로 필요하다.

- review를 생성과 분리하기 위해
- 실패/재시작/resume를 가능하게 하기 위해
- "왜 이런 plan이 나왔는지"를 추적하기 위해
- 큰 컨텍스트 모델이 나와도 planning 품질을 안정적으로 유지하기 위해

### 7.2 No Outline-First Planning

outline은 시작점이 아니라 후반 산출물이다. 프로젝트를 구조화하고, 문서 완결성을 검토하고, work sizing을 끝낸 뒤에만 plan packing과 exec-plan authoring이 가능하다.

### 7.3 Size-Aware Decomposition

`small 규모에서는 검증 또는 의존성 분리를 위해 필요한 경우에만 chunk를 분리한다.`

`분해는 숫자 목표가 아니라 구현 경계와 검증 가능성을 기준으로 한다.`

즉, Planning Engine V3는 "11개 plan, 50개 chunk"처럼 습관적 숫자에 수렴하는 엔진이 아니라, 각 분해에 명확한 이유가 있는 엔진이어야 한다.

## 8. Classification Model

### 8.1 Classification Outputs

모든 planning run은 최소 다음 분류 결과를 남겨야 한다.

- `project_mode`: `greenfield | brownfield`
- `size_class`: `small | medium | large`
- `product_type`
- `decision_mode`: `interactive | hybrid | auto`

Brownfield에서는 분류 결과를 덮어쓰지 않고 `초기값 + 확정값`을 함께 보존한다.

- `initial_size_class`
- `initial_borderline`
- `confirmed_size_class`
- `confirmed_borderline`

즉 Brownfield의 `size_class`와 `borderline`은 planning run의 현재 유효값을 뜻하고, run history에는 초기 provisional 판단과 observation 이후 확정 판단이 모두 남아야 한다.

### 8.2 Classification Inputs

규모 판정은 감으로 하지 않는다. 다음 축을 본다.

- `핵심 기능군 수`
- `사용자 역할 수`
- `주요 유저플로우 수`
- `외부 연동 수`
- `운영/백오피스 요구 강도`
- `비기능 요구 강도`
- Brownfield의 경우 초기 단계에서는 `change_surface_estimate`
- Brownfield의 확정 단계에서는 `confirmed_change_impact`

### 8.3 Heuristic Rules

규모 판정은 `판정축 + 휴리스틱 규칙`으로 한다.

`small`의 전형적 특징:

- 핵심 기능군이 적다
- 역할이 1개 또는 매우 단순한 2개 수준이다
- 외부 연동이 거의 없거나 단순하다
- 운영자/백오피스 요구가 낮다
- 비기능 요구가 기본 수준이다
- Brownfield라면 초기 추정 변경 표면이 좁다

`large`의 전형적 특징:

- 역할이 복수이며 권한 차이가 크다
- 외부 연동이 여러 개다
- 운영자/백오피스 workflow가 중요하다
- 보안/성능/감사 로그/복구 요구가 강하다
- Brownfield라면 초기 추정 변경 표면이 넓고 기존 구조에 파급될 가능성이 높다

`medium`은 둘 사이의 일반적 중간 범위다.

판정은 엄격한 점수표보다 휴리스틱 우선으로 하되, intermediate doc에 근거를 남긴다.

### 8.4 Classification Report Schema

classification 단계는 최소 다음 형식의 intermediate output을 남겨야 한다.

- `project_mode`
- `size_class`
- `product_type`
- `decision_mode`
- `axis_observations`
  - `feature_groups`
  - `roles`
  - `user_flows`
  - `integrations`
  - `ops_complexity`
  - `non_functional_complexity`
  - `change_surface_estimate` (Brownfield initial)
  - `confirmed_change_impact` (Brownfield confirmed)
- `rationale`
  - 최종 판정 근거 3~5줄
- `confidence`
  - `low | medium | high`
- `borderline`
  - `true | false`

Brownfield 추가 필드:

- `classification_snapshot_kind`
  - `initial | confirmed`
- `brownfield_uncertainty`
  - `low | medium | high`
- `requires_observation_reclassification`
  - `true | false`

즉 분류는 단순 label만 남기면 안 되고, 어떤 축이 어떤 판단에 기여했는지 구조적으로 남겨야 한다.

Brownfield에서는 최소 두 개의 snapshot이 남아야 한다.

- `initial`
  - raw code 대량 분석 이전
  - `change_surface_estimate` 기반
- `confirmed`
  - `Brownfield Observation Synthesis` 이후
  - `confirmed_change_impact` 기반

### 8.5 Anchor Cases

엄격한 점수표 대신, 다음과 같은 anchor case를 기준선으로 둔다.

`small anchor`

- 역할 1개 또는 매우 단순한 2개
- 핵심 기능군 1~3개
- 외부 연동 0~1개
- 운영 workflow가 거의 없음
- 비기능 요구가 기본 수준
- Brownfield라면 초기 추정 변경 표면이 좁음

이 조합이면 거의 확실히 `small`이다.

`medium anchor`

- 역할 2개 이상
- 핵심 기능군이 여러 개이지만 도메인이 폭발하지는 않음
- 외부 연동 1~2개
- 일부 운영/관리 화면 필요
- 비기능 요구가 기본 이상이지만 강한 규제/감사 수준은 아님

이 조합이면 기본값은 `medium`이다.

`large anchor`

- 역할 3개 이상 또는 역할 간 권한 차이가 큼
- 핵심 기능군이 여러 도메인으로 나뉨
- 외부 연동 3개 이상 또는 고위험 연동 포함
- 운영/백오피스 workflow가 중요
- 보안/성능/감사 로그/복구 요구가 강함
- Brownfield라면 초기 추정 변경 표면이 넓고 기존 구조에 파급될 가능성이 큼

이 조합이면 거의 확실히 `large`다.

### 8.6 Borderline Rule

애매한 경우는 다음 규칙을 따른다.

- size가 `small`과 `medium` 사이로 흔들리면 기본값은 `medium`
- size가 `medium`과 `large` 사이로 흔들리면 `borderline = true`를 남기고 `medium`으로 시작한다
- Greenfield는 `Product Completeness Review` 종료 후 한 번만 재조정 가능하다
- Brownfield는 `Brownfield Observation Synthesis` 종료 후 한 번만 재조정 가능하다

즉 초기 classification은 보수적으로 중간값을 택하되, borderline 여부를 숨기지 않고 남겨야 한다.

### 8.7 Reclassification Rule

분류 결과는 planning 전체 동안 무한정 바꾸지 않는다.

- 초기 classification 수행
- Greenfield: 이후 `Product Completeness Review` 종료 후 한 번만 재조정 가능
- Brownfield: 이후 `Brownfield Observation Synthesis` 종료 후 한 번만 재조정 가능
- Brownfield의 경우 `initial_*`와 `confirmed_*`는 함께 보존하고, `confirmed_*`만 현재 유효값으로 승격한다

## 9. Document Model

### 9.1 Canonical Docs

정본 문서는 기존 `docs/` 체계에 남는다.

핵심 정본/입력 문서 축:

- `AGENTS.md`
- 공식 spec 본문 (`docs/specs/` 또는 동등한 versioned spec)
- `ARCHITECTURE.md`
- `docs/DESIGN_GUIDE.md`
- `docs/SECURITY.md`
- `docs/design-docs/core-beliefs.md`
- `docs/design-docs/data-model.md`
- 스펙 색인 역할 문서 (`docs/specs/index.md` 또는 `docs/product-specs/index.md`)
- 스펙 본문 역할 문서 (`docs/specs/*.md` 또는 `docs/product-specs/*.md`)
- `docs/exec-plans/*` (최종 파생 출력)

### 9.2 Core Docs

V3의 core docs는 다음 9개 축으로 고정한다.

- `AGENTS.md`
- 공식 spec 본문
- `ARCHITECTURE.md`
- `docs/DESIGN_GUIDE.md`
- `docs/SECURITY.md`
- `docs/design-docs/core-beliefs.md`
- `docs/design-docs/data-model.md`
- 스펙 색인 역할 문서
- 스펙 본문 역할 문서

여기서 중요한 점은 `core doc axes`와 `required set`을 구분하는 것이다.

- `core doc axes`
  - planning engine이 항상 검사해야 하는 문서 축의 전체 집합
- `required set`
  - 현재 `size_class + product_type + project_mode`에서 실제로 반드시 채워져야 하는 문서 집합

즉, 9개 축은 planning engine의 고정 검사 프레임이지만, 모든 축이 모든 프로젝트에서 항상 `required`인 것은 아니다.

기본 원칙:

- `AGENTS.md`, 공식 spec 본문, 스펙 색인 역할 문서는 모든 규모에서 `required`
- `docs/DESIGN_GUIDE.md`는 `small / medium / large` 모두에서 기본 `required`
- `ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/design-docs/core-beliefs.md`, `docs/design-docs/data-model.md`, 스펙 본문 역할 문서는 `small`에서 `conditional`이 될 수 있음
- `medium`과 `large`로 갈수록 위 축들은 점진적으로 `required` 범위로 올라감
- `Brownfield`에서는 기존 canonical docs와 실제 코드 상태를 함께 보고 `required / conditional / not_applicable`를 판정함

### 9.2.1 Document Role Mapping

planning engine은 고정 경로 이름보다 `document_role`을 기준으로 문서를 인식한다.

각 role은 최소 다음 계약을 가져야 한다.

- `allowed_path_aliases`
- `preferred_read_order`
- `preferred_write_target`
- `required_by_profile`

예시 role:

- `spec_index`
  - aliases: `docs/specs/index.md`, `docs/product-specs/index.md`
- `spec_documents`
  - aliases: `docs/specs/*.md`, `docs/product-specs/*.md`
- `architecture`
  - aliases: `ARCHITECTURE.md`, `docs/ARCHITECTURE.md`
- `design_guide`
  - aliases: `docs/DESIGN_GUIDE.md`

`preferred_write_target`은 `project_convention_profile`에 따라 결정한다.

감지 순서:

1. `config` 또는 `AGENTS.md`의 명시 override
2. 기존 파일 레이아웃 감지
3. default profile 적용

기본 default profile은 현재 프로젝트 컨벤션과 맞는 `specs_centered`다.

즉, current convention을 따르는 프로젝트는 `docs/specs/`를 정답 경로로 인정받아야 하며, `docs/product-specs/`는 대체 profile 또는 alias로 처리해야 한다.

### 9.3 Adaptive Docs

adaptive docs는 다음 입력을 기준으로 선택한다.

- 프로젝트 타입
- 기능 집합
- 외부 연동
- 운영 요구

예시:

- `auth.md`
- `deployment.md`
- `billing.md`
- `integrations.md`
- `ops-runbook.md`
- `migration.md`
- `admin-console.md`
- `analytics.md`
- `notifications.md`

이 추가 문서들은 AI가 감으로 늘리는 것이 아니라, 선택 근거가 intermediate doc에 남아야 한다.

## 10. Intermediate Docs and Run Structure

### 10.1 Why Intermediate Docs Exist

intermediate docs는 planning 중간 판단 근거를 남기기 위한 문서다.

필요한 이유:

- 정본 문서를 더럽히지 않기 위해
- 세션이 끊겨도 다음 세션이 이어받게 하기 위해
- review를 별도 단계로 남기기 위해
- replan 차이를 추적하기 위해

### 10.2 Run-Based Storage

planning intermediate docs는 `run 단위 폴더`로 저장한다.

`run`은 planning 실행 1회분을 뜻한다.

예:

- 첫 Greenfield planning
- 같은 공식 버전에 대한 replan
- Brownfield 변경요청 반영 planning

이들은 모두 별도 run이다.

권장 구조:

```text
docs/generated/planning-runs/
  2026-04-07T22-10-00Z-greenfield-v1-draft/
  2026-04-08T09-30-00Z-brownfield-v2-replan/
```

run 폴더 이름은 다음을 포함한다.

- `timestamp`
- `mode`
- `target version`

### 10.3 Intermediate Docs Set

각 run은 최소 다음 intermediate docs를 남긴다.

- `classification-report.md`
- `core-docs-check.md`
- `adaptive-docs-selection.md`
- `core-docs-presence-review.md`
- `product-completeness-review.md`
- `scope-map.md`
- `sizing-report.md`
- `plan-structure-draft.md`
- `plan-review.md`

조건부 intermediate docs:

- `coverage-gap.md` — Greenfield 기본, Brownfield에서도 completeness 근거가 필요하면 생성 가능
- `code-observations/` — Brownfield 기본
- `implementation-observation-summary.md` — Brownfield 기본
- `spec-implementation-gap.md` — Brownfield 기본
- `change-impact-gap.md` — Brownfield 기본

위 gap artifact는 별도 legacy phase를 복제하는 것이 아니라, 기존 stage가 생성하고 다음 stage가 읽는 보조 판단 문서다.

### 10.4 Gap Artifacts

V3는 기존 gap report 개념을 `stage-owned review artifact`로 흡수한다.

원칙:

- gap artifact는 독립 top-level stage가 아니라, 기존 review/structuring 단계가 남기는 conditional intermediate doc다.
- 각 gap artifact는 어떤 입력을 비교했고, 어떤 차이/누락/과설계 후보를 발견했는지 근거를 남긴다.
- 이후 단계는 이 문서를 읽고 scope/sizing/review에 반영해야 한다.

기본 적용:

- `Greenfield`: `coverage-gap.md`를 통해 빠진 설계와 과설계 후보를 잡는다
- `Brownfield`: 먼저 `code-observations/`와 `implementation-observation-summary.md`를 만들고, 그 다음 `spec-implementation-gap.md`, `change-impact-gap.md`를 통해 현재 구현/기존 docs/새 변경의 차이를 잡는다

## 11. Pipeline

Planning Engine V3의 기본 체인은 다음 10단계다.

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

각 단계는 별도 intermediate doc를 남기고, 다음 단계는 이전 문서를 입력으로 읽는다.

gap artifact는 위 10단계 밖의 추가 phase가 아니라, `Product Completeness Review`, `Scope Structuring`, `Plan Review`가 생성/소비하는 conditional intermediate doc다.

다만 `Brownfield`에서는 `Project Classification`과 `Core Docs Check` 사이에 다음 조건부 pre-analysis sub-pipeline이 삽입된다.

1. `Brownfield Code Observation Extraction` (`brownfield_code_observation_extraction`)
2. `Brownfield Observation Synthesis` (`brownfield_observation_synthesis`)
3. `Brownfield Gap Synthesis` (`brownfield_gap_synthesis`)

이 sub-pipeline은 10단계 본체를 대체하지 않는다. 역할은 raw code를 한 번에 읽어 gap을 만드는 대신, 현재 구현 상태를 intermediate docs로 안정적으로 축약하는 것이다.

## 12. Stage Details

### 12.1 Project Classification

프로젝트 유형, 규모, 역할, 연동, 운영 강도를 먼저 판정한다. 이후 review profile과 planning 강도가 이 결과에 따라 달라진다.

중요:

- 이 단계는 코드베이스 전체를 직접 읽어 구현 상태를 파악하는 단계가 아니다.
- 특히 `Brownfield`에서도 classification의 책임은 어디까지나 상위 분류와 초기 planning profile 결정이다.
- 실제 구현 상태 파악은 이 다음의 Brownfield 전용 pre-analysis sub-pipeline이 담당한다.

출력:

- `classification-report.md`

### 12.1.1 Brownfield Code Observation Extraction (`brownfield_code_observation_extraction`)

Brownfield에서는 classification 직후, 현재 코드베이스를 한 번에 읽고 gap을 뽑으려 하지 않는다. 대신 도메인/모듈/기능/entrypoint 단위로 코드를 나눠 여러 세션에서 관찰 기록을 만든다.

원칙:

- 각 세션은 자기 담당 slice만 읽는다.
- 원본 코드 전체를 다시 요약하지 않고, 다음 synthesis에 필요한 관찰 사실만 남긴다.
- 각 observation 문서는 최소 다음을 포함해야 한다.
  - 담당 범위
  - 실제 엔트리포인트/라우트/API
  - 핵심 데이터 모델/상태
  - 주요 권한/역할 분기
  - 외부 연동 흔적
  - 기존 spec과 달라 보이는 지점
  - `unknowns` 또는 추가 확인 필요사항

출력:

- `code-observations/<slice>.md`

### 12.1.2 Brownfield Observation Synthesis (`brownfield_observation_synthesis`)

이 단계는 raw code를 다시 대량으로 읽지 않는다. 대신 앞 단계에서 생성된 `code-observations/` 문서들만 읽고 현재 구현 상태의 요약 스냅샷을 만든다.

이 단계의 목적:

- 분할 관찰 결과를 하나의 현재 시스템 그림으로 합친다
- 중복/충돌 관찰을 정리한다
- 아직 불명확한 영역을 `unknown`으로 명시한다

즉, 이후 gap analysis는 원본 코드 전체가 아니라 이 요약 문서를 기준으로 수행한다.

이 단계가 끝나면 Brownfield는 `confirmed_size_class`, `confirmed_borderline`, `confirmed_change_impact`를 계산할 수 있다. 이 값들은 초기 classification snapshot을 덮어쓰지 않고 추가 snapshot으로 남겨야 한다.

출력:

- `implementation-observation-summary.md`

### 12.1.3 Brownfield Gap Synthesis (`brownfield_gap_synthesis`)

이 단계는 기존 canonical docs, 신규 변경 요청, `implementation-observation-summary.md`를 비교해 Brownfield gap artifact를 생성한다.

원칙:

- `spec-implementation-gap`은 원본 코드를 한 번에 읽어서 바로 만들지 않는다.
- 반드시 `code-observations/`와 `implementation-observation-summary.md`를 거친 뒤 생성한다.
- 구현 상태가 불명확한 경우는 추측으로 메우지 않고 `unknown` 또는 추가 확인 필요로 남긴다.

출력:

- `spec-implementation-gap.md`
- `change-impact-gap.md`

### 12.2 Core Docs Check

core docs가 실제로 존재하는지, 기본 뼈대가 준비됐는지 확인한다.

이 단계는 두 가지를 동시에 남겨야 한다.

- `9개 core axes` 중 현재 무엇이 존재하는지
- 현재 project에서 무엇이 실제 `required set`인지

즉 “무엇을 검사하나”와 “무엇이 지금 꼭 필요한가”를 분리해서 기록해야 한다.

출력:

- `core-docs-check.md`

### 12.3 Adaptive Docs Selection

프로젝트 특성에 따라 추가 문서가 필요한지 결정한다. 어떤 문서를 왜 추가했는지 이유를 남긴다.

출력:

- `adaptive-docs-selection.md`

### 12.4 Core Docs Presence Review

단순 존재 여부뿐 아니라 문서가 비어 있지 않고, 책임이 겹치지 않고, 역할을 수행하는지 검토한다.

또한 이 단계는 project 규모와 타입에 맞는 `required / conditional / not_applicable` 판정이 타당한지도 검토해야 한다.

예:

- `small` 프로젝트에서 `ARCHITECTURE.md`가 없더라도 합리적인 경우가 있을 수 있다
- 반면 `docs/DESIGN_GUIDE.md`는 `small`에서도 기본적으로 빠지면 안 된다

출력:

- `core-docs-presence-review.md`

### 12.5 Product Completeness Review

이 단계는 "빠진 문서"가 아니라 "이 서비스가 원활히 돌아가기 위해 필요한 설계가 빠졌는가"를 검사한다.

강제 체크 범주:

- 페이지/기능 목록
- 유저플로우
- 롤별 이동/권한
- 로그인 후 리다이렉트
- 기본 화면 세트
- empty / loading / error state
- CRUD 전주기
- 알림/피드백
- 운영/관리 화면
- 외부 연동/설정 의존성
- 버전 이후 운영 흐름
- 비기능 요구

중요:

- 각 항목이 무엇을 의미하는지 문서에 정의해야 한다.
- 프로젝트 분류 결과에 따라 `required / conditional / not_applicable`로 적용 강도를 조정한다.
- Greenfield에서는 이 단계가 `coverage-gap.md`를 생성해 빠진 설계와 과설계 후보를 남겨야 한다.

이 단계는 단순 언급 여부가 아니라 coverage level을 판정해야 한다.

coverage level:

- `missing`
  - 문서에 해당 항목이 없다
- `mentioned`
  - 항목은 언급되었지만 매우 얕고, 구현 범위나 관계가 불명확하다
- `scoped`
  - 범위, 목적, 연결 관계가 정의되어 있다
- `implementation_ready`
  - 구현 가능한 수준의 구체성이 있다
- `not_applicable`
  - 현재 프로젝트에는 필요하지 않다

기본 원칙:

- `small`에서는 모든 항목이 무조건 `implementation_ready`일 필요는 없다
- 하지만 `required` 항목은 최소 통과선 이상이어야 한다
- completeness review는 각 항목별로 `required minimum`을 계산해야 한다

또한 `Product Completeness Review`는 규모별로 강도가 달라야 한다.

- `small`
  - 먼저 applicability를 계산해 `required subset`만 깊게 본다
  - 나머지 항목은 `conditional` 또는 `not_applicable`로 빠르게 닫을 수 있다
  - 즉 12개 범주 전체를 같은 깊이로 채우지 않는다
- `medium`
  - 대부분의 user-facing 범주를 최소 `scoped` 이상으로 요구한다
  - 운영/비기능 범주는 조건부로 더 깊게 본다
- `large`
  - 12개 범주 전반을 적극적으로 평가하고, 더 많은 항목이 `implementation_ready`를 요구받는다

즉 `small`에서는 “모든 매트릭스를 채운다”가 아니라, `applicability-first lightweight profile`로 planning 비용이 구현 비용을 압도하지 않게 해야 한다.

예시 최소 통과선:

- `페이지/기능 목록`
  - `small`: `scoped`
  - `medium/large`: `implementation_ready`
- `유저플로우`
  - `small`: `scoped`
  - `medium/large`: `implementation_ready`
- `기본 화면 세트`
  - `small`: `mentioned` 또는 `scoped`
  - `medium/large`: `scoped`
- `외부 연동/설정 의존성`
  - 연동이 있으면 최소 `scoped`
  - high-risk 또는 `large`면 `implementation_ready`
- `비기능 요구`
  - `small`: `mentioned`
  - `medium/large`: `scoped`
  - security-critical면 `implementation_ready`

각 completeness 항목은 최소 다음을 출력해야 한다.

- `category`
- `applicability`
- `coverage_level`
- `required_minimum`
- `pass | fail`
- `follow_up_action`
  - `ask`
  - `assume`
  - `defer`
  - `reopen`

`small`에서의 최소 운영 규칙:

- applicability가 `not_applicable`이면 즉시 종료 가능
- applicability가 `conditional`이면 간단한 근거와 함께 `mentioned` 또는 `scoped` 수준으로 닫을 수 있다
- 오직 `required subset`만 깊은 review 대상으로 삼는다

출력:

- `product-completeness-review.md`
- `coverage-gap.md` (Greenfield 기본, 필요시 Brownfield도 생성 가능)

### 12.6 Scope Structuring

문서를 그대로 나열하지 않고, 구현 경계와 사용자 가치 단위에 맞게 work map으로 재구성한다.

Brownfield에서는 scope structuring 전에 다음 delta artifact가 준비되어야 한다.

- `implementation-observation-summary.md`
- `spec-implementation-gap.md`
- `change-impact-gap.md`

이 문서들은 분할 코드 관찰과 관찰 합성을 거쳐 만들어진 현재 구현 요약, 기존 canonical docs, 신규 변경 요청을 비교한 결과이며, scope map은 이 차이를 work item으로 번역한 결과여야 한다.

출력:

- `scope-map.md`
- `spec-implementation-gap.md` (Brownfield 기본)
- `change-impact-gap.md` (Brownfield 기본)

### 12.7 Work Sizing

각 work item에 복잡도와 영향도를 붙인다.

판단 기준:

- 복잡도
- 결합도
- 불확실성
- 외부 의존성
- 테스트/리뷰 부담
- 아키텍처 영향도
- Brownfield의 경우 변경 영향 범위

출력:

- `sizing-report.md`

### 12.8 Plan Packing

이 단계에서 work item을 exec-plan과 chunk로 묶는다.

원칙:

- 숫자를 맞추기 위해 묶지 않는다.
- 구현 경계, 의존성, 검증 가능성, 독립 실행성 기준으로 묶는다.
- `small 규모에서는 검증 또는 의존성 분리를 위해 필요한 경우에만 chunk를 분리한다.`
- `분해는 숫자 목표가 아니라 구현 경계와 검증 가능성을 기준으로 한다.`

출력:

- `plan-structure-draft.md`

### 12.9 Plan Review

review는 별도 단계이며, 한 세션에 몰지 않는다.

최소 review 관점:

- `coverage`
- `sizing`
- `executionability`
- `overdesign`

정확한 의미:

- `coverage`: spec과 completeness 요구가 plan에 빠짐없이 반영되었는가
- `sizing`: 프로젝트 규모 대비 과소/과대 분해는 아닌가
- `executionability`: 각 plan/chunk가 실제로 실행 가능하고, 검증/완료 판정이 가능한가
- `overdesign`: 불필요한 문서, 화면, 플로우, 분해를 억지로 넣지 않았는가

review는 gap artifact를 읽고 판단해야 한다.

- Greenfield review는 최소 `coverage-gap.md`를 읽고 coverage/overdesign를 판정한다
- Brownfield review는 최소 `spec-implementation-gap.md`, `change-impact-gap.md`를 읽고 coverage/executionability/overdesign를 판정한다

필요하면 review를 여러 세션으로 나눈다.

출력:

- `plan-review.md`

### 12.10 Exec-Plan Authoring

review를 통과한 구조를 parser-friendly exec-plan 문서로 작성한다. 이 단계는 새로운 설계를 만드는 단계가 아니라, 확정된 구조를 실행 계약으로 번역하는 단계다.

출력:

- `docs/exec-plans/*`

## 13. Greenfield vs Brownfield

### 13.1 Greenfield

Greenfield의 핵심 목표는 빠진 기획 없이 docs/spec/plan 체인을 완성하는 것이다. completeness bias가 강해야 한다.

특징:

- 초기 요구사항에서 출발
- 기본 화면, 권한, redirect, error state를 적극 보완
- `Hybrid` 모드가 특히 유용함

### 13.2 Brownfield

Brownfield의 핵심 목표는 현재 상태를 읽고, 변경 영향만큼만 정확히 확장하는 것이다. delta/impact bias가 강해야 한다.

특징:

- 현재 공식 spec version, 현재 docs, 실제 구현 상태, 신규 submission을 함께 읽음
- 불필요한 전체 재기획을 피함
- 영향 범위와 기존 구조 보존이 중요함
- 실제 구현 상태 파악은 `코드 전체 직접 대량 분석`이 아니라 `분할 관찰 -> 관찰 합성 -> gap synthesis`로 수행함

권장 흐름:

1. 기존 canonical docs와 신규 변경 요청을 읽음
2. 코드베이스를 도메인/모듈/기능 단위로 나눠 `code-observations/` 생성
3. `implementation-observation-summary.md`로 현재 구현 상태를 합성
4. 이를 기준으로 `spec-implementation-gap.md`, `change-impact-gap.md` 생성
5. 그 gap artifact를 읽고 `Scope Structuring` 이후 단계 진행

이 구조의 목적은 LLM이 대규모 코드베이스 전체를 한 번에 읽고 정확한 gap을 뽑아내야 하는 부담을 줄이는 데 있다.

## 14. Gap Report Reuse

기존 docs-orchestrator의 gap report 개념은 재사용할 가치가 있다. 다만 그대로 복제하지 않고 용도를 분리한다.

재사용 방향:

- `coverage gap`
- `spec-implementation gap`
- `change impact gap`

용도:

- Greenfield에서는 빠진 설계와 과설계를 잡는 review artifact
- Brownfield에서는 현재 구현/기존 docs/새 변경의 차이를 분석하는 artifact

적용 방식:

- `coverage gap`은 주로 `Product Completeness Review`가 생성하고 `Plan Review`가 소비한다
- `spec-implementation gap`은 Brownfield `Code Observation Extraction -> Observation Synthesis -> Gap Synthesis`를 거친 뒤 `Scope Structuring` 입력 artifact로 생성된다
- `change impact gap`은 Brownfield `Gap Synthesis`에서 생성되어 `Scope Structuring`과 `Work Sizing`의 입력 artifact가 된다
- 이 artifact들은 최종적으로 `plan-review.md`와 exec-plan packing rationale에 흡수된다

## 15. Question Policy

항목이 비었다고 무조건 질문하지 않는다. 그렇다고 AI가 무조건 다 채우지도 않는다.

기본 원칙:

- `합리적 기본값을 채우고, 중요도 높은 것만 질문`

질문 대상이 되는 경우:

- 아키텍처 방향을 크게 바꾸는 결정
- 역할/권한/운영 모델 변화
- 비용/시간/품질에 큰 영향이 있는 결정
- 이후 공식 spec version의 강제력을 크게 좌우하는 결정

자동으로 채울 수 있는 예:

- 표준 empty/loading/error state
- 기본 로그인 후 이동 규칙
- 일반적인 기본 화면 세트의 기본값

단, 자동으로 채운 경우에도 근거를 intermediate docs에 남긴다.

## 16. Anti-Overdesign Rules

과설계를 막기 위해 다음 규칙을 둔다.

### 16.1 YAGNI Gate

추가 문서, 추가 화면, 추가 플로우는 다음 중 하나에 근거해야 한다.

- 실제 사용자 가치
- 운영 필수성
- 보안/권한/실행 완결성

### 16.2 Evidence Rule

AI가 무언가를 추가하면 다음을 intermediate docs에 남긴다.

- 어떤 요구사항/문서에서 유도됐는지
- 어떤 빈 구멍을 메우는 것인지

### 16.3 Surface Area Cap

질문 없이 자동으로 추가 가능한 범위를 제한한다. 큰 구조 변화, 많은 신규 문서 추가, 역할 체계 변경은 질문 대상이 되어야 한다.

## 17. Final Output Contract

planning engine의 최종 출력은 다음 세트다.

- 보완/완성된 canonical docs
- run 단위 intermediate docs
- gap artifact set (`coverage-gap`, `spec-implementation-gap`, `change-impact-gap` 중 applicable subset)
- parser-friendly `ExecPlanSet`

최소 메타데이터:

- 기준 공식 버전 또는 기준 입력 문서 세트
- classification 결과
- decision mode
- adaptive docs 선택 결과
- 발견된 gap 요약
- packing 원칙
- replan 여부

## 18. Consequences

이 설계가 고정되면 이후 planning 구현은 다음을 만족해야 한다.

- docs-orchestrator의 planning 역할은 점진적으로 V3 core로 대체된다.
- Codex CLI 실행 가능성을 고려한 단계 분할과 intermediate docs 체인을 가진다.
- outline을 먼저 만들지 않는다.
- 프로젝트 규모와 변경 영향에 따라 review profile과 분해 강도가 달라진다.
- plan 수와 chunk 수는 목표값이 아니라 결과값이다.

Planning Engine V3는 `문서 생성기`가 아니라 `고품질 planning을 위한 공통 core`여야 한다.
