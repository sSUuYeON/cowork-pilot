"""Codex CLI harness — exec-plan lifecycle via ``codex exec``.

Drop-in replacement for the existing ``run_harness()`` that uses
``codex exec --dangerously-bypass-approvals-and-sandbox`` instead of
opening Cowork sessions via AppleScript.

Plan lifecycle is identical to the original harness:
  active/ → chunk-by-chunk execution → completed/ → promote from planning/

Key difference: no TUI manipulation, no JSONL polling for auto-response.
Each chunk is a single ``codex exec`` subprocess.  We monitor its Codex
JSONL for progress, and on completion we verify checkboxes + run [BUILD]
criteria locally.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from cowork_pilot.plan_parser import Chunk, parse_exec_plan, update_checkboxes
from cowork_pilot.session_manager import (
    find_next_incomplete_chunk,
    move_to_completed,
    notify_escalate,
    promote_next_plan,
    build_session_prompt,
)
from cowork_pilot.completion_detector import run_build_criteria
from cowork_pilot.codex.models import ChunkResult, ChunkRunStatus
from cowork_pilot.codex.exec_runner import run_chunk_with_retry
from cowork_pilot.codex.config import CodexExecConfig

logger = logging.getLogger("cowork-pilot.codex.harness")

_RESULT_SNIPPET_CHARS = 2000


# ── Codex compatibility + skill references ──────────────────────────

_CODEX_EXEC_COMPAT_NOTE = """\

## Codex Exec Compatibility

위 session prompt의 순서와 요구사항을 그대로 따른다.
`/engineering:code-review`, `/chunk-complete:chunk-complete`, `/vm-install:vm-install`
같은 slash command 표기는 Codex exec에서 직접 수행해야 할 작업 지시로 해석해라.
작업 시작 전에 현재 active exec-plan 파일을 직접 다시 읽고, 현재 chunk의
Completion Criteria를 확인해라.
완료 후 통과한 criteria만 체크하고, exec-plan 파일을 `active/`에서 `completed/`로
이동하지 마라."""

_CODE_REVIEW_SKILL_REFERENCE = """\

## Skill Reference: code-review

Use this when the prompt asks for `/engineering:code-review`.

Review the code for:
- Security: SQL injection, XSS, CSRF, auth flaws, secrets in code, insecure deserialization, path traversal, SSRF
- Performance: N+1 queries, unnecessary memory allocations, O(n^2) hot paths, missing indexes, unbounded loops or queries, resource leaks
- Correctness: empty input, null handling, overflow, race conditions, error propagation, off-by-one, type safety
- Maintainability: naming clarity, single responsibility, duplication, test coverage, documentation for non-obvious logic

Output expectations:
- Rate each dimension
- Provide specific actionable findings with file and line references
- Prioritize critical issues first
- Include positive observations alongside issues

Do not stop at reporting issues. Fix the important problems you find before moving on to chunk completion."""

_CHUNK_COMPLETE_SKILL_REFERENCE = """\

## Skill Reference: chunk-complete

Use this when the prompt asks for `/chunk-complete:chunk-complete`.

Process:
1. Read the current exec-plan in `docs/exec-plans/active/` and inspect the current chunk's Completion Criteria.
2. Verify each criterion directly. Check file existence, code state, and behavior yourself.
3. For `[BUILD]` criteria, do not run the build or test command in Codex. The local harness runs those.
4. Mark only the criteria that actually passed: `- [ ]` -> `- [x]`.
5. Partial completion is allowed. Leave unmet criteria as `- [ ]`.
6. If every criterion in the current chunk is `[x]`, the chunk is complete.
7. If every chunk in the exec-plan is complete, update metadata `status: completed`.

Critical rule:
- Never move the exec-plan file from `active/` to `completed/`. Harness handles file movement.

