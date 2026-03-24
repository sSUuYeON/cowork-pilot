# Phase 2: Harness Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a harness orchestrator that reads exec-plan MD files, opens Cowork sessions per Chunk, monitors completion via idle detection + CLI verification, and transitions to the next Chunk automatically.

**Architecture:** Three new modules layered on top of Phase 1: `plan_parser.py` (MD → dataclasses), `completion_detector.py` (idle detection + CLI verification), `session_manager.py` (Chunk lifecycle control). These integrate into the existing `main.py` run loop via a `--mode harness` flag.

**Tech Stack:** Python 3.10+, dataclasses, re (regex), subprocess (CLI invocation), existing `session_opener.py` + `responder.py` + `session_finder.py`

**Spec:** `docs/specs/2026-03-24-harness-orchestrator-design.md`
**Conventions:** `docs/project-conventions.md`

## Metadata
- project_dir: /Users/yeonsu/Documents/GitHub/cowork-pilot
- spec: docs/specs/2026-03-24-harness-orchestrator-design.md
- created: 2026-03-24
- status: pending

---

## Chunk 1: Plan Parser — Models + Parsing

### Completion Criteria
- [x] pytest tests/test_plan_parser.py::test_parse_metadata 통과
- [x] pytest tests/test_plan_parser.py::test_parse_chunks 통과
- [x] src/cowork_pilot/plan_parser.py 파일 존재
- [x] tests/fixtures/sample_exec_plan.md 파일 존재

### Tasks
- Task 1: Test fixture — sample exec-plan MD file
- Task 2: Dataclass models for ExecPlan, Chunk, CompletionCriterion
- Task 3: Metadata parser (title, project_dir, status)
- Task 4: Chunk splitter (regex-based `## Chunk N:` detection)
- Task 5: Completion Criteria parser (`- [ ]` / `- [x]` checkboxes)

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 Chunk 1을 진행해.
AGENTS.md와 docs/specs/2026-03-24-harness-orchestrator-design.md의 섹션 4.1을 참고해서 Task 1~5를 순서대로 구현해.
docs/project-conventions.md의 섹션 4(exec-plan 형식)에 정의된 파싱 규칙(정규식 포함)을 정확히 따라.

TDD로 진행해: 먼저 테스트 작성 → 실패 확인 → 구현 → 통과 확인.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 2: Plan Parser — Prompt Extraction + Checkbox Update

### Completion Criteria
- [x] pytest tests/test_plan_parser.py 전체 통과
- [x] plan_parser.py에 parse_exec_plan() 함수 존재
- [x] plan_parser.py에 update_checkboxes() 함수 존재

### Tasks
- Task 6: Session Prompt extractor (code block extraction with fallback to plain text)
- Task 7: Checkbox updater (update `- [ ]` → `- [x]` in file)
- Task 8: Full integration — parse_exec_plan() 함수로 전체 파일 파싱
- Task 9: Edge case 테스트 — 빈 Session Prompt, 여러 코드 블록, 모든 체크박스 완료 등

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, Chunk 2를 시작해.
Chunk 1에서 만든 plan_parser.py에 Session Prompt 추출과 체크박스 업데이트 기능을 추가해.
docs/specs/2026-03-24-harness-orchestrator-design.md의 섹션 4.1 파싱 규칙과 섹션 6.4를 참고해.

TDD로 진행해. 완료 조건을 모두 만족시켜.
```

---

## Chunk 3: Completion Detector

### Completion Criteria
- [x] pytest tests/test_completion_detector.py 통과
- [x] src/cowork_pilot/completion_detector.py 파일 존재

### Tasks
- Task 10: Idle detection — `is_idle_trigger()` function
- Task 11: CLI verification — build verification prompt + call CLI + parse response
- Task 12: Feedback text builder — INCOMPLETE → feedback template
- Task 13: Feedback sender — clipboard + AppleScript paste (reuse session_opener functions)

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, Chunk 3을 시작해.
docs/specs/2026-03-24-harness-orchestrator-design.md의 섹션 4.2(completion_detector)와 섹션 6.3(idle 감지 타이밍)을 참고해.

TDD로 진행해. 완료 조건을 모두 만족시켜.
```

---

## Chunk 4: Session Manager

### Completion Criteria
- [x] pytest tests/test_session_manager.py 통과
- [x] src/cowork_pilot/session_manager.py 파일 존재

### Tasks
- Task 14: Session lifecycle — open session + detect new JSONL (race condition 방지 포함)
- Task 15: Chunk transition — completed → next chunk, all done → move to completed/
- Task 16: Retry counters — per-chunk CLI failure count + INCOMPLETE feedback count
- Task 17: ESCALATE handler — macOS notification + loop pause
- Task 18: Checkbox update orchestration — call plan_parser to update file on COMPLETED

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, Chunk 4를 시작해.
docs/specs/2026-03-24-harness-orchestrator-design.md의 섹션 4.3(session_manager)와 섹션 6.2(세션 전환 감지)를 참고해.

session_manager.py는 plan_parser.py, completion_detector.py, session_opener.py, session_finder.py를 조합하는 상위 제어 모듈이다.
TDD로 진행해. 완료 조건을 모두 만족시켜.
```

---

## Chunk 5: Main Loop Integration + Config

### Completion Criteria
- [x] pytest tests/ 전체 통과 (기존 79개 + 신규 테스트 모두)
- [x] `python -m cowork_pilot --mode harness --help` 실행 시 에러 없음
- [x] config.toml에 [harness] 섹션 존재

### Tasks
- Task 19: Config 확장 — HarnessConfig dataclass + load_config() 수정
- Task 20: main.py 수정 — `--mode harness` 플래그 + harness run loop
- Task 21: main.py harness 루프 — Phase 1 + Phase 2 통합 (단일 스레드 협력적 멀티태스킹)
- Task 22: config.toml 기본 템플릿 업데이트
- Task 23: AGENTS.md 업데이트 — harness 경로 추가

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, Chunk 5를 시작해.
docs/specs/2026-03-24-harness-orchestrator-design.md의 섹션 6.1(Phase 1과의 동시 실행)과 섹션 8(config.toml)을 참고해.

기존 main.py의 run() 함수와 cli() 함수를 수정한다.
기존 79개 테스트가 깨지지 않도록 주의해.
완료 조건을 모두 만족시켜.
```

---

## Chunk 6: End-to-End Smoke Test

### Completion Criteria
- [x] pytest tests/ 전체 통과
- [x] tests/fixtures/sample_exec_plan.md를 사용한 통합 테스트 존재
- [x] docs/exec-plans/active/phase-2-harness.md의 모든 Chunk 체크박스가 [x]

### Tasks
- Task 24: 통합 테스트 — sample exec-plan으로 session_manager 전체 흐름 (mock AppleScript + mock CLI)
- Task 25: Edge case 테스트 — 빈 exec-plan, 모든 Chunk 이미 완료, 파싱 에러 등
- Task 26: 최종 확인 — 전체 pytest 실행, 기존 + 신규 모두 통과

### Session Prompt
```
docs/exec-plans/active/phase-2-harness.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, Chunk 6을 시작해.

이 Chunk은 통합 테스트와 엣지 케이스 테스트를 작성한다.
AppleScript와 CLI는 mock으로 대체하되, 전체 파이프라인(파싱 → 세션 열기 → idle 감지 → 검증 → 체크박스 업데이트 → 다음 Chunk)이 올바르게 동작하는지 확인한다.
기존 79개 테스트가 깨지지 않도록 주의해.
완료 조건을 모두 만족시켜.
```
