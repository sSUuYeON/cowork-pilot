# Planning Pipeline Jinja2 Template Design

> **Date:** 2026-04-09
> **Status:** Approved
> **Scope:** planning pipeline 프롬프트를 Jinja2 템플릿으로 전환, docs-orchestrator 수준의 작업 지시서로 품질 향상

---

## 1. 배경 및 동기

### 현재 문제

`prompts.py`의 `render_stage_prompt()`는 Python `lines.append()`로 프롬프트를 조립한다. 결과물은 메타데이터 나열(PURPOSE, JSON KEYS, FORBIDDEN)일 뿐 **절차 지시가 없다**. AI에게 "뭘 해라"만 말하고 "어떻게 해라"가 없는 구조.

예시 — 현재 classification 프롬프트:
```
stage=classification
target_version=

PURPOSE: Analyze project inputs and produce a classification report...
OUTPUT FILE: classification-report.md
REQUIRED JSON KEYS: project_mode, product_type, size_class, ...
FORBIDDEN:
- Do NOT produce a plan or scope — only classify.
```

반면 docs-orchestrator의 phase1_single.j2:
```
읽어야 할 파일:
- {{ source_docs }}
- output-formats.md
- project-conventions.md

다음을 수행하라:
1. 원본 기획서를 모두 읽는다
2. 프로젝트 타입을 추론한다
3. 도메인과 기능을 식별하고 분할 계획을 수립한다
4. analysis-report.md를 작성한다
5. domain-extracts/를 생성한다
   - 중요: "요약"하지 말고 관련 원문을 그대로 복사하라
   ...

품질 규칙:
- "요약"하지 말고 원문을 그대로 복사하라
- 모든 복사 문단 앞에 <!-- SOURCE: --> 주석을 달아라
```

현재 planning 프롬프트는 **스펙 시트**이고, docs-orchestrator 프롬프트는 **작업 지시서**이다.

### 목표

1. planning pipeline의 프롬프트를 docs-orchestrator 수준의 작업 지시서로 전환
2. 프롬프트 텍스트와 Python 로직을 분리하여 프롬프트만 수정 가능하게 함
3. 코드베이스 내 일관성 — docs-orchestrator와 동일한 Jinja2 패턴 적용
4. `_STAGE_REQUIRED_KEYS` 중복 제거로 단일 소스 확보

---

## 2. 설계 결정

### 접근법: 하이브리드 (`{% include %}` only)

- `{% include %}`만 사용, `{% extends %}`는 사용하지 않음
- 각 `.j2`가 **완결된 작업 지시서** — 해당 파일만 열면 전체 프롬프트가 보임
- 반복되는 섹션(read_set 루프, 완료 프로토콜, output format)만 `_includes/`에서 가져옴
- docs-orchestrator의 `orchestrator_templates/` 패턴과 동일

**선택 이유:**
- docs-orchestrator가 이미 이 패턴으로 운영 중 → 코드베이스 일관성
- `{% extends %}` 상속 체인 추적 없이 직관적으로 읽힘
- 각 `.j2`가 독립적 문서로서 완결성 보유

---

## 3. 파일 구조

### 3.1 기존 `planning_templates/` (참고)

`src/cowork_pilot/planning_templates/`에 10개 `.j2` 파일이 이미 존재하지만, 이는 **stage 결과/요약 렌더링용**이며 아무 데서도 import되지 않는 미사용 파일이다. 우리가 만드는 AI 프롬프트 템플릿과는 용도가 완전히 다르며, 경로도 다르다 (planning 패키지 바깥 vs 안쪽).

### 3.2 신규 디렉토리

```
src/cowork_pilot/planning/
  planning_templates/
    _includes/
      read_set.j2                # 공통: 읽어야 할 파일 목록 루프
      output_format.j2           # 공통: JSON 블록 + 필수 키 안내
      completion_protocol.j2     # 공통: DONE 마커 + COWORK_PILOT_EVENT 예시
    classification.j2
    core_docs_check.j2
    adaptive_docs_selection.j2
    core_docs_presence_review.j2
    product_completeness_review.j2
    scope_structuring.j2
    work_sizing.j2
    plan_packing.j2
    plan_review.j2
    exec_plan_skeleton.j2
    exec_plan_feature_outline.j2
    exec_plan_detail.j2
    exec_plan_authoring.j2
    brownfield_code_observation_extraction.j2
    brownfield_observation_synthesis.j2
    brownfield_gap_synthesis.j2
  prompts.py                     # render_stage_prompt() 내부를 Jinja2로 교체
```

