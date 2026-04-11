"""Unit tests for :func:`compute_available_extracts` (Chunk 4 · Task 4.1)."""
from __future__ import annotations

from pathlib import Path

from cowork_pilot.orchestrator_prompts import compute_available_extracts


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_computes_presence_map(tmp_path: Path) -> None:
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "shared.md")
    _touch(extracts / "host" / "_overview.md")
    _touch(extracts / "host" / "create-poll.md")
    _touch(extracts / "voter" / "cast-vote.md")

    info = compute_available_extracts(extracts)

    assert info.shared is True
    assert info.overviews == {"host": True, "voter": False}
    assert sorted(info.features["host"]) == ["create-poll.md"]
    assert sorted(info.features["voter"]) == ["cast-vote.md"]


def test_missing_extracts_root_returns_empty(tmp_path: Path) -> None:
    info = compute_available_extracts(tmp_path / "nope")
    assert info.shared is False
    assert info.overviews == {}
    assert info.features == {}


def test_references_dir_is_ignored(tmp_path: Path) -> None:
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "shared.md")
    _touch(extracts / "references" / "checklists.md")
    _touch(extracts / "host" / "_overview.md")
    _touch(extracts / "host" / "create-poll.md")

    info = compute_available_extracts(extracts)

    assert info.overviews == {"host": True}
    assert "references" not in info.overviews
    assert "references" not in info.features
