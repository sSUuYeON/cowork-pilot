"""Main docs-orchestrator state machine.

Implements the Phase 0 → 1 → 1.5 → 2 → 3 → 4 → 5 → done orchestration loop.
Design reference: §3 (동작 흐름), §5.0–5.5, §7.3, §9, §12.1.

Reuses existing cowork-pilot infrastructure:
- session_opener.open_new_session() for opening Cowork sessions
- session_manager.detect_new_jsonl() for JSONL file detection
- completion_detector.is_idle_trigger() for idle detection
- watcher / responder modules for Phase 1 auto-response (cooperative loop)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.orchestrator_prompts import build_session_prompt, get_section_keywords
from cowork_pilot.orchestrator_state import (
    OrchestratorState,
    StepStatus,
    _MIN_LINES_BY_PHASE,
    _DONE_MARKER,
    _file_has_done_marker,
    compute_adaptive_timeout,
    estimate_sessions,
    generate_gap_summary,
    load_state,
    recover_running_step,
    save_state,
)
from cowork_pilot.quality_gate import GateResult, check_phase1_quality


# ── Constants ───────────────────────────────────────────────────────

_SOURCE_DIR_NAME = "sources"
_GENERATED_DIR = "docs/generated"
_STATE_FILENAME = "orchestrator-state.json"
_REFERENCES_DIR = "references"
_PLANNING_DIR = "docs/exec-plans/planning"

_FORBIDDEN_EXPRESSIONS = [
    "적절한", "필요시", "충분한", "등등", "TBD", "추후 작성", "TODO",
]


def _parse_expected_files(prompt: str) -> list[Path]:
    """Extract expected output file paths from a rendered prompt.

    Parses the ``출력 파일:`` section and returns a list of ``Path`` objects.
    This makes the template the single source of truth for expected paths,
    eliminating hard-coded path duplication in orchestrator code.
    """
    # Find the "출력 파일:" section
    match = re.search(r"출력 파일:\s*\n((?:\s*-\s*.+\n?)+)", prompt)
    if not match:
        return []
    block = match.group(1)
    paths: list[Path] = []
    for line in block.strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            path_str = line[2:].strip()
            if path_str:
                paths.append(Path(path_str))
    return paths


# ── Index generation ───────────────────────────────────────────────


def _generate_specs_index(specs_dir: Path) -> None:
    """Generate index.md by scanning all spec files in the directory.

    Called once after all phase_3_B bundles complete, so the index
    always reflects the full set of product-specs.
    """
    if not specs_dir.exists():
        return

    spec_files = sorted(
        f for f in specs_dir.glob("*.md")
        if f.name != "index.md"
    )

    if not spec_files:
        return

    lines: list[str] = ["# Product Specs 색인", ""]
    lines.append("| 문서 | 설명 | 상태 |")
    lines.append("|------|------|------|")

    for spec_file in spec_files:
        # Extract title from first heading line
        description = ""
        try:
            with open(spec_file, "r", encoding="utf-8") as f:
                for file_line in f:
                    file_line = file_line.strip()
                    if file_line.startswith("# "):
                        description = file_line[2:].strip()
                        # Remove " — 제품 스펙" suffix if present
                        if "—" in description:
                            description = description.split("—")[0].strip()
                        break
        except OSError:
            description = spec_file.stem

        if not description:
            description = spec_file.stem

        lines.append(
            f"| [{spec_file.name}](./{spec_file.name}) "
            f"| {description} | Draft |"
        )

    lines.append("")
    lines.append(_DONE_MARKER)

    index_path = specs_dir / "index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Generated {index_path}", file=sys.stderr)


# ── Public entry point ──────────────────────────────────────────────


def run_docs_orchestrator(
    config: Config,
    orch_config: DocsOrchestratorConfig,
) -> None:
    """Main orchestrator state-machine loop.

    Reads ``orchestrator-state.json``, determines the next step, opens AI
    sessions as needed, waits for completion, and updates the state file.
    Handles Phase 0 → 1 → 1.5 → 2 → 3 → 4 → 5 → done.
    """
    project_dir = Path(config.project_dir)
    generated_dir = project_dir / _GENERATED_DIR
    state_path = generated_dir / _STATE_FILENAME
    base_path = Path(config.session_base_path).expanduser()

    # Load or create state
    state = load_state(state_path)

    # Recover from a previous crash (§8.3)
    if state.current.get("status") == "running":
        print("Recovering from interrupted session...", file=sys.stderr)
        state = recover_running_step(state, project_dir)
        save_state(state, state_path)

    # Main loop
    while True:
        next_step = _determine_next_step(state)

        if next_step is None:
            # Check if this is a max-retry stop vs genuine completion
            phase_1_5_errors = sum(
                1 for e in state.errors if e.get("step") == "phase_1_5"
            )
            if phase_1_5_errors >= _PHASE_1_5_MAX_RETRIES:
                print(
                    f"\n⚠️  Phase 1.5 품질 검증이 {phase_1_5_errors}회 실패하여 중단합니다.\n"
                    "   해결 방법:\n"
                    "   1. docs/generated/orchestrator-state.json 삭제 후 재실행\n"
                    "   2. 또는 Phase 1 AI 세션 출력물(docs/generated/)을 수동 확인\n",
                    file=sys.stderr,
                )
                _notify_escalate(f"Phase 1→1.5 반복 실패 ({phase_1_5_errors}회) — 수동 확인 필요")
            else:
                print("All steps completed!", file=sys.stderr)
            break

        print(f"\n>>> Next step: {next_step}", file=sys.stderr)

        if next_step == "phase_0":
            state = _run_phase_0(
                state, config, orch_config, project_dir, generated_dir, state_path,
            )
        elif next_step == "phase_1_5":
            # Must check phase_1_5 BEFORE phase_1 (startswith match)
            state = _run_phase_1_5(
                state, config, orch_config, project_dir, state_path,
            )
        elif next_step.startswith("phase_1"):
            state = _run_phase_1(
                state, config, orch_config, project_dir, generated_dir,
                base_path, state_path,
            )
            # If Phase 1.5 failed, the state will reflect it and the next
            # iteration will decide whether to retry or escalate.
        elif next_step == "phase_2":
            state = _run_phase_2(
                state, config, orch_config, project_dir, base_path, state_path,
            )
        elif next_step in ("phase_3_A", "phase_3_B", "phase_3_C", "phase_3_D"):
            state = _run_phase_3(
                state, config, orch_config, project_dir, base_path, state_path,
            )
        elif next_step in ("phase_4_1", "phase_4_2", "phase_4_3"):
            state = _run_phase_4(
                state, config, orch_config, project_dir, base_path, state_path,
                next_step,
            )
        elif next_step == "phase_5_outline":
            state = _run_phase_5_outline(
                state, config, orch_config, project_dir, base_path, state_path,
            )
        elif next_step.startswith("phase_5_detail:"):
            state = _run_phase_5_detail(
                state, config, orch_config, project_dir, base_path, state_path,
                next_step,
            )
        elif next_step == "done":
            _run_final_completion(state, project_dir)
            break
        else:
            print(f"Unknown step: {next_step}", file=sys.stderr)
            break

        save_state(state, state_path)


# ── Phase 0 ─────────────────────────────────────────────────────────


def _run_phase_0(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    generated_dir: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 0: initial setup (no AI session).

    1. Create docs/generated/ directory
    2. Verify source documents exist
    3. Copy references/ from skill directory → docs/generated/references/
    4. Estimate sessions → ask y/n confirmation
    5. Create initial orchestrator-state.json
    """
    print("Phase 0: Initial setup", file=sys.stderr)

    # 1. Create docs/generated/
    generated_dir.mkdir(parents=True, exist_ok=True)

    # 2. Source documents
    source_dir = project_dir / _SOURCE_DIR_NAME
    source_files = _find_source_files(project_dir)
    if not source_files:
        print(
            f"Error: No source documents found in {source_dir} or project root.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_names = [f.name for f in source_files]
    source_line_count = sum(_count_lines(f) for f in source_files)
    print(f"  Source documents: {source_names} ({source_line_count} lines)", file=sys.stderr)

    # 3. Copy references/
    _copy_references(project_dir, generated_dir)

    # 4. Parse domains/features from source docs (lightweight heuristic)
    domains, features = _scan_source_structure(source_files, source_line_count)
    print(f"  Domains: {domains}", file=sys.stderr)
    print(f"  Features: {features}", file=sys.stderr)

    # 5. Estimate sessions
    estimated = estimate_sessions(domains, features, source_line_count)
    time_optimistic = estimated * 5
    time_pessimistic = estimated * 10
    print(
        f"\n  Estimated sessions: {estimated}"
        f"\n  Estimated time: ~{time_optimistic}–{time_pessimistic} min",
        file=sys.stderr,
    )

    # Ask y/n (in production; skipped via orch_config flag in tests)
    if not _confirm_proceed():
        print("Aborted by user.", file=sys.stderr)
        sys.exit(0)

    # 6. Build initial state
    now = datetime.now().isoformat()
    new_state = OrchestratorState(
        current={"phase": "phase_1", "step": "phase_1", "status": "idle"},
        project_summary={
            "type": "unknown",
            "source_docs": source_names,
            "domains": domains,
            "features": {d: features.get(d, []) for d in domains},
            "estimated_sessions": estimated,
            "source_line_count": source_line_count,
        },
        completed=[
            StepStatus(
                step="phase_0",
                status="completed",
                completed_at=now,
                result="success",
                note=f"도메인 {len(domains)}개, 소스 {source_line_count}줄",
            )
        ],
        pending=[],
        errors=[],
        updated_at=now,
        mode=orch_config.docs_mode,
        manual_override=list(orch_config.manual_override),
        project_dir=str(project_dir),
    )

    save_state(new_state, state_path)
    print("  Phase 0 completed — state file created.", file=sys.stderr)
    return new_state


# ── Phase 1 ─────────────────────────────────────────────────────────


def _run_phase_1(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    generated_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 1: structure analysis + raw-text extraction.

    If source_line_count <= 3000 → single session.
    Otherwise → 1 session for overall analysis + N domain sessions.
    """
    print("Phase 1: Structure analysis + extraction", file=sys.stderr)

    summary = state.project_summary
    source_line_count = int(summary.get("source_line_count", 0))
    source_docs = summary.get("source_docs", [])
    domains = summary.get("domains", [])
    features = summary.get("features", {})

    # Mark as running
    state = _update_state_running(state, "phase_1")
    save_state(state, state_path)

    if source_line_count <= 3000:
        # Single session
        prompt = build_session_prompt(
            "phase1_single",
            project_dir=str(project_dir),
            source_docs=source_docs,
            domains=domains,
            features=features,
        )
        expected_files = _parse_expected_files(prompt)

        watch_mode = _determine_watch_mode("phase_1", orch_config)
        jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
        if jsonl_path is None:
            return _update_state_error(state, "phase_1", "세션 열기 실패")

        completed = _wait_for_session_completion(
            jsonl_path, expected_files, config, orch_config, watch_mode,
        )
        if not completed:
            return _update_state_error(state, "phase_1", "세션 완료 대기 실패")

        state = _update_state_completed(state, "phase_1", "1세션 처리 완료")
    else:
        # Multi-session: 1a (analysis) + 1b-N (per domain)
        # Session 1a: overall analysis + shared.md
        prompt_1a = build_session_prompt(
            "phase1_single",
            project_dir=str(project_dir),
            source_docs=source_docs,
            domains=domains,
            features=features,
        )
        expected_1a = [generated_dir / "analysis-report.md"]
        watch_mode = _determine_watch_mode("phase_1", orch_config)

        jsonl_path = _open_orchestrator_session(prompt_1a, config, orch_config, base_path)
        if jsonl_path is None:
            return _update_state_error(state, "phase_1", "1a 세션 열기 실패")

        completed = _wait_for_session_completion(
            jsonl_path, expected_1a, config, orch_config, watch_mode,
        )
        if not completed:
            return _update_state_error(state, "phase_1", "1a 세션 완료 실패")

        # Session 1b-N: per domain extraction
        for domain in domains:
            step_name = f"phase_1:{domain}"
            state = _update_state_running(state, step_name)
            save_state(state, state_path)

            domain_features = features.get(domain, [])
            prompt_1b = build_session_prompt(
                "phase1_domain",
                project_dir=str(project_dir),
                source_docs=source_docs,
                domain=domain,
                features=domain_features,
            )
            domain_dir = generated_dir / "domain-extracts" / domain
            expected_1b = [domain_dir]  # Directory existence

            jsonl_path = _open_orchestrator_session(prompt_1b, config, orch_config, base_path)
            if jsonl_path is None:
                return _update_state_error(state, step_name, f"도메인 {domain} 세션 열기 실패")

            completed = _wait_for_session_completion(
                jsonl_path, expected_1b, config, orch_config, watch_mode,
            )
            if not completed:
                return _update_state_error(state, step_name, f"도메인 {domain} 완료 실패")

            state = _update_state_completed(state, step_name, f"도메인 {domain} 추출 완료")
            save_state(state, state_path)

        state = _update_state_completed(state, "phase_1", "다세션 처리 완료")

    # Refresh domains/features from actual domain-extracts/ output (§fix: Phase 0→1 drift)
    state = _refresh_domains_from_extracts(state, project_dir)
    save_state(state, state_path)

    return state


# ── Phase 1.5 ───────────────────────────────────────────────────────


def _run_phase_1_5(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 1.5: extraction quality gate (no AI session).

    Calls check_phase1_quality() and decides next action:
    - passed → advance to Phase 2
    - coverage fail → ESCALATE (user decides retry/continue/abort)
    - feature fail → supplementary extraction sessions
    - section coverage fail → advisory warning only (AI 출력 형식 불일치 허용)
    """
    print("Phase 1.5: Quality gate", file=sys.stderr)

    state = _update_state_running(state, "phase_1_5")
    save_state(state, state_path)

    gate_result = check_phase1_quality(project_dir, orch_config)

    print(f"  Coverage ratio: {gate_result.coverage_ratio:.2f}", file=sys.stderr)
    if gate_result.uncovered_sections:
        print(f"  Uncovered sections (advisory): {gate_result.uncovered_sections}", file=sys.stderr)
    if gate_result.missing_features:
        print(f"  Missing features: {gate_result.missing_features}", file=sys.stderr)

    if gate_result.passed:
        # SOURCE 태그 미커버는 advisory — passed 판정에 포함되지 않음
        if gate_result.uncovered_sections:
            print(
                f"  ⚠ SOURCE 태그 미커버 섹션 {len(gate_result.uncovered_sections)}개 (warning, 진행 허용)",
                file=sys.stderr,
            )
        print("  Quality gate PASSED.", file=sys.stderr)
        state = _update_state_completed(
            state,
            "phase_1_5",
            f"통과 — 커버리지 {gate_result.coverage_ratio:.2f}",
        )
        return state

    # Gate failed — determine failure type
    note_parts: list[str] = []

    has_coverage_fail = gate_result.coverage_ratio < orch_config.coverage_ratio_threshold
    has_feature_fail = len(gate_result.missing_features) > 0

    if has_coverage_fail:
        note_parts.append(f"커버리지 {gate_result.coverage_ratio:.2f} < {orch_config.coverage_ratio_threshold}")

    if gate_result.uncovered_sections:
        # Advisory only — quality_gate.py §검증2와 일치:
        # AI 출력 형식이 SOURCE 태그를 정확히 포함하지 않을 수 있으므로 경고만 표시
        note_parts.append(f"미커버 섹션 {len(gate_result.uncovered_sections)}개 (advisory)")

    if has_feature_fail:
        note_parts.append(f"누락 기능 {len(gate_result.missing_features)}개")

    note = "; ".join(note_parts)

    # Validation 1 failure (coverage) → ESCALATE + rollback Phase 1
    if has_coverage_fail:
        print(f"  Quality gate FAILED (ESCALATE): {note}", file=sys.stderr)
        print("  → Phase 1을 롤백하여 재실행 가능하게 합니다.", file=sys.stderr)
        _notify_escalate(f"Phase 1.5 품질 검증 실패: {note}")
        state = _rollback_phase_1(state)
        state = _update_state_error(state, "phase_1_5", f"ESCALATE: {note}")
        return state

    # Validation 3 only (missing features) → supplementary sessions possible
    if has_feature_fail:
        print(f"  Quality gate FAILED (missing features only): {note}", file=sys.stderr)
        print("  → Phase 1을 롤백하여 재실행 가능하게 합니다.", file=sys.stderr)
        state = _rollback_phase_1(state)
        state = _update_state_error(
            state,
            "phase_1_5",
            f"누락 기능 보충 필요: {', '.join(gate_result.missing_features)}",
        )
        return state

    # Shouldn't reach here, but handle gracefully
    state = _update_state_error(state, "phase_1_5", f"예상치 못한 실패: {note}")
    return state


# ── Feature bundling ───────────────────────────────────────────────


def _build_feature_bundles(
    features_with_lines: list[tuple[str, str, int]],
    config: DocsOrchestratorConfig,
) -> list[list[tuple[str, str]]]:
    """Group features into bundles based on domain-extract line counts.

    Each element in *features_with_lines* is ``(domain, feature, line_count)``.

    Rules (§5.2):
    - If ``line_count > config.feature_bundle_threshold_lines`` → standalone.
    - Otherwise, greedily pack consecutive small features up to
      ``config.max_bundle_size`` items per bundle.

    Returns a list of bundles.  Each bundle is a list of ``(domain, feature)``
    tuples.
    """
    threshold = config.feature_bundle_threshold_lines
    max_size = config.max_bundle_size

    bundles: list[list[tuple[str, str]]] = []
    current_bundle: list[tuple[str, str]] = []

    for domain, feature, lines in features_with_lines:
        if lines > threshold:
            # Flush any accumulated bundle
            if current_bundle:
                bundles.append(current_bundle)
                current_bundle = []
            bundles.append([(domain, feature)])
        else:
            current_bundle.append((domain, feature))
            if len(current_bundle) >= max_size:
                bundles.append(current_bundle)
                current_bundle = []

    # Flush remaining
    if current_bundle:
        bundles.append(current_bundle)

    return bundles


def _get_features_with_lines(
    project_dir: Path,
    state: OrchestratorState,
) -> list[tuple[str, str, int]]:
    """Scan domain-extract files and return ``(domain, feature, line_count)`` tuples."""
    generated_dir = project_dir / _GENERATED_DIR
    extracts_dir = generated_dir / "domain-extracts"
    features = state.project_summary.get("features", {})

    result: list[tuple[str, str, int]] = []
    for domain, feature_list in features.items():
        if not isinstance(feature_list, list):
            continue
        for feature in feature_list:
            # Convention: {domain}/{feature}.md
            extract_path = extracts_dir / domain / f"{feature}.md"
            lines = _count_lines(extract_path)
            result.append((domain, str(feature), lines))

    return result


def _resolve_bundles(
    features_with_lines: list[tuple[str, str, int]],
    config: DocsOrchestratorConfig,
    state: OrchestratorState,
) -> list[list[tuple[str, str]]]:
    """Build bundles, but if ``bundle_disabled`` is True, return all-singleton."""
    bundle_disabled = state.project_summary.get("bundle_disabled", False)
    if bundle_disabled:
        return [[(d, f)] for d, f, _ in features_with_lines]
    return _build_feature_bundles(features_with_lines, config)


# ── Phase 2 ─────────────────────────────────────────────────────────


def _run_phase_2(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 2: gap analysis — per-feature (or bundled) sessions.

    §5.2: For each feature (or bundle), open a gap-analysis session.
    After all sessions complete, generate ``_summary.md`` (§12.5).
    """
    print("Phase 2: Gap analysis", file=sys.stderr)

    generated_dir = project_dir / _GENERATED_DIR
    gap_reports_dir = generated_dir / "gap-reports"
    gap_reports_dir.mkdir(parents=True, exist_ok=True)

    features_with_lines = _get_features_with_lines(project_dir, state)

    # Filter out individually completed features before bundling
    completed_steps = {s.step for s in state.completed}
    features_with_lines = [
        (d, f, lines) for d, f, lines in features_with_lines
        if f"phase_2:{d}:{f}" not in completed_steps
        and not _is_feature_in_completed_bundle(d, f, "phase_2", completed_steps)
    ]

    if not features_with_lines:
        return state

    bundles = _resolve_bundles(features_with_lines, orch_config, state)

    for bundle in bundles:
        # Step name: use first feature as identifier
        first_domain, first_feature = bundle[0]
        if len(bundle) == 1:
            step_name = f"phase_2:{first_domain}:{first_feature}"
        else:
            names = "+".join(f"{d}:{f}" for d, f in bundle)
            step_name = f"phase_2:{names}"

        # Skip already-completed steps
        completed_steps = {s.step for s in state.completed}
        if step_name in completed_steps:
            continue

        state = _update_state_running(state, step_name)
        save_state(state, state_path)

        # Determine mode (§6.4 hybrid: check domain against manual_override)
        watch_mode = _determine_watch_mode(step_name, orch_config)

        # Build prompt
        mode_str = "manual" if not watch_mode else "auto"
        phase_template = f"phase2_{mode_str}"

        features_for_prompt = [
            {"domain": d, "feature": f} for d, f in bundle
        ]

        prompt = build_session_prompt(
            phase_template,
            project_dir=str(project_dir),
            features=features_for_prompt,
            domain=first_domain,
            feature=first_feature,
        )

        expected_files = _parse_expected_files(prompt)

        jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
        if jsonl_path is None:
            return _update_state_error(state, step_name, f"갭 분석 세션 열기 실패: {step_name}")

        completed = _wait_for_session_completion(
            jsonl_path, expected_files, config, orch_config, watch_mode,
        )
        if not completed:
            return _update_state_error(state, step_name, f"갭 분석 세션 완료 실패: {step_name}")

        state = _update_state_completed(state, step_name, f"갭 분석 완료: {step_name}")
        save_state(state, state_path)

    # Phase 2 summary (§12.5)
    summary_text = generate_gap_summary(gap_reports_dir)
    summary_path = gap_reports_dir / "_summary.md"
    summary_path.write_text(summary_text, encoding="utf-8")

    state = _update_state_completed(state, "phase_2_summary", "갭 분석 요약 생성 완료")
    return state


# ── Phase 3 ─────────────────────────────────────────────────────────

# Group ordering: A → B → C → D (§5.3)
_PHASE3_GROUP_ORDER = ["A", "B", "C", "D"]


def _run_phase_3(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 3: document generation — groups A → B → C → D.

    §5.3 group ordering:
    - A: design-docs (1 session)
    - B: product-specs (bundled like Phase 2)
    - C: ARCHITECTURE, DESIGN_GUIDE, SECURITY (1 session)
    - D: AGENTS.md — must be last (1 session)
    """
    print("Phase 3: Document generation", file=sys.stderr)

    generated_dir = project_dir / _GENERATED_DIR
    completed_steps = {s.step for s in state.completed}

    # ── Group A: design-docs ──
    step_a = "phase_3_A"
    if step_a not in completed_steps:
        state = _run_phase_3_group_a(
            state, config, orch_config, project_dir, base_path, state_path,
        )
        completed_steps = {s.step for s in state.completed}
        if step_a not in completed_steps:
            return state  # Error occurred

    # ── Group B: product-specs (bundled) ──
    state = _run_phase_3_group_b(
        state, config, orch_config, project_dir, base_path, state_path,
    )
    # Note: old B errors from previous runs should NOT block C.
    # _run_phase_3_group_b() already returns early via _update_state_error()
    # when a bundle fails in the current run, so an explicit check here
    # is unnecessary and causes infinite loops when stale errors remain
    # in state.errors with step names that don't match completed entries.
    completed_steps = {s.step for s in state.completed}

    # ── Group B index: generate product-specs/index.md ──
    _generate_specs_index(project_dir / "docs" / "product-specs")

    # ── Group C: ARCHITECTURE, DESIGN_GUIDE, SECURITY ──
    step_c = "phase_3_C"
    if step_c not in completed_steps:
        state = _run_phase_3_group_c(
            state, config, orch_config, project_dir, base_path, state_path,
        )
        completed_steps = {s.step for s in state.completed}
        if step_c not in completed_steps:
            return state

    # ── Group D: AGENTS.md (must be last) ──
    step_d = "phase_3_D"
    if step_d not in completed_steps:
        state = _run_phase_3_group_d(
            state, config, orch_config, project_dir, base_path, state_path,
        )

    return state


def _run_phase_3_group_a(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 3-A: design-docs (single session)."""
    step = "phase_3_A"
    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase3_design_docs",
        project_dir=str(project_dir),
    )

    generated_dir = project_dir / _GENERATED_DIR
    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 3-A 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 3-A 세션 완료 실패")

    state = _update_state_completed(state, step, "design-docs 생성 완료")
    save_state(state, state_path)
    return state


def _run_phase_3_group_b(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 3-B: product-specs (bundled like Phase 2)."""
    features_with_lines = _get_features_with_lines(project_dir, state)

    # Filter out individually completed features before bundling
    completed_steps = {s.step for s in state.completed}
    features_with_lines = [
        (d, f, lines) for d, f, lines in features_with_lines
        if f"phase_3_B:{d}:{f}" not in completed_steps
        and not _is_feature_in_completed_bundle(d, f, "phase_3_B", completed_steps)
    ]

    if not features_with_lines:
        return state

    bundles = _resolve_bundles(features_with_lines, orch_config, state)

    for bundle in bundles:
        first_domain, first_feature = bundle[0]
        if len(bundle) == 1:
            step_name = f"phase_3_B:{first_domain}:{first_feature}"
        else:
            names = "+".join(f"{d}:{f}" for d, f in bundle)
            step_name = f"phase_3_B:{names}"

        completed_steps = {s.step for s in state.completed}
        if step_name in completed_steps:
            continue

        state = _update_state_running(state, step_name)
        save_state(state, state_path)

        watch_mode = _determine_watch_mode(step_name, orch_config)

        features_for_prompt = [
            {"domain": d, "feature": f} for d, f in bundle
        ]

        prompt = build_session_prompt(
            "phase3_product_spec",
            project_dir=str(project_dir),
            features=features_for_prompt,
            domain=first_domain,
            feature=first_feature,
        )

        expected_files = _parse_expected_files(prompt)

        jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
        if jsonl_path is None:
            return _update_state_error(state, step_name, f"Phase 3-B 세션 열기 실패: {step_name}")

        completed = _wait_for_session_completion(
            jsonl_path, expected_files, config, orch_config, watch_mode,
        )
        if not completed:
            return _update_state_error(state, step_name, f"Phase 3-B 세션 완료 실패: {step_name}")

        state = _update_state_completed(state, step_name, f"product-spec 생성 완료: {step_name}")
        save_state(state, state_path)

    return state


def _run_phase_3_group_c(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 3-C: ARCHITECTURE, DESIGN_GUIDE, SECURITY (single session)."""
    step = "phase_3_C"
    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase3_architecture",
        project_dir=str(project_dir),
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 3-C 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 3-C 세션 완료 실패")

    state = _update_state_completed(state, step, "ARCHITECTURE 등 생성 완료")
    save_state(state, state_path)
    return state


def _run_phase_3_group_d(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 3-D: AGENTS.md — must be generated last (single session)."""
    step = "phase_3_D"
    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase3_agents",
        project_dir=str(project_dir),
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 3-D 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 3-D 세션 완료 실패")

    state = _update_state_completed(state, step, "AGENTS.md 생성 완료")
    save_state(state, state_path)
    return state


def check_bundle_quality_degradation(
    state: OrchestratorState,
    project_dir: Path,
) -> OrchestratorState:
    """Check if bundled sessions have quality degradation (§5.3).

    If 3+ last-document quality failures found in Phase 4-2 rescore,
    set ``bundle_disabled: true`` in project_summary.
    """
    rescore_path = project_dir / _GENERATED_DIR / "phase4-rescore.md"
    if not rescore_path.exists():
        return state

    content = rescore_path.read_text(encoding="utf-8")
    # Count quality degradation markers for bundle-last documents
    degradation_count = len(re.findall(
        r"(?:품질\s*저하|quality\s*degradation|악화)",
        content,
        re.IGNORECASE,
    ))

    if degradation_count >= 3:
        new_summary = dict(state.project_summary)
        new_summary["bundle_disabled"] = True
        return OrchestratorState(
            current=state.current,
            project_summary=new_summary,
            completed=state.completed,
            pending=state.pending,
            errors=state.errors,
            updated_at=datetime.now().isoformat(),
            mode=state.mode,
            manual_override=state.manual_override,
            project_dir=state.project_dir,
        )

    return state


# ── Phase 4 ─────────────────────────────────────────────────────────


def _run_phase_4(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
    step: str,
) -> OrchestratorState:
    """Phase 4: quality review — 3 sub-sessions (§5.4).

    - 4-1: consistency check (section_keywords injected)
    - 4-2: checklist rescore (per-feature, bundled like Phase 2)
    - 4-3: expression quality scan + QUALITY_SCORE.md
    """
    if step == "phase_4_1":
        return _run_phase_4_1(state, config, orch_config, project_dir, base_path, state_path)
    elif step == "phase_4_2":
        return _run_phase_4_2(state, config, orch_config, project_dir, base_path, state_path)
    elif step == "phase_4_3":
        return _run_phase_4_3(state, config, orch_config, project_dir, base_path, state_path)
    return state


def _run_phase_4_1(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 4-1: consistency check with section_keywords injection (§5.4)."""
    step = "phase_4_1"
    print("Phase 4-1: Consistency check", file=sys.stderr)

    state = _update_state_running(state, step)
    save_state(state, state_path)

    # Get section keywords from output-formats.md
    refs_dir = project_dir / _GENERATED_DIR / _REFERENCES_DIR
    output_formats_path = refs_dir / "output-formats.md"
    project_type = state.project_summary.get("type", "unknown")
    section_keywords = get_section_keywords(output_formats_path, project_type)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase4_consistency",
        project_dir=str(project_dir),
        section_keywords=section_keywords,
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 4-1 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 4-1 세션 완료 실패")

    state = _update_state_completed(state, step, "정합성 검사 완료")
    save_state(state, state_path)
    return state


def _run_phase_4_2(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 4-2: checklist rescore — per-feature like Phase 2 (§5.4).

    After rescore, checks bundle quality degradation: if 3+ last-document
    quality failures → sets ``bundle_disabled: true``.
    """
    step = "phase_4_2"
    print("Phase 4-2: Checklist rescore", file=sys.stderr)

    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)

    features = state.project_summary.get("features", {})
    feature_list_for_prompt = []
    for domain, flist in features.items():
        if isinstance(flist, list):
            for f in flist:
                feature_list_for_prompt.append({"domain": domain, "feature": f})

    prompt = build_session_prompt(
        "phase4_rescore",
        project_dir=str(project_dir),
        features=feature_list_for_prompt,
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 4-2 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 4-2 세션 완료 실패")

    state = _update_state_completed(state, step, "체크리스트 재평가 완료")
    save_state(state, state_path)

    # Check bundle quality degradation (§5.3)
    state = check_bundle_quality_degradation(state, project_dir)
    save_state(state, state_path)

    return state


def _run_phase_4_3(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 4-3: expression quality scan + QUALITY_SCORE.md (§5.4).

    Runs grep-based forbidden expression search before the AI session,
    injecting results into the prompt.
    """
    step = "phase_4_3"
    print("Phase 4-3: Expression quality + QUALITY_SCORE", file=sys.stderr)

    state = _update_state_running(state, step)
    save_state(state, state_path)

    # Grep-based forbidden expression search
    forbidden_hits = _grep_forbidden_expressions(project_dir)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase4_quality",
        project_dir=str(project_dir),
        forbidden_hits=forbidden_hits,
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 4-3 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 4-3 세션 완료 실패")

    state = _update_state_completed(state, step, "표현 품질 검사 + QUALITY_SCORE 생성 완료")
    save_state(state, state_path)
    return state


def _grep_forbidden_expressions(project_dir: Path) -> list[dict[str, str]]:
    """Grep docs/ for forbidden expressions (§5.4 세션 4-3).

    Returns a list of ``{"file": ..., "line": ..., "expression": ...}`` dicts.
    """
    docs_dir = project_dir / "docs"
    if not docs_dir.is_dir():
        return []

    hits: list[dict[str, str]] = []
    for md_file in docs_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for expr in _FORBIDDEN_EXPRESSIONS:
                if expr in line:
                    hits.append({
                        "file": str(md_file.relative_to(project_dir)),
                        "line": str(i),
                        "expression": expr,
                    })
    return hits


# ── Phase 5 ─────────────────────────────────────────────────────────


def _run_phase_5_outline(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
) -> OrchestratorState:
    """Phase 5-outline: exec-plan design — 1 session (§5.5.1)."""
    step = "phase_5_outline"
    print("Phase 5-outline: exec-plan design", file=sys.stderr)

    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)
    prompt = build_session_prompt(
        "phase5_outline",
        project_dir=str(project_dir),
    )

    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, "Phase 5-outline 세션 열기 실패")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, "Phase 5-outline 세션 완료 실패")

    state = _update_state_completed(state, step, "exec-plan outline 설계 완료")
    save_state(state, state_path)
    return state


def _run_phase_5_detail(
    state: OrchestratorState,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    project_dir: Path,
    base_path: Path,
    state_path: Path,
    step: str,
) -> OrchestratorState:
    """Phase 5-detail: exec-plan detail — 1 session per plan (§5.5.2).

    *step* has the form ``phase_5_detail:{plan_name}``.
    """
    plan_name = step.split(":", 1)[1]
    print(f"Phase 5-detail: {plan_name}", file=sys.stderr)

    state = _update_state_running(state, step)
    save_state(state, state_path)

    watch_mode = _determine_watch_mode(step, orch_config)

    # Parse the plan number and bare name from the plan_name (e.g. "01-project-setup")
    plan_number = plan_name.split("-", 1)[0]   # "01"
    plan_bare_name = plan_name.split("-", 1)[1] if "-" in plan_name else plan_name  # "project-setup"
    prompt = build_session_prompt(
        "phase5_detail",
        project_dir=str(project_dir),
        plan_number=plan_number,
        plan_name=plan_bare_name,
    )

    planning_dir = project_dir / _PLANNING_DIR
    planning_dir.mkdir(parents=True, exist_ok=True)
    expected = _parse_expected_files(prompt)

    jsonl_path = _open_orchestrator_session(prompt, config, orch_config, base_path)
    if jsonl_path is None:
        return _update_state_error(state, step, f"Phase 5-detail 세션 열기 실패: {plan_name}")

    completed = _wait_for_session_completion(
        jsonl_path, expected, config, orch_config, watch_mode,
    )
    if not completed:
        return _update_state_error(state, step, f"Phase 5-detail 세션 완료 실패: {plan_name}")

    state = _update_state_completed(state, step, f"exec-plan {plan_name} 상세 작성 완료")
    save_state(state, state_path)
    return state


def _parse_outline_plans(outline_path: Path) -> list[dict]:
    """Parse exec-plan file list from the outline markdown.

    Looks for table rows like ``| 1 | 01-project-setup.md | ... |``
    or header patterns like ``## 01-project-setup.md 상세``.

    Returns ``[{"number": "01", "name": "01-project-setup", "filename": "01-project-setup.md"}, ...]``
    """
    if not outline_path.exists():
        return []

    content = outline_path.read_text(encoding="utf-8")
    plans: list[dict] = []
    seen_names: set[str] = set()

    # Pattern 1: table rows — ``| N | NN-name.md | ... |``
    table_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*(\d{2}-[a-zA-Z0-9_-]+)\.md\s*\|",
        re.MULTILINE,
    )
    for match in table_pattern.finditer(content):
        name = match.group(1)
        if name not in seen_names:
            seen_names.add(name)
            number = name.split("-", 1)[0]
            plans.append({
                "number": number,
                "name": name,
                "filename": f"{name}.md",
            })

    # Pattern 2: section headers — ``## NN-name.md 상세`` or ``## NN-name.md``
    header_pattern = re.compile(
        r"^##\s+(\d{2}-[a-zA-Z0-9_-]+)\.md",
        re.MULTILINE,
    )
    for match in header_pattern.finditer(content):
        name = match.group(1)
        if name not in seen_names:
            seen_names.add(name)
            number = name.split("-", 1)[0]
            plans.append({
                "number": number,
                "name": name,
                "filename": f"{name}.md",
            })

    # Sort by number
    plans.sort(key=lambda p: p["number"])
    return plans


# ── Final completion ───────────────────────────────────────────────


def _run_final_completion(
    state: OrchestratorState,
    project_dir: Path,
) -> None:
    """Final completion check and summary output (§9).

    1. Verify all steps completed in orchestrator-state.json
    2. Verify exec-plan files exist in docs/exec-plans/planning/
    3. Print terminal summary (total sessions, elapsed time, errors, marker_missing warnings)
    4. macOS notification
    """
    print("\n" + "=" * 60, file=sys.stderr)
    print("Docs Orchestrator — Final Completion", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # 1. Count completed steps, errors, marker_missing warnings
    total_sessions = len(state.completed)
    total_errors = len(state.errors)
    marker_missing_count = sum(
        1 for s in state.completed
        if getattr(s, "marker_missing", False)
    )

    # 2. Calculate elapsed time
    timestamps = []
    for s in state.completed:
        if s.completed_at:
            try:
                timestamps.append(datetime.fromisoformat(s.completed_at))
            except (ValueError, TypeError):
                pass
    if len(timestamps) >= 2:
        elapsed = timestamps[-1] - timestamps[0]
        elapsed_str = str(elapsed)
    else:
        elapsed_str = "N/A"

    # 3. Check planning files
    planning_dir = project_dir / _PLANNING_DIR
    planning_files = sorted(planning_dir.glob("*.md")) if planning_dir.is_dir() else []

    # 4. Print summary
    print(f"\n  Total sessions completed: {total_sessions}", file=sys.stderr)
    print(f"  Elapsed time: {elapsed_str}", file=sys.stderr)
    print(f"  Errors: {total_errors}", file=sys.stderr)
    print(f"  Marker-missing warnings: {marker_missing_count}", file=sys.stderr)
    print(f"  Exec-plan files: {len(planning_files)}", file=sys.stderr)

    if planning_files:
        for pf in planning_files:
            print(f"    - {pf.name}", file=sys.stderr)
    else:
        print("  WARNING: No exec-plan files found in docs/exec-plans/planning/", file=sys.stderr)

    print("=" * 60, file=sys.stderr)

    # 5. macOS notification
    _notify_completion(total_sessions, total_errors, len(planning_files))


def _notify_completion(total_sessions: int, total_errors: int, plan_count: int) -> None:
    """Send macOS notification for completion."""
    try:
        from cowork_pilot.responder import notify
        notify(
            "Docs Orchestrator 완료",
            f"세션 {total_sessions}개 완료, 에러 {total_errors}개, exec-plan {plan_count}개 생성",
        )
    except Exception:
        print("  (macOS notification failed)", file=sys.stderr)


# ── Session management helpers ──────────────────────────────────────


def _open_orchestrator_session(
    prompt: str,
    config: Config,
    orch_config: DocsOrchestratorConfig,
    base_path: Path,
) -> Path | None:
    """Open a new Cowork session and detect the new JSONL file.

    Reuses session_opener.open_new_session() + session_manager.detect_new_jsonl().
    """
    from cowork_pilot.session_manager import detect_new_jsonl, _get_jsonl_snapshot
    from cowork_pilot.session_opener import open_new_session

    snapshot = _get_jsonl_snapshot(base_path)

    success = open_new_session(
        initial_prompt=prompt,
        session_load_delay=orch_config.session_open_delay,
    )
    if not success:
        return None

    return detect_new_jsonl(
        base_path,
        snapshot,
        timeout=orch_config.session_detect_timeout,
        poll_interval=orch_config.session_detect_poll_interval,
    )


def _wait_for_session_completion(
    jsonl_path: Path,
    expected_files: list[Path],
    config: Config,
    orch_config: DocsOrchestratorConfig,
    watch_mode: bool,
) -> bool:
    """Wait for session completion using idle detection + output file verification.

    §7.3 completion logic:
    - idle detection via is_idle_trigger()
    - output file existence + done marker check
    - marker-missing fallback (§2.7)
    - auto mode: Phase 1 Watch cooperative loop
    - manual mode: output file polling only
    """
    from cowork_pilot.completion_detector import is_idle_trigger
    from cowork_pilot.watcher import JSONLTail, WatcherStateMachine, parse_jsonl_line

    if watch_mode:
        return _wait_with_cooperative_loop(
            jsonl_path, expected_files, config, orch_config,
        )
    else:
        return _wait_with_polling(
            jsonl_path, expected_files, config, orch_config,
        )


def _wait_with_cooperative_loop(
    jsonl_path: Path,
    expected_files: list[Path],
    config: Config,
    orch_config: DocsOrchestratorConfig,
) -> bool:
    """Auto mode: cooperative loop with Phase 1 auto-response + idle detection.

    Mirrors run_harness() pattern from main.py.
    """
    from cowork_pilot.completion_detector import is_idle_trigger
    from cowork_pilot.main import process_one_event
    from cowork_pilot.models import Event, WatcherState
    from cowork_pilot.watcher import JSONLTail, WatcherStateMachine, parse_jsonl_line

    tail = JSONLTail(jsonl_path)
    sm = WatcherStateMachine(debounce_seconds=config.debounce_seconds)

    last_record: dict | None = None
    last_record_time = time.monotonic()

    timeout = orch_config.idle_timeout_seconds

    while True:
        now = time.monotonic()

        # Read new JSONL lines
        new_lines = tail.read_new_lines()
        if new_lines:
            last_record_time = time.monotonic()

        for line in new_lines:
            try:
                raw_record = json.loads(line.strip())
                if isinstance(raw_record, dict):
                    last_record = raw_record
            except (ValueError, json.JSONDecodeError):
                pass

            parsed = parse_jsonl_line(line)
            if parsed is None:
                continue

            if parsed["type"] == "assistant":
                for tu in parsed["tool_uses"]:
                    sm.on_tool_use(tu)
            elif parsed["type"] == "user":
                for tr_id in parsed["tool_results"]:
                    sm.on_tool_result(tr_id)

        sm.tick()

        # Auto-respond to events
        event = sm.get_pending_event()
        if event is not None:
            from cowork_pilot.dispatcher import extract_context
            context = extract_context(jsonl_path, max_lines=10)
            event = Event(
                event_type=event.event_type,
                tool_use_id=event.tool_use_id,
                tool_name=event.tool_name,
                questions=event.questions,
                tool_input=event.tool_input,
                context_lines=context,
            )
            success = process_one_event(event, jsonl_path, config, config._logger if hasattr(config, '_logger') else _get_logger(config))
            if success:
                sm.on_tool_result(event.tool_use_id)
            else:
                sm.state = WatcherState.IDLE
                sm.pending_tool_use = None

        # Check idle + completion
        if is_idle_trigger(last_record, last_record_time, now, idle_timeout_seconds=timeout):
            # Check output files + done marker
            if _check_output_files(expected_files):
                return True

            # Marker-missing fallback (§2.7): grace period
            print("  Idle detected but marker missing — waiting grace period...", file=sys.stderr)
            time.sleep(orch_config.idle_grace_seconds)

            if _check_output_files(expected_files):
                return True

            # Fallback: check line count
            if _check_output_files_fallback(expected_files):
                print("  Marker missing but content sufficient — proceeding.", file=sys.stderr)
                return True

            print("  Session appears stuck — completion failed.", file=sys.stderr)
            return False

        time.sleep(config.poll_interval_seconds)


def _wait_with_polling(
    jsonl_path: Path,
    expected_files: list[Path],
    config: Config,
    orch_config: DocsOrchestratorConfig,
) -> bool:
    """Manual mode: poll output files only (no auto-response)."""
    from cowork_pilot.completion_detector import is_idle_trigger
    from cowork_pilot.watcher import JSONLTail

    tail = JSONLTail(jsonl_path)
    last_record: dict | None = None
    last_record_time = time.monotonic()

    timeout = orch_config.idle_timeout_seconds

    while True:
        now = time.monotonic()

        new_lines = tail.read_new_lines()
        if new_lines:
            last_record_time = time.monotonic()
            for line in new_lines:
                try:
                    raw = json.loads(line.strip())
                    if isinstance(raw, dict):
                        last_record = raw
                except (ValueError, json.JSONDecodeError):
                    pass

        # Check output files periodically
        if _check_output_files(expected_files):
            return True

        # Idle detection
        if is_idle_trigger(last_record, last_record_time, now, idle_timeout_seconds=timeout):
            # Grace period for marker
            time.sleep(orch_config.idle_grace_seconds)

            if _check_output_files(expected_files):
                return True

            if _check_output_files_fallback(expected_files):
                return True

            return False

        time.sleep(orch_config.completion_poll_interval)


# ── Output file verification ────────────────────────────────────────


def _resolve_separator_fallback(expected: Path) -> Path:
    """If expected file (with --) doesn't exist, try single-hyphen variant.

    AI sessions sometimes normalize '--' to '-' in filenames.
    When the single-hyphen variant exists, rename it to the canonical '--' form
    and return the canonical path. Otherwise return the original path unchanged.
    """
    if expected.exists() or expected.is_dir():
        return expected
    stem = expected.stem
    if "--" not in stem:
        return expected
    # Try single-hyphen variant: ai-agent--nl-parser → ai-agent-nl-parser
    alt_stem = stem.replace("--", "-")
    alt_path = expected.with_name(alt_stem + expected.suffix)
    if alt_path.exists():
        # Rename to canonical form so future checks also pass
        alt_path.rename(expected)
        print(
            f"  [fallback] Renamed '{alt_path.name}' → '{expected.name}'",
            file=sys.stderr,
        )
    return expected


def _check_output_files(expected_files: list[Path]) -> bool:
    """Check that all expected output files exist and have done markers.

    Applies separator fallback: if 'domain--feature.md' is missing but
    'domain-feature.md' exists, renames it to the canonical '--' form first.
    """
    if not expected_files:
        return False
    for f in expected_files:
        f = _resolve_separator_fallback(f)
        if f.is_dir():
            # For directories, check at least one .md file with marker
            md_files = list(f.glob("*.md"))
            if not md_files:
                return False
            if not any(_file_has_done_marker(mf) for mf in md_files):
                return False
        else:
            if not _file_has_done_marker(f):
                return False
    return True


def _check_output_files_fallback(expected_files: list[Path]) -> bool:
    """Marker-missing fallback: check files exist with minimum line count (§2.7).

    Also applies separator fallback for '--' vs '-' filename variants.
    """
    if not expected_files:
        return False
    for f in expected_files:
        f = _resolve_separator_fallback(f)
        if f.is_dir():
            md_files = list(f.glob("*.md"))
            if not md_files:
                return False
            for mf in md_files:
                lines = _count_lines(mf)
                min_lines = _get_min_lines_for_file(mf)
                if lines < min_lines:
                    return False
        else:
            if not f.exists():
                return False
            lines = _count_lines(f)
            min_lines = _get_min_lines_for_file(f)
            if lines < min_lines:
                return False
    return True


def _get_min_lines_for_file(path: Path) -> int:
    """Determine minimum line count for marker-missing fallback based on file path."""
    name = path.name.lower()
    if "analysis-report" in name:
        return _MIN_LINES_BY_PHASE.get("phase_1", 30)
    if "gap-report" in name or "gap_report" in name:
        return _MIN_LINES_BY_PHASE.get("phase_2", 20)
    if "product-spec" in name or "product_spec" in name:
        return _MIN_LINES_BY_PHASE.get("phase_3_product_spec", 50)
    if "design-doc" in name or "design_doc" in name:
        return _MIN_LINES_BY_PHASE.get("phase_3_design_doc", 30)
    if "phase4" in name:
        return _MIN_LINES_BY_PHASE.get("phase_4", 20)
    if "exec-plan" in name or "exec_plan" in name:
        return _MIN_LINES_BY_PHASE.get("phase_5", 30)
    # Default for domain-extract feature files
    return _MIN_LINES_BY_PHASE.get("phase_1_domain", 10)


# ── State transition helpers ────────────────────────────────────────


def _rollback_phase_1(state: OrchestratorState) -> OrchestratorState:
    """Remove Phase 1 from completed so it can re-run.

    When Phase 1.5 quality gate fails, Phase 1 needs to re-run to
    produce better output.  This removes phase_1 (and any phase_1:*
    domain sub-steps) from the completed list.
    """
    new_completed = [
        s for s in state.completed
        if not (s.step == "phase_1" or s.step.startswith("phase_1:"))
    ]
    return OrchestratorState(
        current=state.current,
        project_summary=state.project_summary,
        completed=new_completed,
        pending=state.pending,
        errors=state.errors,
        updated_at=datetime.now().isoformat(),
        mode=state.mode,
        manual_override=state.manual_override,
        project_dir=state.project_dir,
    )


def _update_state_running(state: OrchestratorState, step: str) -> OrchestratorState:
    """Transition current step to 'running' status."""
    phase = step.split(":")[0]
    return OrchestratorState(
        current={"phase": phase, "step": step, "status": "running"},
        project_summary=state.project_summary,
        completed=state.completed,
        pending=state.pending,
        errors=state.errors,
        updated_at=datetime.now().isoformat(),
        mode=state.mode,
        manual_override=state.manual_override,
        project_dir=state.project_dir,
    )


def _update_state_completed(
    state: OrchestratorState,
    step: str,
    note: str = "",
) -> OrchestratorState:
    """Mark a step as completed and advance the state."""
    now = datetime.now().isoformat()
    new_completed = list(state.completed) + [
        StepStatus(
            step=step,
            status="completed",
            completed_at=now,
            result="success",
            note=note,
        )
    ]
    return OrchestratorState(
        current={**state.current, "status": "idle"},
        project_summary=state.project_summary,
        completed=new_completed,
        pending=state.pending,
        errors=state.errors,
        updated_at=now,
        mode=state.mode,
        manual_override=state.manual_override,
        project_dir=state.project_dir,
    )


def _update_state_error(
    state: OrchestratorState,
    step: str,
    error: str,
) -> OrchestratorState:
    """Record an error for the current step."""
    now = datetime.now().isoformat()
    new_errors = list(state.errors) + [{
        "at": now,
        "step": step,
        "error": error,
        "action": "재시도 필요",
    }]
    return OrchestratorState(
        current={**state.current, "status": "idle"},
        project_summary=state.project_summary,
        completed=state.completed,
        pending=state.pending,
        errors=new_errors,
        updated_at=now,
        mode=state.mode,
        manual_override=state.manual_override,
        project_dir=state.project_dir,
    )


_PHASE_1_5_MAX_RETRIES = 3


def _determine_next_step(state: OrchestratorState) -> str | None:
    """Determine the next step based on current state.

    Phase 0 → 1 → 1.5 → 2 (per feature) → 2_summary → 3_A → 3_B (per feature)
    → 3_C → 3_D → (Phase 4+ handled in later chunks).
    Returns None when all steps are done.
    """
    completed_steps = {s.step for s in state.completed}

    # Phase 0
    if "phase_0" not in completed_steps:
        return "phase_0"

    # Phase 1
    if "phase_1" not in completed_steps:
        return "phase_1"

    # Phase 1.5 — retry with rollback
    if "phase_1_5" not in completed_steps:
        # Count consecutive phase_1_5 errors to prevent infinite loops
        phase_1_5_error_count = sum(
            1 for e in state.errors if e.get("step") == "phase_1_5"
        )
        if phase_1_5_error_count >= _PHASE_1_5_MAX_RETRIES:
            # Max retries exhausted — stop the loop
            return None
        return "phase_1_5"

    # Phase 2: per-feature gap analysis
    features = state.project_summary.get("features", {})
    all_phase2_done = True
    for domain, feature_list in features.items():
        if not isinstance(feature_list, list):
            continue
        for feature in feature_list:
            step = f"phase_2:{domain}:{feature}"
            if step not in completed_steps:
                # Check bundled step names too
                if not _is_feature_in_completed_bundle(domain, str(feature), "phase_2", completed_steps):
                    all_phase2_done = False
                    break
        if not all_phase2_done:
            break

    if not all_phase2_done:
        return "phase_2"

    # Phase 2 summary
    if "phase_2_summary" not in completed_steps:
        return "phase_2"

    # Phase 3: A → B → C → D
    if "phase_3_A" not in completed_steps:
        return "phase_3_A"

    # Phase 3-B: per-feature product-specs
    all_phase3b_done = True
    for domain, feature_list in features.items():
        if not isinstance(feature_list, list):
            continue
        for feature in feature_list:
            step = f"phase_3_B:{domain}:{feature}"
            if step not in completed_steps:
                if not _is_feature_in_completed_bundle(domain, str(feature), "phase_3_B", completed_steps):
                    all_phase3b_done = False
                    break
        if not all_phase3b_done:
            break

    if not all_phase3b_done:
        return "phase_3_B"

    if "phase_3_C" not in completed_steps:
        return "phase_3_C"

    if "phase_3_D" not in completed_steps:
        return "phase_3_D"

    # Phase 4: quality review — 4-1 → 4-2 → 4-3
    if "phase_4_1" not in completed_steps:
        return "phase_4_1"

    if "phase_4_2" not in completed_steps:
        return "phase_4_2"

    if "phase_4_3" not in completed_steps:
        return "phase_4_3"

    # Phase 5: exec-plan generation
    if "phase_5_outline" not in completed_steps:
        return "phase_5_outline"

    # Phase 5 detail: one session per exec-plan in the outline
    outline_path = Path(state.project_dir) / _GENERATED_DIR / "exec-plan-outline.md"
    if outline_path.exists():
        plans = _parse_outline_plans(outline_path)
        for plan in plans:
            plan_name = plan["name"]
            step = f"phase_5_detail:{plan_name}"
            if step not in completed_steps:
                return step

    # All phases done
    return "done"


def _is_feature_in_completed_bundle(
    domain: str,
    feature: str,
    phase_prefix: str,
    completed_steps: set[str],
) -> bool:
    """Check if a feature was completed as part of a bundle step.

    Bundle step names look like ``phase_2:auth:login+payment:refund``.
    """
    target = f"{domain}:{feature}"
    for step in completed_steps:
        if step.startswith(f"{phase_prefix}:") and "+" in step:
            # e.g. "phase_2:auth:login+payment:refund"
            bundle_part = step[len(phase_prefix) + 1:]  # "auth:login+payment:refund"
            parts = bundle_part.split("+")
            if target in parts:
                return True
    return False


def _determine_watch_mode(step: str, orch_config: DocsOrchestratorConfig) -> bool:
    """Determine whether to use watch mode (auto-response) for a step.

    Returns True for auto mode, False for manual mode.
    For hybrid mode: returns False if the step's domain is in manual_override.
    """
    mode = orch_config.docs_mode

    if mode == "auto":
        return True
    if mode == "manual":
        return False

    # hybrid mode: check manual_override list
    if mode == "hybrid":
        # Extract domain from step name (e.g. "phase_2:payment:refund" → "payment")
        parts = step.split(":")
        if len(parts) >= 2:
            domain = parts[1]
            if domain in orch_config.manual_override:
                return False
        return True

    # Default to auto
    return True


# ── Utility helpers ─────────────────────────────────────────────────


def _find_source_files(project_dir: Path) -> list[Path]:
    """Find source planning documents in the project."""
    source_dir = project_dir / _SOURCE_DIR_NAME
    files: list[Path] = []
    if source_dir.is_dir():
        files = sorted(source_dir.glob("*.md"))
    # If no sources/ directory, check project root for planning docs
    if not files:
        for pattern in ["기획서*.md", "planning*.md", "spec*.md", "요구사항*.md"]:
            files.extend(sorted(project_dir.glob(pattern)))
    return files


def _count_lines(path: Path) -> int:
    """Count lines in a file. Returns 0 if file doesn't exist or is unreadable."""
    if not path.exists():
        return 0
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (UnicodeDecodeError, OSError):
        # File may contain partially-written multibyte characters or be
        # locked by another process.  Fall back to byte-level counting.
        try:
            data = path.read_bytes()
            return data.count(b"\n") or (1 if data else 0)
        except OSError:
            return 0


def _copy_references(project_dir: Path, generated_dir: Path) -> None:
    """Copy references/ from skill directory to docs/generated/references/."""
    dest = generated_dir / _REFERENCES_DIR
    dest.mkdir(parents=True, exist_ok=True)

    # Look for references in skill directory
    skill_refs = Path(__file__).parent.parent.parent / "skills" / "docs-orchestrator" / "references"
    if not skill_refs.is_dir():
        # Try alternate locations
        skill_refs = project_dir / "skills" / "docs-orchestrator" / "references"

    if skill_refs.is_dir():
        for ref_file in skill_refs.glob("*.md"):
            shutil.copy2(str(ref_file), str(dest / ref_file.name))
        print(f"  Copied references/ from {skill_refs}", file=sys.stderr)
    else:
        print("  Warning: references/ not found in skill directory.", file=sys.stderr)


def _scan_source_structure(
    source_files: list[Path],
    source_line_count: int,
) -> tuple[list[str], dict[str, list[str]]]:
    """Lightweight heuristic to extract domains/features from source docs.

    Scans for ## headers to build a rough domain/feature map.
    This is a preliminary estimate — Phase 1 AI session does the real analysis.
    """
    domains: list[str] = []
    features: dict[str, list[str]] = {}

    for sf in source_files:
        text = sf.read_text(encoding="utf-8")
        current_domain = sf.stem  # Use filename as domain name
        if current_domain not in domains:
            domains.append(current_domain)
            features[current_domain] = []

        import re
        headers = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
        for h in headers:
            feature_name = h.strip()
            if feature_name and feature_name not in features[current_domain]:
                features[current_domain].append(feature_name)

    # Ensure at least one domain
    if not domains:
        domains = ["default"]
        features["default"] = ["main"]

    return domains, features


def _refresh_domains_from_extracts(
    state: OrchestratorState,
    project_dir: Path,
) -> OrchestratorState:
    """Scan domain-extracts/ directory to refresh project_summary domains/features.

    Phase 1 AI session may reorganise domains differently from Phase 0's
    heuristic parse.  This function reads the *actual* directory structure
    produced by Phase 1 and updates project_summary so that Phase 2+ use
    the correct domain/feature names.

    Called at the end of _run_phase_1() after all sessions complete.
    """
    generated_dir = project_dir / _GENERATED_DIR
    extracts_dir = generated_dir / "domain-extracts"

    if not extracts_dir.exists():
        print("  Warning: domain-extracts/ not found — skipping summary refresh.", file=sys.stderr)
        return state

    new_domains: list[str] = []
    new_features: dict[str, list[str]] = {}

    for entry in sorted(extracts_dir.iterdir()):
        if not entry.is_dir():
            continue  # Skip shared.md and other files
        domain = entry.name
        new_domains.append(domain)
        features_in_domain: list[str] = []
        for feat_file in sorted(entry.iterdir()):
            if feat_file.is_file() and feat_file.suffix == ".md":
                features_in_domain.append(feat_file.stem)
        new_features[domain] = features_in_domain

    if not new_domains:
        print("  Warning: No domain directories found in domain-extracts/ — keeping original summary.", file=sys.stderr)
        return state

    old_domains = state.project_summary.get("domains", [])
    old_features = state.project_summary.get("features", {})

    if new_domains != old_domains or new_features != old_features:
        print(f"  Refreshing project_summary: {old_domains} → {new_domains}", file=sys.stderr)
        print(f"  Features: {new_features}", file=sys.stderr)

        updated_summary = dict(state.project_summary)
        updated_summary["domains"] = new_domains
        updated_summary["features"] = new_features

        state = OrchestratorState(
            current=state.current,
            project_summary=updated_summary,
            completed=state.completed,
            pending=state.pending,
            errors=state.errors,
            updated_at=datetime.now().isoformat(),
            mode=state.mode,
            manual_override=state.manual_override,
            project_dir=state.project_dir,
        )
    else:
        print("  project_summary domains/features unchanged.", file=sys.stderr)

    return state


def _confirm_proceed() -> bool:
    """Ask user y/n confirmation on terminal. Returns True on 'y'."""
    try:
        answer = input("\nProceed? (y/n): ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _notify_escalate(message: str) -> None:
    """Send macOS notification for ESCALATE."""
    try:
        from cowork_pilot.responder import notify
        notify("⚠️ Docs Orchestrator — ESCALATE", message)
    except Exception:
        print(f"  ESCALATE: {message}", file=sys.stderr)


def _get_logger(config: Config):
    """Get or create a StructuredLogger."""
    from cowork_pilot.logger import StructuredLogger
    return StructuredLogger(config.log_path, config.log_level)
