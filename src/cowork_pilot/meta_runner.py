"""Meta-agent runner — Step 0~4 orchestration.

Coordinates brief collection, scaffolding, and Phase 2 harness
execution to go from a user description to a fully scaffolded project.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from cowork_pilot.brief_parser import parse_brief
from cowork_pilot.config import Config, HarnessConfig, MetaConfig, load_harness_config
from cowork_pilot.logger import StructuredLogger
from cowork_pilot.scaffolder import scaffold_project
from cowork_pilot.session_opener import open_new_session
from cowork_pilot.session_finder import find_active_jsonl


# ── Brief prompt ─────────────────────────────────────────────────────

BRIEF_PROMPT_TEMPLATE = """\
사용자가 새 프로젝트를 만들려고 합니다.

사용자의 설명: "{description}"

아래 브리프 템플릿의 항목을 하나씩 AskUserQuestion으로 물어보세요.
필수 항목(name, description, type, language, framework)은 반드시 답을 받아야 합니다.
선택 항목은 사용자가 "몰라" 또는 "알아서 해"라고 하면 스킵합니다.

모든 항목을 채웠으면 "이대로 진행할까요?" 확인 질문을 합니다.
승인 시 채워진 브리프를 docs/project-brief.md로 저장하고 세션을 종료합니다.
{resume_section}

## 브리프 항목

### 필수 (반드시 질문)
1. **프로젝트 이름** (name)
2. **한 줄 설명** (description)
3. **프로젝트 유형** (type): web-app, cli, api, library, mobile, other
4. **프로그래밍 언어** (language)
5. **프레임워크** (framework)

### 선택 (물어보되 스킵 가능)
6. 데이터베이스 (database)
7. 스타일링 (styling)
8. 패키지 매니저 (package_manager)
9. 페이지/기능 목록 (Pages/Features) — 각각 이름, 설명, 핵심 요소
10. 데이터 모델 (Data Model) — 엔티티, 필드, 관계
11. 아키텍처 결정 (Architecture Decisions)
12. 제약 (Constraints) — 인증, 배포, 성능, 접근성
13. 하지 않을 것 (Non-Goals)
14. 참고 자료 (References)

## 출력 형식

docs/project-brief.md로 저장. 형식:

```
# Project Brief

## 1. Overview
- name: "값"
- description: "값"
- type: "값"

## 2. Tech Stack
- language: "값"
- framework: "값"
- database: "값"
- styling: "값"
- package_manager: "값"

## 3. Pages / Features
- page: "이름"
  description: "설명"
  key_elements: ["요소1", "요소2"]

## 4. Data Model
- entity: "이름"
  fields: ["필드1", "필드2"]
  relations: ["관계1"]

## 5. Architecture Decisions
- decision: "결정"
  rationale: "근거"

## 6. Constraints
- auth: "값"
- deployment: "값"
- performance: "값"
- accessibility: "값"
- other: []

## 7. Non-Goals
- "하지 않을 것"

## 8. References
- ref: "이름"
  url: "URL"
  notes: "메모"
```
"""


BRIEF_RESUME_SECTION = """\
## 이전에 부분적으로 채워진 브리프

이전 세션에서 브리프가 부분적으로 채워졌습니다. 아래 내용을 기반으로 이어서 진행하세요.
이미 채워진 항목은 다시 물어볼 필요 없이 확인만 하고, 빠진 항목만 새로 물어보세요.

```
{existing_brief}
```
"""


def build_brief_prompt(
    meta_config: MetaConfig,
    existing_brief: str | None = None,
) -> str:
    """Build the initial prompt for the brief-filling Cowork session.

    If existing_brief is provided (resume mode), includes it in the prompt
    so the session continues from where the user left off.
    """
    resume_section = ""
    if existing_brief:
        resume_section = BRIEF_RESUME_SECTION.format(existing_brief=existing_brief)
    return BRIEF_PROMPT_TEMPLATE.format(
        description=meta_config.initial_description,
        resume_section=resume_section,
    )


# ── Harness config conversion ────────────────────────────────────────

def harness_config_from(meta_config: MetaConfig) -> HarnessConfig:
    """Create a HarnessConfig pointing at the meta project's exec-plans."""
    return HarnessConfig(
        exec_plans_dir="docs/exec-plans",
    )


# ── Brief completion detection ───────────────────────────────────────

def _session_ended(jsonl_path: Path) -> bool:
    """Check if the session JSONL indicates the session has ended.

    Detects the 'summary' record type that Cowork writes when a session
    finishes, or checks if the file hasn't been modified recently and
    contains a stop signal.
    """
    if not jsonl_path.exists():
        return False
    try:
        # Read last few lines efficiently
        text = jsonl_path.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().splitlines()
        # Check last 5 lines for session-end markers
        import json as _json
        for line in lines[-5:]:
            try:
                record = _json.loads(line.strip())
                if isinstance(record, dict):
                    # "summary" type = session completed
                    if record.get("type") == "summary":
                        return True
                    # "system" with subtype "end" = session ended
                    if (record.get("type") == "system"
                            and record.get("subtype") == "end"):
                        return True
            except (ValueError, _json.JSONDecodeError):
                continue
    except OSError:
        pass
    return False