총 16개 `.j2` + 3개 `_includes/`. 전체 `PlanningStage` enum 16개를 모두 커버한다.

---

## 4. 공통 섹션 순서 (모든 `.j2` 동일)

docs-orchestrator와 동일한 고정 순서:

```
{# Stage 주석 #}
stage={{ stage }}
target_version={{ target_version }}

읽어야 할 파일:
{% include '_includes/read_set.j2' %}

다음을 수행하라:
(stage별 고유 절차)

출력 파일:
- {{ output_file }}

{% include '_includes/output_format.j2' %}

품질 규칙:
(stage별 고유 품질 규칙)

{% include '_includes/completion_protocol.j2' %}
```

---

## 5. `_includes/` 공통 블록

### `_includes/read_set.j2`

```jinja
{% for path in read_set %}
- {{ path }}
{% endfor %}
{% if handoff_summary %}

이전 stage 핸드오프 요약:
{{ handoff_summary }}
{% endif %}
{% if restored_context %}

복원된 컨텍스트:
{{ restored_context }}
{% endif %}
```

### `_includes/output_format.j2`

```jinja
출력 형식:
- Markdown 파일에 fenced JSON 블록(```json ... ```)을 포함하라
- 필수 JSON 키: {{ json_keys | join(', ') }}
- JSON 블록 이후에 분석 근거나 부연 설명을 자유롭게 작성해도 된다
```

### `_includes/completion_protocol.j2`

```jinja
완료 프로토콜:
1. 출력 파일의 마지막 줄에 반드시 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
2. 메시지 끝에 다음 형식의 이벤트 번들을 emit하라:

<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: {{ stage }}
event_id: {{ stage }}-done
reason: stage completed successfully
summary: (작업 요약을 한 줄로)
outputs:
  - {{ output_file }}
</COWORK_PILOT_EVENT>

진행 중 질문이 필요하면 INPUT_REQUIRED, 승인이 필요하면 APPROVAL_REQUIRED,
더 이상 진행 불가하면 NEEDS_HUMAN 타입을 사용하라.
각 이벤트에는 type, stage, event_id, reason 필드가 반드시 포함되어야 한다.
```

---

## 6. Stage별 고유 절차

### 6.1 classification.j2

```
다음을 수행하라:
1. 읽어야 할 파일을 모두 읽는다
2. 프로젝트의 입력 소스(기획서, README, 기존 코드 등)를 파악한다
3. project_mode를 판단한다 (greenfield / brownfield)
   - 기존 소스 코드가 있으면 brownfield, 없으면 greenfield
4. product_type 후보를 나열하고, 근거를 들어 하나를 선택한다
   - 예: webapp, api, cli, library, mobile, monorepo
5. size_class를 판단한다
   - 기준: 기능 수, 예상 파일 수, 도메인 복잡도
   - small: 기능 5개 이하, medium: 6~15개, large: 16개 이상
   - 반드시 판단 근거를 명시하라
6. core_user_flows를 식별한다 — 사용자 관점의 핵심 시나리오 3~7개
7. primary_entities를 식별한다 — 핵심 데이터 모델/개체
8. risks를 식별한다 — 기술적 위험, 불확실한 영역, 의존성 위험
9. 위 결과를 fenced JSON 블록으로 작성한다

품질 규칙:
- size_class는 반드시 근거(기능 수, 복잡도)와 함께 판단하라. 감으로 쓰지 마라
- core_user_flows는 "로그인" 같은 한 단어가 아니라 "사용자가 이메일로 회원가입하고 프로필을 설정한다" 수준으로 작성하라
- 이 stage에서는 scope, plan, work item을 생성하지 마라 — 오직 분류만 하라
```

### 6.2 core_docs_check.j2

