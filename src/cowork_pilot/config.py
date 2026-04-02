from __future__ import annotations

import os
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
    project_dir: str = ""  # resolved to cwd in __post_init__

    def __post_init__(self):
        if self.codex_args is None:
            self.codex_args = ["-q"]
        if self.claude_args is None:
            self.claude_args = ["-p"]
        if not self.project_dir:
            self.project_dir = os.getcwd()


@dataclass
class HarnessConfig:
    """Harness-specific configuration (loaded from config.toml [harness])."""
    idle_timeout_seconds: float = 30.0
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


@dataclass
class ReviewConfig:
    """Code review configuration (loaded from config.toml [review])."""
    enabled: bool = True
    skip_chunks: list[int] = field(default_factory=list)


@dataclass
class MetaConfig:
    """Meta-agent configuration (loaded from config.toml [meta])."""
    approval_mode: str = "auto"  # "manual" | "auto"
    project_dir: str = ""
    initial_description: str = ""  # CLI에서 전달받는 초기 설명
    brief_template_dir: str = ""   # 기본값: 패키지 내 brief_templates/

    def __post_init__(self):
        if not self.brief_template_dir:
            self.brief_template_dir = str(
                Path(__file__).parent / "brief_templates"
            )


@dataclass
class DocsOrchestratorConfig:
    """Docs-orchestrator configuration (loaded from config.toml [docs_orchestrator])."""
    idle_timeout_seconds: float = 120.0
    completion_poll_interval: float = 5.0
    idle_grace_seconds: float = 30.0
    feature_bundle_threshold_lines: int = 200
    max_bundle_size: int = 2
    coverage_ratio_threshold: float = 0.8
    adaptive_timeout_min: float = 60.0
    adaptive_timeout_max: float = 300.0
    adaptive_timeout_multiplier: float = 1.5
    docs_mode: str = "auto"       # "auto" | "manual"
    manual_override: list[str] = field(default_factory=list)

    # Session timing (기존 HarnessConfig와 동일 패턴)
    session_open_delay: float = 3.0
    session_prompt_delay: float = 1.0
    session_detect_timeout: float = 10.0
    session_detect_poll_interval: float = 1.0

    # Engine (main Config에서 상속)
    engine: str = "claude"
    engine_command: str = "claude"
    engine_args: list[str] = field(default_factory=lambda: ["-p"])


def load_docs_orchestrator_config(
    path: Path, base_config: Config | None = None
) -> DocsOrchestratorConfig:
    """Load docs-orchestrator config from config.toml's [docs_orchestrator] section.

    If ``base_config`` is provided, engine settings are inherited from it.
    """
    orch = DocsOrchestratorConfig()

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

        d = data.get("docs_orchestrator", {})
        orch.idle_timeout_seconds = d.get("idle_timeout_seconds", orch.idle_timeout_seconds)
        orch.completion_poll_interval = d.get("completion_poll_interval", orch.completion_poll_interval)
        orch.idle_grace_seconds = d.get("idle_grace_seconds", orch.idle_grace_seconds)
        orch.feature_bundle_threshold_lines = d.get("feature_bundle_threshold_lines", orch.feature_bundle_threshold_lines)
        orch.max_bundle_size = d.get("max_bundle_size", orch.max_bundle_size)
        orch.coverage_ratio_threshold = d.get("coverage_ratio_threshold", orch.coverage_ratio_threshold)
        orch.adaptive_timeout_min = d.get("adaptive_timeout_min", orch.adaptive_timeout_min)
        orch.adaptive_timeout_max = d.get("adaptive_timeout_max", orch.adaptive_timeout_max)
        orch.adaptive_timeout_multiplier = d.get("adaptive_timeout_multiplier", orch.adaptive_timeout_multiplier)
        orch.docs_mode = d.get("docs_mode", orch.docs_mode)
        orch.manual_override = d.get("manual_override", orch.manual_override)

        ds = d.get("session", {})
        orch.session_open_delay = ds.get("open_delay_seconds", orch.session_open_delay)
        orch.session_prompt_delay = ds.get("prompt_delay_seconds", orch.session_prompt_delay)
        orch.session_detect_timeout = ds.get("detect_timeout_seconds", orch.session_detect_timeout)
        orch.session_detect_poll_interval = ds.get("detect_poll_interval", orch.session_detect_poll_interval)

    # Inherit engine settings from base config
    if base_config is not None:
        orch.engine = base_config.engine
        if base_config.engine == "codex":
            orch.engine_command = base_config.codex_command
            orch.engine_args = base_config.codex_args or ["-q"]
        else:
            orch.engine_command = base_config.claude_command
            orch.engine_args = base_config.claude_args or ["-p"]

    return orch


def load_review_config(path: Path) -> ReviewConfig:
    """Load review config from config.toml's [review] section."""
    if not path.exists():
        return ReviewConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    r = data.get("review", {})
    return ReviewConfig(
        enabled=r.get("enabled", True),
        skip_chunks=r.get("skip_chunks", []),
    )


def load_meta_config(path: Path) -> MetaConfig:
    """Load meta-agent config from config.toml's [meta] section."""
    if not path.exists():
        return MetaConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    m = data.get("meta", {})
    return MetaConfig(
        approval_mode=m.get("approval_mode", "manual"),
        project_dir=m.get("project_dir", ""),
    )


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
        project_dir=data.get("project", {}).get("dir", os.getcwd()),
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