def wait_for_brief_completion(
    jsonl_path: Path,
    meta_config: MetaConfig,
    poll_interval: float = 2.0,
    timeout: float = 3600.0,  # 1 hour max
) -> Path:
    """Wait for the brief-filling session to complete.

    Completion is detected when docs/project-brief.md exists in project_dir.
    The file is written by the Cowork session (not by us).

    Also monitors the session JSONL for early termination — if the session
    ends without producing the brief file, raises RuntimeError instead of
    waiting until timeout.

    Returns the path to the completed brief file.
    Raises TimeoutError if timeout exceeded.
    Raises RuntimeError if session ended without producing the brief.
    """
    brief_path = Path(meta_config.project_dir) / "docs" / "project-brief.md"
    start = time.monotonic()

    while (time.monotonic() - start) < timeout:
        if brief_path.exists() and brief_path.stat().st_size > 0:
            return brief_path
        if _session_ended(jsonl_path):
            raise RuntimeError(
                "Brief session ended without producing "
                f"{brief_path}. Check the session log: {jsonl_path}"
            )
        time.sleep(poll_interval)

    raise TimeoutError(f"Brief not completed within {timeout}s")


# ── Notification ─────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    """Send macOS notification."""
    from cowork_pilot.responder import notify
    notify(title, message)


def notify_and_wait_approval(meta_config: MetaConfig) -> None:
    """Send notification and wait for user to approve (manual mode).

    In manual mode, waits for a sentinel file:
    {project_dir}/docs/.meta-approved
    """
    _notify(
        "메타 에이전트 — 승인 필요",
        "docs/ 구조가 생성되었습니다. 확인 후 승인해주세요.",
    )

    sentinel = Path(meta_config.project_dir) / "docs" / ".meta-approved"
    print(f"\n승인 대기 중... 확인 후 다음 파일을 생성하세요: {sentinel}")
    print(f"  touch {sentinel}")

    while not sentinel.exists():
        time.sleep(2.0)

    # Clean up sentinel
    sentinel.unlink(missing_ok=True)


# ── Main orchestration ───────────────────────────────────────────────

