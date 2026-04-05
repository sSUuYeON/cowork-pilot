"""Codex-specific configuration, loaded from config.toml's [codex] section.

Follows the same pattern as the base config module but lives in the
codex package to avoid touching existing code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class CodexExecConfig:
    """Configuration for ``codex exec`` plan execution."""
    command: str = "codex"
    extra_args: list[str] = field(default_factory=list)
    build_timeout_seconds: float = 3000.0
    stalled_output_timeout_seconds: float = 600.0
    max_retries: int = 3
    build_repair_max_retries: int = 3


def load_codex_exec_config(path: Path) -> CodexExecConfig:
    """Load ``[codex.exec]`` section from config.toml.

    Falls back to [engine.codex] for the command if [codex.exec]
    is not present, maintaining backward compatibility.
    """
    cfg = CodexExecConfig()

    if not path.exists():
        return cfg

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Primary: [codex.exec] section
    codex_section = data.get("codex", {})
    exec_section = codex_section.get("exec", {})

    if exec_section:
        cfg.command = exec_section.get("command", cfg.command)
        cfg.extra_args = exec_section.get("args", cfg.extra_args)
        cfg.build_timeout_seconds = exec_section.get(
            "build_timeout_seconds", cfg.build_timeout_seconds
        )
        cfg.stalled_output_timeout_seconds = exec_section.get(
            "stalled_output_timeout_seconds",
            cfg.stalled_output_timeout_seconds,
        )
        cfg.max_retries = exec_section.get("max_retries", cfg.max_retries)
        cfg.build_repair_max_retries = exec_section.get(
            "build_repair_max_retries", cfg.build_repair_max_retries
        )
    else:
        # Fallback: [engine.codex] for the command name
        engine_codex = data.get("engine", {}).get("codex", {})
        if engine_codex:
            cfg.command = engine_codex.get("command", cfg.command)

    return cfg
