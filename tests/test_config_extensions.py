"""Tests for production-readiness: agents/routines/budgets/plugins config blocks."""
from __future__ import annotations

from pathlib import Path


from backoffice.config import load_config, validate_extensions


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


_BASE = """\
runner:
  command: "claude"
  mode: "claude-print"

deploy:
  provider: bunny
  bunny:
    storage_zone: "x"

targets:
  back-office:
    path: /tmp/x
    language: python

"""


def test_load_config_with_agents_dict_form(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
agents:
  fix-agent:
    role: fixer
    adapter_type: process
""",
    )
    config = load_config(cfg)
    assert len(config.agents) == 1
    assert config.agents[0]["name"] == "fix-agent"
    assert config.agents[0]["role"] == "fixer"


def test_load_config_with_agents_list_form(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
agents:
  - name: fix-agent
    role: fixer
""",
    )
    config = load_config(cfg)
    assert config.agents[0]["name"] == "fix-agent"


def test_load_config_with_routines(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
routines:
  hourly-audit:
    name: Hourly portfolio audit
    trigger_kind: cron
    trigger:
      interval_seconds: 3600
    action_kind: noop
""",
    )
    config = load_config(cfg)
    assert len(config.routines) == 1
    assert config.routines[0]["id"] == "hourly-audit"
    assert config.routines[0]["trigger_kind"] == "cron"


def test_load_config_with_budgets(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
budgets:
  - id: global-cap
    scope: global
    soft_limit_usd: 50
    hard_limit_usd: 100
""",
    )
    config = load_config(cfg)
    assert config.budgets[0]["scope"] == "global"
    assert config.budgets[0]["hard_limit_usd"] == 100


def test_load_config_with_plugins(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
plugins:
  - name: sample-plugin
    extension_point: adapter
    path: /opt/plugins/sample.py
    attribute: SampleAdapter
""",
    )
    config = load_config(cfg)
    assert config.plugins[0]["name"] == "sample-plugin"


def test_default_extensions_are_empty(tmp_path: Path):
    cfg = _write(tmp_path / "config.yaml", _BASE)
    config = load_config(cfg)
    assert config.agents == []
    assert config.routines == []
    assert config.budgets == []
    assert config.plugins == []


def test_garbage_extension_entries_are_dropped(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
agents:
  - "not-a-mapping"
  - name: good
    role: fixer
""",
    )
    config = load_config(cfg)
    assert [a["name"] for a in config.agents] == ["good"]


# ──────────────────────────────────────────────────────────────────────
# validate_extensions()
# ──────────────────────────────────────────────────────────────────────


def test_validate_extensions_passes_clean_config(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
routines:
  - id: r1
    name: x
    trigger_kind: manual
    action_kind: noop
budgets:
  - id: b1
    scope: global
    soft_limit_usd: 1
""",
    )
    config = load_config(cfg)
    assert validate_extensions(config) == []


def test_validate_extensions_catches_invalid_routine(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
routines:
  - id: bad
    trigger_kind: not-a-kind
""",
    )
    config = load_config(cfg)
    errors = validate_extensions(config)
    assert any("bad" in e for e in errors)


def test_validate_extensions_catches_invalid_budget(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
budgets:
  - id: bad
    scope: not-a-scope
""",
    )
    config = load_config(cfg)
    errors = validate_extensions(config)
    assert any("bad" in e for e in errors)


def test_validate_extensions_catches_invalid_agent_role(tmp_path: Path):
    cfg = _write(
        tmp_path / "config.yaml",
        _BASE
        + """\
agents:
  - name: weird
    role: nope
""",
    )
    config = load_config(cfg)
    errors = validate_extensions(config)
    assert any("weird" in e for e in errors)
