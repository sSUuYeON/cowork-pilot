# Cowork Pilot

Auto-response agent for Cowork. Watches JSONL, judges questions via CLI agents, inputs responses via AppleScript.

## Directory Map

- `src/cowork_pilot/` — Python orchestrator (dumb, no intelligence)
- `docs/decision-criteria.md` — 도구별/질문 유형별 판단 기준 (실데이터 기반, 180줄)
- `docs/golden-rules.md` — 절대 규칙, ESCALATE 블랙리스트, 거부 목록 (실데이터 기반, 150줄)
- `docs/specs/` — Design specs
- `docs/exec-plans/planning/` — 대기 중인 구현 계획 (번호순 자동 승격)
- `docs/exec-plans/active/` — 현재 진행 중인 실행 계획 (최대 1개)
- `tests/` — pytest tests with JSONL fixtures
- `config.toml` — Runtime configuration
- `src/cowork_pilot/brief_parser.py` — 브리프 MD 파싱
- `src/cowork_pilot/scaffolder.py` — 프로젝트 디렉토리 + 템플릿 스캐폴딩
- `src/cowork_pilot/meta_runner.py` — Phase 3 메타 에이전트 오케스트레이션
- `src/cowork_pilot/brief_templates/` — Jinja2 프로젝트 템플릿 (9개 .j2 파일)

## When Making Changes

1. Read `docs/golden-rules.md` before any change
2. Run `pytest` after every change
3. Follow existing patterns in `src/cowork_pilot/`
4. Each file has one responsibility — don't merge concerns
5. 오판단 발견 시 → golden-rules.md에 규칙 추가 → 테스트 fixture 추가

## Conventions

- Python 3.10+, type hints everywhere
- Dataclasses for data, no classes with methods for orchestrator logic
- Functions over classes for pipeline steps
- All tests in `tests/`, mirroring `src/` structure

## Project Conventions

`docs/project-conventions.md` 참조 — 폴더 구조, AGENTS.md 형식, spec/exec-plan 작성 규칙 정의.
하네스 오케스트레이터가 실행하는 모든 프로젝트가 이 컨벤션을 따른다.

## Harness (자동 실행 시스템)

- `docs/exec-plans/planning/` — 대기 중인 구현 계획 (번호순 자동 승격)
- `docs/exec-plans/active/` — 현재 진행 중인 구현 계획 (최대 1개)
- `docs/exec-plans/completed/` — 완료된 구현 계획
- exec-plan 포맷: Chunk별 Tasks + Completion Criteria + Session Prompt
- Chunk 완료 시 체크박스 `[x]`로 업데이트됨
- `--mode harness` 플래그로 실행

## Key Design Decision

CLI 에이전트는 AGENTS.md를 자동으로 읽지 않을 수 있다. Dispatcher가 docs/의 내용을
직접 프롬프트에 주입한다. 이 파일은 사람과 에이전트 모두를 위한 참고 문서.
