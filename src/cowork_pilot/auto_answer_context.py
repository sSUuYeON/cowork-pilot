from __future__ import annotations

from pathlib import Path

from cowork_pilot.auto_answer_models import Phase2StepInputs
from cowork_pilot.orchestrator_prompts import AvailableExtracts
from cowork_pilot.source_contradictions import (
    DetectedContradiction,
    contradiction_item_json_path,
    contradiction_resolution_path,
)


def _append_unique_path(paths: list[Path], candidate: Path) -> None:
    if candidate.exists() and candidate not in paths:
        paths.append(candidate)


def _file_contains(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _has_done_marker(path: Path) -> bool:
    return _file_contains(path, "<!-- ORCHESTRATOR:DONE -->")


def _parse_gap_report_path(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    if "--" not in stem:
        return None
    domain, feature = stem.split("--", 1)
    if not domain or not feature:
        return None
    return domain, feature


def _find_prior_ai_decision_reports(
    generated_dir: Path,
    bundle: list[tuple[str, str]],
) -> list[Path]:
    gap_reports_dir = generated_dir / "gap-reports"
    if not gap_reports_dir.exists():
        return []

    bundle_domains = {domain for domain, _ in bundle}
    results: list[Path] = []
    for path in sorted(gap_reports_dir.glob("*.md")):
        parsed = _parse_gap_report_path(path)
        if parsed is None:
            continue
        domain, _feature = parsed
        if domain not in bundle_domains:
            continue
        if _file_contains(path, "[AI_DECISION]"):
            results.append(path)
    return results


def _find_completed_gap_reports(
    generated_dir: Path,
    bundle: list[tuple[str, str]],
) -> list[Path]:
    gap_reports_dir = generated_dir / "gap-reports"
    if not gap_reports_dir.exists():
        return []

    bundle_domains = {domain for domain, _ in bundle}
    bundle_pairs = set(bundle)
    results: list[Path] = []
    for path in sorted(gap_reports_dir.glob("*.md")):
        parsed = _parse_gap_report_path(path)
        if parsed is None:
            continue
        if parsed not in bundle_pairs and parsed[0] not in bundle_domains:
            continue
        if _has_done_marker(path):
            results.append(path)
    return results


def resolve_phase2_step_inputs(
    *,
    project_dir: Path,
    step_name: str,
    phase_template: str,
    bundle: list[tuple[str, str]],
    extracts: AvailableExtracts,
    overview_reasons: dict[str, str],
) -> Phase2StepInputs:
    """Resolve the full phase2 input/output contract for one bundle."""

    generated_dir = project_dir / "docs" / "generated"
    extracts_root = generated_dir / "domain-extracts"

    first_domain, first_feature = bundle[0]
    features_for_prompt = [{"domain": d, "feature": f} for d, f in bundle]

    required: list[Path] = [
        generated_dir / "references" / "checklists.md",
        generated_dir / "analysis-report.md",
        extracts_root / "shared.md",
    ]
    for domain, feature in bundle:
        required.append(extracts_root / domain / f"{feature}.md")

    optional: list[Path] = []
    for domain, present in extracts.overviews.items():
        if not present:
            continue
        overview_path = extracts_root / domain / "_overview.md"
        if overview_path not in required:
            _append_unique_path(optional, overview_path)

    for domain, feature in bundle:
        gap_report = generated_dir / "gap-reports" / f"{domain}--{feature}.md"
        _append_unique_path(optional, gap_report)
        resolution_glob = (
            generated_dir
            / "contradiction-resolutions"
            / f"{domain}--{feature}--*.md"
        )
        for resolution_path in sorted(resolution_glob.parent.glob(resolution_glob.name)):
            _append_unique_path(optional, resolution_path)

    for prior_report in _find_prior_ai_decision_reports(generated_dir, bundle):
        _append_unique_path(optional, prior_report)

    for completed_gap_report in _find_completed_gap_reports(generated_dir, bundle):
        _append_unique_path(optional, completed_gap_report)

    output_files = [
        generated_dir / "gap-reports" / f"{domain}--{feature}.md"
        for domain, feature in bundle
    ]

    render_kwargs: dict[str, object] = {
        "project_dir": str(project_dir),
        "features": features_for_prompt,
        "domain": first_domain,
        "feature": first_feature,
        "extracts": extracts,
        "overview_reasons": overview_reasons,
    }

    return Phase2StepInputs(
        step_name=step_name,
        phase_template=phase_template,
        render_kwargs=render_kwargs,
        required_inputs=required,
        optional_inputs=optional,
        output_files=output_files,
    )


def resolve_phase2_conflict_inputs(
    *,
    project_dir: Path,
    contradiction: DetectedContradiction,
    phase_template: str,
    extracts: AvailableExtracts,
    overview_reasons: dict[str, str],
) -> Phase2StepInputs:
    """Resolve the full input/output contract for one phase2 conflict step."""

    generated_dir = project_dir / "docs" / "generated"
    extracts_root = generated_dir / "domain-extracts"
    contradiction_json = contradiction_item_json_path(
        generated_dir,
        contradiction.contradiction_id,
    )
    output_path = contradiction_resolution_path(
        generated_dir,
        contradiction.contradiction_id,
    )

    required = [
        generated_dir / "references" / "checklists.md",
        generated_dir / "analysis-report.md",
        extracts_root / "shared.md",
        extracts_root / contradiction.domain / f"{contradiction.feature}.md",
        contradiction_json,
    ]
    optional: list[Path] = []
    overview_path = extracts_root / contradiction.domain / "_overview.md"
    if overview_path.exists():
        optional.append(overview_path)

    render_kwargs: dict[str, object] = {
        "project_dir": str(project_dir),
        "contradiction": contradiction,
        "extracts": extracts,
        "overview_reasons": overview_reasons,
    }

    return Phase2StepInputs(
        step_name=f"phase_2_conflict:{contradiction.contradiction_id}",
        phase_template=phase_template,
        render_kwargs=render_kwargs,
        required_inputs=required,
        optional_inputs=optional,
        output_files=[output_path],
    )
