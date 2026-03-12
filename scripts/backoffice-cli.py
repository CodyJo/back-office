#!/usr/bin/env python3
"""Back Office command-line interface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run_command(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=ROOT)
    return completed.returncode


def run_commands(commands: list[list[str]]) -> int:
    for command in commands:
        exit_code = run_command(command)
        if exit_code != 0:
            return exit_code
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back Office CLI for audits, dashboard refreshes, workflow scaffolding, and deploys."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Inspect agent/runtime setup and optionally create missing config files.")
    setup.add_argument("--check-only", action="store_true", help="Only report current setup state.")
    setup.add_argument("--write-missing-configs", action="store_true", help="Create missing config files from examples.")
    setup.add_argument("--interactive", action="store_true", help="Prompt before writing missing config files.")
    subparsers.add_parser("runners", help="List installed runner CLIs and show the active runner config.")
    activate_runner = subparsers.add_parser("activate-runner", help="Persist a runner choice from the CLIs installed on this system.")
    activate_runner.add_argument("--runner", required=True, help="Runner binary name such as claude or codex.")
    activate_runner.add_argument("--runner-command", help="Optional full command to persist instead of the bare binary.")
    activate_runner.add_argument("--mode", help="Optional runner mode such as claude-print or stdin-text.")
    subparsers.add_parser("list-targets", help="List configured audit targets.")
    subparsers.add_parser("refresh", help="Refresh local dashboard data from existing results.")
    subparsers.add_parser("deploy", help="Publish dashboard assets using sync-dashboard.sh.")
    subparsers.add_parser("test", help="Run Back Office test gates.")

    audit = subparsers.add_parser("audit", help="Run a local audit for a configured target.")
    audit.add_argument("--target", required=True, help="Configured target name, for example bible-app.")
    audit.add_argument("--departments", help="Comma-separated department keys, for example qa,product.")
    audit.add_argument("--deploy", action="store_true", help="Publish dashboard assets after a successful audit.")

    audit_all = subparsers.add_parser("audit-all", help="Run local audits for all configured targets.")
    audit_all.add_argument("--targets", help="Optional comma-separated target subset.")
    audit_all.add_argument("--departments", help="Optional comma-separated department subset.")
    audit_all.add_argument("--deploy", action="store_true", help="Publish dashboard assets after a successful audit run.")

    scaffold = subparsers.add_parser("scaffold-workflows", help="Scaffold GitHub Actions into a configured target repo.")
    scaffold.add_argument("--target", required=True, help="Configured target name.")

    quick_sync = subparsers.add_parser("quick-sync", help="Upload one department's data to configured dashboard targets.")
    quick_sync.add_argument("--department", required=True, help="Department key such as qa, seo, product, or all.")
    quick_sync.add_argument("--repo", required=True, help="Repo name to scope the quick sync.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "setup":
      command = ["python3", "scripts/backoffice_setup.py"]
      if args.check_only:
        command.append("--check-only")
      if args.write_missing_configs:
        command.append("--write-missing-configs")
      if args.interactive:
        command.append("--interactive")
      return run_command(command)
    if args.command == "runners":
      return run_command(["python3", "scripts/backoffice_setup.py", "--list-runners"])
    if args.command == "activate-runner":
      command = ["python3", "scripts/backoffice_setup.py", "--activate-runner", args.runner]
      if args.runner_command:
        command.extend(["--runner-command", args.runner_command])
      if args.mode:
        command.extend(["--mode", args.mode])
      return run_command(command)
    if args.command == "list-targets":
      return run_command(["python3", "scripts/local_audit_workflow.py", "list-targets"])
    if args.command == "refresh":
      return run_command(["python3", "scripts/local_audit_workflow.py", "refresh"])
    if args.command == "deploy":
      return run_command(["bash", "scripts/sync-dashboard.sh"])
    if args.command == "test":
      return run_command(["make", "test"])
    if args.command == "audit":
      command = ["python3", "scripts/local_audit_workflow.py", "run-target", "--target", args.target]
      if args.departments:
        command.extend(["--departments", args.departments])
      commands = [command]
      if args.deploy:
        commands.append(["bash", "scripts/sync-dashboard.sh"])
      return run_commands(commands)
    if args.command == "audit-all":
      command = ["python3", "scripts/local_audit_workflow.py", "run-all"]
      if args.targets:
        command.extend(["--targets", args.targets])
      if args.departments:
        command.extend(["--departments", args.departments])
      commands = [command]
      if args.deploy:
        commands.append(["bash", "scripts/sync-dashboard.sh"])
      return run_commands(commands)
    if args.command == "scaffold-workflows":
      return run_command(["python3", "scripts/scaffold-github-workflows.py", "--target", args.target])
    if args.command == "quick-sync":
      return run_command(["bash", "scripts/quick-sync.sh", args.department, args.repo])
    return 1


if __name__ == "__main__":
    sys.exit(main())
