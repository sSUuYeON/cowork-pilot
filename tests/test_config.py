from pathlib import Path
from cowork_pilot.config import Config, load_config


def test_config_defaults():
    config = Config()
    assert config.engine == "codex"
    assert config.debounce_seconds == 2.0
    assert config.max_retries == 3
    assert config.post_verify_timeout_seconds == 10.0


def test_load_config_from_toml(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("""
[engine]
default = "claude"

[watcher]
debounce_seconds = 3.0

[responder]
max_retries = 5
post_verify_timeout_seconds = 15.0
""")
    config = load_config(toml_path)
    assert config.engine == "claude"
    assert config.debounce_seconds == 3.0
    assert config.max_retries == 5


def test_load_config_missing_file():
    config = load_config(Path("/nonexistent/config.toml"))
    assert config.engine == "codex"  # falls back to defaults
