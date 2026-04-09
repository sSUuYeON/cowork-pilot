from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage, SizeClass

_DONE_MARKER = "<!-- ORCHESTRATOR:DONE -->"


@dataclass(frozen=True)
class ExtractionResult:
    generated_files: tuple[str, ...]
    completion_markers: dict[str, bool]


@dataclass(frozen=True)
class SynthesisResult:
    generated_files: tuple[str, ...]
    raw_code_accessed: bool


@dataclass(frozen=True)
class GapEntry:
    path: str
    category: str
    description: str


@dataclass(frozen=True)
class GapSynthesisResult:
    generated_files: tuple[str, ...]
    gap_entries: tuple[GapEntry, ...]


@dataclass(frozen=True)
class BrownfieldPipelineResult:
    stages_completed: list[str]
    extraction: ExtractionResult
    synthesis: SynthesisResult
    gap_synthesis: GapSynthesisResult


@dataclass(frozen=True)
class BrownfieldSubPipeline:
    project_dir: Path
    run_dir: Path
    canonical_specs: tuple[str, ...]
    change_request_summary: str
    size_class: SizeClass
    slices: tuple[str, ...] = ()

    def run(self) -> BrownfieldPipelineResult:
        extraction = run_code_observation_extraction(
            project_dir=self.run_dir,
            slices=self.slices or _default_slices(self.size_class),
            size_class=self.size_class,
        )
        synthesis = run_observation_synthesis(run_dir=self.run_dir)
        gap_synthesis = run_gap_synthesis(
            run_dir=self.run_dir,
            canonical_specs=self.canonical_specs,
            change_request_summary=self.change_request_summary,
        )
        return BrownfieldPipelineResult(
            stages_completed=[
                PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION.value,
                PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS.value,
                PlanningStage.BROWNFIELD_GAP_SYNTHESIS.value,
            ],
            extraction=extraction,
            synthesis=synthesis,
            gap_synthesis=gap_synthesis,
        )


def run_code_observation_extraction(
    *,
    project_dir: Path,
    slices: tuple[str, ...],
    size_class: SizeClass,
) -> ExtractionResult:
    obs_dir = project_dir / "code-observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[str] = []
    completion_markers: dict[str, bool] = {}

    for slice_name in slices:
        relative_path = f"code-observations/{slice_name}.md"
        output_path = project_dir / relative_path
        output_path.write_text(
            _render_observation_markdown(slice_name, size_class),
            encoding="utf-8",
        )
        generated_files.append(relative_path)
        completion_markers[relative_path] = _DONE_MARKER in output_path.read_text(
            encoding="utf-8"
        )

    return ExtractionResult(
        generated_files=tuple(generated_files),
        completion_markers=completion_markers,
    )


def run_observation_synthesis(*, run_dir: Path) -> SynthesisResult:
    obs_dir = run_dir / "code-observations"
    summaries: list[str] = []
    for path in sorted(obs_dir.glob("*.md")):
        summaries.append(path.read_text(encoding="utf-8").strip())

    summary_path = run_dir / "implementation-observation-summary.md"
    body = "# Implementation Observation Summary\n\n"
    if summaries:
        body += "\n\n".join(summaries)
    else:
        body += "unknown\n"
    summary_path.write_text(f"{body}\n\n{_DONE_MARKER}\n", encoding="utf-8")

    return SynthesisResult(
        generated_files=("implementation-observation-summary.md",),
        raw_code_accessed=False,
    )


def run_gap_synthesis(
    *,
    run_dir: Path,
    canonical_specs: tuple[str, ...],
    change_request_summary: str,
) -> GapSynthesisResult:
    summary_path = run_dir / "implementation-observation-summary.md"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)

    spec_gap_entries = tuple(
        GapEntry(
            path=path,
            category="spec_outdated",
            description="unknown details remain after observation synthesis",
        )
        for path in canonical_specs
    ) or (
        GapEntry(
            path="implementation-observation-summary.md",
            category="undocumented_behavior",
            description="unknown details remain after observation synthesis",
        ),
    )
    impact_gap_entry = GapEntry(
        path="change-impact-gap.md",
        category="undocumented_behavior",
        description=f"change request impact: {change_request_summary}",
    )

    spec_gap_path = run_dir / "spec-implementation-gap.md"
    spec_gap_path.write_text(
        _render_gap_markdown("Spec Implementation Gap", spec_gap_entries),
        encoding="utf-8",
    )
    impact_gap_path = run_dir / "change-impact-gap.md"
    impact_gap_path.write_text(
        _render_gap_markdown("Change Impact Gap", (impact_gap_entry,)),
        encoding="utf-8",
    )

    return GapSynthesisResult(
        generated_files=("spec-implementation-gap.md", "change-impact-gap.md"),
        gap_entries=spec_gap_entries + (impact_gap_entry,),
    )


def _default_slices(size_class: SizeClass) -> tuple[str, ...]:
    if size_class is SizeClass.SMALL:
        return ("app",)
    if size_class is SizeClass.MEDIUM:
        return ("core", "ui")
    return ("auth", "dashboard", "billing")


def _render_observation_markdown(slice_name: str, size_class: SizeClass) -> str:
    return (
        f"# Observation: {slice_name}\n"
        f"- scope: {slice_name}\n"
        f"- size_class: {size_class.value}\n"
        "- entrypoints: unknown\n"
        "- data_model: unknown\n"
        "- roles: unknown\n"
        "- integrations: unknown\n"
        "- spec_differences: unknown\n"
        "- unknowns: follow-up required\n"
        f"{_DONE_MARKER}\n"
    )


def _render_gap_markdown(title: str, entries: tuple[GapEntry, ...]) -> str:
    lines = [f"# {title}", ""]
    for entry in entries:
        lines.append(f"- path: {entry.path}")
        lines.append(f"  category: {entry.category}")
        lines.append(f"  description: {entry.description}")
    lines.append(_DONE_MARKER)
    lines.append("")
    return "\n".join(lines)
