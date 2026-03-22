"""Local audit workflow orchestration for Back Office.

Ported from scripts/local_audit_workflow.py. Instead of spawning subprocess
calls to other Python scripts, this module calls backoffice package functions
directly for aggregate, delivery, and task-queue operations.  Shell scripts
(agents/*.sh, job-status.sh) are still executed via subprocess.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)

SCRIPT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("BACK_OFFICE_ROOT", SCRIPT_ROOT)
CONFIG_PATH = os.path.join(DATA_ROOT, "config", "targets.yaml")
RESULTS_DIR = os.path.join(DATA_ROOT, "results")
DASHBOARD_DIR = os.path.join(DATA_ROOT, "dashboard")
JOB_STATUS_SCRIPT = os.environ.get(
    "BACK_OFFICE_JOB_STATUS_SCRIPT",
    os.path.join(SCRIPT_ROOT, "scripts", "job-status.sh"),
)
AUDIT_LOG_JSON = os.path.join(RESULTS_DIR, "local-audit-log.json")
AUDIT_LOG_MD = os.path.join(RESULTS_DIR, "local-audit-log.md")
AUDIT_LOG_DASH_JSON = os.path.join(DASHBOARD_DIR, "local-audit-log.json")
AUDIT_LOG_DASH_MD = os.path.join(DASHBOARD_DIR, "local-audit-log.md")
RUN_LOCK_FILE = os.path.join(RESULTS_DIR, ".local-audit-run.lock")

DEPARTMENT_SCRIPTS = {
    "qa": os.path.join(SCRIPT_ROOT, "agents", "qa-scan.sh"),
    "seo": os.path.join(SCRIPT_ROOT, "agents", "seo-audit.sh"),
    "ada": os.path.join(SCRIPT_ROOT, "agents", "ada-audit.sh"),
    "compliance": os.path.join(SCRIPT_ROOT, "agents", "compliance-audit.sh"),
    "monetization": os.path.join(SCRIPT_ROOT, "agents", "monetization-audit.sh"),
    "product": os.path.join(SCRIPT_ROOT, "agents", "product-audit.sh"),
}

FINDINGS_FILES = {
    "qa": "findings.json",
    "seo": "seo-findings.json",
    "ada": "ada-findings.json",
    "compliance": "compliance-findings.json",
    "monetization": "monetization-findings.json",
    "product": "product-findings.json",
}

SCORE_FIELDS = {
    "seo": "seo_score",
    "ada": "compliance_score",
    "compliance": "compliance_score",
    "monetization": "monetization_readiness_score",
    "product": "product_readiness_score",
}

ALL_DEPARTMENTS = list(DEPARTMENT_SCRIPTS.keys())


def extract_scanned_at(payload: dict) -> str | None:
    """Extract the scan timestamp from a findings payload."""
    if not isinstance(payload, dict):
        return None
    direct = payload.get("scanned_at") or payload.get("timestamp")
    if direct:
        return direct
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    audit_date = meta.get("auditDate") or meta.get("audit_date")
    if isinstance(audit_date, str) and audit_date:
        return f"{audit_date}T00:00:00Z"
    generated_at = meta.get("generated_at") or meta.get("generatedAt")
    if isinstance(generated_at, str) and generated_at:
        return generated_at
    return None


def extract_score(payload: dict, department: str, summary: dict) -> int | float | None:
    """Extract the department score from a findings payload."""
    if department == "qa":
        return qa_score_from_summary(summary)

    if isinstance(summary, dict):
        score_field = SCORE_FIELDS.get(department, "")
        if score_field and isinstance(summary.get(score_field), (int, float)):
            return summary.get(score_field)

    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    meta_score_fields = {
        "seo": ["seoScore", "seo_score", "overallScore", "overall_score"],
        "ada": ["complianceScore", "compliance_score"],
        "compliance": ["complianceScore", "compliance_score"],
        "monetization": ["monetizationReadinessScore", "monetization_readiness_score", "overallScore", "overall_score"],
        "product": ["productReadinessScore", "product_readiness_score", "overallScore", "overall_score"],
    }
    for key in meta_score_fields.get(department, []):
        value = meta.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def load_targets(config_path: str = CONFIG_PATH, config=None) -> list[dict]:
    """Load targets from config object or YAML file.

    When *config* is provided and has targets, those are used directly.
    Otherwise falls back to reading from *config_path*.
    """
    if config is not None and hasattr(config, "targets") and config.targets:
        return [
            {
                "name": name,
                "path": target.path,
                "language": target.language,
                "default_departments": list(target.default_departments),
                "context": target.context,
            }
            for name, target in config.targets.items()
        ]

    with open(config_path) as f:
        payload = yaml.safe_load(f) or {}
    targets = payload.get("targets", [])
    if not isinstance(targets, list):
        raise ValueError("config/targets.yaml must define a top-level 'targets' list")
    return targets


def normalize_departments(value, fallback=None) -> list[str]:
    """Normalize department input to a validated list of department names."""
    if value is None:
        value = fallback or ALL_DEPARTMENTS
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = list(value)
    invalid = [item for item in items if item not in DEPARTMENT_SCRIPTS]
    if invalid:
        raise ValueError(f"Unknown departments: {', '.join(sorted(invalid))}")
    return items


def resolve_target(targets: list[dict], target_name: str) -> dict:
    """Find a target by name in the targets list."""
    for target in targets:
        if target.get("name") == target_name:
            return target
    raise ValueError(f"Unknown target: {target_name}")


def default_departments(target: dict) -> list[str]:
    """Return the default departments for a target."""
    return normalize_departments(target.get("default_departments"), ALL_DEPARTMENTS)


def read_json(path: str):
    """Load a JSON file, returning None on missing or malformed files."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def qa_score_from_summary(summary: dict) -> int | None:
    """Calculate a QA score from severity counts.

    Formula: 100 - critical*15 - high*8 - medium*3 - low*1, floored at 0.
    """
    if not isinstance(summary, dict):
        return None
    critical = int(summary.get("critical", 0))
    high = int(summary.get("high", 0))
    medium = int(summary.get("medium", 0))
    low = int(summary.get("low", 0))
    return max(0, 100 - critical * 15 - high * 8 - medium * 3 - low)


