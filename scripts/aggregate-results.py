#!/usr/bin/env python3
"""Aggregate all results/ subdirectories into department-specific dashboard JSON payloads."""

import json
import os
import sys
from datetime import datetime, timezone


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def aggregate_qa(results_dir, dashboard_dir):
    """Aggregate QA findings into qa-data.json (original behavior)."""
    repos = []
    totals = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0,
              "total_findings": 0, "total_fixed": 0, "total_failed": 0,
              "total_skipped": 0, "total_in_progress": 0}

    for repo_name in sorted(os.listdir(results_dir)):
        repo_dir = os.path.join(results_dir, repo_name)
        if not os.path.isdir(repo_dir):
            continue

        findings_data = load_json(os.path.join(repo_dir, "findings.json"))
        fixes_data = load_json(os.path.join(repo_dir, "fixes.json"))

        if not findings_data:
            continue

        summary = findings_data.get("summary", {})
        findings = findings_data.get("findings", [])

        fix_map = {}
        if fixes_data:
            for fix in fixes_data.get("fixes", []):
                fix_map[fix["finding_id"]] = fix

        enriched = []
        for f in findings:
            fid = f["id"]
            fix_info = fix_map.get(fid, {})
            enriched.append({
                "id": fid,
                "severity": f["severity"],
                "category": f["category"],
                "title": f["title"],
                "file": f.get("file", ""),
                "line": f.get("line"),
                "effort": f.get("effort", "unknown"),
                "fixable": f.get("fixable_by_agent", False),
                "status": fix_info.get("status", "open"),
                "commit": fix_info.get("commit_hash", ""),
                "fixed_at": fix_info.get("fixed_at", ""),
            })

        fixed = sum(1 for e in enriched if e["status"] == "fixed")
        failed = sum(1 for e in enriched if e["status"] == "failed")
        skipped = sum(1 for e in enriched if e["status"] == "skipped")
        in_progress = sum(1 for e in enriched if e["status"] == "in-progress")

        totals["critical"] += summary.get("critical", 0)
        totals["high"] += summary.get("high", 0)
        totals["medium"] += summary.get("medium", 0)
        totals["low"] += summary.get("low", 0)
        totals["info"] += summary.get("info", 0)
        totals["total_findings"] += summary.get("total", 0)
        totals["total_fixed"] += fixed
        totals["total_failed"] += failed
        totals["total_skipped"] += skipped
        totals["total_in_progress"] += in_progress

        repos.append({
            "name": repo_name,
            "scanned_at": findings_data.get("scanned_at", ""),
            "summary": summary,
            "fix_summary": {
                "fixed": fixed, "failed": failed, "skipped": skipped,
                "in_progress": in_progress,
                "open": len(enriched) - fixed - failed - skipped - in_progress,
            },
            "lint": findings_data.get("lint_results", {}),
            "tests": findings_data.get("test_results", {}),
            "findings": enriched,
        })

    return {
        "department": "qa",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "repos": repos,
    }


def aggregate_department(results_dir, findings_filename, department_name):
    """Aggregate department-specific findings across all repos."""
    repos = []
    totals = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0,
              "total_findings": 0}

    for repo_name in sorted(os.listdir(results_dir)):
        repo_dir = os.path.join(results_dir, repo_name)
        if not os.path.isdir(repo_dir):
            continue

        data = load_json(os.path.join(repo_dir, findings_filename))
        if not data:
            continue

        summary = data.get("summary", {})
        findings = data.get("findings", [])

        totals["critical"] += summary.get("critical", 0)
        totals["high"] += summary.get("high", 0)
        totals["medium"] += summary.get("medium", 0)
        totals["low"] += summary.get("low", 0)
        totals["info"] += summary.get("info", 0)
        totals["total_findings"] += summary.get("total", 0)

        repo_entry = {
            "name": repo_name,
            "scanned_at": data.get("scanned_at", ""),
            "summary": summary,
            "findings": [{
                "id": f["id"],
                "severity": f["severity"],
                "category": f["category"],
                "title": f["title"],
                "file": f.get("file", ""),
                "line": f.get("line"),
                "effort": f.get("effort", "unknown"),
                "fixable": f.get("fixable_by_agent", False),
                "status": "open",
            } for f in findings],
        }

        # Include department-specific metadata
        if "categories" in data:
            repo_entry["categories"] = data["categories"]
        if "frameworks" in data:
            repo_entry["frameworks"] = data["frameworks"]
        if "seo_score" in summary:
            repo_entry["seo_score"] = summary["seo_score"]
        if "compliance_score" in summary:
            repo_entry["compliance_score"] = summary["compliance_score"]
        if "wcag_level" in summary:
            repo_entry["wcag_level"] = summary["wcag_level"]

        repos.append(repo_entry)

    return {
        "department": department_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "repos": repos,
    }


def write_json(data, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def aggregate(results_dir, output_path):
    dashboard_dir = os.path.dirname(output_path) or "."

    # QA department (backward-compatible — also writes data.json)
    qa_data = aggregate_qa(results_dir, dashboard_dir)
    write_json(qa_data, output_path)  # data.json (backward compat)
    write_json(qa_data, os.path.join(dashboard_dir, "qa-data.json"))
    print(f"QA: {qa_data['totals']['total_findings']} findings across "
          f"{len(qa_data['repos'])} repos, {qa_data['totals']['total_fixed']} fixed")

    # SEO department
    seo_data = aggregate_department(results_dir, "seo-findings.json", "seo")
    write_json(seo_data, os.path.join(dashboard_dir, "seo-data.json"))
    print(f"SEO: {seo_data['totals']['total_findings']} findings across "
          f"{len(seo_data['repos'])} repos")

    # ADA department
    ada_data = aggregate_department(results_dir, "ada-findings.json", "ada")
    write_json(ada_data, os.path.join(dashboard_dir, "ada-data.json"))
    print(f"ADA: {ada_data['totals']['total_findings']} findings across "
          f"{len(ada_data['repos'])} repos")

    # Compliance department
    comp_data = aggregate_department(results_dir, "compliance-findings.json", "compliance")
    write_json(comp_data, os.path.join(dashboard_dir, "compliance-data.json"))
    print(f"Compliance: {comp_data['totals']['total_findings']} findings across "
          f"{len(comp_data['repos'])} repos")

    # Summary
    total = (qa_data["totals"]["total_findings"] + seo_data["totals"]["total_findings"] +
             ada_data["totals"]["total_findings"] + comp_data["totals"]["total_findings"])
    print(f"\nTotal across all departments: {total} findings")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: aggregate-results.py <results-dir> <output.json>",
              file=sys.stderr)
        sys.exit(1)
    aggregate(sys.argv[1], sys.argv[2])
