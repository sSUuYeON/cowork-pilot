from __future__ import annotations

import argparse
import asyncio
import sys

import pytest

from cowork_pilot.config import PlanningConfig
from cowork_pilot.planning.models import ProjectMode


def test_codex_main_accepts_planning_subcommand(monkeypatch):
    called: dict[str, object] = {}

    async def fake_run_planning(args):
        called["command"] = args.command
        called["project_mode"] = args.project_mode
        called["request"] = args.request
        called["request_file"] = args.request_file
        called["change_request"] = args.change_request
        called["change_request_file"] = args.change_request_file
        return 0

    import cowork_pilot.codex.main as codex_main

    monkeypatch.setattr(codex_main, "_run_planning", fake_run_planning)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot-codex",
            "planning",
            "--project-dir",
            "/tmp/project",
            "--project-mode",
            "brownfield",
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

    with pytest.raises(SystemExit) as exc:
        codex_main.cli()

    assert exc.value.code == 0
    assert called["command"] == "planning"
    assert called["project_mode"] == "brownfield"
    assert called["request"] == "build a dashboard"
    assert called["request_file"] == "request.md"
    assert called["change_request"] == "adjust auth"
    assert called["change_request_file"] == "change-request.md"


def test_run_planning_bootstraps_context(tmp_path, monkeypatch):
    import cowork_pilot.codex.main as codex_main

    captured: dict[str, object] = {}
    run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "run-1"

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

    exit_code = asyncio.run(
        codex_main._run_planning(
            argparse.Namespace(project_dir=str(tmp_path), config=str(tmp_path / "config.toml"))
        )
    )

    context = captured["context"]
    assert exit_code == 0
    assert context.run_dir == run_dir
    assert context.project_dir == tmp_path
    assert context.target_version == "codex-planning"


def test_run_planning_uses_config_project_dir_when_cli_missing(tmp_path, monkeypatch):
    import cowork_pilot.codex.main as codex_main

    captured: dict[str, object] = {}
    run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "run-1"
    config_project_dir = tmp_path / "config-project"

    monkeypatch.setattr(
        "cowork_pilot.config.load_planning_config",
        lambda path: PlanningConfig(),
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_config",
        lambda path: type("Config", (), {"project_dir": str(config_project_dir)})(),
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

    exit_code = asyncio.run(
        codex_main._run_planning(
            argparse.Namespace(project_dir="", config=str(tmp_path / "config.toml"))
        )
    )

    context = captured["context"]
    assert exit_code == 0
    assert context.project_dir == config_project_dir
    assert context.run_dir == run_dir


def test_run_planning_preserves_resolved_planning_text_and_run_id_mode(tmp_path, monkeypatch):
    import cowork_pilot.codex.main as codex_main

    captured: dict[str, object] = {}
    call_order: list[str] = []

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

    exit_code = asyncio.run(
        codex_main._run_planning(
            argparse.Namespace(project_dir=str(tmp_path), config=str(tmp_path / "config.toml"))
        )
    )

    context = captured["context"]
    assert exit_code == 0
    assert call_order[0] == "bundle"
    assert call_order[1] == "run_id:brownfield:codex-planning"
    assert context.request_text == "resolved request"
    assert context.change_request_text == "resolved change request"


def test_codex_cli_planning_reports_missing_request_file_cleanly(monkeypatch, capsys):
    import cowork_pilot.codex.main as codex_main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot-codex",
            "--config",
            "config.toml",
            "planning",
            "--request-file",
            "missing-request.md",
        ],
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_config",
        lambda path: type("Config", (), {"project_dir": "/tmp/project"})(),
    )
    monkeypatch.setattr(
        "cowork_pilot.config.load_planning_config",
        lambda path: PlanningConfig(),
    )

    with pytest.raises(SystemExit) as exc:
        codex_main.cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "request file not found" in captured.err


def test_brownfield_cli_change_request_skips_template_wait(tmp_path):
    import cowork_pilot.codex.main as codex_main

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
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

    exit_code = asyncio.run(
        codex_main._run_planning(
            argparse.Namespace(
                project_dir=str(project_dir),
                config=str(config_path),
                project_mode="brownfield",
                request="current flow needs redesign",
                request_file="",
                change_request="change login landing to dashboard",
                change_request_file="",
            )
        )
    )

    run_dir = project_dir / "docs" / "generated" / "planning-runs" / "brownfield-codex-planning"
    assert exit_code == 0
    assert (run_dir / "stage-handoffs").exists()
    # With the new skeleton→feature-outline→detail flow, exec-plan.md is no longer
    # produced via EXEC_PLAN_AUTHORING; verify the run completed instead
    assert (run_dir / "run-state.json").exists()
    assert "change login landing to dashboard" in (
        run_dir / "inputs" / "change-request.md"
    ).read_text(encoding="utf-8")
