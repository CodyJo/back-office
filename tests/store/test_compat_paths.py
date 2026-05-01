"""Compatibility tests: FileStore must use the same on-disk paths
and produce byte-equivalent payloads compared to the legacy direct-write
code in ``backoffice.tasks``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backoffice.domain import Task
from backoffice.store import FileStore, TaskQueueState
from backoffice.tasks import build_dashboard_payload, ensure_task_defaults


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_QUEUE = REPO_ROOT / "config" / "task-queue.yaml"


# ──────────────────────────────────────────────────────────────────────
# Path layout
# ──────────────────────────────────────────────────────────────────────


def test_default_paths_match_legacy_layout(tmp_path: Path):
    """FileStore must default to today's paths exactly so the dashboard,
    sync engine, and CLI continue to work without rewiring."""
    store = FileStore(root=tmp_path)
    assert store.task_queue_path() == tmp_path / "config" / "task-queue.yaml"
    assert store.task_queue_results_mirror_path() == tmp_path / "results" / "task-queue.json"
    assert (
        store.task_queue_dashboard_mirror_path()
        == tmp_path / "dashboard" / "task-queue.json"
    )
    assert store.audit_log_path() == tmp_path / "results" / "audit-events.jsonl"


def test_custom_dirs_override_defaults(tmp_path: Path):
    store = FileStore(
        root=tmp_path,
        config_dir=tmp_path / "alt-config",
        results_dir=tmp_path / "alt-results",
        dashboard_dir=tmp_path / "alt-dashboard",
    )
    assert store.task_queue_path() == tmp_path / "alt-config" / "task-queue.yaml"
    assert store.task_queue_results_mirror_path() == tmp_path / "alt-results" / "task-queue.json"
    assert store.task_queue_dashboard_mirror_path() == tmp_path / "alt-dashboard" / "task-queue.json"
    assert store.audit_log_path() == tmp_path / "alt-results" / "audit-events.jsonl"


# ──────────────────────────────────────────────────────────────────────
# Live config/task-queue.yaml round-trip
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not LIVE_QUEUE.exists(), reason="config/task-queue.yaml not present")
def test_file_store_loads_live_queue_without_data_loss(tmp_path: Path):
    """Copy the live queue into a sandboxed root, load via FileStore,
    save back, and confirm the canonical YAML round-trips losslessly."""
    sandbox = tmp_path / "config"
    sandbox.mkdir()
    target = sandbox / "task-queue.yaml"
    raw_text = LIVE_QUEUE.read_text()
    target.write_text(raw_text)

    store = FileStore(root=tmp_path)
    state = store.load_task_queue()

    assert state.tasks, "expected the live queue to have at least one task"

    # Each task must round-trip through the canonical legacy form.
    raw = yaml.safe_load(raw_text)
    expected = [ensure_task_defaults(t, targets={}) for t in raw.get("tasks", [])]
    actual = [t.to_dict() for t in state.tasks]
    assert actual == expected


# ──────────────────────────────────────────────────────────────────────
# Byte-level mirror compatibility with backoffice.tasks
# ──────────────────────────────────────────────────────────────────────


def test_mirror_json_structurally_matches_legacy(tmp_path: Path, monkeypatch):
    """FileStore.save_task_queue must write a JSON mirror that parses
    to the same payload as the legacy ``backoffice.tasks.save_payload``
    path. Key order may differ — Task.to_dict() emits a fixed schema —
    but readers compare by content, never by byte order.
    """
    fixed = "2026-04-29T13:00:00+00:00"
    monkeypatch.setattr("backoffice.tasks.iso_now", lambda: fixed)

    task_dict = ensure_task_defaults(
        {"id": "t1", "repo": "back-office", "title": "x", "status": "ready"},
        targets={},
    )

    # Legacy: build_dashboard_payload directly on the canonical dict.
    legacy_payload = build_dashboard_payload([task_dict])

    # New: route through Task model and FileStore.
    store = FileStore(root=tmp_path)
    state = TaskQueueState(version=1, tasks=[Task.from_dict(task_dict)])
    store.save_task_queue(state)

    written_results = json.loads(store.task_queue_results_mirror_path().read_text())
    written_dashboard = json.loads(store.task_queue_dashboard_mirror_path().read_text())
    assert written_results == legacy_payload
    assert written_dashboard == legacy_payload


def test_legacy_save_payload_remains_byte_identical(tmp_path: Path, monkeypatch):
    """The migrated ``backoffice.tasks.save_payload`` still produces the
    same bytes as before — atomicity was added without rewriting the
    payload pipeline, so on-disk format is unchanged."""
    from backoffice.tasks import save_payload

    fixed = "2026-04-29T13:00:00+00:00"
    monkeypatch.setattr("backoffice.tasks.iso_now", lambda: fixed)

    config_path = tmp_path / "config" / "task-queue.yaml"
    results_dir = tmp_path / "results"
    dashboard_dir = tmp_path / "dashboard"
    payload = {
        "version": 1,
        "tasks": [{"id": "t1", "repo": "back-office", "title": "x", "status": "ready"}],
    }
    save_payload(payload, {}, config_path, results_dir, dashboard_dir)

    # Reproduce the legacy bytes locally.
    canonical = {
        "version": 1,
        "tasks": [
            ensure_task_defaults(
                {"id": "t1", "repo": "back-office", "title": "x", "status": "ready"},
                targets={},
            )
        ],
    }
    expected_yaml = yaml.safe_dump(canonical, sort_keys=False)
    expected_dashboard = build_dashboard_payload(canonical["tasks"])
    expected_json = json.dumps(expected_dashboard, indent=2, default=str) + "\n"

    assert config_path.read_text() == expected_yaml
    assert (results_dir / "task-queue.json").read_text() == expected_json
    assert (dashboard_dir / "task-queue.json").read_text() == expected_json


def test_filestore_yaml_structurally_matches_safe_dump(tmp_path: Path):
    """FileStore writes via yaml.safe_dump — bytes from the new path
    parse to the same structured value as the legacy serializer."""
    task_dict = ensure_task_defaults(
        {"id": "t1", "repo": "back-office", "title": "x", "status": "ready"},
        targets={},
    )
    state = TaskQueueState(version=1, tasks=[Task.from_dict(task_dict)])
    expected_text = yaml.safe_dump(state.to_dict(), sort_keys=False)

    store = FileStore(root=tmp_path)
    store.save_task_queue(state)
    # Bytes match because we use the same yaml.safe_dump under the hood.
    assert store.task_queue_path().read_text() == expected_text
    # Round-trip parses to the same structure.
    assert yaml.safe_load(store.task_queue_path().read_text()) == state.to_dict()