```
다음을 수행하라:
1. classification-report.md를 읽고 project_mode, product_type, size_class를 확인한다
2. 프로젝트에 필요한 문서 역할(doc role) 목록을 결정한다
   - 예: AGENTS.md, ARCHITECTURE.md, design-docs, product-specs 등
   - size_class에 따라 필수/선택을 구분하라
3. 프로젝트 디렉토리에서 각 역할에 해당하는 기존 파일을 탐색한다
   - 정확한 파일 경로를 resolved_existing_paths에 기록하라
4. 존재하지 않는 역할을 missing_roles에 기록한다
5. 대체 가능한 문서가 있으면 substitutions에 기록한다
   - 예: ARCHITECTURE.md가 없지만 README에 아키텍처 섹션이 있는 경우
6. 위 결과를 fenced JSON 블록으로 작성한다

품질 규칙:
- 문서 내용을 만들어내지 마라 — 존재 여부와 역할 필요성만 판단하라
- resolved_existing_paths는 실제 존재하는 파일의 정확한 경로여야 한다
- scope나 plan 관련 내용을 생성하지 마라
```

### 6.3 adaptive_docs_selection.j2

```
다음을 수행하라:
1. classification-report.md와 core-docs-check.md를 읽는다
2. core docs 외에 추가로 읽어야 할 문서를 선별한다
   - 프로젝트 크기, 유형, 복잡도에 따라 판단
   - 디스크에 실제 존재하는 파일만 선택하라
3. 각 선택에 대해 selection_reasons에 "왜 이 문서가 필요한가"를 명시한다
4. 검토했으나 선택하지 않은 후보를 rejected_candidates에 기록한다
   - 탈락 이유를 간단히 명시하라
5. 위 결과를 fenced JSON 블록으로 작성한다

품질 규칙:
- core-docs-check.md에서 이미 resolved된 core docs를 반복하지 마라 — 추가/조건부 문서만 다루라
- 존재하지 않는 파일을 selected_paths에 넣지 마라
- scope나 plan 관련 내용을 생성하지 마라
```

### 6.4 scope_structuring.j2

```
다음을 수행하라:
1. classification-report.md의 core_user_flows와 primary_entities를 읽는다
2. core-docs-check.md와 adaptive-docs-selection.md에서 참조할 문서 목록을 확인한다
3. 제품을 기능적 도메인으로 분해한다
   - 도메인은 사용자가 인지하는 제품 기능 단위여야 한다
   - 예: "인증", "결제", "대시보드", "알림" (O)
   - 예: "agents", "spec_index", "design_guide" (X — 이것은 문서 역할이지 제품 도메인이 아니다)
4. 각 도메인 아래 구체적인 feature를 나열한다
5. user_flows를 정리한다 — 도메인을 가로지르는 사용자 시나리오
6. out_of_scope를 명시한다 — 이유를 반드시 달아라
7. 위 결과를 fenced JSON 블록으로 작성한다

품질 규칙:
- 문서 역할 이름(agents, spec_index, design_guide, architecture, security, core_beliefs, data_model, spec_documents)을 도메인이나 feature 이름으로 사용하지 마라
- 도메인은 기술 레이어(frontend, backend, database)가 아니라 제품 기능 단위여야 한다
- work item이나 plan chunk를 생성하지 마라 — 오직 scope만 정의하라
- out_of_scope 항목마다 제외 이유를 달아라
```

### 6.5 work_sizing.j2

```
다음을 수행하라:
1. scope-map.md를 읽고 domains, features, user_flows를 파악한다
2. 각 feature에 대해 work item을 생성한다:
   - id: 고유 식별자 (예: "WI-001")
   - title: 작업 제목
   - domain: scope-map.md의 도메인
   - feature: scope-map.md의 feature
   - size: S / M / L 중 하나
   - risk: low / medium / high 중 하나
   - depends_on: 의존하는 다른 work item의 id 목록
3. size 판단 기준을 명시하라:
   - S: 1-2일, 단일 모듈, 명확한 구현 경로
   - M: 3-5일, 2-3개 모듈, 일부 설계 판단 필요
   - L: 1주+, 여러 모듈, 설계 결정 또는 외부 의존성
4. depends_on 관계가 순환하지 않는지 확인하라
5. 위 결과를 fenced JSON 블록으로 작성한다 — work_items 배열

품질 규칙:
- scope를 재정의하지 마라 — scope-map.md를 그대로 입력으로 받아라
- 모든 work item의 size에 판단 근거를 간단히 달아라
- depends_on이 순환(cycle)하면 안 된다
- plan chunk나 실행 순서를 생성하지 마라
```

