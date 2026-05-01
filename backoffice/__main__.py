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

    # Drift check between backoffice.yaml and legacy targets.yaml
    sub.add_parser(
        "check-drift",
        help="Report any drift between backoffice.yaml and config/targets.yaml",
    )

    # Targets JSON — stable machine-readable output for shell consumers
    tj = sub.add_parser(
        "targets-json",
        help="Emit all validated targets as a JSON array (for overnight.sh et al)",
    )
    tj.add_argument("--filter", help="Comma-separated target names to include")
    tj.add_argument(
        "--require-path",
        action="store_true",
        help="Only emit targets whose path exists and contains .git",
    )

    # Policy — per-target autonomy gate evaluation
    policy = sub.add_parser(
        "policy",
        help="Evaluate a per-target autonomy gate (exit 0=allow, 1=block, 2=error)",
    )
    policy.add_argument("repo", help="Target repo name")
    policy.add_argument("gate", help="Gate name (fix, feature_dev, auto_merge, auto_commit, deploy)")
    policy.add_argument(
        "--context",
        action="append",
        default=[],
        help="key=value context pair (repeatable), e.g. --context worktree_clean=false",
    )

    # Loop state (execution ledger + failure memory + quarantine)
    state = sub.add_parser(
        "state",
        help="Overnight loop state helpers (ledger, failure memory, quarantine)",
    )
    state_sub = state.add_subparsers(dest="state_command")

    ledger = state_sub.add_parser(
        "ledger-append",
        help="Append a decision record to the execution ledger",
    )
    ledger.add_argument("--path", help="Ledger JSONL path (default: results/overnight-ledger.jsonl)")
    ledger.add_argument("--cycle", required=True, help="Cycle ID")
    ledger.add_argument("--action", required=True, help="Action (fix|feature|deploy|rollback|plan)")
    ledger.add_argument("--target", required=True, help="Target repo name")
    ledger.add_argument("--allow", required=True, choices=["true", "false"], help="Allowed?")
    ledger.add_argument("--reason", required=True, help="Machine-readable reason code")
    ledger.add_argument("--detail", default="{}", help="JSON object of extra detail")

    blocked = state_sub.add_parser(
        "blocked-items",
        help="Emit JSON array of recently-failed (repo,title) items",
    )
    blocked.add_argument("--history", help="History JSON path (default: results/overnight-history.json)")
    blocked.add_argument("--window", type=int, default=2, help="Number of cycles to inspect")

    quar = state_sub.add_parser(
        "quarantined",
        help="Emit JSON array of repos currently under quarantine",
    )
    quar.add_argument("--history", help="History JSON path (default: results/overnight-history.json)")
    quar.add_argument("--threshold", type=int, default=3, help="Consecutive rollbacks to flag")
    quar.add_argument("--overrides", help="Manual clear path (default: results/quarantine-clear.json)")

    # Invoke (backend bridge)
    invoke = sub.add_parser("invoke", help="Invoke an AI backend directly")
    invoke.add_argument("--backend", required=True, help="Backend name (claude, codex)")
    invoke.add_argument("--prompt", required=True, help="Prompt text")
    invoke.add_argument("--tools", default="", help="Comma-separated tool list")
    invoke.add_argument("--repo", required=True, help="Target repo directory")

    # Servers
    serve = sub.add_parser("serve", help="Local dashboard dev server")
    serve.add_argument("--port", type=int, default=8070)

    api = sub.add_parser("api-server", help="Production API server")
    api.add_argument("--port", type=int)
    api.add_argument("--bind", default="0.0.0.0")

    # ────────────────────────────────────────────────────────────────
    # Phase 4–12 control-plane subcommands
    # ────────────────────────────────────────────────────────────────

    sub.add_parser("agents", help="Agent registry CRUD")
    sub.add_parser("routines", help="Routine CRUD + manual run")
    sub.add_parser("budgets", help="Budget visibility")
    sub.add_parser("tokens", help="Per-agent API token issue / revoke / list")
    sub.add_parser("runs", help="List / show recorded runs")
    sub.add_parser("export", help="Deterministic export of operator-owned config")
    sub.add_parser("import", help="Validate (and optionally apply) an export payload")

    # Preview — generate preview artifact for a fix-agent branch
    prev = sub.add_parser(
        "preview",
        help="Generate preview JSON artifact for a fix-agent branch",
    )
    prev.add_argument("--repo-path", required=True, help="Path to the repo checkout")
    prev.add_argument("--repo-name", required=True, help="Target repo name")
    prev.add_argument("--job-id", required=True, help="Fix job ID")
    prev.add_argument("--branch", required=True, help="Current preview branch name")
    prev.add_argument("--base-ref", required=True, help="Base ref (e.g. main)")
    prev.add_argument("--findings", required=True, help="Path to findings JSON array")
    prev.add_argument("--remote-url", help="Override for git remote URL")
    prev.add_argument("--out", required=True, help="Destination JSON path")

    return parser


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(argv) if argv is not None else sys.argv[1:]

    # Phase 4–12 subcommands forward the rest of argv to their own
    # parsers so we don't duplicate option declarations across modules.
    if effective_argv and effective_argv[0] in {
        "agents",
        "routines",
        "budgets",
        "tokens",
        "runs",
        "export",
        "import",
    }:
        return _dispatch_extension(effective_argv[0], effective_argv[1:])

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
            workflow_argv = effective_argv
            if args.command == "audit":
                workflow_argv = ["run-target", "--target", args.target]
                if args.departments:
                    workflow_argv += ["--departments", args.departments]
            elif args.command == "audit-all":
                workflow_argv = ["run-all"]
                if args.targets:
                    workflow_argv += ["--targets", args.targets]
                if args.departments:
                    workflow_argv += ["--departments", args.departments]
            return workflow_main(workflow_argv)
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

    if args.command == "invoke":
        from backoffice.backends import get_backend
        from backoffice.config import load_config

        cfg = load_config()
        backend_name = args.backend
        backend_cfg = cfg.agent_backends.get(backend_name)
        if backend_cfg:
            # Convert frozen BackendConfig to plain dict for the backend constructor
            bc = {
                "command": backend_cfg.command,
                "model": backend_cfg.model,
                "mode": backend_cfg.mode,
                "local_budget": backend_cfg.local_budget,
            }
        else:
            # Allow ad-hoc backend names not in config
            bc = {}
        backend = get_backend(backend_name, bc)
        tools = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools else []
        result = backend.invoke(args.prompt, tools, args.repo)
        if result.output:
            print(result.output, end="")
        if result.error:
            print(result.error, end="", file=sys.stderr)
        return result.exit_code

    if args.command == "check-drift":
        from backoffice.config import load_config
        from backoffice.config_drift import detect_drift
        import json
        cfg = load_config()
        legacy_path = cfg.root / "config" / "targets.yaml"
        report = detect_drift(cfg, legacy_path)
        payload = {
            "ok": report.ok,
            "legacy_path": str(legacy_path),
            "conflicts": report.conflicts,
            "extra_in_legacy": report.extra_in_legacy,
            "extra_in_unified": report.extra_in_unified,
        }
        print(json.dumps(payload, indent=2))
        return 0 if report.ok else 1

    if args.command == "targets-json":
        from backoffice.config import load_config
        import json
        import os
        cfg = load_config()
        filter_list: list[str] = []
        if args.filter:
            filter_list = [f.strip() for f in args.filter.split(",") if f.strip()]
        out: list[dict] = []
        for name, t in cfg.targets.items():
            if filter_list and name not in filter_list:
                continue
            if args.require_path:
                if not t.path or not os.path.isdir(t.path):
                    continue
                if not os.path.isdir(os.path.join(t.path, ".git")):
                    continue
            out.append({
                "name": name,
                "path": t.path,
                "language": t.language,
                "lint_command": t.lint_command,
                "test_command": t.test_command,
                "coverage_command": t.coverage_command,
                "deploy_command": t.deploy_command,
                "autonomy": {
                    "allow_fix": t.autonomy.allow_fix,
                    "allow_feature_dev": t.autonomy.allow_feature_dev,
                    "allow_auto_commit": t.autonomy.allow_auto_commit,
                    "allow_auto_merge": t.autonomy.allow_auto_merge,
                    "allow_auto_deploy": t.autonomy.allow_auto_deploy,
                    "require_clean_worktree": t.autonomy.require_clean_worktree,
                    "require_tests": t.autonomy.require_tests,
                    "max_changes_per_cycle": t.autonomy.max_changes_per_cycle,
                    "deploy_mode": t.autonomy.deploy_mode,
                },
            })
        print(json.dumps(out))
        return 0

    if args.command == "policy":
        from backoffice.policy import main as policy_main
        argv = [args.repo, args.gate]
        for ctx in args.context:
            argv += ["--context", ctx]
        return policy_main(argv)

    if args.command == "state":
        from backoffice.config import load_config
        from backoffice.overnight_state import (
            ExecutionLedger,
            FailureMemory,
            LedgerRecord,
            Quarantine,
        )
        import json
        cfg = load_config()
        results_dir = cfg.root / "results"

        if args.state_command == "ledger-append":
            path = args.path or str(results_dir / "overnight-ledger.jsonl")
            try:
                detail = json.loads(args.detail)
            except json.JSONDecodeError as exc:
                print(f"Invalid --detail JSON: {exc}", file=sys.stderr)
                return 2
            ledger = ExecutionLedger(path)
            ledger.append(LedgerRecord(
                cycle_id=args.cycle,
                action=args.action,
                target=args.target,
                allow=(args.allow == "true"),
                reason=args.reason,
                detail=detail if isinstance(detail, dict) else {},
            ))
            return 0

        if args.state_command == "blocked-items":
            history = args.history or str(results_dir / "overnight-history.json")
            mem = FailureMemory(history, window=args.window)
            payload = [
                {"repo": repo, "title": title}
                for repo, title in sorted(mem.blocked_items())
            ]
            print(json.dumps(payload))
            return 0

        if args.state_command == "quarantined":
            history = args.history or str(results_dir / "overnight-history.json")
            overrides = args.overrides or str(results_dir / "quarantine-clear.json")
            q = Quarantine(history, threshold=args.threshold, overrides_path=overrides)
            print(json.dumps(sorted(q.flagged())))
            return 0

        parser.parse_args(["state", "--help"])
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

    if args.command == "preview":
        from pathlib import Path
        import json
        from backoffice.preview import PreviewInputs, build_preview

        repo_path = Path(args.repo_path)
        try:
            findings = json.loads(Path(args.findings).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Failed to read findings: {exc}", file=sys.stderr)
            return 2
        if not isinstance(findings, list):
            print("Findings file must contain a JSON array", file=sys.stderr)
            return 2

        remote = args.remote_url or _derive_remote(repo_path)
        payload = build_preview(PreviewInputs(
            repo_path=repo_path,
            repo_name=args.repo_name,
            job_id=args.job_id,
            branch=args.branch,
            base_ref=args.base_ref,
            findings_addressed=findings,
            remote_url=remote,
        ))
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
        return 0

    parser.print_help()
    return 1


def _derive_remote(repo_path) -> str | None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    url = result.stdout.strip()
    return url or None


# ──────────────────────────────────────────────────────────────────────
# Phase 4–12 subcommand dispatcher
# ──────────────────────────────────────────────────────────────────────


def _dispatch_extension(name: str, argv: list[str]) -> int:
    """Forward to the relevant module's CLI ``main(argv)``."""
    setup_logging(verbose=False, json_output=False)
    if name == "agents":
        from backoffice.agents import main as agents_main
        return agents_main(argv)
    if name == "routines":
        from backoffice.routines_cli import main as routines_main
        return routines_main(argv)
    if name == "budgets":
        from backoffice.budgets_cli import main as budgets_main
        return budgets_main(argv)
    if name == "tokens":
        from backoffice.tokens_cli import main as tokens_main
        return tokens_main(argv)
    if name == "runs":
        from backoffice.runs_cli import main as runs_main
        return runs_main(argv)
    if name == "export":
        from backoffice.portable_cli import export_main
        return export_main(argv)
    if name == "import":
        from backoffice.portable_cli import import_main
        return import_main(argv)
    print(f"unknown extension subcommand: {name}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
