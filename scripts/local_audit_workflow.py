#!/usr/bin/env python3
"""Local audit workflow orchestration for Back Office.

This script keeps local audits reproducible across all configured projects.
It can list targets, refresh dashboard artifacts from existing results, run
audits for one target, or run audits across every configured target.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import yaml

QA_ROOT = os.environ.get(
    "BACK_OFFICE_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
CONFIG_PATH = os.path.join(QA_ROOT, "config", "targets.yaml")
RESULTS_DIR = os.path.join(QA_ROOT, "results")
DASHBOARD_DIR = os.path.join(QA_ROOT, "dashboard")
AGGREGATE_SCRIPT = os.environ.get(
    "BACK_OFFICE_AGGREGATE_SCRIPT",
    os.path.join(QA_ROOT, "scripts", "aggregate-results.py"),
)
JOB_STATUS_SCRIPT = os.environ.get(
    "BACK_OFFICE_JOB_STATUS_SCRIPT",
    os.path.join(QA_ROOT, "scripts", "job-status.sh"),
)
AUDIT_LOG_JSON = os.path.join(RESULTS_DIR, "local-audit-log.json")
AUDIT_LOG_MD = os.path.join(RESULTS_DIR, "local-audit-log.md")
AUDIT_LOG_DASH_JSON = os.path.join(DASHBOARD_DIR, "local-audit-log.json")
AUDIT_LOG_DASH_MD = os.path.join(DASHBOARD_DIR, "local-audit-log.md")
RUN_LOCK_FILE = os.path.join(RESULTS_DIR, ".local-audit-run.lock")

DEPARTMENT_SCRIPTS = {
    "qa": os.path.join(QA_ROOT, "agents", "qa-scan.sh"),
    "seo": os.path.join(QA_ROOT, "agents", "seo-audit.sh"),
    "ada": os.path.join(QA_ROOT, "agents", "ada-audit.sh"),
    "compliance": os.path.join(QA_ROOT, "agents", "compliance-audit.sh"),
    "monetization": os.path.join(QA_ROOT, "agents", "monetization-audit.sh"),
    "product": os.path.join(QA_ROOT, "agents", "product-audit.sh"),
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


def load_targets(config_path: str = CONFIG_PATH) -> list[dict]:
    with open(config_path) as f:
        payload = yaml.safe_load(f) or {}
    targets = payload.get("targets", [])
    if not isinstance(targets, list):
        raise ValueError("config/targets.yaml must define a top-level 'targets' list")
    return targets


def normalize_departments(value, fallback=None) -> list[str]:
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
    for target in targets:
        if target.get("name") == target_name:
            return target
    raise ValueError(f"Unknown target: {target_name}")


def default_departments(target: dict) -> list[str]:
    return normalize_departments(target.get("default_departments"), ALL_DEPARTMENTS)


def read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def qa_score_from_summary(summary: dict) -> int | None:
    if not isinstance(summary, dict):
        return None
    critical = int(summary.get("critical", 0))
    high = int(summary.get("high", 0))
    medium = int(summary.get("medium", 0))
    low = int(summary.get("low", 0))
    return max(0, 100 - critical * 15 - high * 8 - medium * 3 - low)


def summarize_department(repo_dir: str, department: str) -> dict:
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

    score = None
    if department == "qa":
        score = qa_score_from_summary(summary)
    elif isinstance(summary, dict):
        score = summary.get(SCORE_FIELDS.get(department, ""), None)

    return {
        "department": department,
        "status": "complete",
        "findings_path": findings_path,
        "scanned_at": (
            payload.get("scanned_at")
            or payload.get("timestamp")
            or (summary.get("scanned_at") if isinstance(summary, dict) else None)
        ),
        "findings_total": total,
        "score": score,
        "summary": summary if isinstance(summary, dict) else {},
        "summary_text": payload.get("summary") if isinstance(payload.get("summary"), str) else None,
    }


def collect_target_snapshot(target: dict) -> dict:
    repo_name = target["name"]
    repo_dir = os.path.join(RESULTS_DIR, repo_name)
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


def write_audit_log(targets: list[dict]) -> None:
    snapshots = [collect_target_snapshot(target) for target in targets]
    history = read_json(os.path.join(RESULTS_DIR, ".jobs-history.json")) or []
    payload = {
        "generated_at": iso_now(),
        "targets": snapshots,
        "recent_runs": history[-20:],
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(AUDIT_LOG_JSON, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    with open(AUDIT_LOG_DASH_JSON, "w") as f:
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

    with open(AUDIT_LOG_MD, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    with open(AUDIT_LOG_DASH_MD, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def refresh_dashboard_artifacts(targets: list[dict]) -> None:
    subprocess.run(
        ["python3", AGGREGATE_SCRIPT, RESULTS_DIR, os.path.join(DASHBOARD_DIR, "data.json")],
        cwd=QA_ROOT,
        check=True,
    )
    write_audit_log(targets)


def run_job_status(command: str, *args: str) -> None:
    subprocess.run(["bash", JOB_STATUS_SCRIPT, command, *args], cwd=QA_ROOT, check=True)


def run_department(target: dict, department: str) -> None:
    repo_path = target["path"]
    script = DEPARTMENT_SCRIPTS[department]
    subprocess.run(["bash", script, repo_path], cwd=QA_ROOT, check=True)


def run_target(target: dict, departments: list[str], refresh: bool = True) -> None:
    repo_path = target["path"]
    run_job_status("init", repo_path, " ".join(departments))
    try:
        for department in departments:
            run_department(target, department)
    finally:
        jobs_file = os.path.join(RESULTS_DIR, ".jobs.json")
        if os.path.exists(jobs_file):
            try:
                run_job_status("finalize")
            except subprocess.CalledProcessError:
                pass


def with_run_lock(fn):
    def _wrapped(args):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(RUN_LOCK_FILE, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(
                    "Another local audit workflow is already running. Wait for it to finish before starting a new target."
                ) from exc
            return fn(args)

    return _wrapped


@with_run_lock
def handle_list_targets(args) -> int:
    targets = load_targets(args.config)
    for target in targets:
        print(f"{target['name']}: {target['path']}")
    return 0


@with_run_lock
def handle_refresh(args) -> int:
    targets = load_targets(args.config)
    refresh_dashboard_artifacts(targets)
    print("Refreshed dashboard data, self-audit data, and local audit log.")
    return 0


@with_run_lock
def handle_run_target(args) -> int:
    targets = load_targets(args.config)
    target = resolve_target(targets, args.target)
    departments = normalize_departments(args.departments, default_departments(target))
    run_target(target, departments)
    refresh_dashboard_artifacts(targets)
    print(f"Completed local audit for {target['name']}: {', '.join(departments)}")
    return 0


@with_run_lock
def handle_run_all(args) -> int:
    targets = load_targets(args.config)
    selected_targets = targets
    if args.targets:
        wanted = {item.strip() for item in args.targets.split(",") if item.strip()}
        selected_targets = [target for target in targets if target["name"] in wanted]
    for target in selected_targets:
        departments = normalize_departments(args.departments, default_departments(target))
        print(f"==> {target['name']}: {', '.join(departments)}")
        run_target(target, departments)
    refresh_dashboard_artifacts(targets)
    print(f"Completed local audits for {len(selected_targets)} target(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
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


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "list-targets": handle_list_targets,
        "refresh": handle_refresh,
        "run-target": handle_run_target,
        "run-all": handle_run_all,
    }
    try:
        return handlers[args.command](args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
