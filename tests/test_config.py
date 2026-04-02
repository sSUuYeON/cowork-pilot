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


from cowork_pilot.config import (
    MetaConfig, load_meta_config,
    ReviewConfig, load_review_config,
    DocsOrchestratorConfig, load_docs_orchestrator_config,
)


class TestReviewConfig:
    def test_defaults(self):
        rc = ReviewConfig()
        assert rc.enabled is True
        assert rc.skip_chunks == []

    def test_load_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[review]\n'
            'enabled = false\n'
            'skip_chunks = [1, 5]\n'
        )
        rc = load_review_config(toml_file)
        assert rc.enabled is False
        assert rc.skip_chunks == [1, 5]

    def test_load_missing_file(self, tmp_path):
        rc = load_review_config(tmp_path / "nonexistent.toml")
        assert rc.enabled is True
        assert rc.skip_chunks == []

    def test_load_missing_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[engine]\ndefault = "claude"\n')
        rc = load_review_config(toml_file)
        assert rc.enabled is True


class TestMetaConfig:
    def test_defaults(self):
        mc = MetaConfig()
        assert mc.approval_mode == "auto"
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
        assert mc.approval_mode == "auto"


class TestDocsOrchestratorConfig:
    def test_defaults(self):
        oc = DocsOrchestratorConfig()
        assert oc.idle_timeout_seconds == 120.0
        assert oc.completion_poll_interval == 5.0
        assert oc.idle_grace_seconds == 30.0
        assert oc.feature_bundle_threshold_lines == 200
        assert oc.max_bundle_size == 2
        assert oc.coverage_ratio_threshold == 0.8
        assert oc.adaptive_timeout_min == 60.0
        assert oc.adaptive_timeout_max == 300.0
        assert oc.adaptive_timeout_multiplier == 1.5
        assert oc.docs_mode == "auto"
        assert oc.manual_override == []
        assert oc.engine == "claude"
        assert oc.engine_args == ["-p"]
        assert oc.session_open_delay == 3.0

    def test_load_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[docs_orchestrator]\n'
            'idle_timeout_seconds = 180.0\n'
            'completion_poll_interval = 10.0\n'
            'feature_bundle_threshold_lines = 300\n'
            'max_bundle_size = 3\n'
            'coverage_ratio_threshold = 0.9\n'
            'adaptive_timeout_min = 90.0\n'
            'adaptive_timeout_max = 600.0\n'
            'adaptive_timeout_multiplier = 2.0\n'
            'docs_mode = "manual"\n'
            'manual_override = ["payment", "auth"]\n'
        )
        oc = load_docs_orchestrator_config(toml_file)
        assert oc.idle_timeout_seconds == 180.0
        assert oc.completion_poll_interval == 10.0
        assert oc.feature_bundle_threshold_lines == 300
        assert oc.max_bundle_size == 3
        assert oc.coverage_ratio_threshold == 0.9
        assert oc.adaptive_timeout_min == 90.0
        assert oc.adaptive_timeout_max == 600.0
        assert oc.adaptive_timeout_multiplier == 2.0
        assert oc.docs_mode == "manual"
        assert oc.manual_override == ["payment", "auth"]

    def test_load_missing_file(self, tmp_path):
        oc = load_docs_orchestrator_config(tmp_path / "nonexistent.toml")
        assert oc.idle_timeout_seconds == 120.0
        assert oc.docs_mode == "auto"

    def test_load_missing_section(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[engine]\ndefault = "claude"\n')
        oc = load_docs_orchestrator_config(toml_file)
        assert oc.idle_timeout_seconds == 120.0

    def test_engine_inheritance_from_base_config(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[docs_orchestrator]\n')
        base = Config(engine="codex", codex_command="/usr/bin/codex", codex_args=["-q", "--fast"])
        oc = load_docs_orchestrator_config(toml_file, base_config=base)
        assert oc.engine == "codex"
        assert oc.engine_command == "/usr/bin/codex"
        assert oc.engine_args == ["-q", "--fast"]

    def test_session_timing_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[docs_orchestrator]\n'
            '[docs_orchestrator.session]\n'
            'open_delay_seconds = 5.0\n'
            'prompt_delay_seconds = 2.0\n'
            'detect_timeout_seconds = 15.0\n'
            'detect_poll_interval = 2.0\n'
        )
        oc = load_docs_orchestrator_config(toml_file)
        assert oc.session_open_delay == 5.0
        assert oc.session_prompt_delay == 2.0
        assert oc.session_detect_timeout == 15.0
        assert oc.session_detect_poll_interval == 2.0
