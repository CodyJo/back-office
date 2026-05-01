"""Tests for backoffice.policy — per-target autonomy gating.

The overnight loop asks `should I do X against repo Y?` dozens of times per
cycle. Today it spawns `python3 -c "..."` inline, re-parsing YAML every time
and interpolating shell strings into Python code.

This module provides a single, testable decision surface:
 - load_autonomy(config, repo) -> Autonomy
 - evaluate_gate(autonomy, gate, context) -> GateDecision
 - a CLI entry point (`python -m backoffice policy ...`) so overnight.sh
   can ask the same questions without inlining YAML parsers.
"""
from __future__ import annotations

import json
import textwrap

import pytest

from backoffice.config import Autonomy, Target, Config
from backoffice.policy import (
    GATES,
    evaluate_gate,
    load_autonomy,
    main as policy_main,
)


# ──────────────────────────────────────────────────────────────────────────────
# load_autonomy
# ──────────────────────────────────────────────────────────────────────────────

def _mk_config(**targets):
    return Config(targets={name: Target(path=path, autonomy=auton)
                           for name, (path, auton) in targets.items()})


def test_load_autonomy_returns_target_policy():
    auton = Autonomy(allow_feature_dev=True, deploy_mode="production-allowed")
    cfg = _mk_config(selah=("/tmp/selah", auton))
    result = load_autonomy(cfg, "selah")
    assert result is auton


def test_load_autonomy_unknown_repo_raises():
    cfg = _mk_config()
    with pytest.raises(KeyError, match="unknown-repo"):
        load_autonomy(cfg, "unknown-repo")


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_gate — explicit, policy-as-data
# ──────────────────────────────────────────────────────────────────────────────

def test_fix_gate_allowed_by_default():
    d = evaluate_gate(Autonomy(), "fix", context={})
    assert d.allow is True
    assert d.reason == "policy:allow_fix"


def test_fix_gate_blocked_when_disabled():
    d = evaluate_gate(Autonomy(allow_fix=False), "fix", context={})
    assert d.allow is False
    assert "allow_fix" in d.reason


def test_feature_gate_blocked_by_default():
    d = evaluate_gate(Autonomy(), "feature_dev", context={})
    assert d.allow is False
    assert "allow_feature_dev" in d.reason


def test_feature_gate_allowed_when_enabled():
    d = evaluate_gate(
        Autonomy(allow_feature_dev=True), "feature_dev", context={}
    )
    assert d.allow is True


def test_auto_merge_gate_blocked_by_default():
    d = evaluate_gate(Autonomy(), "auto_merge", context={})
    assert d.allow is False


def test_deploy_gate_requires_both_allow_and_mode():
    blocked_mode = evaluate_gate(
        Autonomy(allow_auto_deploy=True, deploy_mode="disabled"),
        "deploy",
        context={},
    )
    assert blocked_mode.allow is False
    assert "deploy_mode" in blocked_mode.reason

    blocked_flag = evaluate_gate(
        Autonomy(allow_auto_deploy=False, deploy_mode="production-allowed"),
        "deploy",
        context={},
    )
    assert blocked_flag.allow is False
    assert "allow_auto_deploy" in blocked_flag.reason


def test_deploy_gate_allows_when_both_set():
    d = evaluate_gate(
        Autonomy(allow_auto_deploy=True, deploy_mode="production-allowed"),
        "deploy",
        context={},
    )
    assert d.allow is True


def test_dirty_worktree_blocks_when_required():
    d = evaluate_gate(
        Autonomy(require_clean_worktree=True),
        "fix",
        context={"worktree_clean": False},
    )
    assert d.allow is False
    assert "worktree" in d.reason


def test_dirty_worktree_ignored_when_not_required():
    d = evaluate_gate(
        Autonomy(require_clean_worktree=False),
        "fix",
        context={"worktree_clean": False},
    )
    assert d.allow is True


def test_unknown_gate_raises():
    with pytest.raises(ValueError, match="unknown gate"):
        evaluate_gate(Autonomy(), "rm_rf_slash", context={})


def test_all_registered_gates_are_documented():
    """Registered gates must have a human-readable doc — required for
    execution ledger reason strings."""
    for gate_name, spec in GATES.items():
        assert spec.description, f"gate {gate_name} has no description"


# ──────────────────────────────────────────────────────────────────────────────
# CLI: `python -m backoffice policy <repo> <gate> [--context key=val ...]`
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cli_config(tmp_path, monkeypatch):
    cfg = tmp_path / "backoffice.yaml"
    cfg.write_text(textwrap.dedent("""\
        runner: {command: "codex"}
        deploy: {provider: bunny, bunny: {storage_zone: z}}
        targets:
          shipit:
            path: /tmp/shipit
            autonomy:
              allow_feature_dev: true
              allow_auto_merge: true
              allow_auto_deploy: true
              deploy_mode: production-allowed
          locked:
            path: /tmp/locked
            autonomy:
              allow_fix: false
    """))
    monkeypatch.setenv("BACK_OFFICE_CONFIG", str(cfg))
    return cfg


def test_policy_cli_prints_json_decision(cli_config, capsys):
    rc = policy_main(["shipit", "fix"])
    captured = capsys.readouterr()
    assert rc == 0
    decision = json.loads(captured.out)
    assert decision["allow"] is True
    assert decision["gate"] == "fix"
    assert decision["repo"] == "shipit"


def test_policy_cli_returns_nonzero_when_blocked(cli_config, capsys):
    rc = policy_main(["locked", "fix"])
    captured = capsys.readouterr()
    decision = json.loads(captured.out)
    assert decision["allow"] is False
    assert rc == 1


def test_policy_cli_unknown_repo_returns_2(cli_config, capsys):
    rc = policy_main(["no-such-repo", "fix"])
    assert rc == 2


def test_policy_cli_accepts_context_flags(cli_config, capsys):
    rc = policy_main([
        "shipit", "fix",
        "--context", "worktree_clean=false",
    ])
    captured = capsys.readouterr()
    decision = json.loads(captured.out)
    assert decision["allow"] is False
    assert "worktree" in decision["reason"]
    assert rc == 1