Red flags:
- Finishing tasks without checking criteria
- Bulk-checking criteria without verification
- Treating code completion as enough without checkbox updates
- Marking the whole chunk complete when only some criteria passed"""


# ── Prompt builder that includes review + chunk-complete ────────────

def _harness_prompt_builder(chunk: Chunk, project_dir: str) -> str:
    """Build the prompt by reusing the original session prompt wrapper."""
    from cowork_pilot.config import load_review_config
    review_config = None
    config_path = Path(project_dir) / "config.toml"
    if config_path.exists():
        review_config = load_review_config(config_path)

    enriched_prompt = build_session_prompt(chunk, review_config=review_config)

    header = (
        f"You are working on: Chunk {chunk.number} — {chunk.name}\n"
        f"Project directory: {project_dir}\n"
        f"\n"
        f"Complete the following tasks without asking follow-up questions.\n"
        f"\n"
        f"---\n"
    )

    return (
        header
        + enriched_prompt
        + _CODEX_EXEC_COMPAT_NOTE
        + _CODE_REVIEW_SKILL_REFERENCE
        + _CHUNK_COMPLETE_SKILL_REFERENCE
    )


def _build_repair_prompt(chunk: Chunk, project_dir: str, build_error_log: str) -> str:
    """Build a focused prompt for build-repair retry.

    Includes the original session prompt for context, the build error log,
    and strict instructions to preserve existing implementation while making
    minimal fixes.  Does NOT include code-review or chunk-complete skill
    references — this is a focused fix, not a full implementation pass.
    """
    header = (
        f"You are working on: Chunk {chunk.number} — {chunk.name}\n"
        f"Project directory: {project_dir}\n"
        f"\n"
        f"## Build Repair Mode\n"
        f"\n"
        f"이 chunk의 구현은 완료되었으나 로컬 빌드가 실패했다.\n"
        f"비빌드 Completion Criteria는 이미 통과한 상태이므로 유지할 것.\n"
        f"기존 구현 의도를 보존하고 최소 수정으로 빌드 오류만 해결할 것.\n"
        f"\n"
    )
    original = (
        f"### Original Session Prompt (맥락 참고용)\n"
        f"{chunk.session_prompt}\n"
        f"\n"
    )
    error = (
        f"### Build Error Log\n"
        f"```\n"
        f"{build_error_log}\n"
        f"```\n"
        f"\n"
    )
    footer = (
        f"수정 후 [BUILD] 항목은 직접 실행하지 말 것 — 로컬 harness가 자동으로 실행한다.\n"
        f"exec-plan 파일의 체크박스를 변경하지 말 것.\n"
    )
    return header + original + error + footer


def _build_incomplete_repair_prompt(
    chunk: Chunk,
    project_dir: str,
    unchecked_descriptions: list[str],
) -> str:
    """Build a focused prompt for retrying incomplete (non-build) criteria.

    Lists only the unchecked criteria and instructs codex to fix only those,
    preserving everything that already passes.  Does NOT include code-review
    or chunk-complete skill references.
    """
    criteria_list = "\n".join(f"- {desc}" for desc in unchecked_descriptions)
    header = (
        f"You are working on: Chunk {chunk.number} — {chunk.name}\n"
        f"Project directory: {project_dir}\n"
        f"\n"
        f"## Incomplete Criteria Repair Mode\n"
        f"\n"
        f"이 chunk의 codex exec는 성공했으나 일부 Completion Criteria가 아직 미충족이다.\n"
        f"이미 통과한 criteria와 기존 구현은 절대 건드리지 말 것.\n"
        f"아래 미충족 항목만 해결할 것.\n"
        f"\n"
    )
    original = (
        f"### Original Session Prompt (맥락 참고용)\n"
        f"{chunk.session_prompt}\n"
        f"\n"
    )
    unchecked = (
        f"### 미충족 Completion Criteria\n"
        f"{criteria_list}\n"
        f"\n"
    )
    footer = (
        f"[BUILD] 항목은 직접 실행하지 말 것 — 로컬 harness가 자동으로 실행한다.\n"
        f"통과한 criteria의 체크박스를 변경하지 말 것.\n"
    )
    return header + original + unchecked + footer


async def _run_incomplete_repair_loop(
    plan_path: Path,
    chunk: Chunk,
    project_dir: str,
    unchecked_descriptions: list[str],
    exec_config: CodexExecConfig,
) -> tuple[str, str]:
    """Run incomplete-criteria repair loop.

    Sends a focused prompt listing only unchecked criteria, then re-verifies.
    If verification returns BUILD_FAILED, delegates to ``_run_build_repair_loop``.
    Repeats up to ``exec_config.max_retries`` times.

    Returns:
        (status, detail) — same contract as _verify_and_update_chunk.
    """
    max_attempts = exec_config.max_retries

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Incomplete repair attempt %d/%d for chunk %d",
            attempt, max_attempts, chunk.number,
        )
        print(
            f"  🔄 Incomplete repair attempt {attempt}/{max_attempts}",
            file=sys.stderr,
        )

        repair_prompt = _build_incomplete_repair_prompt(
            chunk, project_dir, unchecked_descriptions,
        )

        def _repair_builder(c: Chunk, p: str, _prompt=repair_prompt) -> str:
            return _prompt

        result = await run_chunk_with_retry(
            chunk,
            project_dir,
            max_retries=1,
            codex_command=exec_config.command,
            codex_extra_args=exec_config.extra_args or None,
            timeout_seconds=exec_config.build_timeout_seconds,
            stalled_output_timeout_seconds=exec_config.stalled_output_timeout_seconds,
            prompt_builder=_repair_builder,
        )

        _print_chunk_result(result)

        if result.status != ChunkRunStatus.SUCCESS:
            logger.warning(
                "Incomplete repair attempt %d: codex exec failed (%s)",
                attempt, result.status.value,
            )
            print(
                f"  ✗ Repair codex exec failed ({result.status.value})",
                file=sys.stderr,
            )
            continue

        # Re-verify
        verify_status, verify_detail = _verify_and_update_chunk(
            plan_path, chunk, project_dir,
            build_timeout=exec_config.build_timeout_seconds,
        )

        if verify_status == "COMPLETED":
            return (verify_status, verify_detail)

        if verify_status == "BUILD_FAILED":
            # Delegate to build-repair loop
            print(
                f"  ⚠ Build failed during incomplete repair, entering build repair loop",
                file=sys.stderr,
            )
            return await _run_build_repair_loop(
                plan_path=plan_path,
                chunk=chunk,
                project_dir=project_dir,
                build_error_log=verify_detail,
                exec_config=exec_config,
            )

        # Still INCOMPLETE — update unchecked list for next attempt
        fresh_chunk = _find_chunk_by_number(plan_path, chunk.number)
        if fresh_chunk is not None:
            unchecked_descriptions = [
                _format_completion_criterion_label(cr.description, cr.build_command)
                for cr in fresh_chunk.completion_criteria
                if not cr.checked
            ]
        logger.warning(
            "Incomplete repair attempt %d: still incomplete",
            attempt,
        )
        print(
            f"  ✗ Still incomplete after repair attempt {attempt}",
            file=sys.stderr,
        )

    return ("INCOMPLETE", ", ".join(unchecked_descriptions))


async def _run_build_repair_loop(
    plan_path: Path,
    chunk: Chunk,
    project_dir: str,
    build_error_log: str,
    exec_config: CodexExecConfig,
) -> tuple[str, str]:
    """Run build-repair retry loop.

    Sends a focused repair prompt to codex, then re-runs local build
    verification.  Repeats up to ``exec_config.build_repair_max_retries``
    times.  Each iteration uses the latest build error log so codex sees
    fresh diagnostics.

    Returns:
        (status, detail) — same contract as _verify_and_update_chunk.
    """
    max_attempts = exec_config.build_repair_max_retries

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Build repair attempt %d/%d for chunk %d",
            attempt, max_attempts, chunk.number,
        )
        print(
            f"  🔧 Build repair attempt {attempt}/{max_attempts}",
            file=sys.stderr,
        )

        repair_prompt = _build_repair_prompt(chunk, project_dir, build_error_log)

        def _repair_builder(c: Chunk, p: str, _prompt=repair_prompt) -> str:
            return _prompt

        result = await run_chunk_with_retry(
            chunk,
            project_dir,
            max_retries=1,
            codex_command=exec_config.command,
            codex_extra_args=exec_config.extra_args or None,
            timeout_seconds=exec_config.build_timeout_seconds,
            stalled_output_timeout_seconds=exec_config.stalled_output_timeout_seconds,
            prompt_builder=_repair_builder,
        )

        _print_chunk_result(result)

        if result.status != ChunkRunStatus.SUCCESS:
            logger.warning(
                "Build repair attempt %d: codex exec failed (%s)",
                attempt, result.status.value,
            )
            print(
                f"  ✗ Repair codex exec failed ({result.status.value})",
                file=sys.stderr,
            )
            continue

        # Re-verify: run local builds again
        verify_status, verify_detail = _verify_and_update_chunk(
            plan_path, chunk, project_dir,
            build_timeout=exec_config.build_timeout_seconds,
        )

        if verify_status != "BUILD_FAILED":
            return (verify_status, verify_detail)

        # Still failing — update error log for next attempt
        build_error_log = verify_detail
        logger.warning(
            "Build repair attempt %d: build still failing",
            attempt,
        )
        print(
            f"  ✗ Build still failing after repair attempt {attempt}",
            file=sys.stderr,
        )

    return ("BUILD_FAILED", build_error_log)


def _find_chunk_by_number(plan_path: Path, chunk_number: int) -> Chunk | None:
    """Return the chunk with the given number from the current plan file."""
    plan = parse_exec_plan(plan_path)
    for chunk in plan.chunks:
        if chunk.number == chunk_number:
            return chunk
    return None


def _format_completion_criterion_label(description: str, build_command: str) -> str:
    """Render a completion criterion label for terminal output."""
    if build_command:
        return f"[BUILD] {description}"
    return description


def _print_recognized_criteria(chunk: Chunk) -> None:
    """Print the criteria the parser recognized for this chunk."""
    criteria = chunk.completion_criteria
    print(
        f"    Recognized Completion Criteria ({len(criteria)}):",
        file=sys.stderr,
    )
    for criterion in criteria:
        mark = "x" if criterion.checked else " "
        label = _format_completion_criterion_label(
            criterion.description,
            criterion.build_command,
        )
        print(f"      - [{mark}] {label}", file=sys.stderr)


def _get_unchecked_criteria(plan_path: Path, chunk_number: int) -> list[str]:
    """List unchecked completion criteria for the current chunk state."""
    chunk = _find_chunk_by_number(plan_path, chunk_number)
    if chunk is None:
        return []

    return [
        _format_completion_criterion_label(cr.description, cr.build_command)
        for cr in chunk.completion_criteria
        if not cr.checked
    ]


def _print_unchecked_criteria(plan_path: Path, chunk_number: int) -> None:
    """Print any remaining unchecked completion criteria for a chunk."""
    unchecked = _get_unchecked_criteria(plan_path, chunk_number)
    if not unchecked:
        return

    print("    Remaining Completion Criteria:", file=sys.stderr)
    for item in unchecked:
        print(f"      - [ ] {item}", file=sys.stderr)


# ── Post-exec verification ──────────────────────────────────────────

def _verify_and_update_chunk(
    plan_path: Path,
    chunk: Chunk,
    project_dir: str,
    build_timeout: float = 600.0,
) -> tuple[str, str]:
    """After codex exec finishes, verify the chunk and update checkboxes.

    Steps:
    1. Re-parse the plan to check if codex already updated checkboxes
    2. Run [BUILD] criteria locally
    3. If all criteria are checked → COMPLETED
    4. If non-build criteria remain unchecked → INCOMPLETE (do not force-check)

    Returns:
        (status, detail)
        status ∈ {"COMPLETED", "INCOMPLETE", "BUILD_FAILED"}
    """
    # Re-parse to see current state
    fresh_chunk = _find_chunk_by_number(plan_path, chunk.number)

    if fresh_chunk is None:
        return ("INCOMPLETE", "Chunk not found after re-parsing exec-plan")

    # Run [BUILD] criteria locally
    has_unchecked_builds = any(
        c.build_command and not c.checked
        for c in fresh_chunk.completion_criteria
    )

    if has_unchecked_builds:
        build_status, build_detail = run_build_criteria(
            fresh_chunk, project_dir, plan_path,
            timeout=build_timeout,
        )
        if build_status == "FAILED":
            logger.warning("Build failed for chunk %d: %s", chunk.number, build_detail)
            return ("BUILD_FAILED", build_detail)

    # Re-parse after build criteria may have updated checkboxes
    fresh_chunk = _find_chunk_by_number(plan_path, chunk.number)
    if fresh_chunk is None:
        return ("INCOMPLETE", "Chunk disappeared after build verification")

    # Check if all criteria are now satisfied
    unchecked = [
        cr for cr in fresh_chunk.completion_criteria
        if not cr.checked
    ]

    if not unchecked:
        return ("COMPLETED", "")

    # Report remaining unchecked criteria — do NOT force-check
    unchecked_desc = ", ".join(
        _format_completion_criterion_label(cr.description, cr.build_command)
        for cr in unchecked
    )
    logger.info(
        "Chunk %d: %d criteria still unchecked: %s",
        chunk.number, len(unchecked), unchecked_desc,
    )
    return ("INCOMPLETE", unchecked_desc)


# ── Notification helper ─────────────────────────────────────────────

def _notify(title: str, body: str, tts: bool = False) -> None:
    """Send macOS notification (best-effort)."""
    try:
        from cowork_pilot.responder import notify
        notify(title, body, tts=tts)
    except Exception:
        pass  # Non-critical


def _print_dry_run_preview(plan_path: Path, project_dir: str) -> None:
    """Preview the current active plan without modifying any files."""
    plan = parse_exec_plan(plan_path)
    print(f"\nPlan: {plan.title} ({plan_path.name})", file=sys.stderr)

    for chunk in plan.chunks:
        if chunk.status == "completed":
            continue

        prompt = _harness_prompt_builder(chunk, project_dir)
        print(f"\n  Chunk {chunk.number}: {chunk.name}", file=sys.stderr)
        _print_recognized_criteria(chunk)
        print(f"  [DRY RUN] Would execute codex exec", file=sys.stderr)
        print(
            f"  Prompt ({len(prompt)} chars): {prompt[:150]}...",
            file=sys.stderr,
        )


# ── Main harness loop ───────────────────────────────────────────────

async def run_codex_harness(
    exec_plans_dir: str,
    project_dir: str,
    exec_config: CodexExecConfig,
    *,
    dry_run: bool = False,
) -> bool:
    """Run the full harness loop: plan lifecycle + codex exec.

    Mirrors ``main.py:run_harness()`` but uses codex exec subprocess.

    Args:
        exec_plans_dir: Path to docs/exec-plans/ (contains active/, planning/, completed/)
        project_dir: Project working directory for codex exec
        exec_config: Codex exec configuration
        dry_run: Preview without executing

    Returns:
        True if all plans completed successfully.
    """
    plans_dir = Path(exec_plans_dir)
    active_dir = plans_dir / "active"
    active_dir.mkdir(parents=True, exist_ok=True)

    print("Codex Harness starting", file=sys.stderr)
    print(f"  Plans dir: {plans_dir}", file=sys.stderr)
    print(f"  Project: {project_dir}", file=sys.stderr)
    if dry_run:
        print(f"  *** DRY RUN ***", file=sys.stderr)
    print(file=sys.stderr)

    while True:
        # ── Find or promote active plan ─────────────────────────────
        plan_files = list(active_dir.glob("*.md"))

        if not plan_files:
            promoted = promote_next_plan(plans_dir)
            if promoted is None:
                print("No more plans to execute. Done!", file=sys.stderr)
                _notify("✅ Codex Harness", "모든 구현 계획이 완료되었습니다.", tts=True)
                return True
            print(f"Promoted: {promoted.name}", file=sys.stderr)
            plan_files = [promoted]

        if len(plan_files) > 1:
            names = [f.name for f in plan_files]
            print(
                f"Error: active/에 계획이 2개 이상입니다: {names}",
                file=sys.stderr,
            )
            notify_escalate("active/에 계획이 2개 이상 — 수동 확인 필요")
            return False

        plan_path = plan_files[0]

        if dry_run:
            _print_dry_run_preview(plan_path, project_dir)
            return True

        try:
            plan = parse_exec_plan(plan_path)
        except (ValueError, OSError) as e:
            notify_escalate(f"exec-plan parse error: {e}")
            return False

        print(f"\nPlan: {plan.title} ({plan_path.name})", file=sys.stderr)

        # ── Process chunks ──────────────────────────────────────────
        all_chunks_ok = True

        while True:
            plan = parse_exec_plan(plan_path)
            chunk = find_next_incomplete_chunk(plan)

            if chunk is None:
                # All chunks done
                break

            print(
                f"\n  Chunk {chunk.number}: {chunk.name}",
                file=sys.stderr,
            )
            _print_recognized_criteria(chunk)

            # Execute chunk via codex exec (with retry)
            result = await run_chunk_with_retry(
                chunk,
                project_dir,
                max_retries=exec_config.max_retries,
                codex_command=exec_config.command,
                codex_extra_args=exec_config.extra_args or None,
                timeout_seconds=exec_config.build_timeout_seconds,
                stalled_output_timeout_seconds=exec_config.stalled_output_timeout_seconds,
                prompt_builder=_harness_prompt_builder,
            )

            _print_chunk_result(result)

            if result.status == ChunkRunStatus.SUCCESS:
                # Verify + update checkboxes
                verify_status, verify_detail = _verify_and_update_chunk(
                    plan_path, chunk, project_dir,
                    build_timeout=exec_config.build_timeout_seconds,
                )
                if verify_status == "COMPLETED":
                    print(f"  ✓ Chunk {chunk.number} completed", file=sys.stderr)
                    if verify_detail:
                        print(f"    verify: {verify_detail}", file=sys.stderr)
                elif verify_status == "BUILD_FAILED":
                    # Enter build-repair loop
                    print(
                        f"  ⚠ Chunk {chunk.number}: build failed, entering repair loop",
                        file=sys.stderr,
                    )
                    if verify_detail:
                        print(f"    build error: {verify_detail[:200]}", file=sys.stderr)

                    repair_status, repair_detail = await _run_build_repair_loop(
                        plan_path=plan_path,
                        chunk=chunk,
                        project_dir=project_dir,
                        build_error_log=verify_detail,
                        exec_config=exec_config,
                    )
                    if repair_status == "COMPLETED":
                        print(
                            f"  ✓ Chunk {chunk.number} completed after build repair",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    repair: {repair_detail}", file=sys.stderr)
                    elif repair_status == "INCOMPLETE":
                        # Build fixed, but non-build criteria still unchecked
                        print(
                            f"  ⚠ Chunk {chunk.number}: build repaired but criteria still incomplete",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    incomplete: {repair_detail[:200]}", file=sys.stderr)
                        _print_unchecked_criteria(plan_path, chunk.number)

                        fresh = _find_chunk_by_number(plan_path, chunk.number)
                        unchecked_descs = [
                            _format_completion_criterion_label(cr.description, cr.build_command)
                            for cr in (fresh.completion_criteria if fresh else [])
                            if not cr.checked
                        ]

                        print(
                            f"  ↻ Chunk {chunk.number}: entering incomplete repair loop",
                            file=sys.stderr,
                        )
                        inc_status, inc_detail = await _run_incomplete_repair_loop(
                            plan_path=plan_path,
                            chunk=chunk,
                            project_dir=project_dir,
                            unchecked_descriptions=unchecked_descs,
                            exec_config=exec_config,
                        )
                        if inc_status == "COMPLETED":
                            print(
                                f"  ✓ Chunk {chunk.number} completed after build + incomplete repair",
                                file=sys.stderr,
                            )
                        else:
                            print(
                                f"  ✗ Chunk {chunk.number}: incomplete repair failed — {inc_status}",
                                file=sys.stderr,
                            )
                            if inc_detail:
                                print(f"    detail: {inc_detail[:200]}", file=sys.stderr)
                            _print_unchecked_criteria(plan_path, chunk.number)
                            notify_escalate(
                                f"Chunk {chunk.number} ({chunk.name}) incomplete repair 실패 — "
                                f"{inc_status}: {inc_detail[:200] if inc_detail else ''}"
                            )
                            all_chunks_ok = False
                            break
                    else:
                        # BUILD_FAILED — build repair couldn't fix it
                        print(
                            f"  ✗ Chunk {chunk.number}: build repair failed — {repair_status}",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    detail: {repair_detail[:200]}", file=sys.stderr)
                        _print_unchecked_criteria(plan_path, chunk.number)
                        notify_escalate(
                            f"Chunk {chunk.number} ({chunk.name}) build repair 실패 — "
                            f"{repair_status}: {repair_detail[:200]}"
                        )
                        all_chunks_ok = False
                        break
                else:
                    # INCOMPLETE — some criteria unchecked
                    print(
                        f"  ⚠ Chunk {chunk.number}: codex succeeded but verify={verify_status}",
                        file=sys.stderr,
                    )
                    if verify_detail:
                        print(f"    verify: {verify_detail}", file=sys.stderr)
                    _print_unchecked_criteria(plan_path, chunk.number)

                    # Collect unchecked criteria descriptions for focused retry
                    fresh = _find_chunk_by_number(plan_path, chunk.number)
                    unchecked_descs = [
                        _format_completion_criterion_label(cr.description, cr.build_command)
                        for cr in (fresh.completion_criteria if fresh else [])
                        if not cr.checked
                    ]

                    print(
                        f"  ↻ Chunk {chunk.number}: entering incomplete repair loop",
                        file=sys.stderr,
                    )
                    repair_status, repair_detail = await _run_incomplete_repair_loop(
                        plan_path=plan_path,
                        chunk=chunk,
                        project_dir=project_dir,
                        unchecked_descriptions=unchecked_descs,
                        exec_config=exec_config,
                    )
                    if repair_status == "COMPLETED":
                        print(
                            f"  ✓ Chunk {chunk.number} completed after incomplete repair",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"  ✗ Chunk {chunk.number}: incomplete repair failed — {repair_status}",
                            file=sys.stderr,
                        )
                        if repair_detail:
                            print(f"    detail: {repair_detail[:200]}", file=sys.stderr)
                        _print_unchecked_criteria(plan_path, chunk.number)
                        notify_escalate(
                            f"Chunk {chunk.number} ({chunk.name}) incomplete repair 실패 — "
                            f"{repair_status}: {repair_detail[:200] if repair_detail else ''}"
                        )
                        all_chunks_ok = False
                        break
            else:
                # Chunk failed after all retries
                print(
                    f"  ✗ Chunk {chunk.number} FAILED after {result.attempt} attempts",
                    file=sys.stderr,
                )
                _print_unchecked_criteria(plan_path, chunk.number)
                notify_escalate(
                    f"Chunk {chunk.number} ({chunk.name}) 실패 — "
                    f"{result.status.value}, {result.attempt}회 시도"
                )
                all_chunks_ok = False
                break

        # ── Plan complete → move to completed/ ──────────────────────
        if all_chunks_ok:
            completed_path = move_to_completed(plan_path)
            print(f"\n  Plan completed → {completed_path}", file=sys.stderr)
            _notify("✅ Plan 완료", plan.title)
        else:
            print(f"\n  Plan failed — stopping", file=sys.stderr)
            return False

    # unreachable, but for type checker
    return True


def _print_chunk_result(result: ChunkResult) -> None:
    """Print chunk execution result to stderr."""
    icon = {
        ChunkRunStatus.SUCCESS: "✓",
        ChunkRunStatus.FAILED: "✗",
        ChunkRunStatus.TIMEOUT: "⏱",
    }.get(result.status, "?")

    duration = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds > 0 else ""
    attempt = f" [attempt {result.attempt}]" if result.attempt > 1 else ""

    print(
        f"  {icon} codex exec: {result.status.value}{duration}{attempt}",
        file=sys.stderr,
    )
    if result.last_message:
        snippet = result.last_message[-_RESULT_SNIPPET_CHARS:].strip()
        print(f"    last message: {snippet}", file=sys.stderr)
    if result.status != ChunkRunStatus.SUCCESS and result.stderr:
        snippet = result.stderr[-_RESULT_SNIPPET_CHARS:].strip()
        print(f"    stderr: ...{snippet}", file=sys.stderr)
    elif result.status != ChunkRunStatus.SUCCESS and result.event_log:
        snippet = result.event_log[-_RESULT_SNIPPET_CHARS:].strip()
        print(f"    events: ...{snippet}", file=sys.stderr)
    elif result.status != ChunkRunStatus.SUCCESS and result.stdout:
        snippet = result.stdout[-_RESULT_SNIPPET_CHARS:].strip()
        print(f"    stdout: ...{snippet}", file=sys.stderr)
