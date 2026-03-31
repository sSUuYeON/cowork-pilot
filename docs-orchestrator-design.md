# docs-orchestrator 스킬 설계서

> 작성일: 2026-03-30
> 최종 수정: 2026-04-01 (2차 리뷰 반영 — 적응형 타임아웃, 묶음 최대 2개, 마커 누락 fallback, 섹션 키워드 매칭, 모듈 분할, references 정의, 테스트 전략, config 통합, _summary.md 생성 명확화)
> 상태: Approved — 구현 단계로 진행 가능

---

## 1. 문제

기존 `docs-restructurer`는 Phase 1~5를 한 세션에서 처리한다. 중소규모 프로젝트에서는 동작하지만, 대규모 프로젝트(product-spec 5개 이상)에서 다음 문제가 발생한다:

1. **컨텍스트 압축으로 인한 품질 저하** — 세션이 길어지면 초반에 읽은 양식 규칙, 원본 기획서의 디테일을 정확히 재현하지 못한다
2. **domain-extract 시 내용 생략** — "요약"하면서 중요한 디테일이 빠진다
3. **Phase 2 갭 분석의 깊이 부족** — 컨텍스트가 이미 차 있어서 체크리스트 항목을 구체적으로 따지지 못하고 대충 넘어간다
4. **수동 세션 관리** — 기존 `docs-analyzer` + `docs-generator` 분리가 있지만, 사용자가 직접 세션을 열고 프롬프트를 작성해야 한다

`docs-orchestrator`는 이 모든 문제를 해결하는 **상태 기반 자동 세션 관리자**다.

---

## 2. 핵심 설계 원칙

### 2.1 "추출, 요약 금지"

domain-extracts에는 원본 기획서의 해당 부분을 **그대로 복사**한다. AI가 재해석하거나 압축하면 정보 손실이 발생한다. 관련 없는 부분만 제거하고, 관련 있는 부분은 원문 그대로 유지한다.

### 2.2 "한 세션, 한 집중"

각 세션은 하나의 명확한 목표만 수행한다. 세션이 컨텍스트 한계에 도달하기 전에 끝나는 단위로 쪼갠다.

### 2.3 "상태 파일이 유일한 진실"

세션 간 맥락 전달은 오직 파일을 통해서만 한다. 오케스트레이터는 상태 파일을 읽고 다음 행동을 결정한다. "기억"에 의존하지 않는다.

### 2.4 "도메인 → 기능 2단계 분할"

대규모 프로젝트에서 도메인 단위만으로는 여전히 크다. 도메인 아래 기능(feature) 단위로 한 번 더 쪼갠다.

### 2.5 "중복 허용, 참조 금지"

domain-extracts의 기능별 파일은 **self-contained** 단위여야 한다. 한 문단이 2개 이상의 기능에 관련되면 양쪽 다 복사하여 중복을 허용한다. "shared.md 참조" 같은 간접 참조는 금지한다.

**3계층 중복 관리 규칙**:

- **`shared.md`**: 모든 도메인이 참조하는 기술 스택, 설계 원칙, 공통 데이터 타입
- **`_overview.md`**: 해당 도메인 내 여러 기능이 공유하는 맥락 (도메인 수준 비즈니스 규칙, 공통 플로우)
- **기능별 `{기능}.md`**: 해당 기능에 직접 관련된 원문. self-contained — 이 파일만 읽으면 해당 기능의 전체 맥락을 파악할 수 있어야 함

**중복 추적**: 복사할 때 해당 문단 앞에 `<!-- SOURCE: 원본파일명#섹션 -->` 주석을 달아 출처를 추적한다. Phase 4-1 정합성 검사에서 같은 SOURCE 태그를 가진 내용의 모순 여부를 확인할 수 있다.

### 2.6 "순차 실행, 병렬 금지"

모든 세션은 **순차적으로** 실행한다. Phase 2의 기능별 갭 분석처럼 논리적으로 독립적인 세션이 있더라도, 현재 Claude Desktop은 이전 세션으로 돌아가서 응답을 입력하는 것이 어렵다. 병렬 세션을 열면 Watch 모드가 어떤 세션에 응답해야 하는지 혼란이 생긴다. 향후 Claude Desktop이 세션 간 전환을 지원하면 병렬 실행을 검토할 수 있다.

### 2.7 "완료 마커로 검증"

모든 AI 세션의 출력 파일은 마지막 줄에 완료 마커 `<!-- ORCHESTRATOR:DONE -->`를 반드시 기록한다. 오케스트레이터는 출력 파일 존재 + 완료 마커 존재를 함께 확인하여 세션 완료를 판단한다. 파일이 존재하지만 마커가 없으면 불완전한 것으로 간주한다.

**마커 누락 fallback (2단계)**:

AI가 마커 기록 지시를 잊을 수 있으므로, 마커 없이 파일이 존재하는 경우 내용 기반 fallback을 적용한다:

1. 마커 없음 + 파일 존재 + 파일 줄 수가 Phase별 최소 기준 이상 → "마커 누락 의심" 상태로 전환, `idle_grace_seconds`(30초) 추가 대기
2. 추가 대기 후에도 마커 없음 + 줄 수 기준 충족 → **내용 기반 완료 판정**으로 전환. `orchestrator-state.json`에 `"marker_missing": true` 경고를 기록하고 다음 단계로 진행
3. 줄 수 기준 미충족이면 → 재시도

**Phase별 최소 줄 수 기준** (코드에 하드코딩):

| Phase | 산출물 | 최소 줄 수 |
|-------|--------|-----------|
| Phase 1 | analysis-report.md | 30줄 |
| Phase 1 | domain-extract 기능별 파일 | 10줄 |
| Phase 2 | gap-report | 20줄 |
| Phase 3 | product-spec | 50줄 |
| Phase 3 | design-doc | 30줄 |
| Phase 4 | phase4-*.md | 20줄 |
| Phase 5 | exec-plan | 30줄 |

---

## 3. 오케스트레이터 동작 흐름

오케스트레이터는 cowork-pilot CLI의 **새 모드**로 구현한다. 기존 `--mode harness`가 exec-plan의 chunk를 순차 실행하듯, `--mode docs-orchestrator`가 Phase/도메인/기능을 순차 실행한다.

**실행 방법:**
```bash
cowork-pilot --mode docs-orchestrator --docs-mode auto     # AI가 갭 분석 결정
cowork-pilot --mode docs-orchestrator --docs-mode manual   # 사용자가 갭 분석 답변
cowork-pilot --mode docs-orchestrator --docs-mode auto --manual-override payment,auth
```

오케스트레이터는 **파이썬 스크립트**다. AI 세션이 아니다. 상태 파일을 읽고 if/else 로직으로 다음 할 일을 판단하고, 기존 `session_opener.open_new_session()`으로 Cowork 세션을 여는 상태 머신이므로 컨텍스트 한계가 없다.

```
cowork-pilot --mode docs-orchestrator 실행
  │
  ▼
상태 파일(orchestrator-state.json) 존재?
  │
  ├─ NO → Phase 0 (초기 설정) 실행
  │        → 사용자에게 모드 질문 (auto/manual)
  │        → orchestrator-state.json 생성
  │
  └─ YES → 상태 파일 로드 (json.load)
           │
           ▼
         현재 상태 판단 (if/else)
           │
           ├─ status == "running" → 재개 복구 로직 (§8.3)
           │
           └─ status == "idle" →
                 다음 할 일 결정
                   │
                   ▼
                 세션 프롬프트 생성 (템플릿 기반)
                   │
                   ▼
                 Cowork 세션 열기
                   │
                   ▼
                 [auto 모드] Phase 1 Watch cooperative loop 시작
                   │
                   ▼
                 세션 완료 대기 (출력 파일 + 완료 마커 확인)
                   │
                   ▼
                 상태 파일 업데이트
                   │
                   ▼
                 다음 단계로 (반복)
```

