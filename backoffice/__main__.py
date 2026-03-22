"""Entry point: python -m backoffice <command>

Dispatches to subcommand modules. Each module exposes a main(argv) function.
"""
from __future__ import annotations

import argparse
import sys

from backoffice.log_config import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backoffice",
        description="Back Office CLI — unified management commands",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument("--json-log", action="store_true", help="JSON log output")

    sub = parser.add_subparsers(dest="command")

    # Config
    cfg = sub.add_parser("config", help="Config operations")
    cfg_sub = cfg.add_subparsers(dest="config_command")
    cfg_sub.add_parser("show", help="Dump resolved config")
    sh = cfg_sub.add_parser("shell-export", help="Output shell vars for agent scripts")
    sh.add_argument("--target", help="Target name")
    sh.add_argument("--fields", nargs="*", help="Fields to export")

    # Sync
    sync = sub.add_parser("sync", help="Dashboard sync")
    sync.add_argument("--dept", help="Quick-sync single department")
    sync.add_argument("--dry-run", action="store_true", help="Log uploads without executing")

    # Audit
    audit = sub.add_parser("audit", help="Run audit on a target")
    audit.add_argument("target", help="Target name")
    audit.add_argument("--departments", "-d", help="Comma-separated departments")
    audit.add_argument("--deploy", action="store_true", help="Sync dashboard after audit")

    # Audit all
    audit_all = sub.add_parser("audit-all", help="Run audits on all targets")
    audit_all.add_argument("--departments", "-d", help="Comma-separated departments")
    audit_all.add_argument("--targets", help="Comma-separated target names")

    # Tasks
    tasks = sub.add_parser("tasks", help="Task queue operations")
    tasks.add_argument("action", nargs="?", default="list",
                       choices=["list", "show", "create", "start", "block",
                                "review", "complete", "cancel", "sync",
                                "seed-etheos"])
    tasks.add_argument("--id", help="Task ID")
    tasks.add_argument("--repo", help="Repository filter")
    tasks.add_argument("--status", help="Status filter")
    tasks.add_argument("--title", help="Task title (for create)")
    tasks.add_argument("--note", help="Note for status change")

    # Regression
    sub.add_parser("regression", help="Run regression suite")

    # Scaffold
    scaffold = sub.add_parser("scaffold", help="Scaffold GitHub Actions workflows")
    scaffold.add_argument("--target", required=True, help="Target name")
    scaffold.add_argument("--workflows", default="ci,preview,cd,nightly")
    scaffold.add_argument("--force", action="store_true")

    # Setup
    setup = sub.add_parser("setup", help="Setup wizard")
    setup.add_argument("--check-only", action="store_true")

    # Refresh
    sub.add_parser("refresh", help="Refresh dashboard artifacts")

    # List targets
    sub.add_parser("list-targets", help="List configured targets")

    # Servers
    serve = sub.add_parser("serve", help="Local dashboard dev server")
    serve.add_argument("--port", type=int, default=8070)

    api = sub.add_parser("api-server", help="Production API server")
    api.add_argument("--port", type=int)
    api.add_argument("--bind", default="0.0.0.0")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(verbose=args.verbose, json_output=args.json_log)

    if not args.command:
        parser.print_help()
        return 0

    # Lazy imports to keep startup fast
    if args.command == "config":
        from backoffice.config import load_config, shell_export
        import json

        cfg = load_config()
        if args.config_command == "shell-export":
            print(shell_export(cfg, args.target, args.fields))
        else:
            print(json.dumps({
                "root": str(cfg.root),
                "runner": {"command": cfg.runner.command, "mode": cfg.runner.mode},
                "targets": list(cfg.targets.keys()),
            }, indent=2))
        return 0

    if args.command == "sync":
        try:
            from backoffice.sync.engine import SyncEngine
            engine = SyncEngine.from_config()
            return engine.run(department=args.dept, dry_run=args.dry_run)
        except ImportError:
            print("Sync module not yet implemented", file=sys.stderr)
            return 1

    if args.command in ("audit", "audit-all", "list-targets", "refresh"):
        try:
            from backoffice.workflow import main as workflow_main
            return workflow_main(sys.argv[1:])
        except ImportError:
            print(f"Workflow module not yet implemented ({args.command})", file=sys.stderr)
            return 1

    if args.command == "tasks":
        try:
            from backoffice.tasks import main as tasks_main
            return tasks_main(sys.argv[1:])
        except ImportError:
            print("Tasks module not yet implemented", file=sys.stderr)
            return 1

    if args.command == "regression":
        try:
            from backoffice.regression import main as regression_main
            return regression_main()
        except ImportError:
            print("Regression module not yet implemented", file=sys.stderr)
            return 1

    if args.command == "scaffold":
        try:
            from backoffice.scaffolding import main as scaffold_main
            return scaffold_main(sys.argv[1:])
        except ImportError:
            print("Scaffolding module not yet implemented", file=sys.stderr)
            return 1

    if args.command == "setup":
        try:
            from backoffice.setup import main as setup_main
            return setup_main(sys.argv[1:])
        except ImportError:
            print("Setup module not yet implemented", file=sys.stderr)
            return 1

    if args.command == "serve":
        try:
            from backoffice.server import main as server_main
            return server_main(port=args.port)
        except ImportError:
            print("Server module not yet implemented", file=sys.stderr)
            return 1

    if args.command == "api-server":
        try:
            from backoffice.api_server import main as api_main
            return api_main(sys.argv[1:])
        except ImportError:
            print("API server module not yet implemented", file=sys.stderr)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
