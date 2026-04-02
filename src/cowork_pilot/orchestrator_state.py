"""Orchestrator state management for docs-orchestrator.

Handles OrchestratorState dataclass, JSON serialization/deserialization,
session estimation, adaptive timeout calculation, gap summary generation,
and running-step recovery.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from cowork_pilot.config import DocsOrchestratorConfig


# ── Dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class StepStatus:
    """Status of a single orchestrator step."""
    step: str
    status: str = "pending"  # "pending" | "running" | "completed" | "error"
    completed_at: str = ""
    result: str = ""
    note: str = ""
    actual_idle_seconds: float = 0.0
    marker_missing: bool = False


@dataclass(frozen=True)
class OrchestratorState:
    """Top-level orchestrator state (frozen — create new instances on update)."""
    current: dict[str, str] = field(default_factory=lambda: {
        "phase": "phase_0",
        "step": "phase_0",
        "status": "idle",
    })
    project_summary: dict[str, object] = field(default_factory=dict)
    completed: list[StepStatus] = field(default_factory=list)
    pending: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    updated_at: str = ""
    mode: str = "auto"
    manual_override: list[str] = field(default_factory=list)
    project_dir: str = ""


# ── Serialization ────────────────────────────────────────────────────


def _step_status_to_dict(s: StepStatus) -> dict[str, object]:
    """Convert StepStatus to a plain dict for JSON serialization."""
    d: dict[str, object] = {"step": s.step, "status": s.status}
    if s.completed_at:
        d["completed_at"] = s.completed_at
    if s.result:
        d["result"] = s.result
    if s.note:
        d["note"] = s.note
    if s.actual_idle_seconds:
        d["actual_idle_seconds"] = s.actual_idle_seconds
    if s.marker_missing:
        d["marker_missing"] = s.marker_missing
    return d


def _dict_to_step_status(d: dict[str, object]) -> StepStatus:
    """Convert a plain dict to StepStatus."""
    return StepStatus(
        step=str(d.get("step", "")),
        status=str(d.get("status", "pending")),
        completed_at=str(d.get("completed_at", "")),
        result=str(d.get("result", "")),
        note=str(d.get("note", "")),
        actual_idle_seconds=float(d.get("actual_idle_seconds", 0.0)),
        marker_missing=bool(d.get("marker_missing", False)),
    )


def _state_to_dict(state: OrchestratorState) -> dict[str, object]:
    """Serialize OrchestratorState to a JSON-compatible dict."""
    return {
        "updated_at": state.updated_at,
        "mode": state.mode,
        "manual_override": state.manual_override,
        "project_dir": state.project_dir,
        "current": dict(state.current),
        "project_summary": dict(state.project_summary),
        "completed": [_step_status_to_dict(s) for s in state.completed],
        "pending": list(state.pending),
        "errors": list(state.errors),
    }


def _dict_to_state(d: dict[str, object]) -> OrchestratorState:
    """Deserialize a dict to OrchestratorState."""
    completed_raw = d.get("completed", [])
    completed = [
        _dict_to_step_status(c) if isinstance(c, dict) else c
        for c in completed_raw  # type: ignore[union-attr]
    ]
    return OrchestratorState(
        current=dict(d.get("current", {})),  # type: ignore[arg-type]
        project_summary=dict(d.get("project_summary", {})),  # type: ignore[arg-type]
        completed=completed,
        pending=list(d.get("pending", [])),  # type: ignore[arg-type]
        errors=list(d.get("errors", [])),  # type: ignore[arg-type]
        updated_at=str(d.get("updated_at", "")),
        mode=str(d.get("mode", "auto")),
        manual_override=list(d.get("manual_override", [])),  # type: ignore[arg-type]
        project_dir=str(d.get("project_dir", "")),
    )


# ── Load / Save ──────────────────────────────────────────────────────


def load_state(path: Path) -> OrchestratorState:
    """Load OrchestratorState from a JSON file.

    Returns a default state if the file does not exist.
    """
    if not path.exists():
        return OrchestratorState()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return _dict_to_state(data)


def save_state(state: OrchestratorState, path: Path) -> None:
    """Save OrchestratorState to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_state_to_dict(state), f, ensure_ascii=False, indent=2)


# ── Session estimation ───────────────────────────────────────────────