def summarize_department(repo_dir: str, department: str) -> dict:
    """Build a summary dict for one department's findings in a repo."""
    findings_path = os.path.join(repo_dir, FINDINGS_FILES[department])
    payload = read_json(findings_path)
    if not payload:
        return {
            "department": department,
            "status": "not-run",
            "findings_path": findings_path,
            "scanned_at": None,
            "findings_total": 0,
            "score": None,
        }

    summary = payload.get("summary", {})
    findings = payload.get("findings", [])
    total = 0
    if isinstance(summary, dict):
        total = summary.get("total", summary.get("total_findings", len(findings)))
    elif isinstance(findings, list):
        total = len(findings)

    score = extract_score(payload, department, summary if isinstance(summary, dict) else {})

    return {
        "department": department,
        "status": "complete",
        "findings_path": findings_path,
        "scanned_at": extract_scanned_at(payload)
        or (summary.get("scanned_at") if isinstance(summary, dict) else None),
        "findings_total": total,
        "score": score,
        "summary": summary if isinstance(summary, dict) else {},
        "summary_text": payload.get("summary") if isinstance(payload.get("summary"), str) else None,
    }


def collect_target_snapshot(target: dict, results_dir: str = RESULTS_DIR) -> dict:
    """Collect a snapshot of all department results for a target."""
    repo_name = target["name"]
    repo_dir = os.path.join(results_dir, repo_name)
    departments = default_departments(target)
    dept_summaries = [summarize_department(repo_dir, department) for department in departments]
    completed = [item for item in dept_summaries if item["status"] == "complete"]
    latest_scan = None
    if completed:
        latest_scan = max(
            (item["scanned_at"] for item in completed if item.get("scanned_at")),
            default=None,
        )

    return {
        "name": repo_name,
        "path": target["path"],
        "language": target.get("language", ""),
        "default_departments": departments,
        "context": target.get("context", "").strip(),
        "latest_scan": latest_scan,
        "department_results": dept_summaries,
    }


