# Planning Engine V3 Rollout Roadmap

> **For agentic workers:** Start with the V3 completion plan **Task 0 (Planning Package Bootstrap)** to create the planning package skeleton. Then execute the runtime handoff implementation plan. Then return to the completion plan Task 1 onwards. Do not skip Task 0; the runtime plan depends on the modules it creates.

**Goal:** `Planning Engine V3`와 `Planning Runtime Handoff`를 연결해, `exec -> cli resume -> exec resume`가 가능한 multi-session planning system을 완성한다.

**Architecture:** 구현은 두 축으로 나뉜다. 첫 번째 축은 `structured marker protocol`, `run state machine`, `stage session profile`, `Codex CLI handoff`를 담당하는 runtime layer다. 두 번째 축은 그 runtime 위에서 실제 `Greenfield/Brownfield`, `Interactive/Hybrid/Auto`, `question/answer loop`, `delta artifact`를 작동시키는 planning behavior layer다.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, asyncio subprocess, pytest

---

## Why Two Plans Exist

현재 `Planning Engine V3`는 뼈대와 문서 산출 구조는 있으나, 실제 질문/응답/세션 handoff와 Greenfield/Brownfield 행동 분기가 비어 있다.

따라서 구현은 반드시 아래 순서로 간다.

0. `docs/superpowers/plans/2026-04-08-planning-engine-v3-completion.md` **Task 0만**
   - `src/cowork_pilot/planning/` 패키지 생성
   - 기초 모듈 뼈대 (models, storage, classification, docs_inventory, completeness, scope, sizing, packing, review, authoring, prompts, runner)
   - baseline 테스트 통과 확인
1. `docs/superpowers/plans/2026-04-08-planning-runtime-handoff-implementation.md` **전체**
   - marker protocol
   - run state machine
   - `exec` / `cli` handoff
   - stage session profile
   - answer / assumption / approval persistence
2. `docs/superpowers/plans/2026-04-08-planning-engine-v3-completion.md` **Task 1 이후**
   - Greenfield / Brownfield 실제 분기
   - Interactive / Hybrid / Auto 실제 동작
   - 질문-답변 반영 루프
   - Brownfield delta artifact generation
   - multi-session stage orchestration
   - empty-project / uploaded-spec flow

둘 중 하나만 구현하면 시스템은 완성되지 않는다.

- runtime만 구현하면 planning intelligence가 비어 있다.
- V3 behavior만 구현하면 질문/자동응답/세션 handoff가 비어 있다.

## Execution Order

### Milestone 0: Planning Package Bootstrap

`src/cowork_pilot/planning/` 디렉토리가 현재 레포에 존재하지 않는다. 모든 후속 작업 전에 V3 completion plan의 **Task 0**을 실행해 패키지와 기초 모듈 뼈대를 만든다.

완료 기준:

- `src/cowork_pilot/planning/` 아래 `__init__.py`, `models.py`, `storage.py`, `classification.py`, `docs_inventory.py`, `completeness.py`, `scope.py`, `sizing.py`, `packing.py`, `review.py`, `authoring.py`, `prompts.py`, `runner.py`가 모두 존재하고 importable
- `tests/test_planning_models.py` 등 baseline 테스트 통과

### Milestone 1: Runtime Foundation

다음이 끝나야 한다.

- marker parser / validator
- planning run state persistence
- stage session profile resolver
- `exec -> interactive CLI resume -> exec resume` command builders
- `waiting_for_input|waiting_for_approval -> running_cli -> running_exec` orchestration helper
- JSON event / final marker extraction
- blocking / non-blocking marker semantics

완료 기준:

- fixture 기반으로 marker parsing이 안정적으로 통과한다
- mocked CLI bridge로 state machine이 `waiting_for_input -> running_cli -> running_exec` 전환을 재현한다
- mocked CLI bridge로 state machine이 `waiting_for_approval -> running_cli -> running_exec` 전환을 재현한다
- 실제 local smoke test에서 non-interactive thread id를 interactive resume로 열 수 있음을 자동 test 또는 manual harness test로 확인한다

### Milestone 2: Planning Behavior Completion

다음이 runtime 위에 올라가야 한다.

- project mode resolver
- Greenfield source adapter
- Brownfield delta analysis
- stage-level question policy
- question / assumption / approval 반영
- stage/substage execution orchestration
- parser-friendly exec-plan authoring까지 연결

완료 기준:

- empty project에서 기획 bootstrap이 가능하다
- uploaded spec를 source material로 읽어 canonical docs draft를 만든다
- brownfield project에서 `spec-implementation-gap.md`와 `change-impact-gap.md`가 생성된다
- greenfield project에서 `product-completeness-review.md`와 `coverage-gap.md`가 함께 생성된다
- `hybrid` 모드에서 초반 질문 집중, 후반 자동 진행이 재현된다
- non-blocking question이 assumption으로 흡수된 뒤 후속 invalidation이 `waiting_for_human`으로 surfaced 된다

### Milestone 3: End-to-End Integration

다음 surface가 같은 core를 타야 한다.

- `python -m cowork_pilot.main --mode planning`
- `python -m cowork_pilot.codex.main planning`
- `docs_orchestrator` planning adapter

완료 기준:

- 같은 project에서 동일한 planning run metadata 형식을 사용한다
- `docs/generated/planning-runs/<run-id>/`에 runtime + stage artifacts가 일관되게 남는다
- `docs/exec-plans/planning/`에 final exec-plan set이 생성된다

## Non-Negotiable Rules During Implementation

- stage 경계는 미리 정의된 `session profile`로만 자른다
- context exhaustion을 세션 경계로 사용하지 않는다
- 질문은 자연어 감지가 아니라 terminal marker로만 처리한다
- `source=exec`에서는 직접 입력을 가정하지 않는다
- `source=cli` handoff는 항상 기존 session `resume` 기준으로 처리한다
- Brownfield에서 spec와 구현이 충돌하면 gap artifact를 남기고 묻어두지 않는다

## Verification Sequence

모든 구현이 끝난 뒤 최소 다음 명령을 통과해야 한다.

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_planning_models.py tests/test_planning_marker_protocol.py tests/test_planning_session_profiles.py tests/test_planning_runtime_state.py tests/test_planning_codex_bridge.py tests/test_planning_runtime_orchestrator.py tests/test_planning_greenfield.py tests/test_planning_brownfield.py tests/test_planning_question_policy.py tests/test_planning_stage_executor.py tests/test_planning_pipeline_units.py tests/test_planning_classification.py tests/test_planning_docs_inventory.py tests/test_planning_completeness.py tests/test_planning_runner.py tests/test_docs_orchestrator.py tests/test_codex_main.py tests/test_main_cli.py tests/test_codex_harness.py tests/test_config.py -q
```

그리고 마지막으로 전체 회귀:

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest -q
```
