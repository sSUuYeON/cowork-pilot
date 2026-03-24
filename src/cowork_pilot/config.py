from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass
class Config:
    engine: str = "claude"
    codex_command: str = "codex"
    codex_args: list[str] | None = None
    claude_command: str = "claude"
    claude_args: list[str] | None = None
    debounce_seconds: float = 2.0
    poll_interval_seconds: float = 0.5
    post_verify_timeout_seconds: float = 10.0
    max_retries: int = 3
    activate_delay_seconds: float = 0.3
    session_base_path: str = "~/Library/Application Support/Claude/local-agent-mode-sessions"
    log_path: str = "logs/cowork-pilot.jsonl"
    log_level: str = "INFO"
    project_dir: str = "."

    def __post_init__(self):
        if self.codex_args is None:
            self.codex_args = ["-q"]
        if self.claude_args is None:
            self.claude_args = ["-p"]


@dataclass
class HarnessConfig:
    """Harness-specific configuration (loaded from config.toml [harness])."""
    idle_timeout_seconds: float = 120.0
    completion_check_max_retries: int = 3
    incomplete_retry_max: int = 3
    exec_plans_dir: str = "docs/exec-plans"

    # Session timing
    session_open_delay: float = 3.0
    session_prompt_delay: float = 1.0
    session_detect_timeout: float = 10.0
    session_detect_poll_interval: float = 1.0

    # Engine for CLI verification (inherits from main Config)
    engine: str = "claude"
    engine_command: str = "claude"
    engine_args: list[str] = field(default_factory=lambda: ["-p"])


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return Config(
        engine=data.get("engine", {}).get("default", "codex"),
        codex_command=data.get("engine", {}).get("codex", {}).get("command", "codex"),
        codex_args=data.get("engine", {}).get("codex", {}).get("args"),
        claude_command=data.get("engine", {}).get("claude", {}).get("command", "claude"),
        claude_args=data.get("engine", {}).get("claude", {}).get("args"),
        debounce_seconds=data.get("watcher", {}).get("debounce_seconds", 2.0),
        poll_interval_seconds=data.get("watcher", {}).get("poll_interval_seconds", 0.5),
        post_verify_timeout_seconds=data.get("responder", {}).get("post_verify_timeout_seconds", 10.0),
        max_retries=data.get("responder", {}).get("max_retries", 3),
        activate_delay_seconds=data.get("responder", {}).get("activate_delay_seconds", 0.3),
        session_base_path=data.get("session", {}).get("base_path", "~/Library/Application Support/Claude/local-agent-mode-sessions"),
        log_path=data.get("logging", {}).get("path", "logs/cowork-pilot.jsonl"),
        log_level=data.get("logging", {}).get("level", "INFO"),
    )


def load_harness_config(path: Path, base_config: Config | None = None) -> HarnessConfig:
    """Load harness-specific config from config.toml's [harness] section.

    If ``base_config`` is provided, engine settings are inherited from it.
    """
    harness = HarnessConfig()

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

        h = data.get("harness", {})
        harness.idle_timeout_seconds = h.get("idle_timeout_seconds", harness.idle_timeout_seconds)
        harness.completion_check_max_retries = h.get("completion_check_max_retries", harness.completion_check_max_retries)
        harness.incomplete_retry_max = h.get("incomplete_retry_max", harness.incomplete_retry_max)
        harness.exec_plans_dir = h.get("exec_plans_dir", harness.exec_plans_dir)

        hs = h.get("session", {})
        harness.session_open_delay = hs.get("open_delay_seconds", harness.session_open_delay)
        harness.session_prompt_delay = hs.get("prompt_delay_seconds", harness.session_prompt_delay)
        harness.session_detect_timeout = hs.get("detect_timeout_seconds", harness.session_detect_timeout)
        harness.session_detect_poll_interval = hs.get("detect_poll_interval", harness.session_detect_poll_interval)

    # Inherit engine settings from base config
    if base_config is not None:
        harness.engine = base_config.engine
        if base_config.engine == "codex":
            harness.engine_command = base_config.codex_command
            harness.engine_args = base_config.codex_args or ["-q"]
        else:
            harness.engine_command = base_config.claude_command
            harness.engine_args = base_config.claude_args or ["-p"]

    return harness