### 3.1 오케스트레이터의 역할 범위

오케스트레이터는 **파이썬 스크립트**이므로 무거운 작업을 하지 않는다. 역할은:

- 상태 파일 파싱 (JSON → 구조체)
- 다음 할 일 결정 (상태 머신 로직)
- 세션 프롬프트 생성 (템플릿 + 변수 치환)
- Cowork 세션 열기 (API 호출)
- [auto 모드] Phase 1 Watch cooperative loop 실행
- 세션 완료 대기 (출력 파일 + 완료 마커 폴링)
- 상태 파일 업데이트 (구조체 → JSON)

실제 분석, 문서 생성, 검증은 모두 **AI 자식 세션**이 수행한다. 오케스트레이터 자체는 AI가 아니므로 컨텍스트 압축 문제가 발생하지 않는다.

---

## 4. 상태 파일 설계

### 4.1 orchestrator-state.json

상태 파일은 **JSON 형식**으로 관리한다. 파이썬에서 `json.load`/`json.dump`로 처리하므로 별도 파서가 필요 없다. 사람이 확인해야 할 때는 터미널에 진행 상황을 출력하거나, 오케스트레이터가 마크다운 뷰를 별도 생성한다.

```json
{
  "updated_at": "2026-03-30T14:00:00",
  "mode": "auto",
  "manual_override": ["payment", "auth"],
  "project_dir": "/path/to/project",

  "current": {
    "phase": "phase_2",
    "step": "phase_2:payment:refund",
    "status": "idle"
  },

  "project_summary": {
    "type": "web-app",
    "source_docs": ["기획서1.md", "기획서2.md"],
    "domains": ["payment", "booking", "user"],
    "features": {
      "payment": ["payment-methods", "refund", "settlement"],
      "booking": ["reservation", "calendar"],
      "user": ["auth", "profile", "settings"]
    },
    "estimated_sessions": 25,
    "estimated_docs": 18
  },

  "completed": [
    {
      "step": "phase_1",
      "completed_at": "2026-03-30T14:00:00",
      "result": "success",
      "note": "도메인 3개, 기능 10개 식별"
    },
    {
      "step": "phase_2:payment:payment-methods",
      "completed_at": "2026-03-30T14:30:00",
      "result": "success",
      "note": "점수 2.7/3.0"
    }
  ],

  "pending": [
    {
      "step": "phase_2:booking:reservation",
      "depends_on": "phase_1",
      "estimated_sessions": 1
    },
    {
      "step": "phase_2:booking:calendar",
      "depends_on": "phase_1",
      "estimated_sessions": 1
    }
  ],

  "errors": [
    {
      "at": "2026-03-30T15:30:00",
      "step": "phase_2:payment:settlement",
      "error": "세션 타임아웃",
      "action": "재시도 예정"
    }
  ]
}
```

### 4.2 domain-extracts 구조 (2단계 분할)

```
docs/generated/
├── orchestrator-state.json        ← 오케스트레이터 상태 (JSON)
├── references/                    ← Phase 0에서 복사한 참조 파일
│   ├── checklists.md
│   ├── output-formats.md
│   └── quality-criteria.md
├── analysis-report.md             ← Phase 1 산출물
├── gap-reports/                   ← Phase 2 산출물 (기능별)
│   ├── _summary.md                ← 전체 갭 분석 요약 (종합 점수)
│   ├── payment--payment-methods.md
│   ├── payment--refund.md
│   ├── payment--settlement.md
│   ├── booking--reservation.md
│   └── booking--calendar.md
├── domain-extracts/               ← Phase 1 산출물 (원문 추출)
│   ├── shared.md                  ← 공통 정보 (기술 스택, 설계 원칙)
│   ├── payment/
│   │   ├── _overview.md           ← 결제 도메인 전체 맥락 (짧게)
│   │   ├── payment-methods.md     ← 결제 수단 관련 원문
│   │   ├── refund.md              ← 환불 관련 원문
│   │   └── settlement.md          ← 정산 관련 원문
│   └── booking/
│       ├── _overview.md
│       ├── reservation.md
│       └── calendar.md
├── exec-plan-outline.md           ← Phase 5 outline 산출물 (중간 산출물이므로 generated/ 내에 위치)
└── progress.md                    ← 문서 생성 진행 상황
```

> **참고**: `exec-plan-outline.md`는 오케스트레이터의 중간 산출물이므로 `docs/generated/`에 위치한다. Phase 5-detail에서 생성되는 최종 exec-plan 파일들은 harness가 실행하는 `docs/exec-plans/planning/`에 저장된다.

```text
# (최종 exec-plan 위치 — 위 generated/ 외부)
docs/exec-plans/planning/         ← Phase 5-detail 산출물 (harness가 실행)
```

---

## 5. 세션 분할 설계

### 5.0 Phase 0: 초기 설정 (오케스트레이터 자체에서 수행)

오케스트레이터가 직접 수행한다 (새 세션 없이):

1. 프로젝트 폴더에 `docs/` 존재 여부 확인
2. 이미 있으면 어디까지 진행됐는지 파악
3. 원본 기획서 파일 목록 확인
4. 사용자에게 모드 선택 질문 (auto / manual)
5. `docs/generated/references/`에 참조 파일 복사 (오케스트레이터 스킬의 `references/` → 프로젝트 내)
6. **예상 세션 수 + 소요 시간 산출 및 사용자 확인**:
   - 산출 공식: Phase 1(원본 3000줄 이하면 1, 초과면 1+도메인 수) + Phase 2(기능 묶음 적용 후 세션 수) + Phase 3(그룹 A/B/C/D 세션 수) + Phase 4(3) + Phase 5(1 + exec-plan 수)
   - 예상 소요 시간: 세션 수 × 5분 (낙관적) ~ 세션 수 × 10분 (보수적)
   - 터미널에 "예상 세션: N개, 예상 소요: ~M분" 출력 후 `y/n` 확인
   - `n`이면 중단. 사용자가 원본 기획서를 줄이거나 설정을 바꿔서 재실행
   - 구현: `orchestrator_state.py`의 `estimate_sessions()` 순수 함수
7. `orchestrator-state.json` 초기 생성 (`estimated_sessions` 필드에 산출 결과 저장)

### 5.1 Phase 1: 구조 분석 + 원문 추출

**세션 수**: 1개 (소규모~중규모) 또는 도메인별 N개 (대규모)

**판단 기준**: 원본 기획서 총 분량이 약 3000줄 이하면 1세션, 초과하면 2단계로 나눈다.

#### 1세션 처리 (소~중규모)

**세션 프롬프트**:
```
프로젝트 경로: {경로}
원본 기획서: {파일 목록}

다음을 수행하라:
1. 원본 기획서를 모두 읽는다
2. 프로젝트 타입을 추론한다
3. 도메인과 기능을 식별하고 분할 계획을 수립한다
4. analysis-report.md를 작성한다
5. domain-extracts/를 생성한다
   - 중요: "요약"하지 말고 관련 원문을 그대로 복사하라
   - 관련 없는 부분만 제거하라
   - 기능별로 파일을 나눠라 (도메인/기능.md)
   - 한 문단이 여러 기능에 관련되면 양쪽 다 복사하라 (중복 허용)
   - 복사한 문단 앞에 <!-- SOURCE: 원본파일명#섹션 --> 주석을 달아라
6. shared.md에는 모든 도메인이 참조하는 공통 정보를 담는다
7. 모든 출력 파일의 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라

docs/generated/references/output-formats.md와 project-conventions.md를 참고하라.
```

#### 2단계 처리 (대규모)

- **세션 1a**: 전체 구조 분석 + analysis-report + 도메인/기능 분할 계획 + shared.md
- **세션 1b-1**: 도메인1 원문 추출 → `domain-extracts/도메인1/`
- **세션 1b-2**: 도메인2 원문 추출 → `domain-extracts/도메인2/`
- ...

