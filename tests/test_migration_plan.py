"""Tests for the migration planning model."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from backoffice import migration_plan


def test_load_seeds_default_plan_when_missing(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()

    payload = migration_plan.load(tmp_path)

    assert payload["goal"]
    assert payload["summary"]["bunny_targets"] >= 1
    assert (tmp_path / "config" / "migration-plan.yaml").exists()
    assert (tmp_path / "dashboard" / "migration-plan.json").exists()


def test_update_item_persists_repository_status_and_target(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()
    seeded = migration_plan.load(tmp_path)

    repo_id = seeded["repositories"][0]["id"]
    updated = migration_plan.update_item(
        tmp_path,
        "repositories",
        repo_id,
        status="blocked",
        target="hybrid",
        notes="Waiting on IAM bootstrap",
        next_step="Finish Scaleway instance baseline",
    )

    repo = next(item for item in updated["repositories"] if item["id"] == repo_id)
    assert repo["status"] == "blocked"
    assert repo["target"] == "hybrid"
    assert repo["notes"] == "Waiting on IAM bootstrap"

    persisted = yaml.safe_load((tmp_path / "config" / "migration-plan.yaml").read_text())
    repo_yaml = next(item for item in persisted["repositories"] if item["id"] == repo_id)
    assert repo_yaml["target"] == "hybrid"


def test_update_item_persists_domain_targets(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()
    seeded = migration_plan.load(tmp_path)

    domain_id = seeded["domains"][0]["id"]
    updated = migration_plan.update_item(
        tmp_path,
        "domains",
        domain_id,
        status="in_progress",
        dns_target="bunny",
        registration_target="keep-current",
        notes="Temporary exception",
    )

    domain = next(item for item in updated["domains"] if item["id"] == domain_id)
    assert domain["dns_target"] == "bunny"
    assert domain["registration_target"] == "keep-current"
    assert domain["status"] == "in_progress"


def test_add_update_caps_log_and_mirrors_json(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()
    migration_plan.load(tmp_path)

    for idx in range(55):
        migration_plan.add_update(tmp_path, actor="tester", message=f"update {idx}")

    payload = json.loads((tmp_path / "dashboard" / "migration-plan.json").read_text())
    assert len(payload["updates"]) == 50
    assert payload["updates"][0]["message"] == "update 54"


def test_seed_wave_one_tasks_creates_queue_entries(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "config" / "targets.yaml").write_text(
        "targets:\n"
        "  - name: back-office\n"
        f"    path: {tmp_path}\n"
        "    language: python\n"
        "  - name: codyjo.com\n"
        f"    path: {tmp_path / 'codyjo.com'}\n"
        "    language: astro\n"
        "  - name: auth-service\n"
        f"    path: {tmp_path / 'auth-service'}\n"
        "    language: node\n"
        "  - name: certstudy\n"
        f"    path: {tmp_path / 'certstudy'}\n"
        "    language: typescript\n"
        "  - name: fuel\n"
        f"    path: {tmp_path / 'fuel'}\n"
        "    language: typescript\n"
    )

    result = migration_plan.seed_wave_one_tasks(tmp_path)

    assert len(result["created_task_ids"]) == 5
    queue_payload = json.loads((tmp_path / "results" / "task-queue.json").read_text())
    assert queue_payload["summary"]["total"] == 5
    assert queue_payload["summary"]["in_progress"] == 1
