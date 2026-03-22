"""Tests for backoffice.setup."""
from __future__ import annotations

import argparse
import shutil
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import backoffice.setup as setup_mod
from backoffice.setup import (
    AGENT_USAGE,
    KNOWN_RUNNERS,
    detect_runner_status,
    ensure_executable,
    load_runner_config_file,
    load_yaml,
    main,
    maybe_copy_file,
    parse_args,
    persist_runner_config,
    print_header,
    summarize_config_state,
    summarize_prereqs,
    summarize_recent_usage,
    summarize_runner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    """Return a Namespace with setup wizard defaults, overriding with kwargs."""
    defaults = dict(
        check_only=False,
        write_missing_configs=False,
        interactive=False,
        list_runners=False,
        activate_runner=None,
        runner_command=None,
        mode=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# KNOWN_RUNNERS / AGENT_USAGE constants
# ---------------------------------------------------------------------------


def test_known_runners_contains_expected_values():
    assert "claude" in KNOWN_RUNNERS
    assert "codex" in KNOWN_RUNNERS
    assert "aider" in KNOWN_RUNNERS


def test_agent_usage_keys_are_shell_scripts():
    for key in AGENT_USAGE:
        assert key.endswith(".sh"), f"Expected .sh suffix: {key}"


def test_agent_usage_has_expected_entries():
    expected = {
        "qa-scan.sh",
        "seo-audit.sh",
        "ada-audit.sh",
        "compliance-audit.sh",
        "monetization-audit.sh",
        "product-audit.sh",
        "fix-bugs.sh",
        "watch.sh",
    }
    assert set(AGENT_USAGE.keys()) == expected


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults():
    args = parse_args([])
    assert args.check_only is False
    assert args.write_missing_configs is False
    assert args.interactive is False
    assert args.list_runners is False
    assert args.activate_runner is None
    assert args.runner_command is None
    assert args.mode is None


def test_parse_args_check_only():
    args = parse_args(["--check-only"])
    assert args.check_only is True


def test_parse_args_activate_runner():
    args = parse_args(["--activate-runner", "codex"])
    assert args.activate_runner == "codex"


def test_parse_args_activate_runner_with_command_and_mode():
    args = parse_args([
        "--activate-runner", "codex",
        "--runner-command", "codex --profile default",
        "--mode", "stdin-text",
    ])
    assert args.activate_runner == "codex"
    assert args.runner_command == "codex --profile default"
    assert args.mode == "stdin-text"


def test_parse_args_list_runners():
    args = parse_args(["--list-runners"])
    assert args.list_runners is True


# ---------------------------------------------------------------------------
# Runner detection — shutil.which checks
# ---------------------------------------------------------------------------


def test_detect_runner_status_returns_available_runners(monkeypatch):
    """detect_runner_status should report runners that shutil.which finds."""
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("claude", "git") else None

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", Path("/nonexistent/backoffice.yaml"))

    runner_cmd, runner_mode, available, file_values = detect_runner_status()
    assert "claude" in available
    assert "codex" not in available
    assert "aider" not in available


def test_detect_runner_status_only_checks_known_runners(monkeypatch):
    """detect_runner_status should only check KNOWN_RUNNERS, not arbitrary binaries."""
    checked = []

    def tracking_which(name):
        checked.append(name)
        return None

    monkeypatch.setattr(shutil, "which", tracking_which)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", Path("/nonexistent/backoffice.yaml"))

    detect_runner_status()
    # Every binary checked must be from KNOWN_RUNNERS (plus possible env lookups)
    for name in checked:
        assert name in KNOWN_RUNNERS, f"Unexpected which() call for: {name}"


def test_detect_runner_status_env_overrides_file(monkeypatch, tmp_path):
    """Environment variables take precedence over config-file values."""
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner:
          command: "aider"
          mode: "stdin-text"
    """))
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    monkeypatch.setenv("BACK_OFFICE_AGENT_RUNNER", "codex")
    monkeypatch.setenv("BACK_OFFICE_AGENT_MODE", "custom-mode")

    runner_cmd, runner_mode, _available, _file_values = detect_runner_status()
    assert runner_cmd == "codex"
    assert runner_mode == "custom-mode"


def test_detect_runner_status_falls_back_to_file(monkeypatch, tmp_path):
    """When no env var is set, detect_runner_status reads from the config file."""
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner:
          command: "aider --model gpt4"
          mode: "stdin-text"
    """))
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)

    runner_cmd, runner_mode, _available, file_values = detect_runner_status()
    assert runner_cmd == "aider --model gpt4"
    assert runner_mode == "stdin-text"
    assert file_values["BACK_OFFICE_AGENT_RUNNER"] == "aider --model gpt4"