### 6.6 plan_packing.j2

```
다음을 수행하라:
1. work-sizing.md와 scope-map.md를 읽는다
2. work item들을 실행 가능한 plan chunk로 그룹핑한다:
   - plan_name: 실행 단위 이름
   - goal: 이 plan이 달성하는 것
   - included_work_item_ids: 포함된 work item id 목록
   - why_grouped: 왜 이 항목들을 묶었는지
   - dependencies: 이 plan이 의존하는 다른 plan 이름 목록
3. 그룹핑 원칙:
   - 의존성 순서를 존중하라 — 의존 대상이 먼저 실행되어야 한다
   - 병렬 실행 가능한 plan은 dependencies가 겹치지 않아야 한다
   - 한 plan에 work item이 너무 많으면 (5개 초과) 분할을 검토하라
4. 모든 work item이 정확히 하나의 plan에 포함되는지 확인하라 — 누락이나 중복 없이
5. 위 결과를 fenced JSON 블록으로 작성한다 — plans 배열

품질 규칙:
- work item을 재추정하지 마라 — work-sizing.md를 그대로 입력으로 받아라
- 모든 work item이 하나의 plan에 포함되어야 한다 (누락 금지)
- review verdict를 생성하지 마라
```

### 6.7 plan_review.j2

```
다음을 수행하라:
1. plan-packing.md, work-sizing.md, scope-map.md를 읽는다
2. 커버리지 검사: scope-map.md의 모든 feature가 work item → plan으로 이어지는지 확인한다
   - 누락된 feature가 있으면 missing_work_items에 기록하라
3. 사이징 검사: work item의 size가 합리적인지 검토한다
   - 과대/과소 추정이 의심되면 issues에 기록하라
4. 실행 가능성 검사: plan의 의존성 순서가 올바른지, 순환이 없는지 확인한다
   - 문제가 있으면 execution_risks에 기록하라
5. 과설계 검사: 불필요하게 분할되거나 scope를 넘어선 항목이 있는지 확인한다
6. 종합 판단:
   - coverage_status: "full" / "partial" / "insufficient"
   - rollback_recommended: true / false — 반드시 근거 문장을 issues에 포함하라
7. 위 결과를 fenced JSON 블록으로 작성한다

품질 규칙:
- plan을 수정하지 마라 — 오직 리뷰만 하라
- rollback_recommended는 boolean이며 근거가 반드시 issues에 있어야 한다
- 모든 verdict 필드를 빠짐없이 채우라
```

### 6.8 core_docs_presence_review.j2

```
다음을 수행하라:
1. classification-report.md를 읽고 프로젝트 특성을 확인한다
2. core-docs-check.md에서 missing_roles와 substitutions를 확인한다
3. 실제 프로젝트 디렉토리를 탐색하여 core docs의 현재 상태를 검증한다:
   - 파일이 존재하는가?
   - 내용이 비어있지 않은가?
   - 역할에 맞는 내용을 담고 있는가?
4. substitution으로 지정된 파일이 실제로 대체 가능한지 확인한다
5. 최종 docs 가용 상태를 정리한다

품질 규칙:
- 문서 내용을 생성하거나 보강하지 마라 — 존재와 적합성만 확인하라
- 파일이 존재하지만 역할에 맞지 않으면 명확히 표시하라
```

### 6.9 product_completeness_review.j2

