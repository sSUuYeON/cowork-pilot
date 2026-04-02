# Build Test Plan

> **For agentic workers:** Sample exec-plan with [BUILD] tags for testing.

**Goal:** Test parsing of [BUILD] tags in completion criteria.

## Metadata
- project_dir: /Users/test/build-project
- spec: docs/specs/sample.md
- created: 2026-04-02
- status: pending

---

## Chunk 1: Setup

### Completion Criteria
- [ ] vercel.json 파일 존재
- [ ] [BUILD] npm run lint
- [ ] [BUILD] npm run build

### Tasks
- Task 1: Vercel 설정
- Task 2: Lint 설정

### Session Prompt
```
프로젝트 설정을 완료하라.
```

---

## Chunk 2: No Build

### Completion Criteria
- [ ] README.md 파일 존재
- [x] [BUILD] npm run test

### Tasks
- Task 3: 문서 작성

### Session Prompt
```
문서를 작성하라.
```
