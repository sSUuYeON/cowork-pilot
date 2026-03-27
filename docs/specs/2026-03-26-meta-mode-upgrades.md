# Meta Mode 업그레이드 — 설계 문서

> 코드리뷰 자동화, 디자인 시스템 구체화, 구현 기록(Implementation Map) 도입
> 작성일: 2026-03-26
> 상태: Draft

---

## 1. 문제 정의

현재 Meta Mode(Phase 3)는 **생성만 연속으로 수행**하고 끝난다. 이로 인해 세 가지 문제가 발생한다:

1. **레이아웃 깨짐**: 디자인 시스템(DESIGN_GUIDE.md)이 추상적이라 생성 시마다 해석이 달라짐. todo 프로젝트의 DESIGN_GUIDE.md는 "프레임워크 기본 primary 색상 사용" 수준으로, 구체적인 spacing/layout 규칙이 없음
2. **품질 검증 부재**: 생성 → 다음 생성으로 바로 넘어가므로, 초반 chunk에서 잡힌 문제가 후반까지 전파됨
3. **코드 네비게이션 부재**: 구현 완료 후 AGENTS.md와 docs/가 "계획" 문서만 가리키고, 실제 코드가 어디에 어떻게 구현됐는지 기록이 없음. 다음 작업 시 AI가 전체 코드베이스를 스캔해야 해서 느리고 토큰 소비가 큼

---

## 2. 개선 항목 요약

| # | 개선 항목 | 목적 | 적용 시점 |
|---|-----------|------|-----------|
| A | 코드리뷰 자동화 | 생성 품질 검증 + 즉시 수정 | 각 chunk 완료 후 |
| B | 디자인 시스템 구체화 | 레이아웃 일관성 확보 | Step 2 (docs 내용 채우기) |
| C | 구현 기록(Implementation Map) | 코드 네비게이션 + 재작업 효율 | 코드리뷰 단계에서 동시 작성 |
| D | AGENTS.md 역할 확장 | 코드 인덱스 진입점 | 구현 기록 작성 시 자동 갱신 |

---

## 3. [A] 코드리뷰 자동화

### 3.1 핵심 개념

현재 파이프라인: `생성(chunk) → /chunk-complete → 다음 chunk`

변경 후: `생성(chunk) → /engineering:code-review → 수정(필요 시) → 구현 기록 작성 → /chunk-complete:chunk-complete → 다음 chunk`

**핵심: `/chunk-complete:chunk-complete`는 항상 마지막에 호출한다.** 이 스킬이 체크박스를 `[x]`로 바꾸고 하네스에 "이 chunk 끝났다"고 알리는 역할이므로, 리뷰 + 수정 + 구현기록이 다 끝난 후에 호출해야 한다.

### 3.2 리뷰 단위

**기능(feature) 단위 = chunk 단위**로 리뷰한다.

근거: 현재 exec-plan의 chunk가 이미 기능 단위로 나뉘어 있음(예: todo 프로젝트의 `03-dashboard.md`, `04-categories-calendar.md`). chunk 완료 시점에 해당 기능이 완결된 상태이므로, 리뷰에 충분한 맥락이 있다.

chunk가 물리적 파일 단위(파일 N개씩)로 잘렸다면 리뷰 효과가 떨어지므로, **chunk 설계 시 반드시 하나의 완결된 기능 단위로 나눠야 한다**는 규칙을 project-conventions.md에 추가한다.

### 3.3 리뷰 방식: `/engineering:code-review` 스킬 활용

별도의 리뷰 세션을 열지 않는다. **구현 세션 안에서** chunk 구현 완료 후 `/engineering:code-review` 스킬을 호출하여 리뷰한다. 이 스킬이 이미 보안, 성능, 정합성 관점의 체계적 리뷰 프로세스를 갖고 있으므로 리뷰 로직을 직접 설계할 필요가 없다.

### 3.4 chunk 내 실행 순서