각 1b-N 세션은 analysis-report.md + 해당 도메인의 원본 기획서만 읽는다.

### 5.1.1 Phase 1.5: 추출 품질 게이트 (오케스트레이터 자체에서 수행)

Phase 1 세션 완료 후, 오케스트레이터가 **AI 세션 없이 파이썬으로 직접** 산출물을 검증한다. Phase 1 산출물의 품질이 낮으면 Phase 2~5 전체가 영향을 받으므로, 여기서 조기 차단한다.

**검증 1 — 커버리지 비율**:
원본 기획서 총 줄 수 대비 domain-extracts 총 줄 수 비율을 측정한다. "요약 금지, 그대로 복사" 원칙이므로 extracts가 원본보다 적으면 안 된다 (중복 허용이므로 같거나 커야 정상).
- 기준: `extracts_total_lines / source_total_lines >= 0.8`
- config.toml `[docs_orchestrator]` 섹션의 `coverage_ratio_threshold`로 조정 가능 (기본값 0.8)
- 0.8 미만이면 뭔가 빠졌다는 신호

**검증 2 — SOURCE 태그 커버리지**:
domain-extracts 안의 `<!-- SOURCE: 파일명#섹션 -->` 태그를 전부 수집하여, 원본 기획서의 주요 섹션(`## ` 헤더 기준)이 최소 1개 이상의 extract에 매핑되는지 확인한다.
- 파이썬으로 원본에서 `^## ` 패턴으로 섹션 목록을 추출
- SOURCE 태그에서 `#` 뒤의 섹션명을 파싱하여 교차 확인
- 커버되지 않은 원본 섹션이 있으면 경고

**검증 3 — 빈 파일 검사**:
analysis-report.md의 기능 목록에 있는 모든 기능에 대해 대응하는 domain-extract 파일이 존재하고 **최소 10줄 이상**인지 확인한다. 파일이 없거나 너무 짧으면 추출이 안 된 것이다.

**실패 시 동작**:
- 검증 1, 2 실패 → 사용자에게 macOS 알림 + 3가지 선택지: (1) Phase 1 재시도, (2) 수동 확인 후 계속, (3) 중단
- 검증 3 실패 → 누락된 기능만 **추가 추출 세션**을 열어 보충 (전체 재시도 불필요)

**구현**: `quality_gate.py` 모듈, 순수 함수 `check_phase1_quality(project_dir) -> GateResult`

```python
@dataclass
class GateResult:
    passed: bool
    coverage_ratio: float          # 검증 1: extracts/source 비율
    uncovered_sections: list[str]  # 검증 2: SOURCE 태그에 없는 원본 섹션
    missing_features: list[str]    # 검증 3: 파일 없거나 10줄 미만인 기능
    warnings: list[str]
```

### 5.2 Phase 2: 갭 분석 (기능별 세션)

**세션 수**: 기능 수만큼 (단, 작은 기능은 묶을 수 있음)

**묶음 기준 (원문 분량 기반)**: 해당 기능의 domain-extract 줄 수로 판단한다.
- domain-extract **200줄 이하**: 2~3개 기능을 한 세션에 묶는다
- domain-extract **200줄 초과**: 단독 세션으로 처리한다
- Phase 1에서 각 기능별 domain-extract의 줄 수를 `analysis-report.md`에 기록해두면, 오케스트레이터가 이 숫자로 자동 판단한다
- config.toml `[docs_orchestrator]` 섹션의 `feature_bundle_threshold_lines`로 조정 가능 (기본값 200, 실험 후 조정 예정 — 현재 추정 기반 기본값)

**각 세션이 읽는 파일**:
- `docs/generated/references/checklists.md` — 체크리스트 정의
- `docs/generated/analysis-report.md` — 프로젝트 전체 맥락
- `docs/generated/domain-extracts/shared.md` — 공통 정보
- `docs/generated/domain-extracts/{도메인}/{기능}.md` — 해당 기능 원문
- `docs/generated/domain-extracts/{도메인}/_overview.md` — 도메인 맥락

**세션 프롬프트 (manual 모드)**:
```
프로젝트 경로: {경로}
대상 기능: {도메인}/{기능}
모드: manual

다음을 수행하라:
1. 위 파일들을 읽는다
2. docs/generated/references/checklists.md의 product-spec 체크리스트를 적용한다
3. 미충족(1점) 항목은 사용자에게 AskUserQuestion으로 질문한다
   - 반드시 구체적 선택지를 제시하라
   - 에러 패스, 데이터 스키마, 성능 기준 등 빠진 것을 빠짐없이 물어라
4. 부분 충족(2점) 항목은 구체화 방향을 제안하고 확인한다
5. 결과를 docs/generated/gap-reports/{도메인}--{기능}.md에 저장한다
   - 사용자 응답의 설계 의도와 방향성도 함께 기록하라
6. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
```

**세션 프롬프트 (auto 모드)**:
```
프로젝트 경로: {경로}
대상 기능: {도메인}/{기능}
모드: auto

다음을 수행하라:
1. 위 파일들을 읽는다
2. docs/generated/references/checklists.md의 product-spec 체크리스트를 적용한다
3. 미충족/부분 충족 항목에 대해:
   - 원본 기획서의 의도를 분석하여 가장 합리적인 방향으로 결정한다
   - 각 결정에 [AI_DECISION] 태그를 붙이고 근거를 명시한다
   - 가능하면 업계 일반적인 패턴을 따른다
   - 프로젝트의 기존 패턴과 일관성을 유지한다
4. 결과를 docs/generated/gap-reports/{도메인}--{기능}.md에 저장한다
   - [AI_DECISION] 태그가 붙은 항목을 별도 섹션으로 모아 사용자가 나중에 한눈에 리뷰 가능하게 한다
5. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
```

**Phase 2 완료 후**: 오케스트레이터가 모든 gap-report를 취합하여 `gap-reports/_summary.md`를 생성한다.

### 5.3 Phase 3: 문서 생성 (기능별 세션)

**세션 수**: 그룹별로 나눈다.

- **세션 3-A**: 그룹 A (design-docs/) — core-beliefs, data-model, auth, deployment
- **세션 3-B-1 ~ 3-B-N**: 그룹 B (product-specs/) — 기능별 또는 도메인별 1세션
- **세션 3-C**: 그룹 C (ARCHITECTURE, DESIGN_GUIDE, SECURITY)
- **세션 3-D**: 그룹 D (AGENTS.md) — **반드시 마지막**. AGENTS.md는 다른 모든 docs의 Directory Map을 포함해야 하므로, 모든 문서가 확정된 후에 생성한다

**기능 묶음 기준 (원문 분량 기반)**: Phase 2와 동일하게 domain-extract 줄 수로 판단한다 (`feature_bundle_threshold_lines` 설정 공유). **한 세션에 묶는 기능 수는 최대 2개**로 제한한다 (`max_bundle_size` 설정).
- domain-extract **200줄 이하**: 최대 2개 묶음
- domain-extract **200줄 초과**: 단독 세션

**묶음 품질 자동 조정**: Phase 4-2 체크리스트 재평가에서 묶음 세션의 **마지막 문서**에 대해 추가 검증 항목("이 문서가 output-formats.md의 필수 섹션을 모두 포함하는가?")을 적용한다. 묶음 후반 문서의 품질 저하가 3건 이상 발견되면, 오케스트레이터가 이후 Phase에서 묶음을 비활성화하고 전부 단독 세션으로 전환한다 (`orchestrator-state.json`에 `"bundle_disabled": true` 플래그 기록).

**각 세션이 읽는 파일**:
- `docs/generated/references/output-formats.md` — 문서 양식 (매 문서마다 재참조)
- `docs/generated/analysis-report.md` — 프로젝트 맥락
- `docs/generated/gap-reports/{도메인}--{기능}.md` — 해당 기능 갭 분석 결과
- `docs/generated/domain-extracts/shared.md` — 공통 정보
- `docs/generated/domain-extracts/{도메인}/{기능}.md` — 해당 기능 원문
- `project-conventions.md` — 있으면 참조

