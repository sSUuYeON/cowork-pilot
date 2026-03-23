# Cowork Pilot

Auto-response agent for Cowork. Watches JSONL, judges questions via CLI agents, inputs responses via AppleScript.

## Directory Map

- `src/cowork_pilot/` — Python orchestrator (dumb, no intelligence)
- `docs/decision-criteria.md` — 도구별/질문 유형별 판단 기준 (실데이터 기반, 180줄)
- `docs/golden-rules.md` — 절대 규칙, ESCALATE 블랙리스트, 거부 목록 (실데이터 기반, 150줄)
- `docs/specs/` — Design specs
- `docs/exec-plans/active/` — 현재 진행 중인 실행 계획
- `tests/` — pytest tests with JSONL fixtures
- `config.toml` — Runtime configuration

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

## Key Design Decision

CLI 에이전트는 AGENTS.md를 자동으로 읽지 않을 수 있다. Dispatcher가 docs/의 내용을
직접 프롬프트에 주입한다. 이 파일은 사람과 에이전트 모두를 위한 참고 문서.
