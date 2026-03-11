#!/usr/bin/env python3
"""Regression tests for the local audit workflow."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml


def check(name, condition, detail=""):
    if condition:
        return True
    message = f"FAIL: {name}"
    if detail:
        message += f" ({detail})"
    raise AssertionError(message)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "local_audit_workflow.py"
    aggregate = repo_root / "scripts" / "aggregate-results.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        targets_path = tmpdir / "targets.yaml"
        results_dir = tmpdir / "results"
        dashboard_dir = tmpdir / "dashboard"
        results_dir.mkdir()
        dashboard_dir.mkdir()

        targets = {
            "targets": [
                {
                    "name": "back-office",
                    "path": "/tmp/back-office",
                    "language": "shell",
                    "default_departments": ["qa"],
                    "context": "Self-audit target",
                },
                {
                    "name": "bible-app",
                    "path": "/tmp/bible-app",
                    "language": "typescript",
                    "default_departments": ["product", "qa"],
                    "context": "Product target",
                },
            ]
        }
        targets_path.write_text(yaml.safe_dump(targets, sort_keys=False))

        write_json(
            results_dir / "back-office" / "findings.json",
            {
                "repo": "back-office",
                "scanned_at": "2026-03-10T10:00:00+00:00",
                "summary": {"total": 1, "critical": 1, "high": 0, "medium": 0, "low": 0},
                "findings": [
                    {"id": "QA-1", "severity": "critical", "category": "security", "title": "Issue"}
                ],
            },
        )
        write_json(
            results_dir / "bible-app" / "product-findings.json",
            {
                "scanned_at": "2026-03-10T11:00:00+00:00",
                "summary": {"total": 2, "critical": 0, "high": 1, "medium": 1, "low": 0, "product_readiness_score": 78},
                "findings": [
                    {"id": "PROD-1", "severity": "high", "category": "ux", "title": "Gap"},
                    {"id": "PROD-2", "severity": "medium", "category": "feature", "title": "Gap 2"},
                ],
            },
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root)

        subprocess.run(
            [
                "python3",
                str(aggregate),
                str(results_dir),
                str(dashboard_dir / "data.json"),
            ],
            check=True,
            env=env,
        )

        subprocess.run(
            [
                "python3",
                str(script),
                "--config",
                str(targets_path),
                "refresh",
            ],
            cwd=repo_root,
            check=True,
            env={
                **env,
                "BACK_OFFICE_ROOT": str(tmpdir),
                "BACK_OFFICE_AGGREGATE_SCRIPT": str(aggregate),
            },
        )

        local_log = json.loads((dashboard_dir / "local-audit-log.json").read_text())
        check("audit_log_has_targets", len(local_log["targets"]) == 2)
        check(
            "back_office_defaults_to_qa",
            local_log["targets"][0]["default_departments"] == ["qa"],
            str(local_log["targets"][0]["default_departments"]),
        )
        back_office_dept = local_log["targets"][0]["department_results"][0]
        check("back_office_findings_count", back_office_dept["findings_total"] == 1)

        self_audit = json.loads((dashboard_dir / "self-audit-data.json").read_text())
        check("self_audit_generated", self_audit["repo"] == "back-office")

        md = (dashboard_dir / "local-audit-log.md").read_text()
        check("markdown_mentions_bible_app", "## bible-app" in md)

    print("local audit workflow tests passed")


if __name__ == "__main__":
    main()