**세션 프롬프트 (Phase 3-B 예시)**:
```
프로젝트 경로: {경로}
대상: product-specs — {기능1}, {기능2}, {기능3}

다음을 수행하라:

각 product-spec에 대해 이 루프를 반복하라:
  ① RE-READ: docs/generated/references/output-formats.md의 product-spec 섹션을 다시 읽는다
  ② RE-READ: 해당 기능의 gap-report와 domain-extract를 다시 읽는다
  ③ GENERATE: product-spec 1개를 생성한다
     - 입력 원문의 실제 내용을 변환한다. TBD/TODO 사용 금지
     - GUIDE 주석 삽입 금지
     - gap-report의 보강 내용을 반드시 활용한다
  ④ VALIDATE: 방금 쓴 파일을 다시 읽어 검증한다
     - 양식 일치, 금지 표현 부재, 측정 가능 수치 존재
  ⑤ SAVE: 검증 통과 후 저장 + progress.md 기록
  ⑥ DONE: 모든 파일의 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커 기록

"이미 읽었으니 기억한다"는 생각을 하지 말라. 매 문서마다 반드시 RE-READ하라.
```

### 5.4 Phase 4: 품질 검토 (3세션 분할)

Phase 4는 검증 항목별로 세션을 나눈다. 어떤 세션도 docs/ 전체를 한꺼번에 읽지 않는다.

#### 세션 4-1: 정합성 검사

docs/ 전체를 통째로 읽지 않고, **교차 검증이 필요한 섹션만 발췌**해서 비교한다.

**읽는 파일**:
- `docs/generated/references/quality-criteria.md` §1 (정합성 기준)
- `docs/design-docs/data-model.md` — 엔티티 정의
- 모든 product-spec의 **데이터/API 관련 섹션만** (섹션 번호가 아니라 제목에 "데이터", "API", "Data", "Schema", "엔티티" 키워드가 포함된 `##` 헤더 아래 섹션. 전체 문서가 아니라 해당 섹션만)
- `ARCHITECTURE.md`의 디렉토리 구조 섹션 (제목에 "디렉토리", "Directory", "구조", "Structure" 포함)
- `AGENTS.md` Directory Map 섹션
- `docs/design-docs/index.md`, `docs/product-specs/index.md`

> **참고**: 섹션 번호(§4 등)가 아니라 **섹션 제목 키워드**로 매칭한다. 프로젝트 타입에 따라 섹션 순서가 달라질 수 있기 때문이다. 오케스트레이터가 프롬프트를 생성할 때 `output-formats.md`에서 프로젝트 타입별 섹션 제목 목록을 읽어 프롬프트에 주입한다.

**추가 검증**: 같은 `<!-- SOURCE: ... -->` 태그를 가진 domain-extract 내용 간 모순이 없는지 확인한다.

**세션 프롬프트**:
```
프로젝트 경로: {경로}
데이터/API 섹션 키워드: {output-formats.md에서 추출한 키워드 목록}

정합성 검사를 수행하라.

1. 데이터 정합성: 각 product-spec에서 제목에 위 키워드가 포함된 섹션을 찾아,
   data-model.md의 엔티티 필드와 일치하는지 교차 검증
2. 구조 정합성: ARCHITECTURE.md 디렉토리 구조 ↔ AGENTS.md Directory Map 일치 확인
3. 참조 정합성: index.md 목록 ↔ 실제 파일 존재 여부
4. design-docs 간 모순 검사
5. SOURCE 태그 정합성: domain-extracts에서 같은 SOURCE 태그를 가진 내용 간 모순 확인
6. 불일치 발견 시 즉시 수정
7. 결과를 docs/generated/phase4-consistency.md에 저장
8. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
```

#### 세션 4-2: 체크리스트 재평가 (기능별 — Phase 2와 동일 구조)

Phase 2 갭 분석과 같은 구조로, **생성된 product-spec에** 체크리스트를 다시 적용한다.
기능별로 세션을 나눌 수 있다 (대규모 시).

**읽는 파일**:
- `docs/generated/references/checklists.md`
- 해당 기능의 생성된 product-spec
- 해당 기능의 gap-report (Phase 2 점수와 비교)

**세션 프롬프트**:
```
프로젝트 경로: {경로}
대상: {기능1}, {기능2}, ...

생성된 product-spec에 체크리스트를 재적용하라.

1. docs/generated/references/checklists.md의 체크리스트로 각 product-spec을 재평가
2. Phase 2 gap-report의 점수와 비교하여 개선/악화 확인
3. 미흡한 항목 발견 시 즉시 수정
4. 결과를 docs/generated/phase4-rescore.md에 저장
5. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
```

#### 세션 4-3: 표현 품질 스캔 + QUALITY_SCORE.md 작성

금지 표현은 **기계적 검색**(grep)으로 찾고, 4-1과 4-2 결과를 종합하여 점수를 산출한다.

**읽는 파일**:
- `docs/generated/references/quality-criteria.md` §2~§5
- `docs/generated/phase4-consistency.md` (세션 4-1 결과)
- `docs/generated/phase4-rescore.md` (세션 4-2 결과)

**세션 프롬프트**:
```
프로젝트 경로: {경로}

1. 모든 docs/ 파일에서 금지 표현을 grep으로 검색
   ("적절한", "필요시", "충분한", "등등", "TBD", "추후 작성", "TODO")
2. 위반 발견 시 즉시 수정
3. phase4-consistency.md와 phase4-rescore.md를 종합
4. docs/QUALITY_SCORE.md를 quality-criteria.md §5 템플릿에 따라 작성
5. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라
```

### 5.5 Phase 5: exec-plans 생성

**2단계로 나눈다.**

#### 5.5.1 Phase 5-outline: exec-plan 설계 (1세션)

전체 docs/를 읽고 exec-plan의 **목차만** 잡는다.

**세션이 읽는 파일** (docs/ 전체를 읽지 않는다 — §2.2 "한 세션, 한 집중" 원칙 준수):
- `docs/generated/references/output-formats.md` §6 (exec-plan 형식)
- `docs/design-docs/index.md` — 설계 문서 목록
- `docs/product-specs/index.md` — 제품 스펙 목록
- `ARCHITECTURE.md` — 전체 구조 (디렉토리 맵 포함)
- `docs/QUALITY_SCORE.md` — 품질 점수 (우선순위 판단용)
- `docs/generated/analysis-report.md` — 도메인/기능 의존 관계

product-spec 본문이나 design-doc 본문은 읽지 않는다. index가 목차 역할을 하므로 outline 설계에 충분하다.

**세션 프롬프트**:
```
프로젝트 경로: {경로}

exec-plan의 전체 구조를 설계하라. 실제 Session Prompt 내용은 채우지 않는다.

1. 구현 순서를 결정한다 (의존성 분석)
2. exec-plan 파일 목록을 확정한다
3. 각 exec-plan의 Chunk 목록을 확정한다:
   - Chunk 제목
   - Completion Criteria (구체적으로)
   - Tasks 목록
   - Session Prompt는 비워둔다 ("다음 세션에서 작성")
4. 결과를 docs/generated/exec-plan-outline.md에 저장한다
5. 파일 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라

다음 형식으로 작성하라:

## exec-plan 개요

| # | 파일명 | 범위 | Chunk 수 | 의존성 |
|---|--------|------|---------|--------|
| 1 | 01-project-setup.md | 초기화, 설정 | 5 | 없음 |
| 2 | 02-data-layer.md | 데이터 모델, DB | 8 | 01 |
| ... | ... | ... | ... | ... |

예상 총 Chunk 수: {N}개

## 01-project-setup.md 상세

### Chunk 1: {제목}
- Completion Criteria:
  - [ ] {조건1}
  - [ ] {조건2}
- Tasks:
  - Task 1: {내용}
  - Task 2: {내용}
- Session Prompt: (다음 세션에서 작성)

### Chunk 2: ...
...

## 02-data-layer.md 상세
...
```

