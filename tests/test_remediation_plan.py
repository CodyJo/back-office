"""Tests for the QA remediation planning model."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from backoffice import remediation_plan


def test_load_seeds_default_plan_when_missing(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()

    payload = remediation_plan.load(tmp_path)

    assert payload["summary"]["wave_count"] == 4
    assert payload["summary"]["repository_count"] >= 4
    assert (tmp_path / "config" / "remediation-plan.yaml").exists()
    assert (tmp_path / "dashboard" / "remediation-plan.json").exists()


def test_saved_yaml_round_trips_summary_data(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()

    payload = remediation_plan.load(tmp_path)

    persisted = yaml.safe_load((tmp_path / "config" / "remediation-plan.yaml").read_text())
    assert persisted["waves"][0]["id"] == payload["waves"][0]["id"]
    assert persisted["approval_checkpoints"][0]["id"] == "checkpoint-1"


def test_load_builds_plan_from_live_findings(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results" / "auth-service").mkdir(parents=True)
    (tmp_path / "results" / "back-office").mkdir(parents=True)
    (tmp_path / "dashboard").mkdir()

    (tmp_path / "results" / "auth-service" / "findings.json").write_text(
        json.dumps(
            {
                "repo_name": "auth-service",
                "findings": [
                    {"severity": "critical", "title": "Case-Insensitive Admin Allowlist Check Is Vulnerable to Homograph Attacks"},
                    {"severity": "high", "title": "Missing Email Validation Code Flow Issue"},
                ],
            }
        )
    )
    (tmp_path / "results" / "back-office" / "findings.json").write_text(
        json.dumps(
            {
                "repo_name": "back-office",
                "findings": [
                    {"severity": "critical", "title": "Path Traversal via user-supplied local_path parameter in product approval endpoint"},
                ],
            }
        )
    )

    payload = remediation_plan.load(tmp_path)

    assert payload["summary"]["repository_count"] == 2
    assert payload["summary"]["wave_count"] == 1
    repo_names = [repo["repo"] for repo in payload["waves"][0]["repositories"]]
    assert repo_names == ["auth-service", "back-office"]
    assert payload["waves"][0]["repositories"][0]["findings"][0]["title"]


def test_seed_wave_one_tasks_creates_queue_entries(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "results" / "back-office").mkdir()
    (tmp_path / "results" / "auth-service").mkdir()
    (tmp_path / "results" / "continuum").mkdir()
    (tmp_path / "results" / "pe-bootstrap").mkdir()
    (tmp_path / "config" / "targets.yaml").write_text(
        "targets:\n"
        "  - name: back-office\n"
        f"    path: {tmp_path}\n"
        "    language: python\n"
        "  - name: auth-service\n"
        f"    path: {tmp_path / 'auth-service'}\n"
        "    language: node\n"
        "  - name: continuum\n"
        f"    path: {tmp_path / 'continuum'}\n"
        "    language: typescript\n"
        "  - name: pe-bootstrap\n"
        f"    path: {tmp_path / 'pe-bootstrap'}\n"
        "    language: python\n"
    )
    (tmp_path / "results" / "back-office" / "findings.json").write_text(
        json.dumps({"repo_name": "back-office", "findings": [{"severity": "critical", "title": "x"}]})
    )
    (tmp_path / "results" / "auth-service" / "findings.json").write_text(
        json.dumps({"repo_name": "auth-service", "findings": [{"severity": "critical", "title": "x"}]})
    )
    (tmp_path / "results" / "continuum" / "findings.json").write_text(
        json.dumps({"repo_name": "continuum", "findings": [{"severity": "critical", "title": "x"}]})
    )
    (tmp_path / "results" / "pe-bootstrap" / "findings.json").write_text(
        json.dumps({"repo_name": "pe-bootstrap", "findings": [{"severity": "critical", "title": "x"}]})
    )

    result = remediation_plan.seed_wave_one_tasks(tmp_path)

    assert len(result["created_task_ids"]) == 4
    queue_payload = json.loads((tmp_path / "results" / "task-queue.json").read_text())
    assert queue_payload["summary"]["total"] == 4
    assert queue_payload["summary"]["pending_approval"] == 4


def test_update_item_persists_wave_and_repo_status(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results" / "back-office").mkdir(parents=True)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "results" / "back-office" / "findings.json").write_text(
        json.dumps({"repo_name": "back-office", "findings": [{"severity": "critical", "title": "x"}]})
    )

    remediation_plan.load(tmp_path)
    updated = remediation_plan.update_item(tmp_path, "waves", "wave-1", status="in_progress", notes="Wave started")
    assert updated["waves"][0]["status"] == "in_progress"
    assert updated["waves"][0]["notes"] == "Wave started"

    updated = remediation_plan.update_item(tmp_path, "repositories", "back-office", status="blocked", notes="Waiting on review")
    repo = updated["waves"][0]["repositories"][0]
    assert repo["status"] == "blocked"
    assert repo["notes"] == "Waiting on review"


def test_add_update_persists_entries(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results" / "back-office").mkdir(parents=True)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "results" / "back-office" / "findings.json").write_text(
        json.dumps({"repo_name": "back-office", "findings": [{"severity": "critical", "title": "x"}]})
    )

    remediation_plan.load(tmp_path)
    payload = remediation_plan.add_update(tmp_path, actor="dashboard", message="Wave 1 kicked off", kind="status")

    assert payload["updates"][0]["message"] == "Wave 1 kicked off"
    stored = json.loads((tmp_path / "dashboard" / "remediation-plan.json").read_text())
    assert stored["updates"][0]["actor"] == "dashboard"
