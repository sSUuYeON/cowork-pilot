from pathlib import Path

import pytest

from cowork_pilot.planning.input_contract import resolve_planning_input_bundle
from cowork_pilot.planning.models import ProjectMode


def test_input_bundle_prefers_cli_request_over_file(tmp_path: Path) -> None:
    request_file = tmp_path / "docs" / "planning" / "request.md"
    request_file.parent.mkdir(parents=True)
    request_file.write_text("file request", encoding="utf-8")

    bundle = resolve_planning_input_bundle(
        project_dir=tmp_path,
        project_mode_arg="greenfield",
        request_arg="cli request",
        request_file_arg=str(request_file),
        change_request_arg="",
        change_request_file_arg="",
    )

    assert bundle.project_mode is ProjectMode.GREENFIELD
    assert bundle.explicit_mode is True
    assert bundle.request_text == "cli request"
    assert bundle.request_source == "cli"


def test_input_bundle_uses_request_file_when_cli_request_missing(tmp_path: Path) -> None:
    request_file = tmp_path / "incoming.md"
    request_file.write_text("file request", encoding="utf-8")

    bundle = resolve_planning_input_bundle(
        project_dir=tmp_path,
        project_mode_arg="brownfield",
        request_arg="",
        request_file_arg=str(request_file),
        change_request_arg="",
        change_request_file_arg="",
    )

    assert bundle.project_mode is ProjectMode.BROWNFIELD
    assert bundle.explicit_mode is True
    assert bundle.request_text == "file request"
    assert bundle.request_source == str(request_file)


def test_input_bundle_raises_value_error_for_missing_request_file(tmp_path: Path) -> None:
    missing_request_file = tmp_path / "missing-request.md"

    with pytest.raises(ValueError, match="request file not found"):
        resolve_planning_input_bundle(
            project_dir=tmp_path,
            project_mode_arg="",
            request_arg="",
            request_file_arg=str(missing_request_file),
            change_request_arg="",
            change_request_file_arg="",
        )
