#!/usr/bin/env python3
"""Generate delivery automation metadata for the Back Office dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

QA_ROOT = Path(
    os.environ.get(
        "BACK_OFFICE_ROOT",
        Path(__file__).resolve().parents[1],
    )
)
CONFIG_PATH = Path(os.environ.get("BACK_OFFICE_TARGETS_CONFIG", QA_ROOT / "config" / "targets.yaml"))
EXAMPLE_CONFIG_PATH = QA_ROOT / "config" / "targets.example.yaml"
RESULTS_DIR = Path(os.environ.get("BACK_OFFICE_RESULTS_DIR", QA_ROOT / "results"))
DASHBOARD_DIR = Path(os.environ.get("BACK_OFFICE_DASHBOARD_DIR", QA_ROOT / "dashboard"))
OUTPUT_PATH = Path(os.environ.get("BACK_OFFICE_DELIVERY_OUTPUT", DASHBOARD_DIR / "automation-data.json"))

WORKFLOW_FILE_GLOBS = ("*.yml", "*.yaml")
SAFE_EFFORTS = {"tiny", "small", "low", "medium"}
SAFE_SEVERITIES = {"info", "low", "medium"}
RISKY_KEYWORDS = (
    "auth",
    "login",
    "register",
    "password",
    "token",
    "jwt",
    "payment",
    "billing",
    "subscription",
    "privacy",
    "consent",
    "gdpr",
    "security",
    "iam",
    "terraform",
    "cloudfront",
    "database migration",
    "dynamodb",
)
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
DEPARTMENT_FILES = {
    "qa": "findings.json",
    "seo": "seo-findings.json",
    "ada": "ada-findings.json",
    "compliance": "compliance-findings.json",
    "privacy": "privacy-findings.json",
    "monetization": "monetization-findings.json",
    "product": "product-findings.json",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path):
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def load_targets_config():
    if CONFIG_PATH.exists():
        return load_yaml(CONFIG_PATH)
    if EXAMPLE_CONFIG_PATH.exists():
        return load_yaml(EXAMPLE_CONFIG_PATH)
    return {"targets": []}


def load_json(path: Path):
    try:
        with path.open() as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_workflows(repo_path: Path) -> list[dict]:
    workflow_dir = repo_path / ".github" / "workflows"
    files = []
    if not workflow_dir.exists():
        return files
    for pattern in WORKFLOW_FILE_GLOBS:
        files.extend(sorted(workflow_dir.glob(pattern)))

    workflows = []
    for file_path in files:
        content = file_path.read_text()
        try:
            parsed = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            parsed = {}
        workflows.append(
            {
                "file": file_path.name,
                "name": parsed.get("name") or file_path.stem,
                "on": parsed.get("on"),
                "jobs": list((parsed.get("jobs") or {}).keys()),
                "content": content,
            }
        )
    return workflows


def contains_schedule(trigger) -> bool:
    if isinstance(trigger, dict):
        return "schedule" in trigger
    if isinstance(trigger, list):
        return "schedule" in trigger
    return trigger == "schedule"


def contains_pull_request(trigger) -> bool:
    if isinstance(trigger, dict):
        return "pull_request" in trigger
    if isinstance(trigger, list):
        return "pull_request" in trigger
    return trigger == "pull_request"


def contains_push_main(trigger) -> bool:
    if not isinstance(trigger, dict):
        return False
    push = trigger.get("push")
    if push is True:
        return True
    if isinstance(push, dict):
        branches = push.get("branches") or []
        return "main" in branches or not branches
    return False


def detect_workflow_status(workflows: list[dict]) -> dict:
    statuses = {
        "ci": {"configured": False, "workflow": "", "status": "missing"},
        "preview": {"configured": False, "workflow": "", "status": "missing"},
        "cd": {"configured": False, "workflow": "", "status": "missing"},
        "nightly": {"configured": False, "workflow": "", "status": "missing"},
    }

    for workflow in workflows:
        file_name = workflow["file"].lower()
        name = workflow["name"].lower()
        content = workflow["content"].lower()
        trigger = workflow["on"]

        if (
            contains_pull_request(trigger)
            or "ci" in file_name
            or "validate" in name
            or "test" in name
        ) and not statuses["ci"]["configured"]:
            statuses["ci"] = {
                "configured": True,
                "workflow": workflow["file"],
                "status": "configured",
            }

        if (
            "preview" in file_name
            or "preview" in name
            or "staging" in name
            or "environment: staging" in content
            or "environment: preview" in content
            or "preview-url" in content
        ) and not statuses["preview"]["configured"]:
            statuses["preview"] = {
                "configured": True,
                "workflow": workflow["file"],
                "status": "configured",
            }

        if (
            contains_push_main(trigger)
            or "deploy" in file_name
            or "deploy" in name
            or "environment: production" in content
        ) and not statuses["cd"]["configured"]:
            statuses["cd"] = {
                "configured": True,
                "workflow": workflow["file"],
                "status": "configured",
            }

        if (
            contains_schedule(trigger)
            or "nightly" in file_name
            or "nightly" in name
            or "schedule:" in content
            or "backoffice" in file_name
        ) and not statuses["nightly"]["configured"]:
            statuses["nightly"] = {
                "configured": True,
                "workflow": workflow["file"],
                "status": "configured",
            }

    return statuses


def read_package_scripts(repo_path: Path) -> dict:
    package_json = load_json(repo_path / "package.json")
    if not package_json:
        return {}
    scripts = package_json.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def detect_command_coverage(target: dict, repo_path: Path) -> dict:
    package_scripts = read_package_scripts(repo_path) if repo_path.exists() else {}

    def has_script(*names: str) -> bool:
        return any(name in package_scripts for name in names)

    return {
        "lint": {
            "configured": bool(target.get("lint_command")),
            "status": "configured" if target.get("lint_command") else "missing",
            "command": target.get("lint_command", ""),
            "script_detected": has_script("lint", "check"),
        },
        "test": {
            "configured": bool(target.get("test_command")),
            "status": "configured" if target.get("test_command") else "missing",
            "command": target.get("test_command", ""),
            "script_detected": has_script("test"),
        },
        "build": {
            "configured": bool(target.get("deploy_command")),
            "status": "configured" if target.get("deploy_command") else "missing",
            "command": target.get("deploy_command", ""),
            "script_detected": has_script("build"),
        },
    }


def find_product_key(repo_name: str, products: list[dict]) -> str:
    for product in products:
        if repo_name in (product.get("repos") or []):
            return product.get("key", "all")
    return "all"


def read_findings(repo_name: str) -> dict:
    repo_dir = RESULTS_DIR / repo_name
    findings = {}
    for department, filename in DEPARTMENT_FILES.items():
        payload = load_json(repo_dir / filename)
        if payload:
            findings[department] = payload.get("findings") or []
    return findings


def is_safe_candidate(department: str, finding: dict) -> bool:
    severity = str(finding.get("severity", "info")).lower()
    effort = str(finding.get("effort", "")).lower()
    status = str(finding.get("status", "open")).lower()
    title = " ".join(
        str(finding.get(field, "")).lower()
        for field in ("title", "category", "description", "fix", "file")
    )
    fixable = bool(finding.get("fixable") or finding.get("fixable_by_agent"))

    if department in {"compliance", "privacy"}:
      return False
    if status not in {"open", "in-progress", ""}:
        return False
    if not fixable:
        return False
    if severity not in SAFE_SEVERITIES:
        return False
    if effort and effort not in SAFE_EFFORTS:
        return False
    return not any(keyword in title for keyword in RISKY_KEYWORDS)


def overnight_bucket(finding: dict) -> str:
    severity = str(finding.get("severity", "info")).lower()
    effort = str(finding.get("effort", "")).lower()
    if severity in {"low", "info"} and effort in {"tiny", "small", "low"}:
        return "Overnight Now"
    if severity == "medium" and effort in {"small", "medium", "low"}:
        return "Next Overnight"
    return "Needs Review"


def sprint_bucket(finding: dict) -> str:
    phase = str(finding.get("priority_phase", "")).lower()
    if phase == "must-have":
        return "Sprint Now"
    if phase == "should-have":
        return "Next Sprint"
    if phase == "nice-to-have":
        return "Later Sprint"
    severity = str(finding.get("severity", "info")).lower()
    if severity in {"critical", "high"}:
        return "Sprint Now"
    if severity == "medium":
        return "Next Sprint"
    return "Backlog"


def summarize_candidates(repo_name: str, findings_by_department: dict) -> dict:
    candidates = []
    sprint_map: dict[str, list[dict]] = {}
    for department, findings in findings_by_department.items():
        for finding in findings:
            if is_safe_candidate(department, finding):
                candidate = {
                    "repo": repo_name,
                    "department": department,
                    "id": finding.get("id", ""),
                    "title": finding.get("title", "Untitled finding"),
                    "severity": str(finding.get("severity", "info")).lower(),
                    "effort": str(finding.get("effort", "unknown")).lower(),
                    "file": finding.get("file", ""),
                    "reason": "Low-risk, fixable, and testable for unattended work.",
                    "bucket": overnight_bucket(finding),
                }
                candidates.append(candidate)

            if department == "product":
                lane = sprint_bucket(finding)
                sprint_map.setdefault(lane, []).append(
                    {
                        "repo": repo_name,
                        "title": finding.get("title", "Untitled finding"),
                        "severity": str(finding.get("severity", "info")).lower(),
                        "effort": str(finding.get("effort", "unknown")).lower(),
                        "status": str(finding.get("status", "open")).lower(),
                    }
                )

    candidates.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["title"]))
    ordered_lanes = []
    for lane in ("Sprint Now", "Next Sprint", "Later Sprint", "Backlog"):
        items = sprint_map.get(lane, [])
        if not items:
            continue
        items.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["title"]))
        ordered_lanes.append({"lane": lane, "items": items[:6]})

    return {
        "safe_candidate_count": len(candidates),
        "safe_candidates": candidates[:12],
        "sprint_lanes": ordered_lanes,
    }


def delivery_readiness(workflows: dict, commands: dict, candidate_count: int) -> int:
    score = 0
    score += 30 if workflows["ci"]["configured"] else 0
    score += 20 if commands["test"]["configured"] else 0
    score += 15 if commands["lint"]["configured"] else 0
    score += 15 if commands["build"]["configured"] else 0
    score += 10 if workflows["preview"]["configured"] else 0
    score += 5 if workflows["cd"]["configured"] else 0
    score += 5 if workflows["nightly"]["configured"] else 0
    if candidate_count:
        score += 5
    return min(score, 100)


def target_summary(target: dict, products: list[dict]) -> dict:
    repo_name = target["name"]
    repo_path = Path(target["path"])
    workflows = detect_workflow_status(list_workflows(repo_path)) if repo_path.exists() else detect_workflow_status([])
    commands = detect_command_coverage(target, repo_path)
    findings_by_department = read_findings(repo_name)
    candidate_summary = summarize_candidates(repo_name, findings_by_department)
    readiness = delivery_readiness(workflows, commands, candidate_summary["safe_candidate_count"])

    return {
        "repo": repo_name,
        "path": str(repo_path),
        "product_key": find_product_key(repo_name, products),
        "language": target.get("language", ""),
        "workflows": workflows,
        "commands": commands,
        "delivery_readiness": readiness,
        "overnight": {
            "safe_candidate_count": candidate_summary["safe_candidate_count"],
            "safe_candidates": candidate_summary["safe_candidates"],
        },
        "sprints": candidate_summary["sprint_lanes"],
        "pr_status": "pr-required" if workflows["ci"]["configured"] else "workflow-missing",
        "preview_status": "configured" if workflows["preview"]["configured"] else "missing",
        "production_status": "approval-gated" if workflows["cd"]["configured"] else "missing",
        "nightly_status": "scheduled" if workflows["nightly"]["configured"] else "missing",
    }


def main() -> int:
    config = load_targets_config()
    targets = config.get("targets") or []
    org_data = load_json(DASHBOARD_DIR / "org-data.json") or {"products": []}

    payload = {
        "generated_at": iso_now(),
        "targets": [target_summary(target, org_data.get("products") or []) for target in targets],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