```
다음을 수행하라:
1. classification-report.md와 scope-map.md(있으면)를 읽는다
2. normalized-request.md에서 사용자의 요구사항을 파악한다
3. 기존 문서와 기획서를 대조하여 제품 완전성을 검토한다:
   - 모든 핵심 사용자 흐름이 문서화되어 있는가?
   - 비기능 요구사항(보안, 성능, 접근성)이 다뤄져 있는가?
   - 엣지 케이스와 에러 처리가 고려되어 있는가?
4. 미충족/부분충족 항목을 카테고리별로 정리한다
5. size_class에 따라 완전성 기준을 조정한다 (small은 관대하게, large는 엄격하게)

품질 규칙:
- 빠진 내용을 직접 채우지 마라 — 무엇이 빠져있는지만 식별하라
- 각 미충족 항목에 심각도(critical/important/nice-to-have)를 달아라
```

### 6.10 exec_plan_skeleton.j2

```
다음을 수행하라:
1. scope-map.md, work-sizing.md, plan-packing.md를 읽는다
2. 전체 exec-plan의 feature 목록을 확정한다
3. feature 간 의존성을 분석하여 실행 순서를 결정한다
4. 의존성 테이블을 작성한다:
   | # | Feature | 의존성 | 실행 순서 |
5. 각 feature의 예상 chunk 수를 산정한다
6. 위 결과를 exec-plan-skeleton.md에 작성한다

품질 규칙:
- chunk 상세 내용을 작성하지 마라 — feature 목록, 순서, 의존성만 다루라
- 의존성 분석을 기반으로 실행 순서를 결정하라
- plan-packing.md의 그룹핑을 존중하라
```

### 6.11 exec_plan_feature_outline.j2

```
대상 feature: {{ substage }}

다음을 수행하라:
1. exec-plan-skeleton.md를 읽고 해당 feature의 위치와 의존성을 확인한다
2. 해당 feature를 chunk 단위로 분해한다
3. 각 chunk에 대해:
   - chunk 제목
   - completion criteria (구체적이고 검증 가능한 조건)
   - task 목록 (각 task는 단일 작업 단위)
4. chunk 간 순서와 의존성을 명시한다

품질 규칙:
- completion criteria는 "구현 완료" 같은 모호한 표현 금지 — "X 테이블에 Y 컬럼이 존재하고 마이그레이션이 통과한다" 수준으로 작성하라
- session prompt는 작성하지 마라 — 다음 단계에서 채운다
- 각 chunk의 task는 5개 이하로 유지하라
```

### 6.12 exec_plan_detail.j2

```
대상 plan: {{ substage }}

다음을 수행하라:
1. exec-plan-outline.md를 읽고 해당 plan의 chunk 목록을 확인한다
2. 각 chunk에 대해 session prompt를 작성한다:
   - AI 세션이 읽어야 할 파일 목록
   - 수행할 작업의 단계별 지시
   - 예상 출력물
   - 검증 방법
3. session prompt는 해당 chunk만으로 완결되어야 한다 — 다른 chunk의 context에 의존하지 마라

품질 규칙:
- session prompt는 self-contained이어야 한다
- "이전 chunk에서 만든 것을 참고하라" 대신 구체적 파일 경로를 명시하라
- completion criteria와 session prompt가 일관되어야 한다
```

### 6.13 brownfield_code_observation_extraction.j2

```
다음을 수행하라:
1. 프로젝트 소스 코드 디렉토리를 탐색한다
2. 디렉토리 구조를 파악한다 — 주요 모듈, 패키지, 진입점
3. 핵심 파일을 읽고 관찰 사항을 기록한다:
   - 사용 중인 프레임워크와 라이브러리
   - 아키텍처 패턴 (MVC, layered, hexagonal 등)
   - 데이터 모델과 스키마
   - API 엔드포인트와 라우팅 구조
   - 테스트 구조와 커버리지 현황
   - 설정 파일과 환경 변수
4. 각 관찰에 근거 파일 경로를 명시하라
5. 결과를 code-observations/ 디렉토리에 슬라이스별로 저장한다

품질 규칙:
- 코드를 평가하지 마라 — 객관적으로 관찰만 하라
- 모든 관찰에 근거 파일 경로를 달아라
- 추측하지 말고 실제 코드에서 확인된 것만 기록하라
- 개선 제안이나 리팩토링 방안을 작성하지 마라
```

### 6.14 brownfield_observation_synthesis.j2

