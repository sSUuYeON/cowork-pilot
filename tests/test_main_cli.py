from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cowork_pilot.config import Config, PlanningConfig
from cowork_pilot.planning.models import ProjectMode


def test_main_cli_accepts_mode_planning(monkeypatch):
    called: dict[str, object] = {}

    def fake_run_planning_mode(config_path, **kwargs):
        called["config_path"] = config_path
        called["kwargs"] = kwargs

    monkeypatch.setattr("cowork_pilot.main.run_planning_mode", fake_run_planning_mode)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot",
            "--mode",
            "planning",
            "--config",
            "config.toml",
            "--project-mode",
            "greenfield",
            "--request",
            "build a dashboard",
            "--request-file",
            "request.md",
            "--change-request",
            "adjust auth",
            "--change-request-file",
            "change-request.md",
        ],
    )

    from cowork_pilot.main import cli

    cli()

    assert called["config_path"] == Path("config.toml")
    assert called["kwargs"] == {
        "project_mode": "greenfield",
        "request": "build a dashboard",
        "request_file": "request.md",
        "change_request": "adjust auth",
        "change_request_file": "change-request.md",
    }


def test_run_planning_mode_bootstraps_context(tmp_path: Path, monkeypatch) -> None:
    from cowork_pilot.main import run_planning_mode

    captured: dict[str, object] = {}
    run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "run-1"

    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_planning_config",
        lambda path: PlanningConfig(),
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.storage.create_run_id",
        lambda mode, target_version: "run-1",
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.storage.bootstrap_run_dir",
        lambda base_dir, run_id: run_dir,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_planning_pipeline",
        lambda context: captured.setdefault("context", context),
    )

    run_planning_mode(tmp_path / "config.toml")

    context = captured["context"]
    assert context.run_dir == run_dir
    assert context.project_dir == tmp_path
    assert context.target_version == "cli-planning"


def test_run_planning_mode_preserves_resolved_planning_text(tmp_path: Path, monkeypatch) -> None:
    from cowork_pilot.main import run_planning_mode

    captured: dict[str, object] = {}
    call_order: list[str] = []

    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_planning_config",
        lambda path: PlanningConfig(default_project_mode="greenfield"),
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.input_contract.resolve_planning_input_bundle",
        lambda **kwargs: call_order.append("bundle") or type(
            "Bundle",
            (),
            {
                "project_mode": ProjectMode.BROWNFIELD,
                "explicit_mode": True,
                "request_text": "resolved request",
                "request_source": "cli",
                "change_request_text": "resolved change request",
                "change_request_source": "cli",
            },
        )(),
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.storage.create_run_id",
        lambda mode, target_version: call_order.append(f"run_id:{mode}:{target_version}") or "run-1",
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.storage.bootstrap_run_dir",
        lambda base_dir, run_id: tmp_path / "docs" / "generated" / "planning-runs" / run_id,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_planning_pipeline",
        lambda context: captured.setdefault("context", context),
    )

    run_planning_mode(
        tmp_path / "config.toml",
        project_mode="brownfield",
        request="resolved request",
        change_request="resolved change request",
    )

    context = captured["context"]
    assert call_order[0] == "bundle"
    assert call_order[1] == "run_id:brownfield:cli-planning"
    assert context.request_text == "resolved request"
    assert context.change_request_text == "resolved change request"


def test_main_cli_planning_reports_missing_change_request_file_cleanly(monkeypatch, capsys) -> None:
    from cowork_pilot.main import cli

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot",
            "--mode",
            "planning",
            "--config",
            "config.toml",
            "--change-request-file",
            "missing-change-request.md",
        ],
    )
    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir="/tmp/project"),
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_planning_config",
        lambda path: PlanningConfig(),
    )

    with pytest.raises(SystemExit) as exc:
        cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "change-request file not found" in captured.err


def test_greenfield_cli_request_generates_exec_plan_and_handoffs(tmp_path: Path) -> None:
    from cowork_pilot.main import run_planning_mode

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            f"[project]\n"
            f'dir = "{project_dir}"\n\n'
            "[planning]\n"
            'run_root = "docs/generated/planning-runs"\n'
            'default_project_mode = "greenfield"\n'
        ),
        encoding="utf-8",
    )

    run_planning_mode(
        config_path,
        project_mode="greenfield",
        request="build a dashboard planning workflow",
    )

    run_dir = project_dir / "docs" / "generated" / "planning-runs" / "greenfield-cli-planning"
    assert (run_dir / "stage-handoffs").exists()
    # With the new skeleton→feature-outline→detail flow, exec-plan.md is no longer
    # produced via EXEC_PLAN_AUTHORING; verify the run completed instead
    assert (run_dir / "run-state.json").exists()
