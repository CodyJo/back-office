"""High-level budget-check facade for the scan/apply pipelines.

Loads the budgets block from ``backoffice.yaml``, loads cost events
from ``results/cost-events.jsonl``, and returns a single
:class:`backoffice.budgets.BudgetDecision` per (target, department).

Callers (``agents/qa-scan.sh``, ``backoffice.apply.runner``) use this
to decide whether to run the AI step or fall back to deterministic
output. Falling back is the *safe* response — never crash on a budget
miss; just record the decision.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from backoffice.budgets import (
    ALLOW,
    BLOCK,
    Budget,
    BudgetDecision,
    evaluate,
    from_config,
    list_cost_events,
)
from backoffice.config import load_config
from backoffice.store import FileStore

logger = logging.getLogger(__name__)


def check(target: str, department: str = "qa") -> BudgetDecision:
    """Evaluate AI spend gate for the given (target, department)."""
    cfg = load_config()
    raw_budgets = getattr(cfg, "budgets", None)
    budgets: list[Budget] = []
    if raw_budgets:
        try:
            budgets = from_config(raw_budgets)
        except Exception:  # malformed config shouldn't block scans
            logger.exception("budgets section in config is malformed; treating as ALLOW")
            return BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None,
                                  reason="budgets-config-malformed")
    if not budgets:
        return BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None,
                              reason="no-budgets-configured")
    try:
        events = list_cost_events(FileStore())
    except Exception:
        logger.exception("could not load cost events; treating as ALLOW")
        return BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None,
                              reason="cost-events-unreadable")
    return evaluate(budgets, events, target=target, department=department)


def is_blocked(target: str, department: str = "qa") -> bool:
    """Convenience: True iff the budget gate decision is BLOCK."""
    return check(target, department).state == BLOCK


# ──────────────────────────────────────────────────────────────────────
# CLI: emits JSON for shell-script consumers
# ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m backoffice budget-check",
        description="Evaluate AI-spend budget gate. Exit 0 if allow/warn, 1 if block.",
    )
    p.add_argument("target", help="Target name from backoffice.yaml")
    p.add_argument("--department", default="qa", help="Department scope (default: qa)")
    args = p.parse_args(argv)
    decision = check(args.target, args.department)
    print(json.dumps({
        "state": decision.state,
        "spent_usd": decision.spent_usd,
        "limit_usd": decision.limit_usd,
        "budget_id": decision.budget_id,
        "reason": decision.reason,
    }))
    return 1 if decision.state == BLOCK else 0


if __name__ == "__main__":
    sys.exit(main())