```
다음을 수행하라:
1. code-observations/ 디렉토리의 모든 슬라이스 파일을 읽는다
2. 관찰 사항을 카테고리별로 종합한다:
   - 아키텍처 개요
   - 데이터 모델 요약
   - API 표면 요약
   - 주요 의존성 목록
   - 코드 패턴과 컨벤션
3. 슬라이스 간 중복을 제거하고 모순이 있으면 표시한다
4. 결과를 implementation-observation-summary.md에 작성한다

품질 규칙:
- 슬라이스에 없는 정보를 추가하지 마라 — 종합만 하라
- 모순되는 관찰이 있으면 양쪽 다 기록하고 [CONFLICT] 태그를 달아라
- 개선 제안을 하지 마라 — 현재 상태 기술만 하라
```

### 6.15 exec_plan_authoring.j2

```
다음을 수행하라:
1. exec-plan-skeleton.md와 feature outline 파일들을 읽는다
2. 모든 feature outline의 chunk들을 통합하여 최종 exec-plan을 구성한다
3. 각 chunk에 대해:
   - 번호와 제목 확정
   - completion criteria 최종 확인
   - task 목록 최종 확인
   - session prompt 포함 여부 확인
4. exec-plan 간 의존성 순서가 올바른지 최종 검증한다
5. 결과를 최종 exec-plan 파일로 작성한다

품질 규칙:
- feature outline에서 이미 작성된 내용을 변경하지 마라 — 통합만 하라
- chunk 번호가 연속적이고 의존성 순서와 일치하는지 확인하라
- 누락된 feature가 없는지 skeleton과 대조하라
```

### 6.16 brownfield_gap_synthesis.j2

```
다음을 수행하라:
1. implementation-observation-summary.md를 읽는다 (현재 코드 상태)
2. normalized-request.md를 읽는다 (변경 요청)
3. 기획서/스펙 문서가 있으면 읽는다
4. 현재 구현과 변경 요청 사이의 갭을 분석한다:
   - spec-implementation-gap.md: 스펙 대비 현재 구현에서 빠진 것
   - change-impact-gap.md: 변경 요청이 기존 코드에 미치는 영향
5. 각 갭 항목에 대해:
   - 영향 범위 (어떤 파일/모듈)
   - 변경 난이도 (low / medium / high)
   - 의존성 (다른 갭 항목과의 관계)

품질 규칙:
- 갭만 식별하라 — 해결 방법을 제시하지 마라
- 각 갭에 영향받는 파일 경로를 명시하라
- 추측 기반 갭은 [UNCERTAIN] 태그를 달아라
- scope, work item, plan을 생성하지 마라
```

---

## 7. `prompts.py` 변경

### 7.1 추가되는 것

```python
from jinja2 import Environment, FileSystemLoader

_STAGE_TEMPLATE_MAP: dict[PlanningStage, str] = {
    PlanningStage.CLASSIFICATION: "classification.j2",
    PlanningStage.CORE_DOCS_CHECK: "core_docs_check.j2",
    PlanningStage.ADAPTIVE_DOCS_SELECTION: "adaptive_docs_selection.j2",
    PlanningStage.CORE_DOCS_PRESENCE_REVIEW: "core_docs_presence_review.j2",
    PlanningStage.PRODUCT_COMPLETENESS_REVIEW: "product_completeness_review.j2",
    PlanningStage.SCOPE_STRUCTURING: "scope_structuring.j2",
    PlanningStage.WORK_SIZING: "work_sizing.j2",
    PlanningStage.PLAN_PACKING: "plan_packing.j2",
    PlanningStage.PLAN_REVIEW: "plan_review.j2",
    PlanningStage.EXEC_PLAN_SKELETON: "exec_plan_skeleton.j2",
    PlanningStage.EXEC_PLAN_FEATURE_OUTLINE: "exec_plan_feature_outline.j2",
    PlanningStage.EXEC_PLAN_DETAIL: "exec_plan_detail.j2",
    PlanningStage.EXEC_PLAN_AUTHORING: "exec_plan_authoring.j2",
    PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION: "brownfield_code_observation_extraction.j2",
    PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS: "brownfield_observation_synthesis.j2",
    PlanningStage.BROWNFIELD_GAP_SYNTHESIS: "brownfield_gap_synthesis.j2",
}

def _get_jinja_env(template_dir: Path | None = None) -> Environment:
    if template_dir is None:
        template_dir = Path(__file__).parent / "planning_templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )
```

