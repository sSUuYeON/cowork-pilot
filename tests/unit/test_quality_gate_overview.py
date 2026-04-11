from pathlib import Path

from cowork_pilot.orchestrator.quality_gate import (
    evaluate_phase1,
    Phase1Result,
)


def _write(path: Path, body: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


DECISION_TABLE = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | lifecycle shared |
| voter | no | self contained |
"""


def _setup_project(
    tmp_path: Path,
    *,
    include_shared: bool = True,
    include_host_overview: bool = True,
) -> Path:
    project = tmp_path / "proj"
    extracts = project / "domain-extracts"
    _write(project / "analysis-report.md", "# report\n" + DECISION_TABLE)
    if include_shared:
        _write(extracts / "shared.md")
    _write(extracts / "host" / "create-poll.md")
    _write(extracts / "host" / "close-poll.md")
    _write(extracts / "voter" / "cast-vote.md")
    if include_host_overview:
        _write(extracts / "host" / "_overview.md", "10 line body\n" * 12)
    return project


def test_happy_path_passes(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    result = evaluate_phase1(project)
    assert isinstance(result, Phase1Result)
    assert result.ok is True
    assert result.hard_failures == []
    assert result.warnings == []


def test_missing_shared_is_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_shared=False)
    result = evaluate_phase1(project)
    assert result.ok is False
    assert any("shared.md" in f for f in result.hard_failures)


def test_missing_overview_for_yes_domain_is_warning(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=False)
    result = evaluate_phase1(project)
    assert result.ok is True, "missing overview must not be a hard fail"
    assert any("host" in w and "_overview" in w for w in result.warnings)


def test_missing_overview_for_no_domain_is_silent(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    # voter has overview_needed=no and no overview file; no warning expected.
    assert not (project / "domain-extracts" / "voter" / "_overview.md").exists()
    result = evaluate_phase1(project)
    assert not any("voter" in w and "_overview" in w for w in result.warnings)


def test_ceremonial_overview_is_warning(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    # Overwrite host overview with a <10-line body.
    (project / "domain-extracts" / "host" / "_overview.md").write_text("one line only\n")
    result = evaluate_phase1(project)
    assert any("host" in w and "10" in w for w in result.warnings)


def test_missing_feature_file_is_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path)
    (project / "domain-extracts" / "host" / "create-poll.md").unlink()
    (project / "domain-extracts" / "host" / "close-poll.md").unlink()
    (project / "domain-extracts" / "voter" / "cast-vote.md").unlink()
    result = evaluate_phase1(project)
    assert result.ok is False
    assert any("feature" in f for f in result.hard_failures)


def test_legacy_project_without_decision_table_does_not_hard_fail(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=False)
    # Strip the decision table.
    (project / "analysis-report.md").write_text("# report\nno table\n")
    result = evaluate_phase1(project)
    assert result.ok is True
    # In legacy mode overview checks are silenced or emitted as informational only.
    assert all("hard" not in w.lower() for w in result.warnings)


def test_legacy_project_with_existing_overview_passes(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, include_host_overview=True)
    (project / "analysis-report.md").write_text("# legacy report without table\n")
    result = evaluate_phase1(project)
    assert result.ok is True
    # No overview-related warnings because we're in legacy mode.
    assert not any("_overview" in w for w in result.warnings)
