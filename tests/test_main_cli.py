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


# ── Docs-orchestrator resume CLI ────────────────────────────────────


def _prepare_docs_project(tmp_path: Path) -> Path:
    """Create a minimal docs/generated/ layout with a config.toml."""
    gen_dir = tmp_path / "docs" / "generated"
    gen_dir.mkdir(parents=True)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[project]\ndir = \"{tmp_path}\"\n\n[engine]\ndefault = \"codex\"\n",
        encoding="utf-8",
    )
    return config_path


def _seed_waiting_runtime(
    tmp_path: Path,
    *,
    step: str = "phase_2:x:y",
    question: str = "What next?",
) -> None:
    """Seed a minimal waiting runtime + state so the resume CLI has
    something to act on. Used by Test Chunk 4 tests after the Chunk 5
    refactor moved the runtime check ahead of the response check.
    """
    import json

    gen_dir = tmp_path / "docs" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "orchestrator-state.json").write_text(
        json.dumps(
            {
                "current": {"step": step, "status": "running"},
                "completed": [],
                "pending": [],
                "errors": [],
                "project_summary": {
                    "domains": [],
                    "features": {},
                    "source_docs": [],
                    "source_line_count": 0,
                },
                "updated_at": "",
                "mode": "auto",
                "manual_override": [],
                "project_dir": str(tmp_path),
            }
        )
    )
    (gen_dir / "orchestrator-runtime.json").write_text(
        json.dumps(
            {
                "backend": "codex",
                "step": step,
                "runtime_state": "waiting_for_input",
                "resume_handle": "tid-001",
                "resume_handle_kind": "codex_thread_id",
                "pending_event_id": "q1",
                "pending_question": {
                    "question": question,
                    "options": [],
                    "recommended": "",
                    "blocking": True,
                },
                "pending_approval": None,
            }
        )
    )


def test_docs_resume_requires_response_when_interactive_never(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """With ``--interactive-resume never`` and no ``--response``, resume must
    exit non-zero with a "response required" style message. This is the
    Chunk 5 replacement for the old test — runtime validation now runs
    first, so we have to seed a waiting runtime before the response check
    can be reached.
    """
    from cowork_pilot.main import cli

    config_path = _prepare_docs_project(tmp_path)
    _seed_waiting_runtime(tmp_path)

    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir=str(tmp_path), engine="codex"),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot",
            "--mode",
            "docs-orchestrator",
            "--docs-subcommand",
            "resume",
            "--interactive-resume",
            "never",
            "--config",
            str(config_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "response" in (captured.err + captured.out).lower()


def test_docs_resume_interactive_always_prompts_when_no_response(
    tmp_path: Path, monkeypatch
) -> None:
    """With ``--interactive-resume always`` and no ``--response``, the CLI
    wrapper must prompt the terminal once (via ``input``) and feed the
    answer into ``resume_waiting_docs_step``. Per MUST 5 the wrapper must
    not loop — we return a ``completed`` outcome so the single call path
    is exercised end-to-end.
    """
    from unittest.mock import MagicMock, patch

    from cowork_pilot.docs_orchestrator_resume import DocsResumeOutcome
    from cowork_pilot.main import cli
    from cowork_pilot.orchestrator_state import OrchestratorState

    config_path = _prepare_docs_project(tmp_path)
    _seed_waiting_runtime(tmp_path, question="Pick a flavor")

    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir=str(tmp_path), engine="codex"),
    )
    # Force interactive path deterministically: every call to the stdlib
    # ``input`` inside the docs terminal UI returns "vanilla".
    monkeypatch.setattr("builtins.input", lambda prompt="": "vanilla")

    captured_calls: dict[str, object] = {}

    def fake_resume_helper(config, orch_config, *, response_text, response_kind):
        captured_calls["response_text"] = response_text
        captured_calls["response_kind"] = response_kind
        captured_calls["interactive_resume"] = orch_config.interactive_resume
        return DocsResumeOutcome(
            status="completed",
            state=OrchestratorState(project_dir=str(tmp_path)),
            step="phase_2:x:y",
        )

    mock_continue = MagicMock()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot",
            "--mode",
            "docs-orchestrator",
            "--docs-subcommand",
            "resume",
            "--interactive-resume",
            "always",
            "--config",
            str(config_path),
        ],
    )

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_waiting_docs_step",
        side_effect=fake_resume_helper,
    ), patch(
        "cowork_pilot.docs_orchestrator.run_docs_orchestrator",
        mock_continue,
    ):
        cli()

    # Prompt path was taken and produced the expected terminal answer.
    assert captured_calls["response_text"] == "vanilla"
    assert captured_calls["response_kind"] == "answer"
    # Interactive resume flag was propagated into orch_config via the
    # Chunk 1 CLI wiring.
    assert captured_calls["interactive_resume"] is True
    # MUST 5: completed → run_docs_orchestrator re-entered exactly once.
    mock_continue.assert_called_once()