def test_detect_runner_status_defaults_when_no_config(monkeypatch):
    """When no config file and no env vars exist, defaults to claude/claude-print."""
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", Path("/nonexistent/backoffice.yaml"))
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)

    runner_cmd, runner_mode, _available, file_values = detect_runner_status()
    assert runner_cmd == "claude"
    assert runner_mode == "claude-print"
    assert file_values == {}


# ---------------------------------------------------------------------------
# load_runner_config_file
# ---------------------------------------------------------------------------


def test_load_runner_config_file_parses_yaml(monkeypatch, tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner:
          command: "codex --profile default"
          mode: "stdin-text"
    """))
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    values = load_runner_config_file()
    assert values["BACK_OFFICE_AGENT_RUNNER"] == "codex --profile default"
    assert values["BACK_OFFICE_AGENT_MODE"] == "stdin-text"


def test_load_runner_config_file_missing_returns_empty(monkeypatch):
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", Path("/nonexistent/backoffice.yaml"))
    values = load_runner_config_file()
    assert values == {}


def test_load_runner_config_file_no_runner_section(monkeypatch, tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text("api:\n  port: 8070\n")
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    values = load_runner_config_file()
    assert values == {}


def test_load_runner_config_file_invalid_yaml(monkeypatch, tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(": : : not valid yaml [")
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    values = load_runner_config_file()
    assert values == {}


# ---------------------------------------------------------------------------
# Config state checking
# ---------------------------------------------------------------------------


def test_summarize_config_state_reports_missing(monkeypatch, tmp_path, capsys):
    """Reports 'missing' when qa-config.yaml and targets.yaml are absent."""
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    args = _make_args()
    summarize_config_state(args)

    captured = capsys.readouterr().out
    assert "qa-config.yaml: missing" in captured
    assert "targets.yaml: missing" in captured


def test_summarize_config_state_reports_present(monkeypatch, tmp_path, capsys):
    """Reports 'present' when config files exist."""
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    (tmp_path / "qa-config.yaml").write_text("dashboard_targets: []\n")
    (tmp_path / "targets.yaml").write_text("targets: []\n")

    args = _make_args()
    summarize_config_state(args)

    captured = capsys.readouterr().out
    assert "qa-config.yaml: present" in captured
    assert "targets.yaml: present" in captured


def test_summarize_config_state_counts_targets(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    (tmp_path / "qa-config.yaml").write_text("dashboard_targets: [{}, {}]\n")
    (tmp_path / "targets.yaml").write_text(textwrap.dedent("""\
        targets:
          - name: alpha
          - name: beta
          - name: gamma
    """))

    args = _make_args()
    summarize_config_state(args)

    captured = capsys.readouterr().out
    assert "Dashboard deploy targets configured: 2" in captured
    assert "Local audit targets configured: 3" in captured
    assert "alpha" in captured
    assert "beta" in captured


def test_summarize_config_state_writes_missing_when_enabled(monkeypatch, tmp_path, capsys):
    """Copies example files when --write-missing-configs is set and examples exist."""
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    (tmp_path / "qa-config.example.yaml").write_text("dashboard_targets: []\n")
    (tmp_path / "targets.example.yaml").write_text("targets: []\n")

    args = _make_args(write_missing_configs=True)
    summarize_config_state(args)

    assert (tmp_path / "qa-config.yaml").exists()
    assert (tmp_path / "targets.yaml").exists()

    captured = capsys.readouterr().out
    assert "Created config/qa-config.yaml from example" in captured
    assert "Created config/targets.yaml from example" in captured


def test_summarize_config_state_check_only_does_not_write(monkeypatch, tmp_path):
    """check_only=True must not create any files even with write_missing_configs."""
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    (tmp_path / "qa-config.example.yaml").write_text("dashboard_targets: []\n")
    (tmp_path / "targets.example.yaml").write_text("targets: []\n")

    args = _make_args(check_only=True, write_missing_configs=True)
    summarize_config_state(args)

    assert not (tmp_path / "qa-config.yaml").exists()
    assert not (tmp_path / "targets.yaml").exists()


# ---------------------------------------------------------------------------
# Prerequisite summarization
# ---------------------------------------------------------------------------


def test_summarize_prereqs_all_found(monkeypatch, capsys):
    def fake_which(name):
        return f"/usr/bin/{name}"

    monkeypatch.setattr(shutil, "which", fake_which)

    result = summarize_prereqs()
    captured = capsys.readouterr().out

    assert "git: found" in captured
    assert "python3: found" in captured
    assert "aws: found" in captured
    assert "PyYAML: found" in captured
    assert result is True


def test_summarize_prereqs_missing_binary(monkeypatch, capsys):
    def fake_which(name):
        if name == "aws":
            return None
        return f"/usr/bin/{name}"

    monkeypatch.setattr(shutil, "which", fake_which)

    result = summarize_prereqs()
    captured = capsys.readouterr().out

    assert "aws: missing" in captured
    assert result is False


def test_summarize_prereqs_all_missing(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = summarize_prereqs()
    captured = capsys.readouterr().out

    assert "git: missing" in captured
    assert "python3: missing" in captured
    assert "aws: missing" in captured
    assert result is False


def test_summarize_prereqs_shows_install_hint(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    summarize_prereqs()
    captured = capsys.readouterr().out
    assert "pip3 install" in captured


# ---------------------------------------------------------------------------
# Runner config persistence — writes to backoffice.yaml
# ---------------------------------------------------------------------------


def test_persist_runner_config_creates_yaml(monkeypatch, tmp_path):
    """persist_runner_config writes runner section to backoffice.yaml."""
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("claude", None, None)

    assert cfg_path.exists()
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["command"] == "claude"
    assert raw["runner"]["mode"] == "claude-print"


def test_persist_runner_config_codex_gets_stdin_text_mode(monkeypatch, tmp_path):
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("codex", None, None)

    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["mode"] == "stdin-text"


def test_persist_runner_config_explicit_mode(monkeypatch, tmp_path):
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("aider", "aider --model gpt4", "custom-mode")

    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["command"] == "aider --model gpt4"
    assert raw["runner"]["mode"] == "custom-mode"


def test_persist_runner_config_preserves_existing_sections(monkeypatch, tmp_path):
    """persist_runner_config should preserve non-runner sections of backoffice.yaml."""
    cfg_path = tmp_path / "backoffice.yaml"
    cfg_path.write_text(textwrap.dedent("""\
        runner:
          command: old-runner
          mode: old-mode
        api:
          port: 9090
          api_key: "my-key"
    """))
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("claude", None, None)

    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["command"] == "claude"
    assert raw["api"]["port"] == 9090
    assert raw["api"]["api_key"] == "my-key"


def test_persist_runner_config_uses_example_when_no_config(monkeypatch, tmp_path):
    """When backoffice.yaml is absent, fall back to example template."""
    cfg_path = tmp_path / "backoffice.yaml"
    example_path = tmp_path / "backoffice.example.yaml"
    example_path.write_text(textwrap.dedent("""\
        runner:
          command: "claude --model haiku"
          mode: "claude-print"
        api:
          port: 8070
    """))
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("codex", None, None)

    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["command"] == "codex"
    assert raw["api"]["port"] == 8070


def test_persist_runner_config_raises_when_binary_missing(monkeypatch, tmp_path):
    """SystemExit raised when the requested runner binary is not on PATH."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", tmp_path / "backoffice.yaml")
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    with pytest.raises(SystemExit, match="Runner binary not found"):
        persist_runner_config("claude", None, None)


