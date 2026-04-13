from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass
class AutoAnswerConfig:
    """Runtime config for docs-orchestrator auto-answer."""

    enabled: bool = False
    phase2_only: bool = True
    engine: str = "codex"
    engine_command: str = "codex"
    engine_args: list[str] = field(default_factory=list)
    timeout_seconds: float = 90.0
    max_attempts_per_event: int = 2
    max_rounds_per_run: int = 100
    escalate_mode: str = "auto"
    conflict_resolver_enabled: bool = True
    max_conflict_resolver_attempts: int = 1
    allow_escalate: bool = True
    claude_max_chars: int = 120_000

    allowed_question_types: frozenset[str] = frozenset({"INPUT_REQUIRED"})
    require_single_select: bool = True


def load_auto_answer_config(
    config_path: Path,
    base_engine: str = "codex",
    base_engine_command: str = "codex",
    base_engine_args: list[str] | None = None,
) -> AutoAnswerConfig:
    """Load ``[docs_orchestrator.auto_answer]`` from ``config.toml``."""

    cfg = AutoAnswerConfig()

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        auto_answer = data.get("docs_orchestrator", {}).get("auto_answer", {})
        cfg.enabled = auto_answer.get("enabled", cfg.enabled)
        cfg.phase2_only = auto_answer.get("phase2_only", cfg.phase2_only)
        cfg.engine = auto_answer.get("engine", base_engine)
        cfg.engine_command = auto_answer.get(
            "engine_command", base_engine_command,
        )
        cfg.engine_args = auto_answer.get("engine_args", base_engine_args or [])
        cfg.timeout_seconds = auto_answer.get(
            "timeout_seconds", cfg.timeout_seconds,
        )
        cfg.max_attempts_per_event = auto_answer.get(
            "max_attempts_per_event", cfg.max_attempts_per_event,
        )
        cfg.max_rounds_per_run = auto_answer.get(
            "max_rounds_per_run", cfg.max_rounds_per_run,
        )
        cfg.escalate_mode = auto_answer.get(
            "escalate_mode", cfg.escalate_mode,
        )
        cfg.conflict_resolver_enabled = auto_answer.get(
            "conflict_resolver_enabled", cfg.conflict_resolver_enabled,
        )
        cfg.max_conflict_resolver_attempts = auto_answer.get(
            "max_conflict_resolver_attempts",
            cfg.max_conflict_resolver_attempts,
        )
        cfg.allow_escalate = auto_answer.get(
            "allow_escalate", cfg.allow_escalate,
        )
        cfg.claude_max_chars = auto_answer.get(
            "claude_max_chars", cfg.claude_max_chars,
        )

    return cfg
