# Phase 2: Sample Implementation Plan

> **For agentic workers:** Sample exec-plan for testing.

**Goal:** Build a sample feature for testing the plan parser.

## Metadata
- project_dir: /Users/test/sample-project
- spec: docs/specs/2026-03-24-sample-design.md
- created: 2026-03-24
- status: pending

---

## Chunk 1: Foundation

### Completion Criteria
- [ ] pytest tests/test_models.py 통과
- [ ] pytest tests/test_config.py 통과
- [ ] src/models.py 파일 존재

### Tasks
- Task 1: Project Scaffold
- Task 2: Models
- Task 3: Config

### Session Prompt
```
docs/exec-plans/active/sample.md를 읽고 Chunk 1을 진행해.
AGENTS.md와 docs/specs/sample-design.md를 참고해서 Task 1~3을 순서대로 구현해.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 2: Watcher

### Completion Criteria
- [x] pytest tests/test_watcher.py 통과
- [x] src/watcher.py 파일 존재

### Tasks
- Task 4: JSONL Parser
- Task 5: State Machine

### Session Prompt
```
docs/exec-plans/active/sample.md를 읽고 다음 미완료 Chunk를 진행해.
이전 Chunk의 체크박스가 완료되어 있는지 확인하고, 다음 Chunk를 시작해.
```

---

## Chunk 3: Integration

### Completion Criteria
- [ ] pytest tests/ 전체 통과
- [ ] npm run build 성공

### Tasks
- Task 6: Wire everything together
- Task 7: Final tests

### Session Prompt
```
docs/exec-plans/active/sample.md를 읽고 다음 미완료 Chunk를 진행해.
완료 조건을 모두 만족시켜.
```