def test_docs_resume_error_when_no_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    """resume when no runtime file exists must exit with non-zero code."""
    from cowork_pilot.main import cli

    config_path = _prepare_docs_project(tmp_path)

    monkeypatch.setattr(
        "cowork_pilot.main.load_config",
        lambda path: Config(project_dir=str(tmp_path), engine="codex"),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cowork-pilot",
            "--mode",
            "docs-orchestrator",
            "--docs-subcommand",
            "resume",
            "--response",
            "some answer",
            "--config",
            str(config_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "runtime" in (captured.err + captured.out).lower()


def test_docs_resume_completed_clears_runtime(tmp_path: Path, monkeypatch) -> None:
    """Integration-level: the thin CLI wrapper must delegate to the pure
    helper and, on ``completed``, clear the runtime, advance the state,
    and re-enter ``run_docs_orchestrator`` exactly once (MUST 5).

    After Chunk 5, ``resume_codex_step`` is imported at module-load time
    into ``cowork_pilot.docs_orchestrator_resume``, so the patch target
    is the binding site there — not ``docs_orchestrator_codex``.
    """
    import json
    import argparse
    from unittest.mock import MagicMock, patch

    from cowork_pilot.docs_orchestrator_codex import CodexStepResult
    from cowork_pilot.main import _run_docs_orchestrator_resume

    _seed_waiting_runtime(tmp_path)
    gen_dir = tmp_path / "docs" / "generated"

    mock_result = CodexStepResult(
        status="completed",
        event_lines=[],
        assistant_message="",
        exit_code=0,
        resume_handle="tid-001",
        waiting_kind=None,
        pending_event_id=None,
        pending_question=None,
        pending_approval=None,
        error="",
    )

    mock_continue = MagicMock()

    with patch(
        "cowork_pilot.docs_orchestrator_resume.resume_codex_step",
        return_value=mock_result,
    ) as mock_resume, patch(
        "cowork_pilot.docs_orchestrator.run_docs_orchestrator",
        mock_continue,
    ):
        from cowork_pilot.config import DocsOrchestratorConfig

        args = argparse.Namespace(
            response="admin approves",
            response_kind="answer",
        )
        config = Config(project_dir=str(tmp_path))
        orch_config = DocsOrchestratorConfig(engine="codex")
        # Chunk 5 reads ``orch_config.interactive_resume``; keep the
        # wrapper on the non-interactive branch for this test.
        orch_config.interactive_resume = False
        _run_docs_orchestrator_resume(args, config, orch_config)

    expected_gap_report = tmp_path / "docs" / "generated" / "gap-reports" / "x--y.md"
    assert mock_resume.call_args is not None
    assert mock_resume.call_args.kwargs["expected_files"] == [expected_gap_report]
    # runtime file must be gone (state written first, then runtime cleared)
    assert not (gen_dir / "orchestrator-runtime.json").exists()
    # state must have the step completed
    state = json.loads((gen_dir / "orchestrator-state.json").read_text())
    completed_steps = [s["step"] for s in state["completed"]]
    assert "phase_2:x:y" in completed_steps
    # auto-continuation must have been called exactly once (MUST 5).
    mock_continue.assert_called_once()