#### 5.5.2 Phase 5-detail: exec-plan 상세 작성 (exec-plan별 1세션)

**세션 수**: exec-plan 파일 수만큼

**각 세션이 읽는 파일**:
- `docs/generated/references/output-formats.md` §6 (매 Chunk마다 재참조)
- `docs/generated/exec-plan-outline.md` — 해당 exec-plan의 outline
- 해당 exec-plan이 참조하는 product-spec, design-docs만 선별 읽기

**세션 프롬프트**:
```
프로젝트 경로: {경로}
대상: exec-plan {번호}-{이름}.md

docs/generated/exec-plan-outline.md에서 이 exec-plan의 outline을 읽고,
각 Chunk의 Session Prompt를 채워 완성하라.

각 Chunk에 대해 이 루프를 반복하라:
  ① RE-READ: docs/generated/references/output-formats.md §6 (파서 호환 규칙 포함) 다시 읽기
  ② GENERATE: 해당 Chunk의 Session Prompt 작성
     - 반드시 plain triple-backtick으로 열기
     - 중첩 코드 블록 금지
     - Chunk 헤더 금지
     - 끝에 Chunk 완료 워크플로 지시 포함
  ③ VALIDATE: 방금 쓴 파일을 다시 읽어 파서 규격 검증
  ④ SAVE: 검증 통과 후 docs/exec-plans/planning/{번호}-{이름}.md에 저장

"이미 읽었으니 기억한다"는 생각을 하지 말라. 매 Chunk마다 반드시 RE-READ하라.

최종 파일의 마지막 줄에 <!-- ORCHESTRATOR:DONE --> 마커를 기록하라.
```

---

## 6. auto / manual 모드

### 6.1 차이점

| 항목 | manual | auto |
|------|--------|------|
| Phase 2 갭 분석 | 사용자에게 AskUserQuestion으로 질문 | AI가 기획 의도를 읽고 합리적으로 결정 |
| 결정 투명성 | 사용자가 직접 답변 → 별도 태그 없음 | [AI_DECISION] 태그 + 근거 명시 |
| 사용자 개입 | 매 기능마다 Q&A 필요 | Phase 2 완료 후 [AI_DECISION] 일괄 리뷰 |
| 속도 | 느림 (사용자 응답 대기) | 빠름 (자동 진행) |
| Watch 모드 연동 | **하지 않음** (사용자가 직접 Cowork 화면에서 응답) | **cooperative loop 실행** (harness와 동일 패턴) |
| 적합한 상황 | 중요한 프로젝트, 세밀한 제어 필요 | 빠르게 초안 잡고 나중에 수정 |

### 6.2 auto 모드 Watch 연동

auto 모드에서는 기존 harness의 cooperative loop와 동일한 패턴으로 Phase 1 Watch를 동시에 실행한다:

- 세션 열기 후 JSONL 감지
- JSONL tail + WatcherStateMachine으로 도구 권한 요청 자동 응답
- idle 감지 + 출력 파일 완료 마커 확인을 동시 수행

manual 모드에서는 Watch를 돌리지 않는다. 사용자가 Cowork 화면을 직접 보면서 AskUserQuestion에 답변하고, 도구 권한도 직접 처리한다. 오케스트레이터는 세션 완료 대기(출력 파일 + 완료 마커 폴링)만 수행한다.

### 6.3 auto 모드 AI 결정 기록 형식

```markdown
## AI 결정 요약

> 이 섹션의 결정들은 AI가 원본 기획서의 의도를 해석하여 내린 것입니다.
> 각 항목을 검토하고, 수정이 필요하면 알려주세요.

| # | 기능 | 결정 항목 | AI 결정 | 근거 | 수정 필요? |
|---|------|---------|---------|------|----------|
| 1 | 결제/환불 | 에러 처리 방식 | 토스트 알림 + 재시도 | 원본에서 "사용자 친화적 에러 처리" 언급 | |
| 2 | 결제/환불 | 환불 처리 시간 | 3영업일 이내 | 업계 일반 기준 적용 | |
| 3 | 예약/캘린더 | 최대 예약 기간 | 90일 | 원본에 명시 없음, 유사 서비스 참고 | |
```

### 6.4 하이브리드 모드

사용자가 `auto`를 선택하되 특정 도메인만 `manual`로 지정할 수 있다:
```
모드: auto
manual_override: [payment, auth]  ← 결제와 인증은 사용자가 직접 결정
```

하이브리드 모드에서 manual_override 도메인의 세션은 Watch를 돌리지 않고, 나머지 auto 도메인의 세션은 Watch를 돌린다.

---

## 7. 세션 열기 메커니즘

오케스트레이터는 cowork-pilot의 기존 세션 관리 인프라를 재활용한다.

### 7.1 기존 cowork-pilot 인프라 활용

cowork-pilot은 이미 세션 생성을 위한 모듈을 보유하고 있다:

- **`session_opener.py`**: AppleScript로 Claude Desktop에 Shift+Cmd+O → 새 세션 열기 → 클립보드에 프롬프트 붙여넣기 → Enter
- **`session_finder.py`**: JSONL 파일 스캔으로 새로 생성된 세션 감지
- **`session_manager.py`**: chunk 라이프사이클 관리 (프롬프트 빌드 → 세션 열기 → JSONL 감지 → 완료 감지)

docs-orchestrator는 `session_manager.py`의 패턴을 따르되, chunk 단위가 아닌 **Phase/도메인/기능 단위**로 세션을 관리한다. 핵심 함수인 `open_new_session(initial_prompt)` 을 그대로 호출하면 된다.

### 7.2 세션 프롬프트 생성 규칙

각 세션 프롬프트에 반드시 포함할 것:

1. **프로젝트 경로** — 파일을 읽고 쓸 위치
2. **읽어야 할 파일 목록** — 세션 시작 시 반드시 읽을 파일들. 경로를 명시적으로 나열
3. **수행할 작업** — 구체적 단계별 지시
4. **출력 파일** — 결과를 저장할 파일 경로
5. **사용할 스킬** — 해당 세션에서 활용할 스킬 (있으면)
6. **품질 규칙** — RE-READ, VALIDATE 등 반복해야 할 규칙
7. **완료 마커** — 모든 출력 파일 마지막 줄에 `<!-- ORCHESTRATOR:DONE -->` 기록 지시

### 7.3 세션 완료 판단

기존 harness가 JSONL idle 감지 → CLI 검증하는 것처럼, docs-orchestrator도 유사한 패턴을 사용한다. 단, **문서 생성 세션은 코드 구현 세션과 특성이 다르다** — Read 여러 번 → 긴 생각(30초~1분+) → Write 1번 패턴이므로 "생각 시간" 동안 JSONL에 이벤트가 찍히지 않아 idle처럼 보일 수 있다.

**타임아웃 설정**: harness의 `idle_timeout_seconds: 30`과 별도로 관리한다. config.toml의 `[docs_orchestrator]` 섹션에서 로드하며, 서로 영향 없다. **적응형 타임아웃**을 사용하여 실측 데이터를 기반으로 자동 조정한다.

```toml
[docs_orchestrator]
idle_timeout_seconds = 120          # 초기값. 첫 3개 세션에만 적용
completion_poll_interval = 5.0      # 출력 파일 + 완료 마커 폴링 주기 (초)
idle_grace_seconds = 30             # idle 의심 후 추가 대기 시간
feature_bundle_threshold_lines = 200  # 기능 묶음 기준 줄 수
max_bundle_size = 2                 # 한 세션에 묶는 최대 기능 수
coverage_ratio_threshold = 0.8      # Phase 1.5 커버리지 비율 기준
adaptive_timeout_min = 60.0         # 적응형 타임아웃 최솟값 (초)
adaptive_timeout_max = 300.0        # 적응형 타임아웃 최댓값 (초)
adaptive_timeout_multiplier = 1.5   # 실측 평균 × 이 배수 = 새 타임아웃
```

