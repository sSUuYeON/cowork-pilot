"""CLI entry point for ``cowork-pilot-codex``.

Usage:
    cowork-pilot-codex exec <plan_path> [--project-dir <dir>] [--dry-run]
    cowork-pilot-codex harness [--exec-plans-dir <dir>] [--project-dir <dir>] [--dry-run]
    cowork-pilot-codex planning [--project-dir <dir>] [--project-mode <mode>] [--request <text>]
        [--request-file <path>] [--change-request <text>] [--change-request-file <path>]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from cowork_pilot.codex.models import ChunkResult, ChunkRunStatus


def _setup_logging(level: str = "INFO") -> None:
    """Configure basic logging for the CLI."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _on_chunk_done(result: ChunkResult) -> None:
    """Print chunk completion status to stderr."""
    icon = {
        ChunkRunStatus.SUCCESS: "✓",
        ChunkRunStatus.FAILED: "✗",
        ChunkRunStatus.TIMEOUT: "⏱",
        ChunkRunStatus.SKIPPED: "⊘",
    }.get(result.status, "?")

    duration = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds > 0 else ""
    attempt = f" [attempt {result.attempt}]" if result.attempt > 1 else ""

    print(
        f"  {icon} Chunk {result.chunk_number}: {result.chunk_name} "
        f"— {result.status.value}{duration}{attempt}",
        file=sys.stderr,
    )


async def _run_exec(args: argparse.Namespace) -> int:
    """Execute an exec-plan via codex exec."""
    from cowork_pilot.codex.exec_runner import run_exec_plan
    from cowork_pilot.config import load_config
    from cowork_pilot.codex.config import load_codex_exec_config

    # Load config
    config_path = Path(args.config)
    base_config = load_config(config_path) if config_path.exists() else None
    exec_config = load_codex_exec_config(config_path)

    # Resolve plan path
    plan_path = Path(args.plan_path)
    if not plan_path.exists():
        print(f"Error: exec-plan not found: {plan_path}", file=sys.stderr)
        return 1

    # Resolve project dir
    project_dir = args.project_dir or (
        base_config.project_dir if base_config else str(Path.cwd())
    )

    # Override from CLI args
    codex_command = args.codex_command or exec_config.command
    timeout = args.timeout or exec_config.build_timeout_seconds
    max_retries = args.max_retries or exec_config.max_retries

    print(f"Codex Exec Runner", file=sys.stderr)
    print(f"  Plan: {plan_path}", file=sys.stderr)
    print(f"  Project: {project_dir}", file=sys.stderr)
    print(f"  Codex: {codex_command}", file=sys.stderr)
    print(f"  Timeout: {timeout}s / Retries: {max_retries}", file=sys.stderr)
    print(
        f"  Stalled output timeout: {exec_config.stalled_output_timeout_seconds}s",
        file=sys.stderr,
    )
    if args.dry_run:
        print(f"  *** DRY RUN — no commands will be executed ***", file=sys.stderr)
    print(file=sys.stderr)

    result = await run_exec_plan(
        plan_path=plan_path,
        project_dir=project_dir,
        codex_command=codex_command,
        codex_extra_args=exec_config.extra_args or None,
        timeout_seconds=timeout,
        stalled_output_timeout_seconds=exec_config.stalled_output_timeout_seconds,
        max_retries=max_retries,
        dry_run=args.dry_run,
        on_chunk_done=_on_chunk_done,
    )

    # Summary
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  {result.summary()}", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)

    if result.all_succeeded:
        print("All chunks completed successfully!", file=sys.stderr)
        return 0
    else:
        failed = [
            r for r in result.chunk_results
            if r.status in (ChunkRunStatus.FAILED, ChunkRunStatus.TIMEOUT)
        ]
        if failed:
            print(f"\nFailed chunks:", file=sys.stderr)
            for r in failed:
                print(f"  Chunk {r.chunk_number}: {r.status.value}", file=sys.stderr)
                if r.stderr:
                    # Show last 500 chars of stderr
                    snippet = r.stderr[-500:].strip()
                    print(f"    stderr: ...{snippet}", file=sys.stderr)
        return 1


