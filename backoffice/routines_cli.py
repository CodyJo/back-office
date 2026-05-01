"""``python -m backoffice routines ...`` CLI."""
from __future__ import annotations

import argparse
import json
import sys

from backoffice.routines import Scheduler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice routines",
        description="Routine CRUD + manual run",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List routines")

    show = sub.add_parser("show", help="Show one routine")
    show.add_argument("routine_id")

    run = sub.add_parser("run", help="Trigger a routine immediately")
    run.add_argument("routine_id")
    run.add_argument("--by", default="operator")

    pause = sub.add_parser("pause", help="Pause a routine")
    pause.add_argument("routine_id")
    pause.add_argument("--by", default="operator")

    resume = sub.add_parser("resume", help="Resume a paused routine")
    resume.add_argument("routine_id")
    resume.add_argument("--by", default="operator")

    args = parser.parse_args(argv)
    scheduler = Scheduler()

    if args.cmd == "list":
        routines = scheduler.list()
        if not routines:
            print("(no routines)")
            return 0
        for r in routines:
            paused = " [paused]" if r.paused else ""
            print(f"{r.id}\t{r.trigger_kind}\t{r.action_kind}\t{r.last_run_at or '-'}{paused}\t{r.name}")
        return 0

    if args.cmd == "show":
        r = scheduler.get(args.routine_id)
        if r is None:
            print(f"not found: {args.routine_id}", file=sys.stderr)
            return 2
        print(json.dumps(r.to_dict(), indent=2))
        return 0

    if args.cmd == "run":
        try:
            result = scheduler.run_now(args.routine_id, actor=args.by)
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["state"] in {"fired", "paused"} else 1

    if args.cmd == "pause":
        try:
            scheduler.pause(args.routine_id, actor=args.by)
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    if args.cmd == "resume":
        try:
            scheduler.resume(args.routine_id, actor=args.by)
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
