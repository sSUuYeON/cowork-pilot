---
name: docs-orchestrator
description: "대규모 프로젝트의 기획서를 자동으로 분석하고 docs/ 구조를 생성하는 상태 기반 자동 세션 관리자. 기존 docs-restructurer가 한 세션에서 Phase 1~5를 처리하는 반면, docs-orchestrator는 Phase/도메인/기능 단위로 세션을 자동 분할하여 컨텍스트 압축 없이 고품질 문서를 생성한다. 트리거: 'docs-orchestrator', '대규모 docs 생성', '자동 문서 오케스트레이션', 'large project docs orchestration', 또는 product-spec이 5개 이상인 대규모 프로젝트에서 docs/ 구조를 자동 생성하려는 모든 요청."
---

# docs-orchestrator

대규모 프로젝트(product-spec 5개 이상)의 기획서를 자동으로 분석하고 docs/ 구조를 생성하는 **상태 기반 자동 세션 관리자**.

## 이 스킬이 하는 일

기존 `docs-restructurer`가 Phase 1~5를 한 세션에서 처리하는 반면, `docs-orchestrator`는 각 Phase를 도메인/기능 단위로 자동 분할하여 독립 세션에서 처리한다. 이를 통해:

- **컨텍스트 압축 없이** 각 세션이 필요한 파일만 읽고 작업
- **domain-extract 시 원문 그대로 복사** (요약 금지 원칙)
- **갭 분석의 깊이 확보** (기능별 독립 세션)
- **수동 세션 관리 불필요** (상태 파일 기반 자동 진행)

## 사용 시점

- product-spec이 5개 이상인 대규모 프로젝트
- 기존 `docs-restructurer`로 처리하기에 프로젝트 규모가 큰 경우
- 자동화된 다세션 문서 생성이 필요한 경우

## 실행 방법

`docs-orchestrator`는 AI 세션이 아닌 **cowork-pilot CLI의 별도 모드**로 실행한다:

```bash
# auto 모드: AI가 갭 분석을 자동으로 결정
cowork-pilot --mode docs-orchestrator --docs-mode auto

# manual 모드: 사용자가 갭 분석에 직접 답변
cowork-pilot --mode docs-orchestrator --docs-mode manual

# hybrid: 특정 도메인만 manual로 처리
cowork-pilot --mode docs-orchestrator --docs-mode auto --manual-override payment,auth
```

## Phase 구성

| Phase | 내용 | 실행 주체 |
|-------|------|----------|
| Phase 0 | 초기 설정 (디렉토리 생성, references 복사, 예상 세션 수 확인) | 오케스트레이터 (파이썬) |
| Phase 1 | 입력 분석 + domain-extract (소규모: 1세션, 대규모: 도메인별 다세션) | AI 세션 |
| Phase 1.5 | 추출 품질 게이트 (커버리지/SOURCE 태그/빈 파일 검증) | 오케스트레이터 (파이썬) |
| Phase 2 | 기능별 갭 분석 (기능별 또는 묶음 세션) | AI 세션 |
| Phase 3 | 문서 생성 (design-docs → product-specs → ARCHITECTURE → AGENTS.md) | AI 세션 |
| Phase 4 | 품질 검토 (정합성 → 체크리스트 재평가 → 표현 품질) | AI 세션 |
| Phase 5 | exec-plan 생성 (outline 설계 → 상세 작성) | AI 세션 |

## 기존 스킬과의 관계

| 기존 스킬 | docs-orchestrator에서의 역할 |
|----------|--------------------------|
| `docs-restructurer` | 중소규모 프로젝트에서는 여전히 단독 사용. 오케스트레이터는 대규모 전용 |
| `docs-analyzer` | Phase 1~2 로직을 오케스트레이터가 흡수. 독립 사용 불필요 |
| `docs-generator` | Phase 3~5 로직을 오케스트레이터가 흡수. 독립 사용 불필요 |
| `docs-restructurer-large` | 오케스트레이터로 대체 |

오케스트레이터가 안정화되면 `docs-analyzer`, `docs-generator`, `docs-restructurer-large`는 deprecated 가능.

## 핵심 설계 원칙

1. **"추출, 요약 금지"** - domain-extracts에는 원본을 그대로 복사
2. **"한 세션, 한 집중"** - 각 세션은 하나의 명확한 목표만 수행
3. **"상태 파일이 유일한 진실"** - 세션 간 맥락 전달은 오직 파일을 통해서만
4. **"도메인 → 기능 2단계 분할"** - 도메인 아래 기능 단위로 세션 분할
5. **"중복 허용, 참조 금지"** - 기능별 파일은 self-contained

## references/ 디렉토리

이 스킬에 번들된 3개 파일은 Phase 0에서 프로젝트의 `docs/generated/references/`로 복사된다:

- `checklists.md` - product-spec 체크리스트 항목 정의
- `output-formats.md` - 문서 타입별 필수 섹션 + 양식 규칙
- `quality-criteria.md` - 정합성/표현 품질/측정 가능성/커버리지 기준

## 설정

`config.toml`의 `[docs_orchestrator]` 섹션에서 설정 가능:

```toml
[docs_orchestrator]
idle_timeout_seconds = 120
completion_poll_interval = 5.0
idle_grace_seconds = 30
feature_bundle_threshold_lines = 200
max_bundle_size = 2
coverage_ratio_threshold = 0.8
adaptive_timeout_min = 60.0
adaptive_timeout_max = 300.0
adaptive_timeout_multiplier = 1.5
```
