from pathlib import Path

from cowork_pilot.orchestrator.feature_detector import detect_features


def _touch(path: Path, body: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_feature_detector_excludes_support_files(tmp_path: Path) -> None:
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "shared.md")
    _touch(extracts / "host" / "_overview.md")
    _touch(extracts / "host" / "create-poll.md")
    _touch(extracts / "host" / "close-poll.md")
    _touch(extracts / "voter" / "cast-vote.md")
    _touch(extracts / "references" / "some-ref.md")

    features = detect_features(extracts)

    names = sorted(f.name for f in features)
    assert names == ["cast-vote.md", "close-poll.md", "create-poll.md"]

    joined = "\n".join(str(f) for f in features)
    assert "shared.md" not in joined
    assert "_overview.md" not in joined
    assert "references" not in joined


def test_feature_detector_empty_when_root_missing(tmp_path: Path) -> None:
    assert detect_features(tmp_path / "nope") == []


def test_feature_detector_ignores_top_level_non_support_markdown(tmp_path: Path) -> None:
    # A stray ``domain-extracts/top-level.md`` is not a feature
    # (features must sit inside a domain directory).
    extracts = tmp_path / "domain-extracts"
    _touch(extracts / "top-level.md")
    _touch(extracts / "host" / "feature.md")
    features = detect_features(extracts)
    assert [p.name for p in features] == ["feature.md"]