def estimate_sessions(
    domains: list[str],
    features: dict[str, list[str]],
    source_line_count: int,
) -> int:
    """Estimate the total number of AI sessions needed.

    Formula from §5.0:
    - Phase 1: 1 session if source <= 3000 lines, else 1 + len(domains)
    - Phase 2: total feature count (simplified — bundle logic reduces this)
    - Phase 3: group A(1) + group B(feature count) + group C(1) + group D(1) = 3 + feature count
    - Phase 4: 3 sessions (consistency + rescore + quality)
    - Phase 5: 1 (outline) + estimated exec-plan count
    """
    total_features = sum(len(fs) for fs in features.values())

    # Phase 1
    if source_line_count <= 3000:
        phase1 = 1
    else:
        phase1 = 1 + len(domains)

    # Phase 2: one session per feature (bundles reduce, but estimate conservatively)
    phase2 = total_features

    # Phase 3: A(1) + B(features) + C(1) + D(1)
    phase3 = 3 + total_features

    # Phase 4: 3 fixed sessions
    phase4 = 3

    # Phase 5: outline(1) + detail sessions (estimate ~1 per 3 features, minimum 1)
    exec_plan_count = max(1, math.ceil(total_features / 3))
    phase5 = 1 + exec_plan_count

    return phase1 + phase2 + phase3 + phase4 + phase5


# ── Adaptive timeout ─────────────────────────────────────────────────


def compute_adaptive_timeout(
    completed_steps: list[StepStatus],
    config: DocsOrchestratorConfig,
) -> float:
    """Compute adaptive timeout based on actual idle seconds from completed steps.

    Uses measured average × multiplier, clamped to [min, max].
    Returns the initial idle_timeout_seconds if fewer than 3 measurements exist.
    """
    measurements = [
        s.actual_idle_seconds
        for s in completed_steps
        if s.actual_idle_seconds > 0
    ]

    if len(measurements) < 3:
        return config.idle_timeout_seconds

    avg = sum(measurements) / len(measurements)
    timeout = avg * config.adaptive_timeout_multiplier

    # Clamp to [min, max]
    return max(config.adaptive_timeout_min, min(config.adaptive_timeout_max, timeout))


# ── Gap summary generation ───────────────────────────────────────────

# Regex patterns for §12.5
_RE_SCORE = re.compile(r"(?:종합|점수)\s*[:：]\s*([\d.]+)\s*/\s*([\d.]+)")
_RE_AI_DECISION = re.compile(r"\[AI_DECISION\]")
_RE_HEADER = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def generate_gap_summary(gap_reports_dir: Path) -> str:
    """Generate _summary.md from gap-report files (§12.5).

    Parses score lines and [AI_DECISION] counts from each gap-report,
    then assembles a markdown table.
    """
    rows: list[dict[str, object]] = []

    for md_file in sorted(gap_reports_dir.glob("*.md")):
        if md_file.name == "_summary.md":
            continue

        content = md_file.read_text(encoding="utf-8")

        # Extract feature name from filename: payment--refund.md → (payment, refund)
        stem = md_file.stem
        if "--" in stem:
            domain, feature = stem.split("--", 1)
        else:
            domain = ""
            feature = stem

        # Parse score
        score_match = _RE_SCORE.search(content)
        if score_match:
            score_str = f"{score_match.group(1)}/{score_match.group(2)}"
            score_val = float(score_match.group(1))
            score_max = float(score_match.group(2))
        else:
            score_str = "-"
            score_val = 0.0
            score_max = 0.0

        # Count [AI_DECISION] tags
        ai_decision_count = len(_RE_AI_DECISION.findall(content))

        rows.append({
            "domain": domain,
            "feature": feature,
            "score_str": score_str,
            "score_val": score_val,
            "score_max": score_max,
            "ai_decision_count": ai_decision_count,
        })

    # Build markdown table
    lines: list[str] = ["# 갭 분석 요약", ""]
    lines.append("| # | 도메인 | 기능 | 점수 | AI 결정 수 |")
    lines.append("|---|--------|------|------|-----------|")

    total_score = 0.0
    total_max = 0.0
    total_ai = 0

    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | {row['domain']} | {row['feature']} "
            f"| {row['score_str']} | {row['ai_decision_count']} |"
        )
        total_score += float(row["score_val"])
        total_max += float(row["score_max"])
        total_ai += int(row["ai_decision_count"])

    lines.append("")
    if total_max > 0:
        avg = total_score / len(rows) if rows else 0
        avg_max = total_max / len(rows) if rows else 0
        lines.append(f"**전체 평균**: {avg:.1f}/{avg_max:.1f}")
    else:
        lines.append("**전체 평균**: -")
    lines.append(f"**총 AI 결정 수**: {total_ai}건")
    lines.append("")
    lines.append("<!-- ORCHESTRATOR:DONE -->")

    return "\n".join(lines)


# ── Running step recovery ────────────────────────────────────────────

# Phase별 최소 줄 수 기준 (§2.7)
_MIN_LINES_BY_PHASE: dict[str, int] = {
    "phase_1": 30,           # analysis-report.md
    "phase_1_domain": 10,    # domain-extract 기능별 파일
    "phase_2": 20,           # gap-report
    "phase_3_product_spec": 50,
    "phase_3_design_doc": 30,
    "phase_4": 20,           # phase4-*.md
    "phase_5": 30,           # exec-plan
}

_DONE_MARKER = "<!-- ORCHESTRATOR:DONE -->"