Session Prompt에 다음 순서를 명시한다:

```
docs/exec-plans/active/{파일명}을 읽고 Chunk {N}을 진행해.
스타일/레이아웃 구현 시 반드시 docs/DESIGN_GUIDE.md를 직접 열어 읽고 수치를 따라라.
코드를 예측하지 말고 항상 직접 확인해라.

다음 순서를 반드시 지켜라:

1. Chunk {N}의 Tasks를 구현해라
2. 구현 완료 후 /engineering:code-review 스킬로 이번 chunk의 코드를 리뷰해라
   - 추가 리뷰 항목: docs/DESIGN_GUIDE.md의 레이아웃/스페이싱 수치 준수 여부
3. 리뷰에서 발견된 문제를 직접 수정해라
4. docs/implementation-map/{기능}/index.md 에 구현 기록을 작성해라
5. 마지막으로 /chunk-complete:chunk-complete 스킬로 완료 처리해라

※ /vm-install:vm-install은 순서 무관 — npm install 등 설치가 필요한 시점에 호출
※ /chunk-complete:chunk-complete는 반드시 마지막에 호출 (리뷰+수정+기록 완료 후)
```

### 3.5 스킬 호출 순서 정리

| 순서 | 스킬 | 시점 | 비고 |
|------|------|------|------|
| (아무때나) | `/vm-install:vm-install` | 설치가 필요할 때 | 순서 무관, 설치 전용 |
| 1 | (없음 — 직접 구현) | chunk Tasks 수행 | |
| 2 | `/engineering:code-review` | 구현 완료 직후 | 리뷰 + 수정 |
| 3 | (없음 — 직접 작성) | implementation-map 작성 | |
| 4 | `/chunk-complete:chunk-complete` | **항상 마지막** | 체크박스 갱신 + 완료 선언 |

### 3.6 리뷰 결과 처리

| 리뷰 결과 | 동작 |
|-----------|------|
| 문제 없음 | 구현 기록 작성 → `/chunk-complete` → 다음 chunk 진행 |
| 수정 가능한 문제 | 직접 수정 → 구현 기록 작성 → `/chunk-complete` → 다음 chunk |
| 심각한 구조적 문제 | ESCALATE → 사람에게 알림 |

### 3.7 Completion Criteria 확장

기존 chunk의 Completion Criteria에 리뷰 관련 조건을 추가:

```markdown
### Completion Criteria
- [ ] npm run build 성공
- [ ] pytest tests/test_dashboard.py 통과
- [ ] docs/implementation-map/dashboard/index.md 파일 존재
```

마지막 항목이 구현 기록 작성 완료를 기계적으로 검증하는 조건이 된다.

### 3.8 하네스 변경 사항

하네스(`session_manager.py`)의 흐름 자체는 크게 변하지 않는다. 리뷰는 **구현 세션 안에서** `/engineering:code-review` 스킬로 수행되므로, 하네스가 별도 리뷰 세션을 열 필요 없다. Session Prompt에 순서가 명시되어 있으므로 Cowork 세션이 알아서 순서대로 실행한다.

```
process_chunk() 흐름 (변경 없음):
  open_session(chunk) → wait_completion() → verify_criteria() → mark_complete()
```

단, Completion Criteria에 `docs/implementation-map/{기능}/index.md 파일 존재` 조건이 추가되므로, 리뷰 + 구현기록이 완료되지 않으면 `verify_criteria()`가 통과하지 않는다.

config.toml에 리뷰 설정 추가:

```toml
[review]
enabled = true                    # Session Prompt에 리뷰 단계 포함 여부
skip_chunks = []                  # 리뷰 건너뛸 chunk 번호 (예: [1] — docs 초기 설정 chunk)
```

`enabled = false`이면 Session Prompt 생성 시 리뷰/구현기록 관련 지시를 제외한다.

---

## 4. [B] 디자인 시스템 구체화

