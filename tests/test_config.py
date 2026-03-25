from pathlib import Path
from cowork_pilot.config import Config, load_config


def test_config_defaults():
    config = Config()
    assert config.engine == "claude"
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
    assert config.engine == "claude"  # falls back to defaults


from cowork_pilot.config import MetaConfig, load_meta_config


class TestMetaConfig:
    def test_defaults(self):
        mc = MetaConfig()
        assert mc.approval_mode == "manual"
        assert mc.project_dir == ""
        assert mc.initial_description == ""
        assert mc.brief_template_dir != ""

    def test_load_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[meta]\n'
            'approval_mode = "auto"\n'
            'project_dir = "/tmp/my-project"\n'
        )
        mc = load_meta_config(toml_file)
        assert mc.approval_mode == "auto"
        assert mc.project_dir == "/tmp/my-project"

    def test_load_missing_file(self, tmp_path):
        mc = load_meta_config(tmp_path / "nonexistent.toml")
        assert mc.approval_mode == "manual"
