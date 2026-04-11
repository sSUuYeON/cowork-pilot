# tests/e2e/conftest.py
from pathlib import Path

import pytest


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _decision_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "## Domain Overview Decisions",
        "",
        "| domain | overview_needed | reason |",
        "|---|---|---|",
    ]
    for d, needed, reason in rows:
        lines.append(f"| {d} | {needed} | {reason} |")
    return "\n".join(lines) + "\n"


@pytest.fixture
def mixed_project(tmp_path: Path) -> Path:
    project = tmp_path / "mixed"
    extracts = project / "domain-extracts"
    _write(
        project / "analysis-report.md",
        "# Analysis Report\n\n"
        + _decision_table([
            ("host", "yes", "poll lifecycle shared"),
            ("voter", "no", "self contained"),
        ]),
    )
    _write(extracts / "shared.md", "# shared\n")
    _write(extracts / "host" / "_overview.md", "# host overview\n" + "line\n" * 15)
    _write(extracts / "host" / "create-poll.md", "# create poll\n")
    _write(extracts / "host" / "close-poll.md", "# close poll\n")
    _write(extracts / "voter" / "cast-vote.md", "# cast vote\n")
    return project


@pytest.fixture
def small_project(tmp_path: Path) -> Path:
    project = tmp_path / "small"
    extracts = project / "domain-extracts"
    _write(
        project / "analysis-report.md",
        "# Analysis Report\n\n"
        + _decision_table([
            ("core", "no", "single feature domain"),
        ]),
    )
    _write(extracts / "shared.md", "# shared\n")
    _write(extracts / "core" / "do-the-thing.md", "# do it\n")
    return project