전체 `PlanningStage` enum 16개를 모두 커버한다. 매핑되지 않는 stage는 존재하지 않는다.

### 7.2 `render_stage_prompt()` 내부 변경

- 시그니처는 **그대로 유지** — 호출자 변경 없음
- stage가 `_STAGE_TEMPLATE_MAP`에 있으면 Jinja2 렌더링
- 모든 16개 stage가 매핑되므로 fallback은 safety net 역할만 함 (미래 stage 추가 대비)
- fallback: `_STAGE_TEMPLATE_MAP`에 없는 stage → `f"{stage.value}:{target_version}\n"` + 기본 completion protocol 텍스트 반환
- `_MARKER_INSTRUCTIONS` 상수 삭제 — `completion_protocol.j2`가 대체

### 7.3 템플릿 변수 계약 (kwargs)

`template.render(**kwargs)`에 전달되는 변수 목록:

| 변수명 | 타입 | 소스 | 설명 |
|--------|------|------|------|
| `stage` | `str` | `PlanningStage.value` | stage 이름 |
| `target_version` | `str` | 함수 파라미터 | 타겟 버전 |
| `read_set` | `tuple[str, ...]` | 함수 파라미터 | 읽어야 할 파일 경로 목록 |
| `handoff_summary` | `str` | 함수 파라미터 | 이전 stage 핸드오프 요약 |
| `restored_context` | `str` | context에서 추출 | 복원된 컨텍스트 (resume 시) |
| `output_file` | `str \| None` | `_resolve_output_file(stage)` | `ARTIFACT_OWNERSHIP_TABLE` 기반 출력 파일명 |
| `json_keys` | `tuple[str, ...]` | `StageContract.json_keys` | 필수 JSON 키 목록 |
| `forbidden` | `tuple[str, ...]` | `StageContract.forbidden` | 금지 규칙 목록 |
| `input_files` | `tuple[str, ...]` | `StageContract.input_files` | 필수 입력 파일 목록 |
| `purpose` | `str` | `StageContract.purpose` | stage 목적 설명 |
| `substage` | `str` | 함수 파라미터 | exec_plan_feature_outline/detail에서 feature/plan 이름 |

`substage` 값 예시:
- `exec_plan_feature_outline`: feature 이름 (예: `"authentication"`, `"payment"`)
- `exec_plan_detail`: plan 이름 (예: `"01-project-setup"`, `"02-data-layer"`)

### 7.4 유지되는 것

- `StageContract` dataclass와 `_STAGE_CONTRACTS` 딕셔너리 — 데이터 정의 역할 유지
- `_resolve_output_file()` — `ARTIFACT_OWNERSHIP_TABLE`에서 파일명 resolve
- `render_greenfield_entry_prompt()` — 이번에 안 건드림
- `render_brownfield_stage_prompt()` — 프로덕션에서 미사용, 이번에 안 건드림

---

## 8. `_STAGE_CONTRACTS` 확장 + `completion_verifier.py` 중복 제거

### 8.1 `_STAGE_CONTRACTS`에 누락 stage 추가

현재 `_STAGE_CONTRACTS`는 7개 converted stage만 포함 (classification ~ plan_review). 나머지 9개 stage를 추가하여 전체 16개를 커버한다:

- `CORE_DOCS_PRESENCE_REVIEW` — json_keys 없음 (JSON 블록 불필요한 stage)
- `PRODUCT_COMPLETENESS_REVIEW` — json_keys 없음 (결과가 별도 구조)
- `EXEC_PLAN_AUTHORING` — json_keys 없음 (exec-plan 파일 자체가 출력)
- `EXEC_PLAN_SKELETON` — json_keys 없음 (마크다운 테이블 출력)
- `EXEC_PLAN_FEATURE_OUTLINE` — json_keys 없음 (마크다운 구조 출력)
- `EXEC_PLAN_DETAIL` — json_keys 없음 (session prompt 텍스트 출력)
- `BROWNFIELD_CODE_OBSERVATION_EXTRACTION` — json_keys 없음 (관찰 텍스트 출력)
- `BROWNFIELD_OBSERVATION_SYNTHESIS` — json_keys 없음 (종합 텍스트 출력)
- `BROWNFIELD_GAP_SYNTHESIS` — json_keys 없음 (갭 분석 텍스트 출력)

