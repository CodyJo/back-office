"""Back Office delegated work queue.

Stores a version-controlled task queue in config/task-queue.yaml and mirrors a
dashboard-friendly JSON payload into results/ and dashboard/.

Replaces scripts/task-queue.py with explicit path arguments in place of env var
lookups, and logger calls in place of print statements.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


STATUS_ORDER = [
    "proposed",
    "ready",
    "in_progress",
    "blocked",
    "ready_for_review",
    "done",
    "cancelled",
]

FINDINGS_FILE_BY_DEPARTMENT = {
    "qa": "findings.json",
    "seo": "seo-findings.json",
    "ada": "ada-findings.json",
    "compliance": "compliance-findings.json",
    "privacy": "privacy-findings.json",
    "monetization": "monetization-findings.json",
    "product": "product-findings.json",
}

BLOCKING_DEPARTMENTS = {"qa", "ada", "compliance", "privacy"}


@dataclass
class TaskContext:
    targets: dict[str, dict]
    payload: dict
    config_path: Path
    results_dir: Path
    dashboard_dir: Path


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text[:48] or "task"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def load_targets(targets_path: Path) -> dict[str, dict]:
    payload = load_yaml(targets_path)
    targets = payload.get("targets", [])
    return {
        target["name"]: target
        for target in targets
        if isinstance(target, dict) and target.get("name")
    }


def load_context(
    config_path: Path,
    targets_path: Path,
    results_dir: Path,
    dashboard_dir: Path,
) -> TaskContext:
    payload = load_yaml(config_path)
    if "tasks" not in payload or not isinstance(payload.get("tasks"), list):
        payload = {"version": 1, "tasks": []}
    return TaskContext(
        targets=load_targets(targets_path),
        payload=payload,
        config_path=config_path,
        results_dir=results_dir,
        dashboard_dir=dashboard_dir,
    )


def ensure_task_defaults(task: dict, targets: dict[str, dict]) -> dict:
    repo = task.get("repo", "")
    target = targets.get(repo, {})
    task = dict(task)
    task.setdefault("status", "proposed")
    task.setdefault("priority", "medium")
    task.setdefault("category", "feature")
    task.setdefault("owner", "")
    task.setdefault("created_by", "product-owner")
    task.setdefault("created_at", iso_now())
    task.setdefault("updated_at", task["created_at"])
    task.setdefault("acceptance_criteria", [])
    task.setdefault("notes", "")
    task.setdefault("history", [])
    task.setdefault("handoff_required", True)
    task.setdefault("verification_command", "")
    task.setdefault("repo_handoff_path", "")
    task.setdefault("audits_required", target.get("default_departments", ["qa", "product"]))
    task.setdefault("product_key", infer_product_key(repo))
    task.setdefault("target_path", target.get("path", ""))
    if not task.get("id"):
        task["id"] = generate_task_id(repo, task["title"])
    return task


def infer_product_key(repo: str) -> str:
    mapping = {
        "etheos-app": "etheos",
        "bible-app": "selah",
        "thenewbeautifulme": "tnbm-tarot",
        "photo-gallery": "analogify-studio",
        "photo-gallery-client-portal": "analogify-studio",
        "codyjo.com": "codyjo-method",
        "back-office": "back-office",
    }
    return mapping.get(repo, repo)


def generate_task_id(repo: str, title: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{repo}:{slugify(title)}:{stamp}"


def save_payload(
    payload: dict,
    targets: dict[str, dict],
    config_path: Path,
    results_dir: Path,
    dashboard_dir: Path,
) -> dict:
    normalized = {
        "version": payload.get("version", 1),
        "tasks": [ensure_task_defaults(task, targets) for task in payload.get("tasks", [])],
    }
    write_yaml(config_path, normalized)
    dashboard_payload = build_dashboard_payload(normalized["tasks"])
    results_path = results_dir / "task-queue.json"
    dashboard_path = dashboard_dir / "task-queue.json"
    for out_path in (results_path, dashboard_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(dashboard_payload, indent=2) + "\n")
    return dashboard_payload


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build_dashboard_payload(tasks: list[dict]) -> dict:
    tasks = [dict(task) for task in tasks]
    for task in tasks:
        task["history"] = sorted(task.get("history", []), key=lambda item: item.get("at", ""))

    counts_by_status: dict[str, int] = {}
    counts_by_repo: dict[str, dict[str, int]] = {}
    for task in tasks:
        status = task.get("status", "proposed")
        repo = task.get("repo", "unknown")
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        repo_bucket = counts_by_repo.setdefault(repo, {"total": 0, "open": 0, "done": 0})
        repo_bucket["total"] += 1
        if status == "done":
            repo_bucket["done"] += 1
        elif status != "cancelled":
            repo_bucket["open"] += 1

    def sort_key(task: dict) -> tuple[int, int, str]:
        try:
            status_index = STATUS_ORDER.index(task.get("status", "proposed"))
        except ValueError:
            status_index = len(STATUS_ORDER)
        priority_index = {"high": 0, "medium": 1, "low": 2}.get(task.get("priority", "medium"), 3)
        return (status_index, priority_index, task.get("created_at", ""))

    ordered = sorted(tasks, key=sort_key)
    return {
        "generated_at": iso_now(),
        "summary": {
            "total": len(ordered),
            "open": sum(1 for task in ordered if task.get("status") not in ("done", "cancelled")),
            "done": sum(1 for task in ordered if task.get("status") == "done"),
            "blocked": sum(1 for task in ordered if task.get("status") == "blocked"),
            "in_progress": sum(1 for task in ordered if task.get("status") == "in_progress"),
            "ready_for_review": sum(1 for task in ordered if task.get("status") == "ready_for_review"),
            "by_status": counts_by_status,
            "by_repo": counts_by_repo,
        },
        "tasks": ordered,
    }


def find_task(tasks: list[dict], task_id: str) -> dict:
    for task in tasks:
        if task.get("id") == task_id:
            return task
    raise SystemExit(f"Unknown task id: {task_id}")


def append_history(task: dict, status: str, actor: str, note: str) -> None:
    task.setdefault("history", []).append(
        {
            "status": status,
            "at": iso_now(),
            "by": actor,
            "note": note.strip(),
        }
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def summarize_gate_status(
    task: dict,
    audit_results_dir: Path,
) -> tuple[bool, list[str]]:
    repo = task.get("repo", "")
    repo_dir = audit_results_dir / repo
    now = datetime.now(timezone.utc)
    max_age = timedelta(days=7)
    failures: list[str] = []

    for department in task.get("audits_required", []):
        findings_file = FINDINGS_FILE_BY_DEPARTMENT.get(department)
        if not findings_file:
            continue
        findings_path = repo_dir / findings_file
        payload = read_json(findings_path)
        if not payload:
            failures.append(f"{department}: no findings artifact at {findings_path}")
            continue
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        scanned_at = (
            payload.get("scanned_at")
            or summary.get("scanned_at")
            or (payload.get("metadata", {}) or {}).get("generated_at")
        )
        scanned_dt = parse_timestamp(scanned_at)
        if not scanned_dt:
            failures.append(f"{department}: missing scanned_at timestamp")
        elif now - scanned_dt > max_age:
            failures.append(f"{department}: stale audit artifact from {scanned_at}")

        if department in BLOCKING_DEPARTMENTS:
            critical = int(summary.get("critical", 0) or 0)
            high = int(summary.get("high", summary.get("high_value", 0)) or 0)
            if critical > 0 or high > 0:
                failures.append(
                    f"{department}: blocking findings remain (critical={critical}, high={high})"
                )

    handoff_path = task.get("repo_handoff_path")
    if task.get("handoff_required") and handoff_path:
        if not Path(handoff_path).exists():
            failures.append(f"handoff missing: {handoff_path}")

    return (len(failures) == 0, failures)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def command_sync(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    payload = save_payload(
        context.payload, context.targets, args.config, args.results_dir, args.dashboard_dir
    )
    logger.info("sync complete: %s", json.dumps(payload["summary"]))
    return 0


def command_list(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    save_payload(
        context.payload, context.targets, args.config, args.results_dir, args.dashboard_dir
    )
    tasks = [ensure_task_defaults(task, context.targets) for task in context.payload.get("tasks", [])]
    if args.repo:
        tasks = [task for task in tasks if task.get("repo") == args.repo]
    if args.status:
        tasks = [task for task in tasks if task.get("status") == args.status]
    if args.product:
        tasks = [task for task in tasks if task.get("product_key") == args.product]

    for task in tasks:
        logger.info(
            "%s | repo=%s | status=%s | priority=%s | title=%s",
            task["id"],
            task.get("repo", ""),
            task.get("status", ""),
            task.get("priority", ""),
            task.get("title", ""),
        )
    return 0


def command_show(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    tasks = [ensure_task_defaults(task, context.targets) for task in context.payload.get("tasks", [])]
    task = find_task(tasks, args.id)
    gates_ok, failures = summarize_gate_status(task, args.results_dir)
    logger.info(
        "%s",
        json.dumps({**task, "gate_check": {"ok": gates_ok, "failures": failures}}, indent=2),
    )
    return 0


def command_create(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    task = ensure_task_defaults(
        {
            "repo": args.repo,
            "title": args.title,
            "category": args.category,
            "priority": args.priority,
            "status": args.status,
            "created_by": args.created_by,
            "owner": args.owner or "",
            "notes": args.notes or "",
            "acceptance_criteria": list(args.acceptance or []),
            "verification_command": args.verification_command or "",
            "repo_handoff_path": args.repo_handoff_path or "",
            "audits_required": list(args.audits or []),
        },
        context.targets,
    )
    append_history(task, task["status"], task["created_by"], "Task created")
    context.payload.setdefault("tasks", []).append(task)
    save_payload(
        context.payload, context.targets, args.config, args.results_dir, args.dashboard_dir
    )
    logger.info("created task: %s", task["id"])
    return 0


def update_status(args: argparse.Namespace, status: str, default_note: str) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    tasks = context.payload.setdefault("tasks", [])
    task = find_task(tasks, args.id)
    actor = args.by or task.get("owner") or "back-office"
    task["status"] = status
    if getattr(args, "owner", None):
        task["owner"] = args.owner
    task["updated_at"] = iso_now()
    note = getattr(args, "note", "") or default_note
    append_history(task, status, actor, note)
    save_payload(
        context.payload, context.targets, args.config, args.results_dir, args.dashboard_dir
    )
    logger.info("%s -> %s", task["id"], status)
    return 0


def command_start(args: argparse.Namespace) -> int:
    return update_status(args, "in_progress", "Task started")


def command_block(args: argparse.Namespace) -> int:
    return update_status(args, "blocked", "Task blocked")


def command_review(args: argparse.Namespace) -> int:
    return update_status(args, "ready_for_review", "Ready for audit and review")


def command_complete(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    tasks = context.payload.setdefault("tasks", [])
    task = find_task(tasks, args.id)
    gates_ok, failures = summarize_gate_status(task, args.results_dir)
    if not gates_ok and not args.allow_incomplete_gates:
        logger.warning("Completion blocked by required gates:")
        for failure in failures:
            logger.warning("- %s", failure)
        return 2
    if failures and args.allow_incomplete_gates:
        note = (args.note or "").strip()
        args.note = (note + " | " if note else "") + "Override used despite gate failures: " + "; ".join(failures)
    return update_status(args, "done", "Task completed")


def command_cancel(args: argparse.Namespace) -> int:
    return update_status(args, "cancelled", "Task cancelled")


def command_seed_etheos(args: argparse.Namespace) -> int:
    context = load_context(args.config, args.targets_config, args.results_dir, args.dashboard_dir)
    existing_ids = {task.get("id") for task in context.payload.get("tasks", [])}
    seeds = [
        {
            "id": "etheos:frontend-stabilization",
            "repo": "etheos-app",
            "title": "Stabilize current event-factory frontend and restore passing gates",
            "category": "bugfix",
            "priority": "high",
            "status": "ready",
            "created_by": "product-owner",
            "owner": "implementation-agent",
            "notes": "Resolve current lint/test regressions on the event-factory branch before deeper backend automation work.",
            "acceptance_criteria": [
                "lint passes",
                "typecheck passes",
                "tests pass",
                "coverage check passes",
                "handoff updated with current clean baseline",
            ],
            "verification_command": "npm run factory:check",
            "repo_handoff_path": "/home/merm/projects/etheos-app/docs/HANDOFF.md",
        },
        {
            "id": "etheos:intake-pipeline",
            "repo": "etheos-app",
            "title": "Implement organizer intake upload pipeline for event docs",
            "category": "feature",
            "priority": "high",
            "status": "ready",
            "created_by": "product-owner",
            "owner": "implementation-agent",
            "notes": "Add authenticated intake records, presigned upload URLs, and S3-backed organizer document uploads.",
            "acceptance_criteria": [
                "organizer can create or update an intake record",
                "organizer can request presigned upload URLs",
                "uploaded document metadata is persisted",
                "privacy copy remains explicit about AI and document use",
                "tests cover intake API behavior",
            ],
            "verification_command": "npm run verify:release",
            "repo_handoff_path": "/home/merm/projects/etheos-app/docs/HANDOFF.md",
        },
        {
            "id": "etheos:factory-builder",
            "repo": "etheos-app",
            "title": "Build AI-agnostic event-config generation pipeline",
            "category": "feature",
            "priority": "high",
            "status": "proposed",
            "created_by": "product-owner",
            "owner": "implementation-agent",
            "notes": "Normalize uploaded docs into event config with organizer-entered facts staying authoritative and provider adapters remaining swappable.",
            "acceptance_criteria": [
                "S3 object completion can trigger a builder job",
                "builder creates normalized sessions speakers resources and FAQs",
                "AI adapter boundary supports provider swap or no-AI mode",
                "organizer can review generated result before publish",
                "handoff documents open issues and validation path",
            ],
            "verification_command": "npm run verify:release",
            "repo_handoff_path": "/home/merm/projects/etheos-app/docs/HANDOFF.md",
        },
    ]
    for seed in seeds:
        if seed["id"] in existing_ids:
            continue
        task = ensure_task_defaults(seed, context.targets)
        append_history(task, task["status"], task["created_by"], "Seeded pilot task")
        context.payload.setdefault("tasks", []).append(task)
    save_payload(
        context.payload, context.targets, args.config, args.results_dir, args.dashboard_dir
    )
    logger.info("Seeded Etheos pilot tasks.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def _default_paths() -> tuple[Path, Path, Path, Path]:
    """Return (config_path, targets_path, results_dir, dashboard_dir) from env or repo layout."""
    import os

    root = Path(os.environ.get("BACK_OFFICE_ROOT", _DEFAULT_ROOT))
    config_path = Path(os.environ.get("BACK_OFFICE_TASK_QUEUE_CONFIG", root / "config" / "task-queue.yaml"))
    targets_path = Path(os.environ.get("BACK_OFFICE_TARGETS_CONFIG", root / "config" / "targets.yaml"))
    results_dir = Path(os.environ.get("BACK_OFFICE_RESULTS_DIR", root / "results"))
    dashboard_dir = Path(os.environ.get("BACK_OFFICE_DASHBOARD_DIR", root / "dashboard"))
    return config_path, targets_path, results_dir, dashboard_dir


def build_parser(
    default_config: Path | None = None,
    default_targets: Path | None = None,
    default_results: Path | None = None,
    default_dashboard: Path | None = None,
) -> argparse.ArgumentParser:
    if default_config is None:
        default_config, default_targets, default_results, default_dashboard = _default_paths()

    parser = argparse.ArgumentParser(description="Back Office delegated task queue")
    parser.add_argument("--config", type=Path, default=default_config, metavar="PATH",
                        help="Path to task-queue.yaml (default: config/task-queue.yaml)")
    parser.add_argument("--targets-config", type=Path, default=default_targets, metavar="PATH",
                        help="Path to targets.yaml (default: config/targets.yaml)")
    parser.add_argument("--results-dir", type=Path, default=default_results, metavar="DIR",
                        help="Results directory (default: results/)")
    parser.add_argument("--dashboard-dir", type=Path, default=default_dashboard, metavar="DIR",
                        help="Dashboard directory (default: dashboard/)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync", help="Normalize the task queue and regenerate dashboard payloads")

    list_parser = subparsers.add_parser("list", help="List queue items")
    list_parser.add_argument("--repo")
    list_parser.add_argument("--status")
    list_parser.add_argument("--product")

    show_parser = subparsers.add_parser("show", help="Show one queue item")
    show_parser.add_argument("--id", required=True)

    create_parser = subparsers.add_parser("create", help="Create a queue item")
    create_parser.add_argument("--repo", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--category", default="feature")
    create_parser.add_argument("--priority", default="medium")
    create_parser.add_argument("--status", default="proposed")
    create_parser.add_argument("--created-by", dest="created_by", default="product-owner")
    create_parser.add_argument("--owner")
    create_parser.add_argument("--notes")
    create_parser.add_argument("--acceptance", action="append")
    create_parser.add_argument("--audits", action="append")
    create_parser.add_argument("--verification-command", dest="verification_command")
    create_parser.add_argument("--repo-handoff-path", dest="repo_handoff_path")

    for command_name in ("start", "block", "review", "complete", "cancel"):
        status_parser = subparsers.add_parser(command_name, help=f"Mark a task as {command_name}")
        status_parser.add_argument("--id", required=True)
        status_parser.add_argument("--by")
        status_parser.add_argument("--owner")
        status_parser.add_argument("--note")
        if command_name == "complete":
            status_parser.add_argument(
                "--allow-incomplete-gates",
                dest="allow_incomplete_gates",
                action="store_true",
                help="Override gate enforcement. Avoid using this outside emergencies.",
            )

    subparsers.add_parser("seed-etheos", help="Seed the Etheos pilot tasks")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "sync": command_sync,
        "list": command_list,
        "show": command_show,
        "create": command_create,
        "start": command_start,
        "block": command_block,
        "review": command_review,
        "complete": command_complete,
        "cancel": command_cancel,
        "seed-etheos": command_seed_etheos,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
