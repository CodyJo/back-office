#!/usr/bin/env python3
"""Write a compact status snapshot for the current Back Office audit run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
STATUS_MD = REPO_ROOT / "SCAN-STATUS.md"
STATUS_JSON = RESULTS_DIR / "scan-status.json"
JOBS_JSON = RESULTS_DIR / ".jobs.json"

DEPARTMENTS = {
    "qa": ("findings.json", "score"),
    "seo": ("seo-findings.json", "seo_score"),
    "ada": ("ada-findings.json", "compliance_score"),
    "compliance": ("compliance-findings.json", "compliance_score"),
    "monetization": ("monetization-findings.json", "monetization_readiness_score"),
    "product": ("product-findings.json", "product_readiness_score"),
    "cloud-ops": ("cloud-ops-findings.json", "cloud_ops_score"),
}


def load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def extract_score(payload: dict, score_key: str) -> int | float | None:
    summary = payload.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get(score_key), (int, float)):
        return summary[score_key]
    if isinstance(payload.get(score_key), (int, float)):
        return payload[score_key]
    return None


def summarize_department(repo_name: str, department: str) -> dict:
    filename, score_key = DEPARTMENTS[department]
    path = RESULTS_DIR / repo_name / filename
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {
            "department": department,
            "status": "missing",
            "file": str(path.relative_to(REPO_ROOT)),
            "scanned_at": None,
            "total": None,
            "score": None,
        }

    summary = payload.get("summary")
    findings = payload.get("findings")
    total = None
    if isinstance(summary, dict):
        total = summary.get("total", summary.get("total_findings"))
    if total is None and isinstance(findings, list):
        total = len(findings)

    scanned_at = payload.get("scanned_at")
    if scanned_at is None and isinstance(summary, dict):
        scanned_at = summary.get("scanned_at")

    return {
        "department": department,
        "status": "complete",
        "file": str(path.relative_to(REPO_ROOT)),
        "scanned_at": scanned_at,
        "total": total,
        "score": extract_score(payload, score_key),
    }


def summarize_target(repo_name: str) -> dict:
    departments = [summarize_department(repo_name, department) for department in DEPARTMENTS]
    completed = [item for item in departments if item["status"] == "complete"]
    latest_scan = max((item["scanned_at"] for item in completed if item["scanned_at"]), default=None)
    return {
        "repo_name": repo_name,
        "latest_scan": latest_scan,
        "completed_departments": len(completed),
        "total_departments": len(departments),
        "departments": departments,
    }


def load_job_state() -> dict | None:
    payload = load_json(JOBS_JSON)
    return payload if isinstance(payload, dict) else None


def build_markdown(snapshot: dict) -> str:
    lines = [
        "# Back Office Scan Status",
        "",
        f"Last updated: `{snapshot['updated_at']}`",
        "",
        "This file is a local progress snapshot for the current Bunny product audit run.",
        "",
    ]

    job = snapshot.get("job_state")
    if job:
        lines.extend(
            [
                "## Active Job",
                "",
                f"- Run ID: `{job.get('run_id') or 'unknown'}`",
                f"- Repo: `{job.get('repo_name') or 'unknown'}`",
                f"- Status: `{job.get('status') or 'unknown'}`",
                f"- Started: `{job.get('started_at') or 'unknown'}`",
                f"- Finished: `{job.get('finished_at') or 'not finished'}`",
                "",
                "| Department | Status | Findings | Score | Exit |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name, payload in (job.get("jobs") or {}).items():
            lines.append(
                f"| {name} | {payload.get('status') or 'unknown'} | "
                f"{payload.get('findings_count') if payload.get('findings_count') is not None else '-'} | "
                f"{payload.get('score') if payload.get('score') is not None else '-'} | "
                f"{payload.get('exit_code') if payload.get('exit_code') is not None else '-'} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Target Snapshot",
            "",
            "| Repo | Progress | Latest Scan | Notes |",
            "|---|---:|---|---|",
        ]
    )
    for target in snapshot["targets"]:
        progress = f"{target['completed_departments']}/{target['total_departments']}"
        notes = []
        for item in target["departments"]:
            if item["status"] == "complete":
                bits = [item["department"]]
                if item["total"] is not None:
                    bits.append(f"findings={item['total']}")
                if item["score"] is not None:
                    bits.append(f"score={item['score']}")
                notes.append(", ".join(bits))
        note_text = "; ".join(notes[-3:]) if notes else "No current findings artifact"
        lines.append(
            f"| {target['repo_name']} | {progress} | {target['latest_scan'] or '-'} | {note_text} |"
        )

    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- Markdown status: `{STATUS_MD.relative_to(REPO_ROOT)}`",
            f"- JSON status: `{STATUS_JSON.relative_to(REPO_ROOT)}`",
            f"- Active job state: `{JOBS_JSON.relative_to(REPO_ROOT)}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a Back Office scan status snapshot")
    parser.add_argument("--targets", required=True, help="Comma-separated repo names")
    args = parser.parse_args()

    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    snapshot = {
        "updated_at": iso_now(),
        "job_state": load_job_state(),
        "targets": [summarize_target(repo_name) for repo_name in targets],
    }

    STATUS_JSON.write_text(json.dumps(snapshot, indent=2) + "\n")
    STATUS_MD.write_text(build_markdown(snapshot) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