### 4.1 현재 문제

todo 프로젝트의 DESIGN_GUIDE.md 분석:

- 디자인 원칙은 잘 정의되어 있음 (최소 마찰, 정보 계층, 일관성, 반응형)
- **빠진 것**: 구체적인 spacing 체계, 레이아웃 그리드, 컴포넌트 간 간격, 브레이크포인트별 레이아웃 규칙
- 결과: AI가 생성할 때마다 padding, margin, flex/grid 구조를 매번 다르게 해석 → 레이아웃 깨짐

### 4.2 DESIGN_GUIDE.md 템플릿 확장

기존 4개 섹션에 3개 섹션을 추가한다:

**추가 섹션 5: 레이아웃 시스템**

```markdown
## 5. 레이아웃 시스템
<!-- GUIDE:
- 내용: 페이지 레이아웃 구조, 그리드 시스템, 브레이크포인트
- 형식: 브레이크포인트 테이블 + 레이아웃 패턴별 ASCII 다이어그램
- 분량: 10~25줄
- 필수 항목:
  - 브레이크포인트 정의 (mobile/tablet/desktop px값)
  - 페이지 최대 너비 (max-width)
  - 사이드바 너비 (있는 경우)
  - 메인 콘텐츠 영역 구조 (flex/grid 방향, 비율)
  - 예시: "사이드바 240px 고정 + 메인 flex-1", "모바일에서 사이드바 하단 네비로 전환"
-->
```

**추가 섹션 6: 스페이싱 체계**

```markdown
## 6. 스페이싱 체계
<!-- GUIDE:
- 내용: 여백, 패딩, 컴포넌트 간 간격의 일관된 수치 체계
- 형식: 스페이싱 스케일 테이블 + 용도별 매핑
- 분량: 8~15줄
- 필수 항목:
  - 기본 단위 (4px 또는 8px 기반)
  - 스케일: xs/sm/md/lg/xl에 대응하는 px값
  - 용도별 매핑:
    - 페이지 패딩 (모바일/데스크톱)
    - 카드 내부 패딩
    - 리스트 아이템 간 간격
    - 섹션 간 간격
  - 예시: "xs=4px, sm=8px, md=16px, lg=24px, xl=32px"
-->
```

**추가 섹션 7: 반응형 규칙**

```markdown
## 7. 반응형 규칙
<!-- GUIDE:
- 내용: 브레이크포인트별 레이아웃 변화 규칙
- 형식: 브레이크포인트별 변화 사항 리스트
- 분량: 8~15줄
- 필수 항목:
  - 각 브레이크포인트에서 네비게이션 변화 (사이드바 → 하단바 등)
  - 그리드 컬럼 수 변화 (1열 → 2열 → 3열 등)
  - 폰트 사이즈 변화 (있는 경우)
  - 숨김/표시 요소
  - 예시: "< 768px: 하단 네비, 1열 레이아웃, 사이드바 숨김"
-->
```

### 4.3 Step 2 내용 채우기 시 강화

docs-setup.md exec-plan의 DESIGN_GUIDE.md 채우기 chunk에 다음 지시를 추가:

```
DESIGN_GUIDE.md를 작성할 때, 반드시 구체적인 수치를 포함해라:
- px 값 (spacing, font-size, breakpoint)
- 색상 hex 코드
- flex/grid 비율
"적절한", "충분한" 같은 주관적 표현 대신 측정 가능한 값을 사용해라.
레이아웃 시스템 섹션에서는 페이지별 레이아웃 구조를 ASCII 다이어그램으로 표현해라.
```

### 4.4 구현 시 참조 강제

코드리뷰 세션의 리뷰 항목에 "DESIGN_GUIDE.md 준수 여부"가 포함되어 있으므로(3.3절 참조), 구현 단계에서도 Session Prompt에 명시적으로 참조를 강제한다:

기존 Session Prompt 패턴:
```
docs/exec-plans/active/{파일명}을 읽고 Chunk N을 진행해.
```

변경:
```
docs/exec-plans/active/{파일명}을 읽고 Chunk N을 진행해.
스타일/레이아웃 구현 시 반드시 docs/DESIGN_GUIDE.md를 직접 열어 읽고 수치를 따라라.
코드를 예측하지 말고 항상 직접 확인해라.
```

---

## 5. [C] 구현 기록 (Implementation Map)

### 5.1 핵심 개념

현재 docs/ 구조:
- `product-specs/` — "이렇게 만들 거다" (계획)
- `design-docs/` — "이런 설계다" (아키텍처)

**추가**:
- `implementation-map/` — "이렇게 만들어졌다" (구현 결과)

product-specs가 **계획 문서**라면, implementation-map은 **구현 기록 문서**다. 이 둘은 성격이 완전히 다르므로 분리한다.

### 5.2 폴더 구조

```
docs/
  implementation-map/
    index.md                          ← 전체 기능 → 폴더 매핑 목차
    {기능이름}/
      index.md                        ← 이 기능의 구현 요약 + 파일 매핑
    {기능이름}/
      index.md
    ...
```

예시 (todo 프로젝트 기준):

```
docs/
  implementation-map/
    index.md
    dashboard/
      index.md
    calendar/
      index.md
    categories-tags/
      index.md
    auth/
      index.md
    recurring/
      index.md
```

### 5.3 index.md (루트) 형식

```markdown
# Implementation Map

> 이 프로젝트의 기능별 구현 위치 색인.
> AI가 특정 기능을 찾을 때 이 파일부터 읽는다.

| 기능 | 폴더 | 핵심 패턴 | 관련 스펙 |
|------|------|-----------|-----------|
| 대시보드 | `implementation-map/dashboard/` | React Query + Zustand | `product-specs/대시보드.md` |
| 캘린더 | `implementation-map/calendar/` | FullCalendar + DnD | `product-specs/캘린더-뷰.md` |
| 인증 | `implementation-map/auth/` | Firebase Auth | `design-docs/auth.md` |
```

### 5.4 기능별 index.md 형식

```markdown
# {기능이름} — 구현 기록

## 구현 패턴
{이 기능이 어떤 패턴/라이브러리로 구현됐는지 1~3줄}
예: "Firestore onSnapshot으로 실시간 동기화, React Context로 상태 공유, 인라인 폼으로 CRUD"

## 파일 매핑

| 역할 | 파일 경로 |
|------|-----------|
| 페이지 | `src/app/page.tsx` |
| 메인 컴포넌트 | `src/components/todo/TodoList.tsx` |
| 데이터 훅 | `src/hooks/useTodos.ts` |
| Firestore 레이어 | `src/lib/firestore/todos.ts` |
| 타입 정의 | `src/types/index.ts` (Todo 인터페이스) |

## 참조 문서
- 스펙: `docs/product-specs/대시보드.md`
- 설계: `docs/design-docs/data-model.md`
```

### 5.5 작성 규칙

1. **"뭘 읽어야 하는지"는 알려주되, "읽은 결과가 뭔지"는 안 알려준다**
   - 적는 것: 파일 경로, 사용한 패턴/라이브러리 이름
   - 안 적는 것: 함수의 로직, 코드 흐름, 구체적 알고리즘
2. **코드가 바뀌면 파일 경로가 바뀔 수 있으므로, 파일 매핑은 최소한으로 유지**
   - 핵심 파일 5~10개만 기록 (유틸리티, 헬퍼는 생략)
3. **구현 패턴은 한두 줄로 요약**
   - "React Query로 서버 상태, Zustand로 클라이언트 상태" 수준
   - 이 정도면 AI가 코드를 읽기 전에 맥락을 잡기에 충분함

### 5.6 작성 시점