**적응형 타임아웃 동작**:
- 각 세션 완료 시 실제 idle 시간(마지막 JSONL 기록 → 완료 마커 출현까지)을 `orchestrator-state.json`의 `completed` 항목에 `actual_idle_seconds` 필드로 기록
- Phase 2 첫 3개 세션이 완료되면, 실측 평균 × `adaptive_timeout_multiplier`(1.5)를 이후 세션의 타임아웃으로 자동 적용
- 최솟값 `adaptive_timeout_min`(60초), 최댓값 `adaptive_timeout_max`(300초)로 클램핑
- `idle_timeout_seconds: 120`은 첫 3개 세션에만 적용되는 초기값

**완료 판정 로직**:

1. 세션 열기 후 JSONL 감지 (`detect_new_jsonl()`)
2. [auto 모드] Phase 1 Watch cooperative loop 실행
3. **출력 파일 + 완료 마커 폴링**: 해당 세션이 생성해야 할 파일이 존재하고, 마지막 줄에 `<!-- ORCHESTRATOR:DONE -->`이 있는지 확인
4. 세션 idle 감지 (JSONL의 마지막 쓰기 시각 기준, `idle_timeout_seconds` 경과)
5. idle 의심 상태에서:
   - 완료 마커 있음 → 정상 완료
   - 완료 마커 없음 → `idle_grace_seconds`(30초) 추가 대기 후 재확인
   - 재확인 후에도 마커 없음 → **마커 누락 fallback 적용** (§2.7 참조):
     - 파일 줄 수가 Phase별 최소 기준 이상 → 내용 기반 완료 판정 + `"marker_missing": true` 경고 기록
     - 줄 수 기준 미충족 → 재시도
   - JSONL 변화 없고 파일도 없음 → 실패로 판정, 재시도 또는 ESCALATE
6. 출력 파일 + 완료 마커 (또는 fallback) 검증 통과 시 → `orchestrator-state.json` 업데이트 + `actual_idle_seconds` 기록
7. 실패 시 → 에러 로그 기록 + 재시도 또는 ESCALATE

---

## 8. 에러 처리

### 8.1 세션 실패 시

세션이 에러로 끝나면:
1. 에러 내용을 `orchestrator-state.json`의 errors 배열에 기록
2. 사용자에게 선택지 제시:
   - (1) 같은 세션 재시도
   - (2) 해당 단계 건너뛰기
   - (3) 전체 중단

### 8.2 컨텍스트 초과 예방

Phase 1에서 원본 기획서가 너무 크면:
- 도메인별로 Phase 1을 분할 (5.1절 2단계 처리)
- 각 분할 세션이 `analysis-report.md` + 해당 도메인 원본만 읽도록

Phase 2에서 기능이 너무 많으면:
- 기능별로 세션을 나누되, 작은 기능은 2~3개 묶기

Phase 5에서 Chunk가 너무 많으면:
- exec-plan 하나당 1세션으로 분리

### 8.3 중단 후 재개 (재시작 복구 정책)

사용자가 중간에 세션을 종료해도, `orchestrator-state.json`에 진행 상황이 저장되어 있으므로 다시 오케스트레이터를 실행하면 이어서 진행한다.

**재시작 시 `running` 상태 처리 정책**:

오케스트레이터가 시작할 때 상태 파일에서 `status: "running"`인 단계를 발견하면 다음 3단계로 복구한다:

1. **출력 파일 + 완료 마커 확인**: 해당 단계의 예상 출력 파일이 존재하고 완료 마커(`<!-- ORCHESTRATOR:DONE -->`)가 있으면 → `completed`로 전환하고 다음 단계로 진행. (오케스트레이터만 죽고 세션은 정상 완료된 경우)

2. **출력 파일 있지만 마커 없음**: 해당 출력 파일을 삭제하고 `pending`으로 되돌린 뒤 재시도. 불완전한 파일을 남겨두면 다음 세션이 잘못된 입력을 읽을 수 있으므로 깨끗하게 시작한다.

3. **출력 파일 자체가 없음**: 그냥 `pending`으로 되돌리고 재시도. 세션이 시작도 못했거나 중간에 죽은 경우.

---

## 9. 전체 세션 흐름 예시 (대규모 프로젝트)

프로젝트: 도메인 3개, 기능 10개

```
세션 0: [오케스트레이터] 초기 설정 + Phase 0
  → orchestrator-state.json 생성
  → docs/generated/references/ 복사

세션 1: [Phase 1] 전체 구조 분석 + shared.md
  → analysis-report.md, shared.md

세션 2: [Phase 1] 결제 도메인 원문 추출
  → domain-extracts/payment/*.md

세션 3: [Phase 1] 예약 도메인 원문 추출
  → domain-extracts/booking/*.md

세션 4: [Phase 1] 사용자 도메인 원문 추출
  → domain-extracts/user/*.md

세션 5: [Phase 2] 결제/결제수단 갭 분석 (auto + Watch)
  → gap-reports/payment--payment-methods.md

세션 6: [Phase 2] 결제/환불 + 결제/정산 갭 분석 (auto + Watch)
  → gap-reports/payment--refund.md, payment--settlement.md

세션 7: [Phase 2] 예약/예약플로우 갭 분석 (auto + Watch)
  → gap-reports/booking--reservation.md

... (기능별 계속)

세션 N: [Phase 2 완료] 오케스트레이터가 _summary.md 생성

세션 N+1: [Phase 3-A] design-docs/ 생성
  → core-beliefs.md, data-model.md, auth.md, ...

세션 N+2: [Phase 3-B-1] 결제 도메인 product-specs
  → payment-methods.md, refund.md, settlement.md

세션 N+3: [Phase 3-B-2] 예약 도메인 product-specs
  → reservation.md, calendar.md

... (도메인별 계속)

세션 N+M: [Phase 3-C] ARCHITECTURE, DESIGN_GUIDE, SECURITY

세션 N+M+1: [Phase 3-D] AGENTS.md

세션 N+M+2: [Phase 4-1] 정합성 검사 (+ SOURCE 태그 정합성)
  → phase4-consistency.md

세션 N+M+3: [Phase 4-2] 체크리스트 재평가 (기능별)
  → phase4-rescore.md

세션 N+M+4: [Phase 4-3] 표현 품질 스캔 + 종합
  → QUALITY_SCORE.md

세션 N+M+5: [Phase 5-outline] exec-plan 설계
  → exec-plan-outline.md

세션 N+M+6: [Phase 5-detail] 01-project-setup.md 상세
  → docs/exec-plans/planning/01-project-setup.md

세션 N+M+7: [Phase 5-detail] 02-data-layer.md 상세
  → docs/exec-plans/planning/02-data-layer.md

... (exec-plan별 계속)

세션 LAST: [오케스트레이터] 최종 확인 + 완료 보고 (AI 세션 아님)
  → orchestrator-state.json의 모든 단계가 completed인지 확인
  → docs/exec-plans/planning/에 파일이 생성되었는지 확인
  → 터미널에 최종 요약 출력 (총 세션 수, 소요 시간, 에러 수)
  → macOS 알림으로 완료 통지
```

예상 총 세션 수: 약 20~30개 (프로젝트 규모에 비례)

---

## 10. 기존 스킬과의 관계

| 기존 스킬 | docs-orchestrator에서의 역할 |
|----------|--------------------------|
| `docs-restructurer` | 중소규모 프로젝트에서는 여전히 단독 사용. 오케스트레이터는 대규모 전용 |
| `docs-analyzer` | Phase 1~2 로직을 오케스트레이터가 흡수. 독립 사용 불필요 |
| `docs-generator` | Phase 3~5 로직을 오케스트레이터가 흡수. 독립 사용 불필요 |
| `docs-restructurer-large` | 오케스트레이터로 대체 |