def test_persist_runner_config_does_not_write_env_format(monkeypatch, tmp_path):
    """The output must be YAML, not the old KEY=VALUE env format."""
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("claude", None, None)

    content = cfg_path.read_text()
    assert "BACK_OFFICE_AGENT_RUNNER=" not in content
    assert "BACK_OFFICE_AGENT_MODE=" not in content


def test_persist_runner_config_prints_summary(monkeypatch, tmp_path, capsys):
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    persist_runner_config("claude", "claude --model haiku", "claude-print")

    captured = capsys.readouterr().out
    assert "Runner Updated" in captured
    assert "claude --model haiku" in captured
    assert "claude-print" in captured


# ---------------------------------------------------------------------------
# load_yaml
# ---------------------------------------------------------------------------


def test_load_yaml_returns_dict(tmp_path):
    f = tmp_path / "data.yaml"
    f.write_text("key: value\nlist:\n  - a\n  - b\n")
    result = load_yaml(f)
    assert result == {"key": "value", "list": ["a", "b"]}


def test_load_yaml_missing_returns_empty(tmp_path):
    result = load_yaml(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_load_yaml_empty_file_returns_empty(tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("")
    result = load_yaml(f)
    assert result == {}


# ---------------------------------------------------------------------------
# maybe_copy_file
# ---------------------------------------------------------------------------


def test_maybe_copy_file_copies_when_enabled(tmp_path):
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"
    src.write_text("hello")

    result = maybe_copy_file(src, dst, enabled=True, interactive=False)

    assert result is True
    assert dst.read_text() == "hello"


def test_maybe_copy_file_skips_when_disabled(tmp_path):
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"
    src.write_text("hello")

    result = maybe_copy_file(src, dst, enabled=False, interactive=False)

    assert result is False
    assert not dst.exists()


def test_maybe_copy_file_skips_when_dest_exists(tmp_path):
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"
    src.write_text("new content")
    dst.write_text("existing content")

    result = maybe_copy_file(src, dst, enabled=True, interactive=False)

    assert result is False
    assert dst.read_text() == "existing content"


# ---------------------------------------------------------------------------
# summarize_runner
# ---------------------------------------------------------------------------


def test_summarize_runner_shows_active_runner(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text("runner:\n  command: codex\n  mode: stdin-text\n")
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "codex" else None)

    result = summarize_runner()

    captured = capsys.readouterr().out
    assert "Active runner command: codex" in captured
    assert "Runner mode: stdin-text" in captured
    assert result is True


def test_summarize_runner_returns_false_when_binary_missing(monkeypatch, tmp_path, capsys):
    # RUNNER_CONFIG must be under ROOT so relative_to() succeeds
    cfg_path = tmp_path / "config" / "backoffice.yaml"
    (tmp_path / "config").mkdir(parents=True)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = summarize_runner()

    assert result is False
    captured = capsys.readouterr().out
    assert "Active runner binary found: no" in captured


# ---------------------------------------------------------------------------
# summarize_recent_usage
# ---------------------------------------------------------------------------


def test_summarize_recent_usage_no_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    summarize_recent_usage()
    captured = capsys.readouterr().out
    assert "No local-audit-log.json found" in captured


def test_summarize_recent_usage_with_runs(monkeypatch, tmp_path, capsys):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    audit_log = results_dir / "local-audit-log.json"
    audit_log.write_text(textwrap.dedent("""\
        recent_runs:
          - repo_name: my-project
            status: completed
            jobs:
              qa:
                status: ok
                findings_count: 3
                elapsed_seconds: 12
                agent_runner: claude
                agent_mode: claude-print
    """))
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    summarize_recent_usage()
    captured = capsys.readouterr().out

    assert "Recorded recent runs: 1" in captured
    assert "my-project" in captured
    assert "completed" in captured
    assert "findings=3" in captured


def test_summarize_recent_usage_empty_runs(monkeypatch, tmp_path, capsys):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "local-audit-log.json").write_text("recent_runs: []\n")
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)

    summarize_recent_usage()
    captured = capsys.readouterr().out

    assert "Recorded recent runs: 0" in captured
    assert "audit-all" in captured


