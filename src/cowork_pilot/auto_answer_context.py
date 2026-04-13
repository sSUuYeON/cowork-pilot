from __future__ import annotations

from pathlib import Path

from cowork_pilot.auto_answer_models import Phase2StepInputs
from cowork_pilot.orchestrator_prompts import AvailableExtracts


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
        if overview_path not in required and overview_path not in optional:
            optional.append(overview_path)

    for domain, feature in bundle:
        gap_report = generated_dir / "gap-reports" / f"{domain}--{feature}.md"
        if gap_report.exists() and gap_report not in optional:
            optional.append(gap_report)

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