오케스트레이터가 안정화되면 `docs-analyzer`, `docs-generator`, `docs-restructurer-large`는 deprecated 가능.

---

## 11. 해결된 설계 결정

| # | 결정 사항 | 결정 | 근거 |
|---|---------|------|------|
| 1 | 세션 묶음 기준 | **원문 분량 기반** (domain-extract 줄 수, 기본 200줄) | 체크리스트 항목 수는 기능마다 동일(8~11개)하여 변별력 없음. 실제 컨텍스트를 차지하는 건 원문 분량. 임계값은 `config.toml`의 `feature_bundle_threshold_lines`로 조정 가능 (실험 후 조정 예정) |
| 2 | Phase 4 분할 | **3세션 분할** (정합성 / 체크리스트 재평가 / 표현 품질+종합) | 어떤 세션도 docs/ 전체를 한꺼번에 읽지 않아야 함 |
| 3 | 오케스트레이터 구현 | **파이썬 스크립트** (AI 세션 아님) | 상태 파일 읽기 + if/else + 세션 열기는 AI가 필요 없음. 컨텍스트 문제 원천 제거 |
| 4 | references/ 위치 | **Phase 0에서 프로젝트 내 `docs/generated/references/`에 복사** | 각 자식 세션이 독립적이므로 스킬이 자동 로드되지 않음. 프로젝트 내 경로로 명시적으로 Read 지시 |
| 5 | 세션 생성 방법 | **cowork-pilot 기존 인프라 재활용** (`session_opener.open_new_session()`) | cowork-pilot이 이미 AppleScript 기반 세션 열기 + JSONL 감지 + idle 감지를 구현하고 있음 |
| 6 | domain-extract 줄 수 기록 | **Phase 1 세션이 파일 저장 직후 `wc -l`로 줄 수 측정 → analysis-report.md에 기록** | 오케스트레이터가 세션 완료 후 파일 시스템에서 직접 측정해도 됨 (파이썬 스크립트이므로 `os.path` 접근 가능) |
| 7 | Phase 4-2 분할 단위 | **Phase 2와 동일한 묶음 기준 적용** (domain-extract 200줄 기준) | 도메인 + 기능별로 최대한 세세하게 나눠야 품질 유지 가능 |
| 8 | 상태 파일 포맷 | **JSON** (`orchestrator-state.json`) | 마크다운 파싱 복잡도 제거. `json.load`/`json.dump`로 처리. 사람 확인용은 터미널 출력 또는 별도 마크다운 뷰 생성 |
| 9 | 원문 중복 처리 | **중복 허용 + SOURCE 태그 추적** | 각 기능별 파일을 self-contained로 유지하여 세션당 읽기 횟수 최소화. `<!-- SOURCE: 원본파일명#섹션 -->` 주석으로 출처 추적, Phase 4에서 정합성 검증 |
| 10 | 세션 완료 판단 | **출력 파일 존재 + 완료 마커** (`<!-- ORCHESTRATOR:DONE -->`) | 파일만 존재하면 불완전할 수 있음. 마커로 세션이 정상 종료까지 도달했는지 확인 |
| 11 | Watch 모드 연동 | **auto 모드만 cooperative loop 실행**, manual 모드는 Watch 없음 | auto는 사용자 개입 없이 자동 진행해야 하므로 도구 권한 자동 응답 필요. manual은 사용자가 직접 Cowork 화면에서 응답 |
| 12 | 중단 후 재개 | **3단계 복구 정책** (마커 확인 → 불완전 파일 삭제 → pending으로 되돌림) | 단순하고 안전한 복구. 불완전한 파일이 다음 세션에 전파되지 않도록 깨끗하게 시작 |
| 13 | Phase 1 품질 게이트 | **Phase 1.5로 파이썬 기계 검증 추가** (커버리지 비율 + SOURCE 태그 + 빈 파일) | Phase 1 산출물이 낮으면 Phase 2~5 전체 영향. 조기 차단 필요 |
| 14 | 병렬 세션 | **순차 실행만 지원** | Claude Desktop에서 이전 세션으로 돌아가 응답하기 어려움. Watch 모드 혼란 방지 |
| 15 | Phase 5-outline 읽기 범위 | **index.md + ARCHITECTURE.md + QUALITY_SCORE.md + analysis-report.md만 읽기** | "docs/ 전체 읽기"는 §2.2 원칙과 충돌. index가 목차 역할을 하므로 본문 불필요 |
| 16 | docs-orchestrator 타임아웃 | **harness와 별도 관리** (`idle_timeout_seconds: 120`) + **적응형 타임아웃** | 문서 생성 세션은 Read→긴 생각→Write 패턴. 30초로는 부족. 첫 3개 세션 실측 후 자동 조정 |
| 17 | Phase 0 사용자 확인 | **예상 세션 수 + 소요 시간 출력 후 y/n 확인** | docs-orchestrator는 20~30 세션을 소비하므로 사용자가 사전에 규모를 인지해야 함 |
| 18 | 묶음 최대 크기 | **최대 2개** (`max_bundle_size`) + **품질 저하 시 자동 비활성화** | RE-READ 지시를 AI가 무시할 수 있으므로 묶음 크기를 제한. Phase 4-2에서 3건 이상 품질 저하 발견 시 `bundle_disabled` 플래그 |
| 19 | 마커 누락 fallback | **내용 기반 fallback** (Phase별 최소 줄 수 기준 충족 시 완료 판정) | AI가 마커 지시를 잊을 수 있음. 줄 수 기준은 코드에 하드코딩 |
| 20 | Phase 4-1 섹션 매칭 | **섹션 제목 키워드 매칭** (번호가 아닌 "데이터", "API" 등 키워드) | 프로젝트 타입에 따라 섹션 순서가 달라질 수 있으므로 번호 의존 제거 |
| 21 | `_summary.md` 생성 | **오케스트레이터(파이썬)가 기계적으로 생성** (AI 세션 아님) | gap-report에서 점수 행 + [AI_DECISION] 수를 정규식으로 추출하여 테이블 합산. §12.5 참조 |
| 22 | references/ 파일 출처 | **오케스트레이터 스킬에 번들** → Phase 0에서 프로젝트 내로 복사 | 기존 docs-restructurer 프롬프트에서 인라인으로 사용하던 양식/기준을 파일로 분리. §12.2 참조 |

---

## 12. 구현 상세

### 12.1 모듈 분할

```
src/cowork_pilot/
├── docs_orchestrator.py        ← 메인 상태 머신 + 루프 (run_docs_orchestrator())
├── quality_gate.py             ← Phase 1.5 검증 (check_phase1_quality())
├── orchestrator_prompts.py     ← Jinja2 템플릿 로드 + 변수 치환 (build_session_prompt())
├── orchestrator_state.py       ← OrchestratorState dataclass + load/save + estimate_sessions() + 적응형 타임아웃 계산
├── orchestrator_templates/     ← Jinja2 프롬프트 템플릿 (.j2 파일)
│   ├── phase1_single.j2
│   ├── phase1_domain.j2
│   ├── phase2_auto.j2
│   ├── phase2_manual.j2
│   ├── phase3_design_docs.j2
│   ├── phase3_product_spec.j2
│   ├── phase3_architecture.j2
│   ├── phase3_agents.j2
│   ├── phase4_consistency.j2
│   ├── phase4_rescore.j2
│   ├── phase4_quality.j2
│   ├── phase5_outline.j2
│   └── phase5_detail.j2
└── (기존 모듈들은 변경 없음)
```

**역할 분담**:

| 모듈 | 역할 | 기존 대응 모듈 |
|------|------|--------------|
| `docs_orchestrator.py` | Phase 판단 → 프롬프트 생성 → 세션 열기 → 완료 대기 → 상태 업데이트 루프 | `main.py`의 `run_harness()` |
| `quality_gate.py` | Phase 1.5 기계 검증 3종 | (신규) |
| `orchestrator_prompts.py` | 세션 프롬프트 생성 (Jinja2) | `session_manager.py`의 `build_session_prompt()` |
| `orchestrator_state.py` | 상태 직렬화/역직렬화 + 산출 로직 | `plan_parser.py` (exec-plan 파싱과 유사한 위상) |

### 12.2 references/ 파일 정의

3개 파일은 **오케스트레이터 스킬에 번들**된다. `skills/docs-orchestrator/references/` 디렉토리에 위치하며, Phase 0에서 프로젝트의 `docs/generated/references/`로 복사한다.

**`checklists.md`**:
- product-spec 체크리스트 항목 정의
- 프로젝트 타입별(web-app, api, mobile) 체크리스트
- 각 항목은 "충족(3점)/부분충족(2점)/미충족(1점)" 3단계 평가 기준
- 출처: 기존 `docs-restructurer` 스킬의 Phase 2에서 프롬프트에 인라인으로 넣던 체크리스트를 파일로 분리

**`output-formats.md`**:
- 각 문서 타입(design-doc, product-spec, ARCHITECTURE, AGENTS.md 등)의 필수 섹션 + 양식 규칙
- 프로젝트 타입별 섹션 수 차이 정의 (web-app: 11섹션, api: 8~10섹션)
- 각 섹션의 제목 키워드 목록 포함 (Phase 4-1 정합성 검사에서 활용)
- 출처: 기존 `docs-restructurer`의 Phase 3에서 프롬프트에 인라인으로 넣던 양식 규칙을 파일로 분리

**`quality-criteria.md`**:
- §1: 정합성 기준 (데이터 모델 ↔ product-spec 교차 검증 규칙)
- §2: 표현 품질 (금지 표현 목록: "적절한", "필요시", "충분한", "등등", "TBD", "추후 작성", "TODO")
- §3: 측정 가능성 기준 (구체적 수치, exit code, 파일 존재 여부 등)
- §4: 커버리지 기준 (원본 기획서 대비 docs/ 커버율)
- §5: QUALITY_SCORE.md 템플릿 (도메인별 점수표 형식)
- 출처: 기존 `docs-restructurer`의 Phase 4에서 프롬프트에 인라인으로 넣던 기준을 파일로 분리

이 3개 파일의 초안은 구현 계획의 **첫 번째 Chunk**에서 기존 `docs-restructurer` 스킬의 프롬프트에서 추출하여 작성한다.

### 12.3 config.toml 통합

기존 `config.py`에 `DocsOrchestratorConfig` dataclass를 추가하고 `load_docs_orchestrator_config()` 함수를 만든다. 기존 `load_harness_config()`, `load_meta_config()` 패턴과 동일하다.

```python
@dataclass
class DocsOrchestratorConfig:
    idle_timeout_seconds: float = 120.0
    completion_poll_interval: float = 5.0
    idle_grace_seconds: float = 30.0
    feature_bundle_threshold_lines: int = 200
    max_bundle_size: int = 2
    coverage_ratio_threshold: float = 0.8
    adaptive_timeout_min: float = 60.0
    adaptive_timeout_max: float = 300.0
    adaptive_timeout_multiplier: float = 1.5
    docs_mode: str = "auto"       # "auto" | "manual"
    manual_override: list[str] = field(default_factory=list)

    # Session timing (기존 HarnessConfig와 동일 패턴)
    session_open_delay: float = 3.0
    session_prompt_delay: float = 1.0
    session_detect_timeout: float = 10.0
    session_detect_poll_interval: float = 1.0

    # Engine (main Config에서 상속)
    engine: str = "claude"
    engine_command: str = "claude"
    engine_args: list[str] = field(default_factory=lambda: ["-p"])
```

`main.py`의 `cli()` 함수에 추가:
- `--mode docs-orchestrator` (기존 choices에 추가)
- `--docs-mode` (auto/manual, 기본값 auto)
- `--manual-override` (콤마 구분 도메인 목록)

### 12.4 테스트 전략

4개 테스트 파일을 추가한다. 모두 기존 패턴대로 외부 CLI/AppleScript 호출 없이 로직만 단위 테스트한다.

**`tests/test_orchestrator_state.py`**:
- `OrchestratorState` 직렬화 → JSON → 역직렬화 라운드트립
- `estimate_sessions()`: 도메인 3개/기능 10개 입력 → 예상 세션 수 산출 검증
- 적응형 타임아웃 계산: 실측 [80, 90, 100]초 → 평균 90 × 1.5 = 135초 (60~300 클램핑 확인)
- `running` 상태 복구 로직: 마커 있음 → completed, 마커 없음 + 파일 있음 → pending 되돌림

**`tests/test_quality_gate.py`**:
- 검증 1 (커버리지 비율): `tmp_path`에 원본 100줄 + extracts 85줄 → pass, 70줄 → fail
- 검증 2 (SOURCE 태그): 원본에 `## 섹션A`, `## 섹션B` → extracts에 `<!-- SOURCE: file#섹션A -->` 있고 `섹션B` 없음 → `uncovered_sections: ["섹션B"]`
- 검증 3 (빈 파일): analysis-report에 기능 3개 → extract 2개만 존재 → `missing_features: ["기능3"]`

**`tests/test_orchestrator_prompts.py`**:
- 각 Phase 템플릿 렌더링 결과에 필수 키워드 포함 검증:
  - 프로젝트 경로, 읽어야 할 파일 목록, `<!-- ORCHESTRATOR:DONE -->` 지시
- Phase 4-1 프롬프트에 섹션 키워드 목록이 주입되는지 확인

**`tests/test_docs_orchestrator.py`**:
- 상태 머신 전이: Phase 0 → 1 → 1.5(게이트) → 2 → 3 → 4 → 5 순서 검증
- Phase 1.5 실패 시 Phase 2로 진행하지 않는지 확인
- `bundle_disabled` 플래그 설정 시 이후 묶음이 비활성화되는지 확인

**fixture**:
- `tests/fixtures/sample_orchestrator_state.json` — 다양한 상태(idle, running, Phase 2 진행 중)
- `tests/fixtures/sample_analysis_report.md` — 도메인/기능 목록 포함
- `tests/fixtures/sample_gap_report.md` — 점수 + [AI_DECISION] 태그 포함

### 12.5 `_summary.md` 생성

오케스트레이터(파이썬)가 Phase 2 완료 후 **기계적으로** 생성한다. AI 세션을 열지 않는다.

**구현**: `orchestrator_state.py`의 `generate_gap_summary(gap_reports_dir: Path) -> str` 순수 함수

**동작**:
1. `gap_reports_dir` 내 모든 `.md` 파일 (`_summary.md` 제외) 순회
2. 각 파일에서 첫 번째 `## ` 헤더 → 기능명 추출
3. 점수 행 파싱: 정규식 `종합\s*[:：]\s*([\d.]+)\s*/\s*([\d.]+)` 또는 `점수\s*[:：]\s*([\d.]+)\s*/\s*([\d.]+)`
4. `[AI_DECISION]` 태그 수 카운트: `grep -c "\\[AI_DECISION\\]"`
5. 결과를 마크다운 테이블로 조합:

```markdown
# 갭 분석 요약

| # | 도메인 | 기능 | 점수 | AI 결정 수 |
|---|--------|------|------|-----------|
| 1 | payment | payment-methods | 2.7/3.0 | 2 |
| 2 | payment | refund | 2.3/3.0 | 4 |
| ... | ... | ... | ... | ... |

**전체 평균**: 2.5/3.0
**총 AI 결정 수**: 12건
```

6. 파일 마지막 줄에 `<!-- ORCHESTRATOR:DONE -->` 기록 (기계 생성이지만 일관성 유지)

---

## 13. 남은 미결 사항

없음 — 모든 설계 결정이 확정됨. 구현 단계로 진행 가능.