이 stage들은 `json_keys=()`로 설정하여 JSON 블록 검증을 건너뛰되, `purpose`와 `forbidden`은 템플릿에서 참조할 수 있도록 채운다.

### 8.2 `completion_verifier.py` 중복 제거

현재 `_STAGE_REQUIRED_KEYS`가 `StageContract.json_keys`와 동일한 데이터를 하드코딩.

변경: `_STAGE_REQUIRED_KEYS` 삭제, `_STAGE_CONTRACTS`에서 `.json_keys`를 import하여 사용.

```python
from cowork_pilot.planning.prompts import _STAGE_CONTRACTS

# _STAGE_REQUIRED_KEYS 삭제, 대신:
def _get_required_keys(stage: PlanningStage) -> tuple[str, ...] | None:
    contract = _STAGE_CONTRACTS.get(stage)
    if contract is None or not contract.json_keys:
        return None
    return contract.json_keys
```

---

## 9. 테스트 전략

1. **템플릿 렌더링 테스트**: 16개 `.j2` 전체를 최소 kwargs로 렌더링하여 Jinja2 문법 에러 없음 확인 (parametrized over all `_STAGE_TEMPLATE_MAP` entries)
2. **렌더링 결과 검증**: 결과에 `<!-- ORCHESTRATOR:DONE -->`, `COWORK_PILOT_EVENT`, 각 stage의 `output_file`이 포함되는지 확인
3. **중복 제거 검증**: `completion_verifier.py`가 `_STAGE_CONTRACTS`에서 키를 올바르게 읽는지 확인. 기존 `_STAGE_REQUIRED_KEYS`와 동일한 결과를 반환하는지 비교 테스트
4. **시그니처 호환성**: 기존 `render_stage_prompt()` 호출 패턴 — `pipeline.py`의 `_render_dispatch_prompt()`가 사용하는 kwargs — 이 동일한 결과 타입(str)을 반환하는지 확인
5. **회귀 테스트**: EXEC_PLAN_SKELETON, EXEC_PLAN_FEATURE_OUTLINE, EXEC_PLAN_DETAIL의 기존 하드코딩 프롬프트와 Jinja2 렌더링 결과가 동일한 핵심 정보를 포함하는지 확인
6. **에러 처리 테스트**: 존재하지 않는 stage 이름으로 렌더링 시 fallback 동작 확인, 템플릿 파일 누락 시 명확한 에러 메시지 확인

---

## 10. 변경 범위 요약

| 파일 | 변경 유형 |
|------|-----------|
| `planning/planning_templates/*.j2` (16개) | **신규** |
| `planning/planning_templates/_includes/*.j2` (3개) | **신규** |
| `prompts.py` | **수정** — Jinja2 렌더링으로 교체, `_STAGE_CONTRACTS` 확장 |
| `completion_verifier.py` | **수정** — `_STAGE_REQUIRED_KEYS` 중복 제거 |
| 테스트 파일 | **신규** |

**안 바뀌는 것:**
- `pipeline.py` — 호출 인터페이스 동일
- `session_profiles.py` — `ARTIFACT_OWNERSHIP_TABLE` 그대로
- `marker_protocol.py` — 파싱 로직 그대로
- `stage_executor.py` — 실행 로직 그대로
- `quality_gate.py` — 게이트 로직 그대로
- `handoffs.py` — 핸드오프 그대로
- `render_greenfield_entry_prompt()` — 이번 범위 밖
- `render_brownfield_stage_prompt()` — 프로덕션 미사용, 이번 범위 밖
- `planning_templates/` (패키지 바깥 기존 디렉토리) — 별도 용도, 미사용