# ---------------------------------------------------------------------------
# print_header
# ---------------------------------------------------------------------------


def test_print_header_outputs_title_and_underline(capsys):
    print_header("Test Section")
    captured = capsys.readouterr().out
    assert "Test Section" in captured
    assert "-" * len("Test Section") in captured


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", tmp_path / "backoffice.yaml")
    monkeypatch.setattr(setup_mod, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(setup_mod, "PROMPTS_DIR", tmp_path / "agents" / "prompts")
    monkeypatch.setattr(setup_mod, "SCRIPTS_DIR", tmp_path / "scripts")
    monkeypatch.setattr(setup_mod, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)

    (tmp_path / "agents").mkdir()
    (tmp_path / "scripts").mkdir()

    result = main(["--check-only"])
    assert result == 0


def test_main_list_runners_returns_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", tmp_path / "backoffice.yaml")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("BACK_OFFICE_AGENT_RUNNER", raising=False)
    monkeypatch.delenv("BACK_OFFICE_AGENT_MODE", raising=False)

    result = main(["--list-runners"])
    assert result == 0
    captured = capsys.readouterr().out
    assert "Back Office Setup" in captured


def test_main_activate_runner_returns_zero(monkeypatch, tmp_path, capsys):
    cfg_path = tmp_path / "backoffice.yaml"
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", cfg_path)
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    result = main(["--activate-runner", "claude"])
    assert result == 0

    raw = yaml.safe_load(cfg_path.read_text()) or {}
    assert raw["runner"]["command"] == "claude"


def test_main_activate_runner_missing_binary_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_mod, "RUNNER_CONFIG", tmp_path / "backoffice.yaml")
    monkeypatch.setattr(setup_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(SystemExit):
        main(["--activate-runner", "claude"])
