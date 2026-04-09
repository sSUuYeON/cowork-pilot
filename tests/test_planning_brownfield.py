from pathlib import Path

import pytest

from cowork_pilot.planning.brownfield import (
    BrownfieldSubPipeline,
    run_code_observation_extraction,
    run_gap_synthesis,
    run_observation_synthesis,
)
from cowork_pilot.planning.models import SizeClass


def test_extraction_produces_per_slice_observation_files(tmp_path: Path):
    result = run_code_observation_extraction(
        project_dir=tmp_path,
        slices=("auth", "dashboard"),
        size_class=SizeClass.MEDIUM,
    )

    assert "code-observations/auth.md" in result.generated_files
    assert "code-observations/dashboard.md" in result.generated_files
    for path in result.generated_files:
        assert result.completion_markers[path] is True


def test_observation_synthesis_reads_only_observation_files(tmp_path: Path):
    obs_dir = tmp_path / "code-observations"
    obs_dir.mkdir()
    (obs_dir / "auth.md").write_text(
        "# Auth\nroutes: /login, /signup\n<!-- ORCHESTRATOR:DONE -->",
        encoding="utf-8",
    )
    (obs_dir / "dashboard.md").write_text(
        "# Dashboard\nroutes: /home\n<!-- ORCHESTRATOR:DONE -->",
        encoding="utf-8",
    )

    result = run_observation_synthesis(run_dir=tmp_path)

    assert "implementation-observation-summary.md" in result.generated_files
    assert result.raw_code_accessed is False


def test_gap_synthesis_requires_observation_summary(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        run_gap_synthesis(
            run_dir=tmp_path,
            canonical_specs=("docs/specs/v2.md",),
            change_request_summary="Add notifications",
        )


def test_gap_synthesis_emits_both_gap_artifacts(tmp_path: Path):
    (tmp_path / "implementation-observation-summary.md").write_text(
        "# Summary\n<!-- ORCHESTRATOR:DONE -->",
        encoding="utf-8",
    )

    result = run_gap_synthesis(
        run_dir=tmp_path,
        canonical_specs=("docs/specs/v2.md",),
        change_request_summary="Add notifications",
    )

    assert "spec-implementation-gap.md" in result.generated_files
    assert "change-impact-gap.md" in result.generated_files


def test_full_brownfield_sub_pipeline_flows_in_order(tmp_path: Path):
    pipeline = BrownfieldSubPipeline(
        project_dir=tmp_path,
        run_dir=tmp_path,
        canonical_specs=("docs/specs/v2.md",),
        change_request_summary="Add notifications",
        size_class=SizeClass.MEDIUM,
    )

    result = pipeline.run()

    assert result.stages_completed == [
        "brownfield_code_observation_extraction",
        "brownfield_observation_synthesis",
        "brownfield_gap_synthesis",
    ]
