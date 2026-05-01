"""Tests for ``Store.transition_task``: state-machine validation, audit
emission, and queue persistence under the lock.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backoffice.domain import IllegalTransition
from backoffice.store import FileStore, TaskNotFound


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


def _seed_queue(store: FileStore, tasks: list[dict]) -> None:
    """Write *tasks* directly to the YAML so transition tests start
    from a known state. Bypasses save_task_queue so we don't depend
    on Phase 2 mirror logic."""
    raw = {"version": 1, "tasks": tasks}
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _task(task_id: str, status: str = "ready", **extras) -> dict:
    base = {
        "id": task_id,
        "repo": "back-office",
        "title": f"Task {task_id}",
        "status": status,
        "priority": "medium",
        "history": [],
    }
    base.update(extras)
    return base


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_transition_legal_move_returns_updated_task(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    task = store.transition_task("t1", "in_progress", actor="operator", reason="start")
    assert task.id == "t1"
    assert task.status == "in_progress"


def test_transition_writes_yaml_and_mirrors(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.transition_task("t1", "in_progress", actor="operator")
    raw = yaml.safe_load(store.task_queue_path().read_text())
    assert raw["tasks"][0]["status"] == "in_progress"
    assert store.task_queue_results_mirror_path().exists()
    assert store.task_queue_dashboard_mirror_path().exists()


def test_transition_appends_history_entry(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.transition_task(
        "t1", "in_progress", actor="operator", reason="manual start"
    )
    raw = yaml.safe_load(store.task_queue_path().read_text())
    history = raw["tasks"][0]["history"]
    assert any(
        h["status"] == "in_progress" and h["by"] == "operator" and h["note"] == "manual start"
        for h in history
    )


def test_transition_emits_one_audit_event(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.transition_task("t1", "in_progress", actor="operator", reason="start")
    events = store.read_audit_events()
    assert len(events) == 1
    evt = events[0]
    assert evt.action == "task.transition"
    assert evt.subject_kind == "task"
    assert evt.subject_id == "t1"
    assert evt.before == {"status": "ready"}
    assert evt.after == {"status": "in_progress"}
    assert evt.actor_id == "operator"
    assert evt.reason == "start"


def test_transition_preserves_other_task_fields(store: FileStore):
    """A transition must not lose unrelated keys on the task or queue."""
    seeded = _task(
        "t1",
        status="ready",
        product_key="back-office",
        target_path="/x",
        approval={"approved_by": "operator", "approved_at": "2026-04-29"},
        custom_field="must survive",
    )
    _seed_queue(store, [seeded])
    store.transition_task("t1", "in_progress", actor="operator")
    raw = yaml.safe_load(store.task_queue_path().read_text())
    task_dict = raw["tasks"][0]
    assert task_dict["custom_field"] == "must survive"
    assert task_dict["product_key"] == "back-office"
    assert task_dict["approval"]["approved_by"] == "operator"


def test_transition_updates_updated_at(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready", updated_at="2026-01-01T00:00:00+00:00")])
    store.transition_task("t1", "in_progress", actor="operator")
    raw = yaml.safe_load(store.task_queue_path().read_text())
    assert raw["tasks"][0]["updated_at"] != "2026-01-01T00:00:00+00:00"


# ──────────────────────────────────────────────────────────────────────
# Illegal transitions
# ──────────────────────────────────────────────────────────────────────


def test_transition_illegal_move_raises(store: FileStore):
    _seed_queue(store, [_task("t1", status="done")])
    with pytest.raises(IllegalTransition) as exc:
        store.transition_task("t1", "in_progress", actor="operator")
    assert exc.value.from_state == "done"
    assert exc.value.to_state == "in_progress"


def test_transition_illegal_does_not_mutate_queue(store: FileStore):
    seeded = _task("t1", status="done")
    _seed_queue(store, [seeded])
    before_text = store.task_queue_path().read_text()
    with pytest.raises(IllegalTransition):
        store.transition_task("t1", "in_progress", actor="operator")
    assert store.task_queue_path().read_text() == before_text


def test_transition_illegal_does_not_emit_audit(store: FileStore):
    _seed_queue(store, [_task("t1", status="done")])
    with pytest.raises(IllegalTransition):
        store.transition_task("t1", "in_progress", actor="operator")
    assert store.read_audit_events() == []


# ──────────────────────────────────────────────────────────────────────
# Missing tasks
# ──────────────────────────────────────────────────────────────────────


def test_transition_unknown_task_raises_task_not_found(store: FileStore):
    _seed_queue(store, [_task("other")])
    with pytest.raises(TaskNotFound):
        store.transition_task("missing", "in_progress", actor="operator")


def test_transition_against_empty_queue_raises_task_not_found(store: FileStore):
    with pytest.raises(TaskNotFound):
        store.transition_task("t1", "in_progress", actor="operator")


# ──────────────────────────────────────────────────────────────────────
# get_task
# ──────────────────────────────────────────────────────────────────────


def test_get_task_returns_typed_task(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    task = store.get_task("t1")
    assert task is not None
    assert task.id == "t1"
    assert task.status == "ready"


def test_get_task_returns_none_for_missing(store: FileStore):
    _seed_queue(store, [_task("other")])
    assert store.get_task("missing") is None


def test_get_task_handles_missing_queue_file(store: FileStore):
    assert store.get_task("anything") is None