def cli() -> None:
    """Entry point for ``cowork-pilot-codex`` command."""
    parser = argparse.ArgumentParser(
        prog="cowork-pilot-codex",
        description="Cowork Pilot — Codex CLI backend",
    )
    parser.add_argument(
        "--config", type=str, default="config.toml",
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── exec subcommand ─────────────────────────────────────────────
    exec_parser = subparsers.add_parser(
        "exec",
        help="Execute an exec-plan via codex exec",
    )
    exec_parser.add_argument(
        "plan_path",
        help="Path to the exec-plan Markdown file",
    )
    exec_parser.add_argument(
        "--project-dir", type=str, default="",
        help="Project working directory (default: from config or cwd)",
    )
    exec_parser.add_argument(
        "--codex-command", type=str, default="",
        help="Override codex command (default: from config)",
    )
    exec_parser.add_argument(
        "--timeout", type=float, default=0,
        help="Per-chunk timeout in seconds (default: from config)",
    )
    exec_parser.add_argument(
        "--max-retries", type=int, default=0,
        help="Max retries per chunk (default: from config)",
    )
    exec_parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview execution without running codex exec",
    )

    # ── harness subcommand ──────────────────────────────────────────
    harness_parser = subparsers.add_parser(
        "harness",
        help="Run full harness loop: plan lifecycle + codex exec (like cowork-pilot --mode harness)",
    )
    harness_parser.add_argument(
        "--exec-plans-dir", type=str, default="",
        help="Path to exec-plans directory (default: from config or docs/exec-plans)",
    )
    harness_parser.add_argument(
        "--project-dir", type=str, default="",
        help="Project working directory (default: from config or cwd)",
    )
    harness_parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview execution without running codex exec",
    )

    planning_parser = subparsers.add_parser(
        "planning",
        help="Run planning runtime",
    )
    planning_parser.add_argument(
        "--project-dir", type=str, default="",
        help="Project working directory (default: cwd)",
    )
    planning_parser.add_argument(
        "--project-mode", type=str, choices=["greenfield", "brownfield"], default="",
        help="Planning mode override (optional)",
    )
    planning_parser.add_argument(
        "--request", type=str, default="",
        help="Planning request text override (optional)",
    )
    planning_parser.add_argument(
        "--request-file", type=str, default="",
        help="Path to a planning request file override (optional)",
    )
    planning_parser.add_argument(
        "--change-request", type=str, default="",
        help="Brownfield change-request text override (optional)",
    )
    planning_parser.add_argument(
        "--change-request-file", type=str, default="",
        help="Path to a brownfield change-request file override (optional)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    _setup_logging(args.log_level)

    if args.command == "exec":
        exit_code = asyncio.run(_run_exec(args))
        sys.exit(exit_code)
    elif args.command == "harness":
        exit_code = asyncio.run(_run_harness(args))
        sys.exit(exit_code)
    elif args.command == "planning":
        try:
            exit_code = asyncio.run(_run_planning(args))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        sys.exit(exit_code)


async def _run_harness(args: argparse.Namespace) -> int:
    """Run the full harness loop."""
    from cowork_pilot.codex.harness import run_codex_harness
    from cowork_pilot.config import load_config, load_harness_config
    from cowork_pilot.codex.config import load_codex_exec_config

    config_path = Path(args.config)
    base_config = load_config(config_path) if config_path.exists() else None
    exec_config = load_codex_exec_config(config_path)

    # Resolve project dir
    project_dir = args.project_dir or (
        base_config.project_dir if base_config else str(Path.cwd())
    )

    # Resolve exec-plans dir
    if args.exec_plans_dir:
        exec_plans_dir = args.exec_plans_dir
    elif base_config and config_path.exists():
        harness_config = load_harness_config(config_path, base_config)
        exec_plans_dir = str(Path(project_dir) / harness_config.exec_plans_dir)
    else:
        exec_plans_dir = str(Path(project_dir) / "docs" / "exec-plans")

    success = await run_codex_harness(
        exec_plans_dir=exec_plans_dir,
        project_dir=project_dir,
        exec_config=exec_config,
        dry_run=args.dry_run,
    )
    return 0 if success else 1


async def _run_planning(args: argparse.Namespace) -> int:
    from cowork_pilot.config import load_config, load_planning_config
    from cowork_pilot.planning.input_contract import resolve_planning_input_bundle
    from cowork_pilot.planning.models import PlanningContext
    from cowork_pilot.planning.runner import run_planning_pipeline
    from cowork_pilot.planning.storage import bootstrap_run_dir, create_run_id

    base_config = load_config(Path(args.config))
    project_dir = Path(args.project_dir) if args.project_dir else Path(base_config.project_dir)
    planning_config = load_planning_config(Path(args.config))
    run_root = project_dir / planning_config.run_root
    input_bundle = resolve_planning_input_bundle(
        project_dir=project_dir,
        project_mode_arg=getattr(args, "project_mode", ""),
        request_arg=getattr(args, "request", ""),
        request_file_arg=getattr(args, "request_file", ""),
        change_request_arg=getattr(args, "change_request", ""),
        change_request_file_arg=getattr(args, "change_request_file", ""),
    )
    run_id = create_run_id(input_bundle.project_mode.value, "codex-planning")
    run_dir = bootstrap_run_dir(run_root, run_id)
    run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            target_version="codex-planning",
            mode=input_bundle.project_mode,
            explicit_mode=input_bundle.explicit_mode,
            request_text=input_bundle.request_text,
            request_source=input_bundle.request_source,
            change_request_text=input_bundle.change_request_text,
            change_request_source=input_bundle.change_request_source,
        )
    )
    return 0


if __name__ == "__main__":
    cli()
