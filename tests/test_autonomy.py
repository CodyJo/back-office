"""Tests for per-target autonomy policy loaded via the unified config.

The overnight loop reads autonomy policy from config/targets.yaml today
(duplicated from backoffice.yaml). These tests drive the unification:
autonomy becomes a first-class field on Target, loadable from
backoffice.yaml, with conservative defaults matching MASTER-PROMPT.md.
"""
from __future__ import annotations

import textwrap

import pytest

from backoffice.config import (
    Autonomy,
    ConfigError,
    load_config,
)


# ──────────────────────────────────────────────────────────────────────────────
# Autonomy dataclass defaults
# ──────────────────────────────────────────────────────────────────────────────

def test_autonomy_defaults_are_conservative():
    """Defaults must match MASTER-PROMPT.md §Per-Target Autonomy Policy."""
    a = Autonomy()
    assert a.allow_fix is True
    assert a.allow_feature_dev is False
    assert a.allow_auto_commit is True
    assert a.allow_auto_merge is False
    assert a.allow_auto_deploy is False
    assert a.require_clean_worktree is True
    assert a.require_tests is True
    assert a.max_changes_per_cycle == 3
    assert a.deploy_mode == "disabled"


def test_autonomy_is_frozen():
    a = Autonomy()
    with pytest.raises(AttributeError):
        a.allow_fix = False


def test_deploy_mode_accepts_known_values():
    for mode in ("disabled", "manual", "staging-only", "production-allowed"):
        Autonomy(deploy_mode=mode)


def test_deploy_mode_rejects_unknown_values():
    with pytest.raises(ValueError, match="deploy_mode"):
        Autonomy(deploy_mode="yolo")


# ──────────────────────────────────────────────────────────────────────────────
# Autonomy loaded from backoffice.yaml
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def config_with_autonomy(tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner:
          command: "codex"
          mode: stdin-text
        deploy:
          provider: bunny
          bunny:
            storage_zone: test-zone
        targets:
          explicit:
            path: /tmp/explicit
            language: python
            autonomy:
              allow_feature_dev: true
              allow_auto_merge: true
              allow_auto_deploy: true
              deploy_mode: production-allowed
              max_changes_per_cycle: 5
          defaults:
            path: /tmp/defaults
            language: python
    """))
    return cfg


def test_target_carries_autonomy_when_specified(config_with_autonomy):
    cfg = load_config(config_with_autonomy)
    explicit = cfg.targets["explicit"]
    assert explicit.autonomy.allow_feature_dev is True
    assert explicit.autonomy.allow_auto_merge is True
    assert explicit.autonomy.allow_auto_deploy is True
    assert explicit.autonomy.deploy_mode == "production-allowed"
    assert explicit.autonomy.max_changes_per_cycle == 5


def test_target_uses_conservative_defaults_when_autonomy_omitted(config_with_autonomy):
    cfg = load_config(config_with_autonomy)
    defaults = cfg.targets["defaults"]
    assert isinstance(defaults.autonomy, Autonomy)
    assert defaults.autonomy.allow_fix is True
    assert defaults.autonomy.allow_feature_dev is False
    assert defaults.autonomy.allow_auto_deploy is False
    assert defaults.autonomy.deploy_mode == "disabled"


def test_invalid_deploy_mode_in_config_fails_closed(tmp_path):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner: {command: "codex"}
        deploy: {provider: bunny, bunny: {storage_zone: z}}
        targets:
          bad:
            path: /tmp/bad
            autonomy:
              deploy_mode: ship-it-hot
    """))
    with pytest.raises(ConfigError, match="deploy_mode"):
        load_config(cfg)
