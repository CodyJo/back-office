"""``python -m backoffice budgets ...`` CLI."""
from __future__ import annotations

import argparse
import json
import sys

from backoffice.budgets import (
    cost_breakdown,
    evaluate,
    from_config,
    list_cost_events,
    total_cost,
)
from backoffice.config import load_config
from backoffice.store import FileStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice budgets",
        description="Budget visibility + spend rollups",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List budgets defined in config")

    spend = sub.add_parser("spend", help="Show total + breakdown of recorded spend")
    spend.add_argument("--target", default="")
    spend.add_argument("--agent-id", default="")

    eval_p = sub.add_parser("evaluate", help="Evaluate budget for a scope")
    eval_p.add_argument("--target", default="")
    eval_p.add_argument("--agent-id", default="")

    args = parser.parse_args(argv)
    config = load_config()
    budgets = from_config(config.budgets)
    store = FileStore(root=config.root)

    if args.cmd == "list":
        if not budgets:
            print("(no budgets configured)")
            return 0
        for b in budgets:
            soft = "-" if b.soft_limit_usd is None else f"${b.soft_limit_usd:.2f}"
            hard = "-" if b.hard_limit_usd is None else f"${b.hard_limit_usd:.2f}"
            scope = f"{b.scope}({b.scope_id})" if b.scope_id else b.scope
            print(f"{b.id}\t{scope}\t{b.period}\tsoft={soft}\thard={hard}")
        return 0

    if args.cmd == "spend":
        events = list_cost_events(store)
        total = total_cost(events)
        breakdown = cost_breakdown(events)
        print(f"total: ${total:.4f} (estimated)")
        for kind, mapping in breakdown.items():
            if not mapping:
                continue
            print(f"\n{kind}:")
            for k, v in sorted(mapping.items(), key=lambda kv: -kv[1]):
                print(f"  {k}: ${v:.4f}")
        return 0

    if args.cmd == "evaluate":
        events = list_cost_events(store)
        decision = evaluate(
            budgets,
            events,
            target=args.target,
            agent_id=args.agent_id,
        )
        print(json.dumps({
            "state": decision.state,
            "spent_usd": decision.spent_usd,
            "limit_usd": decision.limit_usd,
            "budget_id": decision.budget_id,
            "reason": decision.reason,
            "ok": decision.ok,
        }, indent=2))
        return 0 if decision.ok else 1

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
