"""Per-target autonomy policy evaluation.

Single decision surface used by both Python orchestration code and shell
scripts (via `python -m backoffice policy ...`).

Gates are declared as data, not branches, so:
 - the overnight loop can call `evaluate_gate(autonomy, "deploy", ctx)`
   instead of manually combining two booleans plus a string;
 - the CLI can expose every gate uniformly without per-gate plumbing;
 - the execution ledger can log structured reason codes
   (e.g. `block:allow_feature_dev`) rather than free-form strings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backoffice.config import Autonomy, Config, load_config


@dataclass(frozen=True)
class GateDecision:
    gate: str
    allow: bool
    reason: str
    repo: str = ""

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "allow": self.allow,
            "reason": self.reason,
            "repo": self.repo,
        }


@dataclass(frozen=True)
class GateSpec:
    description: str
    decide: Callable[[Autonomy, dict], GateDecision]


def _fix_gate(a: Autonomy, ctx: dict) -> GateDecision:
    if not a.allow_fix:
        return GateDecision("fix", False, "block:allow_fix=false")
    if a.require_clean_worktree and ctx.get("worktree_clean") is False:
        return GateDecision("fix", False, "block:worktree_dirty")
    return GateDecision("fix", True, "policy:allow_fix")


def _feature_gate(a: Autonomy, ctx: dict) -> GateDecision:
    if not a.allow_feature_dev:
        return GateDecision("feature_dev", False, "block:allow_feature_dev=false")
    if a.require_clean_worktree and ctx.get("worktree_clean") is False:
        return GateDecision("feature_dev", False, "block:worktree_dirty")
    return GateDecision("feature_dev", True, "policy:allow_feature_dev")


def _merge_gate(a: Autonomy, ctx: dict) -> GateDecision:
    if not a.allow_auto_merge:
        return GateDecision("auto_merge", False, "block:allow_auto_merge=false")
    return GateDecision("auto_merge", True, "policy:allow_auto_merge")


def _deploy_gate(a: Autonomy, ctx: dict) -> GateDecision:
    if not a.allow_auto_deploy:
        return GateDecision("deploy", False, "block:allow_auto_deploy=false")
    if a.deploy_mode == "disabled":
        return GateDecision("deploy", False, "block:deploy_mode=disabled")
    return GateDecision("deploy", True, f"policy:deploy_mode={a.deploy_mode}")


def _commit_gate(a: Autonomy, ctx: dict) -> GateDecision:
    if not a.allow_auto_commit:
        return GateDecision("auto_commit", False, "block:allow_auto_commit=false")
    return GateDecision("auto_commit", True, "policy:allow_auto_commit")


GATES: dict[str, GateSpec] = {
    "fix": GateSpec(
        "Run the fix agent against a repo (requires allow_fix).",
        _fix_gate,
    ),
    "feature_dev": GateSpec(
        "Run the feature-dev agent (requires allow_feature_dev; off by default).",
        _feature_gate,
    ),
    "auto_merge": GateSpec(
        "Automatically merge a feature branch to default (off by default).",
        _merge_gate,
    ),
    "auto_commit": GateSpec(
        "Commit agent-authored changes (on by default).",
        _commit_gate,
    ),
    "deploy": GateSpec(
        "Run the deploy command (requires allow_auto_deploy AND "
        "deploy_mode != disabled).",
        _deploy_gate,
    ),
}


def load_autonomy(config: Config, repo: str) -> Autonomy:
    target = config.targets.get(repo)
    if target is None:
        raise KeyError(f"no target in config for repo: {repo!r}")
    return target.autonomy


def evaluate_gate(
    autonomy: Autonomy, gate: str, context: dict | None = None
) -> GateDecision:
    if gate not in GATES:
        raise ValueError(f"unknown gate: {gate!r}")
    spec = GATES[gate]
    return spec.decide(autonomy, context or {})


# ──────────────────────────────────────────────────────────────────────────────
# CLI: `python -m backoffice policy <repo> <gate> [--context key=val ...]`
# ──────────────────────────────────────────────────────────────────────────────

def _parse_context(pairs: list[str] | None) -> dict:
    ctx: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            continue
        key, _, val = pair.partition("=")
        key = key.strip()
        val = val.strip()
        if val.lower() in ("true", "false"):
            ctx[key] = val.lower() == "true"
        else:
            ctx[key] = val
    return ctx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice policy",
        description="Evaluate a per-target autonomy gate. Exit 0 if allow, 1 if "
                    "blocked, 2 on error (unknown repo/gate/config).",
    )
    parser.add_argument("repo", help="Target repo name (from backoffice.yaml targets)")
    parser.add_argument("gate", choices=sorted(GATES.keys()), help="Gate name")
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="key=value context pair, repeatable (e.g. --context worktree_clean=false)",
    )
    parser.add_argument(
        "--config",
        help="Path to backoffice.yaml (overrides BACK_OFFICE_CONFIG env var)",
    )
    args = parser.parse_args(argv)

    config_path = args.config or os.environ.get("BACK_OFFICE_CONFIG")
    try:
        config = load_config(Path(config_path)) if config_path else load_config()
    except Exception as exc:
        print(f"policy: config load failed: {exc}", file=sys.stderr)
        return 2

    try:
        autonomy = load_autonomy(config, args.repo)
    except KeyError as exc:
        print(f"policy: {exc}", file=sys.stderr)
        return 2

    ctx = _parse_context(args.context)

    try:
        decision = evaluate_gate(autonomy, args.gate, ctx)
    except ValueError as exc:
        print(f"policy: {exc}", file=sys.stderr)
        return 2

    payload = decision.to_dict()
    payload["repo"] = args.repo
    print(json.dumps(payload))
    return 0 if decision.allow else 1


if __name__ == "__main__":
    sys.exit(main())
