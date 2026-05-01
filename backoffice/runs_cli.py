"""``python -m backoffice runs ...`` CLI."""
from __future__ import annotations

import argparse
import json
import sys

from backoffice.store import FileStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice runs",
        description="Inspect recorded runs",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="List runs")
    list_p.add_argument("--task-id", default=None)
    list_p.add_argument("--state", default=None,
                        help="Filter by state (e.g. running, succeeded)")

    show = sub.add_parser("show", help="Show one run")
    show.add_argument("run_id")

    args = parser.parse_args(argv)
    store = FileStore()

    if args.cmd == "list":
        runs = store.list_runs(task_id=args.task_id)
        if args.state:
            runs = [r for r in runs if r.state == args.state]
        if not runs:
            print("(no runs)")
            return 0
        for r in runs:
            print(f"{r.id}\t{r.state}\t{r.adapter_type}\t{r.task_id}\t{r.agent_id}\t{r.started_at or '-'}\t{r.ended_at or '-'}")
        return 0

    if args.cmd == "show":
        r = store.get_run(args.run_id)
        if r is None:
            print(f"not found: {args.run_id}", file=sys.stderr)
            return 2
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
