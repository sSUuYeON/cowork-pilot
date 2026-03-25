# Meta Mode Resume 설계

> 날짜: 2026-03-25
> 상태: reviewed

## 1. 문제

`run_meta()`는 Step 0~4를 순차 실행하지만, 강종 후 재시작하면 무조건 Step 0부터 다시 시작한다.
Step 0, 1은 멱등(이미 있으면 스킵/덮어쓰지 않음)이라 괜찮지만, Step 2에서 이미 `completed/`로 이동한 `01-docs-setup.md`를 찾지 못해 에러가 발생한다.

## 2. 해결 방향

**파일시스템 기반 상태 추론** — 별도 상태 파일 없이, 각 Step이 시작 시 자신이 이미 완료되었는지 파일시스템 상태를 보고 판단한다. 완료됐으면 스킵, 아니면 실행(또는 이어서 실행).

장점:
- 상태 파일과 실제 파일시스템 간 불일치 위험 없음
- 새로운 저장 메커니즘 불필요
- 기존 파일 이동 로직(`active/ → completed/`, `planning/ → active/`)이 이미 상태 머신 역할

## 3. 각 Step의 Guard 조건

### Step 0: Brief 채우기
- **Guard**: `docs/project-brief.md` 존재 + `parse_brief()` 성공
- **이미 구현됨** — 변경 불필요

### Step 1: Scaffolding
- **Guard 불필요** — `scaffold_project()` 내부의 `_write_if_not_exists()`로 이미 멱등
- 다시 호출해도 기존 파일을 덮어쓰지 않음

### Step 2: docs-setup 하네스
- **Guard**: `completed/01-docs-setup.md` 존재 여부
  - `completed/`에 있음 → **스킵**
  - `active/`에 있음 → `run_harness()` 호출 (chunk resume은 체크박스로 자동)
  - 어디에도 없음 → Step 1이 안 된 것. 에러 또는 Step 1 재실행
- **신규 구현 필요**

### Step 3: 검증/승인
- **Guard**: `approval_mode == "auto"`면 항상 통과 (현재 기본값)
- 변경 불필요

### Step 4: 구현 plans 순차 실행
- **Guard**: 이미 멱등
  - `planning/` 비어있고 `active/` 비어있음 → while 루프 즉시 break (스킵)
  - `active/`에 plan 있음 → 해당 plan의 미완료 chunk부터 이어서
  - `planning/`에 plan 남아있음 → promote 후 실행
- 변경 불필요 — 기존 while 루프 로직이 이미 처리

## 4. 코드 변경 범위

### 4.1 harness_cfg 초기화를 Step 2 guard 이전으로 이동

현재 `harness_cfg` 생성 및 engine 설정 상속 코드가 Step 2 블록 안에 있다.
Step 2가 스킵되면 Step 4에서 `harness_cfg`가 정의되지 않아 `NameError`.

→ `harness_cfg` 초기화를 Step 2 guard **이전**으로 이동 (Step 2, 4 공용).
→ `ignored_sessions.clear()`는 Step 2 실행 블록(else) 안에 남김 (Phase 1 정리는 Step 2가 실행될 때만 필요).

```python
# ── 공통 설정 준비 (Step 2, 4에서 사용) ──────────────────────
config.project_dir = str(project_dir)
harness_cfg = harness_config_from(meta_config)
harness_cfg.engine = config.engine
if config.engine == "codex":
    harness_cfg.engine_command = config.codex_command
    harness_cfg.engine_args = config.codex_args or ["-q"]
else:
    harness_cfg.engine_command = config.claude_command
    harness_cfg.engine_args = config.claude_args or ["-p"]
```

### 4.2 `meta_runner.py` — Step 2 guard 추가

```python
# ── Step 2: Fill docs (Phase 2 harness) ──────────────────────
completed_dir = project_dir / harness_cfg.exec_plans_dir / "completed"
docs_setup_completed = (completed_dir / "01-docs-setup.md").exists()

if docs_setup_completed:
    logger.info("meta", "Step 2: 01-docs-setup already in completed/, skipping",
                completed_file=str(completed_dir / "01-docs-setup.md"))
    print("Step 2: 이미 완료, 스킵")
else:
    logger.info("meta", "Step 2: Filling docs via harness")
    print("\nStep 2: docs/ 내용 채우기 (Phase 2 하네스)...")
    # Phase 1 ON — clear ignored sessions (brief session is done)
    ignored_sessions.clear()
    run_harness(config, harness_cfg, ignored_sessions=ignored_sessions)
```

## 5. 엣지케이스

| 시나리오 | 동작 |
|---------|------|
| Step 2 중간에 강종 (active/에 01-docs-setup.md, chunk 3/5 완료) | Step 2 guard: active/에 있으므로 `run_harness()` 호출 → chunk 4부터 이어서 |
| Step 2 마지막 chunk 완료 직후 강종 (move_to_completed 전) | `run_harness()` 재진입 → `find_next_incomplete_chunk()` = None → completed/로 이동 → return |
| Step 4 중간에 강종 (planning/에 2개 남음, active/ 비어있음) | Step 4 while 루프: promote → 실행 → 반복 |
| Step 4 중간에 강종 (active/에 plan, chunk 2/3 완료) | `run_harness()` 재진입 → chunk 3부터 이어서 |
| 모든 Step 완료 후 재실행 | Step 0~4 전부 스킵, "메타 에이전트 완료!" 출력 |
| `active/01-docs-setup.md`가 corrupted (파싱 불가) | `run_harness()` → `parse_exec_plan()` 실패 → `sys.exit(1)`. 수동으로 파일 삭제 후 재실행 필요 |

## 6. 테스트 계획

- `test_step2_skip_when_completed`: `completed/01-docs-setup.md` 존재 시 `run_harness` 호출 안 됨
- `test_step2_resume_when_active`: `active/01-docs-setup.md` 존재 시 `run_harness` 호출됨
- `test_full_resume_all_steps_done`: 모든 산출물 존재 시 전체 스킵
- `test_harness_cfg_available_after_step2_skip`: Step 2 스킵 후에도 Step 4에서 harness_cfg 사용 가능
- `test_step2_corrupted_active_file`: active/에 파싱 불가 파일 → sys.exit(1) 확인