def run_meta(config: Config, meta_config: MetaConfig) -> None:
    """Execute the full meta-agent workflow (Steps 0~4).

    Step 0: Open brief-filling Cowork session (Phase 1 OFF)
    Step 1: Scaffold project from completed brief
    Step 2: Run Phase 2 harness for docs-setup.md (Phase 1 ON)
    Step 3: Verify + approve (manual or auto)
    Step 4: Run Phase 2 harness for implementation.md (Phase 1 ON)
    """
    from cowork_pilot.main import run_harness
    from cowork_pilot.watcher import WatcherStateMachine

    logger = StructuredLogger(config.log_path, config.log_level)
    logger.info("meta", "Meta-agent starting", project_dir=meta_config.project_dir)

    project_dir = Path(meta_config.project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    base_path = Path(config.session_base_path).expanduser()

    # ── Step 0: Brief filling ────────────────────────────────────
    logger.info("meta", "Step 0: Brief")
    ignored_sessions: set[Path] = set()
    brief_path = project_dir / "docs" / "project-brief.md"
    brief_complete = False

    # Check for existing brief (resume support)
    existing_brief: str | None = None
    if brief_path.exists() and brief_path.stat().st_size > 0:
        existing_brief = brief_path.read_text(encoding="utf-8")
        try:
            parse_brief(brief_path)
            # Brief is complete — skip Step 0 entirely
            brief_complete = True
            logger.info("meta", "Step 0: Existing complete brief found, skipping",
                        brief=str(brief_path))
            print("Step 0: 기존 완성된 브리프 발견, 스킵합니다.")
        except (ValueError, OSError):
            # Brief exists but incomplete — will resume
            logger.info("meta", "Step 0: Partial brief found, resuming")
            print("Step 0: 이전 브리프 이어서 채우기...")

    if not brief_complete:
        if existing_brief is None:
            print("Step 0: 브리프 채우기 세션 열기...")

        prompt = build_brief_prompt(meta_config, existing_brief=existing_brief)
        success = open_new_session(initial_prompt=prompt)
        if not success:
            logger.error("meta", "Failed to open brief session")
            print("Error: 브리프 세션 열기 실패", file=sys.stderr)
            sys.exit(1)

        # Find the new session's JSONL (retry with backoff)
        brief_jsonl = None
        for _attempt in range(10):
            time.sleep(1.0)
            brief_jsonl = find_active_jsonl(base_path)
            if brief_jsonl is not None:
                break
        if brief_jsonl is None:
            logger.error("meta", "Cannot find brief session JSONL after 10s")
            print("Error: 브리프 세션 JSONL을 찾을 수 없습니다.", file=sys.stderr)
            sys.exit(1)

        # ignored_sessions는 run_harness()에 전달되어 Phase 1 auto-response를
        # 특정 세션에서 비활성화하는 데 사용.
        # Step 0에서는 run_meta()가 동기적으로 wait_for_brief_completion을 호출하므로
        # Phase 1 watcher가 동시에 돌지 않지만, Step 2/4에서 run_harness()에 전달 시 의미가 있다.
        # brief_jsonl은 Step 2 진입 전에 discard됨.
        ignored_sessions.add(brief_jsonl)
        logger.info("meta", "Brief session registered as ignored", jsonl=str(brief_jsonl))

        # Wait for brief completion
        print("사용자가 브리프를 채우는 중... (docs/project-brief.md 생성 대기)")
        try:
            brief_path = wait_for_brief_completion(brief_jsonl, meta_config)
        except TimeoutError:
            logger.error("meta", "Brief completion timeout")
            print("Error: 브리프 작성 시간 초과", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as e:
            logger.error("meta", "Brief session ended early", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        logger.info("meta", "Step 0 complete", brief=str(brief_path))
        print(f"브리프 완성: {brief_path}")

    # ── Step 1: Scaffolding ──────────────────────────────────────
    logger.info("meta", "Step 1: Scaffolding")
    print("\nStep 1: 프로젝트 스캐폴딩...")

    brief = parse_brief(brief_path)
    scaffold_project(brief, project_dir)

    logger.info("meta", "Step 1 complete")
    print("스캐폴딩 완료!")

    # ── 공통 설정 준비 (Step 2, 4에서 사용) ──────────────────────
    config.project_dir = str(project_dir)
    harness_cfg = harness_config_from(meta_config)

    # Inherit engine settings
    harness_cfg.engine = config.engine
    if config.engine == "codex":
        harness_cfg.engine_command = config.codex_command
        harness_cfg.engine_args = config.codex_args or ["-q"]
    else:
        harness_cfg.engine_command = config.claude_command
        harness_cfg.engine_args = config.claude_args or ["-p"]

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

    # ── Step 3: Verify + approve ─────────────────────────────────
    logger.info("meta", "Step 3: Verification")
    print("\nStep 3: 검증...")

    if meta_config.approval_mode == "manual":
        notify_and_wait_approval(meta_config)
        logger.info("meta", "Manual approval received")

    # ── Step 4: Implementation (Phase 2 harness) ─────────────────
    # Run all plans from planning/ sequentially.
    # Each iteration: promote next plan → run_harness (executes all chunks)
    # → plan moves to completed/ → loop back for next plan.
    logger.info("meta", "Step 4: Implementation via harness")
    print("\nStep 4: 구현 시작 (Phase 2 하네스)...")

    from cowork_pilot.session_manager import promote_next_plan
    exec_plans_dir = project_dir / harness_cfg.exec_plans_dir
    active_dir = exec_plans_dir / "active"
    plans_executed = 0

    while True:
        # Check if active/ already has a plan (e.g. first iteration or leftover)
        active_plans = list(active_dir.glob("*.md")) if active_dir.exists() else []

        if not active_plans:
            # Try to promote from planning/
            promoted = promote_next_plan(exec_plans_dir)
            if promoted:
                logger.info("meta", "Promoted plan to active", plan=str(promoted))
                print(f"  Plan promoted: {promoted.name}")
            else:
                # Nothing in active/ or planning/ — we're done (or never started)
                if plans_executed == 0 and not (completed_dir / "01-docs-setup.md").exists():
                    # First run: no plans at all — Step 2 should have created them
                    logger.error(
                        "meta",
                        "No plan in active/ or planning/. "
                        "Step 2 should have generated {NN}-*.md files in planning/ "
                        "via docs-setup Chunk 4.",
                        dir=str(exec_plans_dir),
                    )
                    print(
                        "Error: active/와 planning/ 모두 exec-plan이 없습니다.\n"
                        "docs-setup Chunk 4에서 planning/에 구현 계획이 생성되어야 합니다.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                break  # All plans executed (or already completed on resume)

        run_harness(config, harness_cfg, ignored_sessions=ignored_sessions)
        plans_executed += 1
        logger.info("meta", f"Plan #{plans_executed} completed")
        print(f"  Plan #{plans_executed} 완료!")

    logger.info("meta", "Meta-agent complete", plans_executed=plans_executed)
    print(f"\n메타 에이전트 완료! (총 {plans_executed}개 exec-plan 실행)")