코드리뷰 세션에서 리뷰와 동시에 작성한다(3.3절 참조). 리뷰 시 어차피 코드를 읽으므로, 추가 비용이 거의 없다.

흐름: `chunk 구현 완료 → 리뷰 세션 시작 → 코드 읽으며 리뷰 → 리뷰 수정 완료 → 구현 기록 작성 → 리뷰 세션 종료`

---

## 6. [D] AGENTS.md 역할 확장

### 6.1 현재 문제

todo 프로젝트의 AGENTS.md는 docs/ 폴더 안내 역할만 한다:

```markdown
## Directory Map
- `docs/design-docs/` — 설계 문서 (index.md에서 색인)
- `docs/product-specs/` — 페이지/기능별 스펙 (index.md에서 색인)
```

이것은 **문서 디렉토리 지도**이지 **코드 네비게이션 맵**이 아니다.

### 6.2 변경 방향

AGENTS.md의 Directory Map에 `implementation-map/` 참조를 추가하여, **docs(계획/설계)와 코드(구현) 양쪽의 진입점** 역할을 하게 한다.

### 6.3 AGENTS.md 템플릿 변경

기존 `AGENTS.md.j2`에 다음 섹션을 추가:

```markdown
## Implementation Map

이 프로젝트의 기능별 구현 위치는 `docs/implementation-map/index.md`에서 확인한다.
특정 기능의 코드를 찾을 때는 반드시 이 맵을 먼저 참조한다.

## 절대 규칙: 코드를 예측하지 마라

- 코드의 내용, 구조, 위치를 추측하지 마라
- 반드시 파일을 직접 열어 읽고 확인한 후에 작업해라
- Implementation Map은 "어디를 읽어야 하는지" 알려줄 뿐, 코드의 내용을 보장하지 않는다
- "아마 이 함수가 이렇게 되어 있을 것이다"라는 가정 하에 작업하지 마라
```

### 6.4 AI 네비게이션 흐름

변경 전:
```
요청 수신 → AGENTS.md 읽기 → docs/ 문서 읽기 → 프로젝트 전체 스캔 → 해당 파일 찾기 → 작업
```

변경 후:
```
요청 수신 → AGENTS.md 읽기
  → "대시보드 수정" 요청이면?
  → Implementation Map 참조 → dashboard/index.md 읽기
  → src/components/todo/TodoList.tsx 등 핵심 파일 직접 확인
  → 작업
```

토큰 절감: 프로젝트 전체 스캔(수십 개 파일) → 맵 + 핵심 파일 5~10개 직접 읽기

---

## 7. 전체 파이프라인 변경

### 7.1 현재 (Phase 3 Meta Mode)

```
Step 0: 브리프 수집
Step 1: 스캐폴딩 (디렉토리 + 빈 템플릿 생성)
Step 2: 내용 채우기 (docs 문서 작성)
Step 3: 검증/승인
Step 4: 구현 (chunk별 코드 생성)
  └─ chunk 1 생성 → chunk 2 생성 → ... → chunk N 생성 → 끝
```

### 7.2 변경 후

```
Step 0: 브리프 수집
Step 1: 스캐폴딩 (디렉토리 + 빈 템플릿 생성)
  └─ docs/implementation-map/ 디렉토리도 함께 생성 (빈 상태)
Step 2: 내용 채우기 (docs 문서 작성)
  └─ DESIGN_GUIDE.md에 구체적 수치 포함 (레이아웃/스페이싱/반응형)
Step 3: 검증/승인
Step 4: 구현 + 리뷰 (chunk별)
  └─ chunk 1 생성 → chunk 1 리뷰 + 구현기록 작성
  └─ chunk 2 생성 → chunk 2 리뷰 + 구현기록 작성
  └─ ...
  └─ chunk N 생성 → chunk N 리뷰 + 구현기록 작성
  └─ AGENTS.md Implementation Map 섹션 최종 갱신
```

