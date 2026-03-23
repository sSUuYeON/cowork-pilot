from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass
class Config:
    engine: str = "codex"
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
