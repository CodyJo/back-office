"""Tests for detecting drift between the canonical backoffice.yaml
(unified config) and the legacy config/targets.yaml list.

Legacy targets.yaml was the overnight loop's per-target autonomy source.
After unification it becomes deprecated — but while both files exist, we
check for conflicts and surface them to the operator.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backoffice.config import load_config
from backoffice.config_drift import (
    DriftReport,
    detect_drift,
    load_legacy_targets,
)


@pytest.fixture
def unified(tmp_path):
    """Unified config with one target that has explicit autonomy."""
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner: {command: "codex"}
        deploy: {provider: bunny, bunny: {storage_zone: z}}
        targets:
          alpha:
            path: /tmp/alpha
            autonomy:
              allow_feature_dev: true
              deploy_mode: production-allowed
              allow_auto_deploy: true
          beta:
            path: /tmp/beta
    """))
    return cfg


def test_detect_drift_empty_when_no_legacy_file(unified, tmp_path):
    report = detect_drift(load_config(unified), legacy_path=tmp_path / "missing.yaml")
    assert report.ok is True
    assert report.conflicts == []
    assert report.extra_in_legacy == []
    assert report.extra_in_unified == []


def test_detect_drift_flags_target_only_in_legacy(unified, tmp_path):
    legacy = tmp_path / "targets.yaml"
    legacy.write_text(textwrap.dedent("""\
        targets:
          - name: gamma
            path: /tmp/gamma
            autonomy:
              allow_fix: false
    """))
    report = detect_drift(load_config(unified), legacy_path=legacy)
    assert "gamma" in report.extra_in_legacy
    assert report.ok is False


def test_detect_drift_flags_autonomy_field_conflicts(unified, tmp_path):
    legacy = tmp_path / "targets.yaml"
    legacy.write_text(textwrap.dedent("""\
        targets:
          - name: alpha
            path: /tmp/alpha
            autonomy:
              allow_feature_dev: false
              deploy_mode: disabled
    """))
    report = detect_drift(load_config(unified), legacy_path=legacy)
    assert report.ok is False
    # Conflict records include field name and both values
    conflict_fields = {c["field"] for c in report.conflicts if c["target"] == "alpha"}
    assert "allow_feature_dev" in conflict_fields
    assert "deploy_mode" in conflict_fields


def test_detect_drift_ignores_matching_fields(unified, tmp_path):
    legacy = tmp_path / "targets.yaml"
    legacy.write_text(textwrap.dedent("""\
        targets:
          - name: alpha
            path: /tmp/alpha
            autonomy:
              allow_feature_dev: true
              deploy_mode: production-allowed
              allow_auto_deploy: true
    """))
    report = detect_drift(load_config(unified), legacy_path=legacy)
    assert report.conflicts == []
    assert report.ok is True


def test_load_legacy_targets_returns_dict_keyed_by_name(tmp_path):
    legacy = tmp_path / "targets.yaml"
    legacy.write_text(textwrap.dedent("""\
        targets:
          - name: alpha
            path: /tmp/alpha
          - name: beta
            path: /tmp/beta
    """))
    loaded = load_legacy_targets(legacy)
    assert set(loaded.keys()) == {"alpha", "beta"}
    assert loaded["alpha"]["path"] == "/tmp/alpha"
