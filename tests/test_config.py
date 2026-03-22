"""Tests for backoffice.config."""
import os
import textwrap
from pathlib import Path

import pytest

from backoffice.config import (
    Config,
    ConfigError,
    Target,
    load_config,
    shell_export,
    is_shell_safe,
)


@pytest.fixture
def minimal_config(tmp_path):
    """Write a minimal valid config file and return its path."""
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner:
          command: "claude --model haiku"
          mode: claude-print
        api:
          port: 8070
          api_key: ""
          allowed_origins: []
        deploy:
          provider: aws
          aws:
            region: us-west-2
            dashboard_targets: []
        scan:
          max_findings: 200
        fix:
          auto_commit: true
        notifications:
          sync_to_s3: true
        targets:
          demo:
            path: /tmp/demo
            language: python
            default_departments: [qa]
    """))
    return cfg


def test_load_config_returns_frozen_config(minimal_config):
    cfg = load_config(minimal_config)
    assert isinstance(cfg, Config)
    assert cfg.runner.command == "claude --model haiku"
    assert cfg.runner.mode == "claude-print"


def test_target_has_defaults(minimal_config):
    cfg = load_config(minimal_config)
    t = cfg.targets["demo"]
    assert isinstance(t, Target)
    assert t.lint_command == ""
    assert t.deploy_command == ""
    assert t.context == ""


def test_config_is_frozen(minimal_config):
    cfg = load_config(minimal_config)
    with pytest.raises(AttributeError):
        cfg.runner = None


def test_missing_config_raises():
    with pytest.raises(ConfigError, match="Config not found"):
        load_config(Path("/nonexistent/backoffice.yaml"))


def test_malformed_yaml_raises(tmp_path):
    bad = tmp_path / "backoffice.yaml"
    bad.write_text(": : : not valid yaml [")
    with pytest.raises(ConfigError, match="malformed"):
        load_config(bad)


def test_missing_required_field_raises(tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text("runner:\n  command: claude\n")
    with pytest.raises(ConfigError, match="missing"):
        load_config(cfg)


def test_nonexistent_target_path_warns(minimal_config, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="backoffice"):
        load_config(minimal_config)
    assert any("/tmp/demo" in r.message for r in caplog.records)


def test_back_office_root_override(minimal_config, monkeypatch):
    monkeypatch.setenv("BACK_OFFICE_ROOT", "/custom/root")
    cfg = load_config(minimal_config)
    assert cfg.root == Path("/custom/root")


def test_shell_export_runner_vars(minimal_config):
    cfg = load_config(minimal_config)
    output = shell_export(cfg)
    assert 'BACK_OFFICE_AGENT_RUNNER="claude --model haiku"' in output
    assert 'BACK_OFFICE_AGENT_MODE="claude-print"' in output


def test_shell_export_target_fields(minimal_config):
    cfg = load_config(minimal_config)
    output = shell_export(cfg, target_name="demo", fields=["path", "language"])
    parts = output.split("\0")
    assert parts[0] == "/tmp/demo"
    assert parts[1] == "python"


def test_shell_export_rejects_unsafe_values(tmp_path):
    assert is_shell_safe("/tmp/demo") is True
    assert is_shell_safe("echo $(whoami)") is False
    assert is_shell_safe("safe-value") is True
    assert is_shell_safe("rm; cat /etc/passwd") is False


def test_shell_export_missing_target(minimal_config):
    cfg = load_config(minimal_config)
    output = shell_export(cfg, target_name="nonexistent", fields=["path"])
    assert output == ""