def write_audit_log(
    targets: list[dict],
    results_dir: str = RESULTS_DIR,
    dashboard_dir: str = DASHBOARD_DIR,
) -> None:
    """Write JSON and Markdown audit logs for all targets."""
    audit_log_json = os.path.join(results_dir, "local-audit-log.json")
    audit_log_md = os.path.join(results_dir, "local-audit-log.md")
    audit_log_dash_json = os.path.join(dashboard_dir, "local-audit-log.json")
    audit_log_dash_md = os.path.join(dashboard_dir, "local-audit-log.md")

    snapshots = [collect_target_snapshot(target, results_dir) for target in targets]
    history = read_json(os.path.join(results_dir, ".jobs-history.json")) or []
    payload = {
        "generated_at": iso_now(),
        "targets": snapshots,
        "recent_runs": history[-20:],
    }

    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(dashboard_dir, exist_ok=True)
    with open(audit_log_json, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    with open(audit_log_dash_json, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    lines = [
        "# Local Audit Log",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "This file summarizes the latest local audit state for every configured project.",
        "",
    ]
    for snapshot in snapshots:
        lines.append(f"## {snapshot['name']}")
        lines.append("")
        lines.append(f"- Path: `{snapshot['path']}`")
        lines.append(f"- Latest scan: `{snapshot['latest_scan'] or 'not-run'}`")
        lines.append(
            f"- Default departments: `{', '.join(snapshot['default_departments'])}`"
        )
        if snapshot["context"]:
            lines.append(f"- Context: {snapshot['context'].splitlines()[0]}")
        for result in snapshot["department_results"]:
            score = result["score"]
            score_text = "n/a" if score is None else str(score)
            lines.append(
                f"- {result['department']}: status=`{result['status']}`, findings=`{result['findings_total']}`, score=`{score_text}`, scanned_at=`{result['scanned_at'] or 'n/a'}`"
            )
        lines.append("")

    md_content = "\n".join(lines).rstrip() + "\n"
    with open(audit_log_md, "w") as f:
        f.write(md_content)
    with open(audit_log_dash_md, "w") as f:
        f.write(md_content)

    logger.info("Audit log written to %s", audit_log_json)


def refresh_dashboard_artifacts(
    targets: list[dict],
    config=None,
    results_dir: str = RESULTS_DIR,
    dashboard_dir: str = DASHBOARD_DIR,
) -> None:
    """Refresh all dashboard artifacts: aggregate, delivery, task queue, and audit log.

    Calls backoffice.aggregate, backoffice.delivery, and backoffice.tasks
    directly instead of spawning subprocesses.
    """
    from backoffice.aggregate import aggregate as run_aggregate
    from backoffice.delivery import main as delivery_main
    from backoffice.tasks import (
        _default_paths as tasks_default_paths,
        command_sync as tasks_sync,
    )

    # 1. Aggregate results into dashboard JSON
    output_path = os.path.join(dashboard_dir, "data.json")
    run_aggregate(results_dir, output_path)
    logger.info("Aggregated results to %s", output_path)

    # 2. Generate delivery automation data
    delivery_main(config=config)
    logger.info("Delivery data refreshed")

    # 3. Sync task queue
    task_config, task_targets, task_results, task_dashboard = tasks_default_paths()
    ns = argparse.Namespace(
        config=task_config,
        targets_config=task_targets,
        results_dir=task_results,
        dashboard_dir=task_dashboard,
    )
    tasks_sync(ns)
    logger.info("Task queue synced")

    # 4. Write audit log
    write_audit_log(targets, results_dir, dashboard_dir)


def run_job_status(command: str, *args: str) -> None:
    """Run the job-status.sh shell script."""
    subprocess.run(
        ["bash", JOB_STATUS_SCRIPT, command, *args],
        cwd=SCRIPT_ROOT,
        check=True,
    )


def run_department(target: dict, department: str) -> None:
    """Run a department audit shell script for a target."""
    repo_path = target["path"]
    script = DEPARTMENT_SCRIPTS[department]
    subprocess.run(["bash", script, repo_path], cwd=SCRIPT_ROOT, check=True)


def run_target(
    target: dict,
    departments: list[str],
    results_dir: str = RESULTS_DIR,
    refresh: bool = True,
) -> None:
    """Run all specified department audits for a target."""
    repo_path = target["path"]
    run_job_status("init", repo_path, " ".join(departments))
    try:
        for department in departments:
            run_department(target, department)
    finally:
        jobs_file = os.path.join(results_dir, ".jobs.json")
        if os.path.exists(jobs_file):
            try:
                run_job_status("finalize")
            except subprocess.CalledProcessError:
                pass


def with_run_lock(fn):
    """Decorator that acquires an exclusive file lock before running."""
    def _wrapped(args, config=None):
        results_dir = getattr(args, "results_dir", RESULTS_DIR)
        lock_file_path = os.path.join(results_dir, ".local-audit-run.lock")
        os.makedirs(results_dir, exist_ok=True)
        with open(lock_file_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(
                    "Another local audit workflow is already running. "
                    "Wait for it to finish before starting a new target."
                ) from exc
            return fn(args, config=config)

    return _wrapped


@with_run_lock
def handle_list_targets(args, config=None) -> int:
    """Handle the list-targets command."""
    targets = load_targets(args.config, config=config)
    for target in targets:
        logger.info("%s: %s", target["name"], target["path"])
    return 0


@with_run_lock
def handle_refresh(args, config=None) -> int:
    """Handle the refresh command."""
    targets = load_targets(args.config, config=config)
    refresh_dashboard_artifacts(targets, config=config)
    logger.info("Refreshed dashboard data, self-audit data, and local audit log.")
    return 0


@with_run_lock
def handle_run_target(args, config=None) -> int:
    """Handle the run-target command."""
    targets = load_targets(args.config, config=config)
    target = resolve_target(targets, args.target)
    departments = normalize_departments(args.departments, default_departments(target))
    run_target(target, departments)
    refresh_dashboard_artifacts(targets, config=config)
    logger.info("Completed local audit for %s: %s", target["name"], ", ".join(departments))
    return 0


@with_run_lock
def handle_run_all(args, config=None) -> int:
    """Handle the run-all command."""
    targets = load_targets(args.config, config=config)
    selected_targets = targets
    if args.targets:
        wanted = {item.strip() for item in args.targets.split(",") if item.strip()}
        selected_targets = [target for target in targets if target["name"] in wanted]
    for target in selected_targets:
        departments = normalize_departments(args.departments, default_departments(target))
        logger.info("==> %s: %s", target["name"], ", ".join(departments))
        run_target(target, departments)
    refresh_dashboard_artifacts(targets, config=config)
    logger.info("Completed local audits for %d target(s).", len(selected_targets))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the workflow CLI."""
    parser = argparse.ArgumentParser(description="Back Office local audit workflow")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to targets.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-targets", help="List configured local audit targets")
    subparsers.add_parser("refresh", help="Refresh dashboard data and local audit log from current results")

    run_target_parser = subparsers.add_parser("run-target", help="Run local audits for one target")
    run_target_parser.add_argument("--target", required=True, help="Target name from config/targets.yaml")
    run_target_parser.add_argument(
        "--departments",
        help="Comma-separated departments to run. Defaults to target default_departments.",
    )

    run_all_parser = subparsers.add_parser("run-all", help="Run local audits for all configured targets")
    run_all_parser.add_argument(
        "--targets",
        help="Optional comma-separated subset of target names",
    )
    run_all_parser.add_argument(
        "--departments",
        help="Comma-separated departments to apply to every selected target",
    )

    return parser


def main(argv: list[str] | None = None, config=None) -> int:
    """Entry point for the workflow CLI.

    Args:
        argv: Command-line arguments.  Defaults to ``sys.argv[1:]``.
        config: Optional ``backoffice.config.Config`` instance.
    """
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "list-targets": handle_list_targets,
        "refresh": handle_refresh,
        "run-target": handle_run_target,
        "run-all": handle_run_all,
    }
    try:
        return handlers[args.command](args, config=config)
    except (ValueError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