def _file_has_done_marker(path: Path) -> bool:
    """Check if a file ends with the completion marker."""
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8").rstrip()
    return content.endswith(_DONE_MARKER)


def _find_output_files_for_step(step: str, project_dir: Path) -> list[Path]:
    """Determine expected output files for a given step.

    This is a simplified mapping — the full orchestrator will have
    more detailed file mappings per step.
    """
    generated = project_dir / "docs" / "generated"

    if step == "phase_1":
        return [generated / "analysis-report.md"]
    elif step.startswith("phase_1:"):
        # phase_1:domain → domain-extracts/domain/
        parts = step.split(":")
        if len(parts) >= 2:
            domain = parts[1]
            domain_dir = generated / "domain-extracts" / domain
            if domain_dir.exists():
                return list(domain_dir.glob("*.md"))
        return []
    elif step.startswith("phase_2:"):
        # phase_2:domain:feature → gap-reports/domain--feature.md
        parts = step.split(":")
        if len(parts) >= 3:
            domain, feature = parts[1], parts[2]
            return [generated / "gap-reports" / f"{domain}--{feature}.md"]
        return []
    elif step == "phase_3_A":
        dd = project_dir / "docs" / "design-docs"
        if dd.exists():
            return list(dd.glob("*.md"))
        return []
    elif step.startswith("phase_3_B:"):
        # phase_3_B:domain:feature or phase_3_B:d1:f1+d2:f2
        rest = step[len("phase_3_B:"):]
        specs_dir = project_dir / "docs" / "product-specs"
        files: list[Path] = []
        for pair in rest.split("+"):
            parts = pair.split(":", 1)
            if len(parts) == 2:
                d, f = parts
                canonical = specs_dir / f"{d}--{f}.md"
                # Separator fallback: also check single-hyphen variant
                if not canonical.exists():
                    alt = specs_dir / f"{d}-{f}.md"
                    if alt.exists():
                        alt.rename(canonical)
                files.append(canonical)
        return files
    elif step == "phase_3_C":
        return [project_dir / "ARCHITECTURE.md"]
    elif step == "phase_3_D":
        return [project_dir / "AGENTS.md"]
    elif step.startswith("phase_3"):
        return []
    elif step == "phase_4_1":
        return [project_dir / "docs" / "generated" / "phase4-consistency.md"]
    elif step == "phase_4_2":
        return [project_dir / "docs" / "generated" / "phase4-rescore.md"]
    elif step == "phase_4_3":
        return [project_dir / "docs" / "QUALITY_SCORE.md"]
    elif step.startswith("phase_4"):
        return []
    elif step == "phase_5_outline":
        return [project_dir / "docs" / "generated" / "exec-plan-outline.md"]
    elif step.startswith("phase_5_detail:"):
        plan_name = step[len("phase_5_detail:"):]
        return [project_dir / "docs" / "exec-plans" / "planning" / f"{plan_name}.md"]
    elif step.startswith("phase_5"):
        return []

    return []


def recover_running_step(
    state: OrchestratorState, project_dir: Path
) -> OrchestratorState:
    """Recover from a 'running' status after restart (§8.3).

    3-step recovery policy:
    1. Output files + done marker exist → completed
    2. Output files exist but no marker → delete files, set pending
    3. No output files → set pending
    """
    current = state.current
    if current.get("status") != "running":
        return state

    step = current.get("step", "")
    output_files = _find_output_files_for_step(step, Path(state.project_dir or project_dir))

    # Step 1: Check if output files exist with done markers
    if output_files and all(_file_has_done_marker(f) for f in output_files):
        # Session completed successfully — orchestrator just missed it
        new_completed = list(state.completed) + [
            StepStatus(
                step=step,
                status="completed",
                completed_at=datetime.now().isoformat(),
                result="recovered",
                note="복구: 마커 확인으로 completed 전환",
            )
        ]
        new_current = {**current, "status": "idle"}
        return OrchestratorState(
            current=new_current,
            project_summary=state.project_summary,
            completed=new_completed,
            pending=state.pending,
            errors=state.errors,
            updated_at=datetime.now().isoformat(),
            mode=state.mode,
            manual_override=state.manual_override,
            project_dir=state.project_dir,
        )

    # Step 2 & 3: No marker or no files → revert to pending
    # Step 2: If files exist without marker, delete them
    if output_files:
        for f in output_files:
            if f.exists() and not _file_has_done_marker(f):
                f.unlink()

    new_current = {**current, "status": "idle"}
    new_pending = list(state.pending) + [{"step": step, "depends_on": ""}]

    return OrchestratorState(
        current=new_current,
        project_summary=state.project_summary,
        completed=state.completed,
        pending=new_pending,
        errors=state.errors,
        updated_at=datetime.now().isoformat(),
        mode=state.mode,
        manual_override=state.manual_override,
        project_dir=state.project_dir,
    )