### 7.3 스캐폴더 변경 사항

`scaffolder.py`에서 생성하는 구조에 추가:

```python
# 기존
"docs/product-specs/",
"docs/design-docs/",

# 추가
"docs/implementation-map/",
```

`docs-setup-plan.md.j2`에서 생성하는 exec-plan에는 implementation-map 관련 chunk를 **넣지 않는다** (Step 2는 계획 문서만 채우는 단계). implementation-map은 Step 4의 리뷰 세션에서 자동 생성된다.

### 7.4 DESIGN_GUIDE.md.j2 템플릿 변경

기존 4개 섹션(디자인 원칙, 컬러/타이포, 컴포넌트 규칙, 레퍼런스)에 3개 섹션 추가:

- `## 5. 레이아웃 시스템` (4.2절 참조)
- `## 6. 스페이싱 체계` (4.2절 참조)
- `## 7. 반응형 규칙` (4.2절 참조)

---

## 8. 변경 영향 범위

### 8.1 코드 변경

| 파일 | 변경 내용 |
|------|-----------|
| `src/cowork_pilot/session_manager.py` | 리뷰 세션 열기/완료 대기 로직 추가 |
| `src/cowork_pilot/scaffolder.py` | `docs/implementation-map/` 디렉토리 생성 추가 |
| `src/cowork_pilot/brief_templates/DESIGN_GUIDE.md.j2` | 섹션 5~7 추가 |
| `src/cowork_pilot/brief_templates/AGENTS.md.j2` | Implementation Map + 절대규칙 섹션 추가 |
| `src/cowork_pilot/brief_templates/docs-setup-plan.md.j2` | DESIGN_GUIDE 관련 chunk 프롬프트 강화 |
| `src/cowork_pilot/config.py` | ReviewConfig 추가 |
| `config.toml` | `[review]` 섹션 추가 |

### 8.2 문서 변경

| 파일 | 변경 내용 |
|------|-----------|
| `docs/project-conventions.md` | 섹션 추가: chunk는 기능 단위로 나눌 것, implementation-map 형식 표준 |
| `AGENTS.md` | Directory Map에 implementation-map 경로 추가 |

### 8.3 테스트 추가

| 테스트 파일 | 내용 |
|------------|------|
| `tests/test_review_session.py` | 리뷰 세션 열기/결과 처리 |
| `tests/test_scaffolder.py` (기존) | implementation-map 디렉토리 생성 검증 추가 |
| `tests/test_design_guide_template.py` | 확장된 DESIGN_GUIDE 템플릿 렌더링 검증 |

---

## 9. 구현 우선순위

1. **디자인 시스템 구체화** (B) — 가장 먼저. DESIGN_GUIDE.md 템플릿만 확장하면 되므로 변경량 적고, 효과가 즉시 나타남
2. **구현 기록 구조 정의** (C) — 폴더 구조 + index.md 형식만 정하면 됨. scaffolder에 디렉토리 추가
3. **AGENTS.md 역할 확장** (D) — 템플릿에 섹션 추가. C와 함께 진행
4. **코드리뷰 자동화** (A) — 가장 복잡함. session_manager 수정, 리뷰 프롬프트 설계, config 확장. 위 세 개가 먼저 있어야 리뷰 기준이 명확해짐

---

## 10. 미결정 사항

- [ ] 리뷰 세션의 타임아웃: 구현 세션과 같은 idle_timeout(120s)을 쓸지, 더 짧게 할지
- [ ] 리뷰에서 발견된 문제의 심각도 분류 기준 (수정 가능 vs ESCALATE 경계)
- [ ] implementation-map을 코드리뷰 세션이 작성할 때, 기존 index.md가 있으면 어떻게 병합할지 (덮어쓰기 vs 추가)
- [ ] DESIGN_GUIDE.md 작성 시 실제 레퍼런스 이미지/스크린샷을 포함할지 (텍스트만으로 충분한지)
