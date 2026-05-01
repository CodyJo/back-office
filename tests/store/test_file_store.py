"""Tests for ``FileStore`` and ``TaskQueueState``."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import yaml

from backoffice.domain import AuditEvent, Task
from backoffice.store import FileStore, TaskQueueState, get_store


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    """Return a FileStore rooted at *tmp_path* with the standard layout."""
    return FileStore(root=tmp_path)


# ──────────────────────────────────────────────────────────────────────
# TaskQueueState round-trip
# ──────────────────────────────────────────────────────────────────────


def test_task_queue_state_round_trip():
    raw = {
        "version": 1,
        "tasks": [
            {"id": "t1", "repo": "r", "title": "x", "status": "ready"},
            {"id": "t2", "repo": "r", "title": "y", "status": "pending_approval"},
        ],
    }
    state = TaskQueueState.from_dict(raw)
    assert state.version == 1
    assert len(state.tasks) == 2
    assert isinstance(state.tasks[0], Task)
    out = state.to_dict()
    assert out["version"] == 1
    assert out["tasks"][0]["id"] == "t1"
    assert out["tasks"][1]["id"] == "t2"


def test_task_queue_state_handles_missing_fields():
    state = TaskQueueState.from_dict(None)
    assert state.version == 1
    assert state.tasks == []


def test_task_queue_state_preserves_extras():
    raw = {"version": 2, "tasks": [], "future_field": {"hello": "world"}}
    state = TaskQueueState.from_dict(raw)
    assert state.extras == {"future_field": {"hello": "world"}}
    assert state.to_dict() == raw


def test_task_queue_state_filters_garbage_tasks():
    raw = {"version": 1, "tasks": [{"id": "ok"}, "garbage", None]}
    state = TaskQueueState.from_dict(raw)
    assert len(state.tasks) == 1
    assert state.tasks[0].id == "ok"


# ──────────────────────────────────────────────────────────────────────
# FileStore: load_task_queue
# ──────────────────────────────────────────────────────────────────────


def test_load_task_queue_missing_returns_empty(store: FileStore):
    state = store.load_task_queue()
    assert state.version == 1
    assert state.tasks == []


def test_load_task_queue_reads_existing_file(store: FileStore):
    payload = {
        "version": 1,
        "tasks": [{"id": "t1", "repo": "r", "title": "x", "status": "ready"}],
    }
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    state = store.load_task_queue()
    assert len(state.tasks) == 1
    assert state.tasks[0].id == "t1"


def test_load_task_queue_tolerates_malformed_yaml(store: FileStore):
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("::: not valid yaml :::\n  - [")
    state = store.load_task_queue()
    assert state.version == 1
    assert state.tasks == []


def test_load_task_queue_tolerates_non_mapping_root(store: FileStore):
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- just\n- a\n- list\n")
    state = store.load_task_queue()
    assert state.tasks == []


# ──────────────────────────────────────────────────────────────────────
# FileStore: save_task_queue
# ──────────────────────────────────────────────────────────────────────


def test_save_task_queue_writes_all_three_files(store: FileStore):
    state = TaskQueueState(
        version=1,
        tasks=[
            Task(
                id="t1",
                repo="back-office",
                title="Fix foo",
                status="ready",
                created_at="2026-04-29T00:00:00+00:00",
                updated_at="2026-04-29T00:00:00+00:00",
            ),
        ],
    )
    store.save_task_queue(state)

    assert store.task_queue_path().exists()
    assert store.task_queue_results_mirror_path().exists()
    assert store.task_queue_dashboard_mirror_path().exists()


def test_save_task_queue_yaml_round_trips(store: FileStore):
    state = TaskQueueState(
        version=1,
        tasks=[Task(id="t1", repo="r", title="x", status="ready")],
    )
    store.save_task_queue(state)

    reloaded = store.load_task_queue()
    assert reloaded.version == 1
    assert len(reloaded.tasks) == 1
    assert reloaded.tasks[0].id == "t1"


def test_save_task_queue_mirrors_match(store: FileStore):
    """Both JSON mirrors must contain identical bytes."""
    state = TaskQueueState(
        version=1,
        tasks=[Task(id="t1", repo="r", title="x", status="ready")],
    )
    store.save_task_queue(state)

    a = store.task_queue_results_mirror_path().read_bytes()
    b = store.task_queue_dashboard_mirror_path().read_bytes()
    assert a == b


def test_save_task_queue_mirror_format_matches_legacy(store: FileStore):
    """The JSON mirror must match what backoffice.tasks.build_dashboard_payload
    produces today (already used by the dashboard SPA)."""
    from backoffice.tasks import build_dashboard_payload

    task_dict = {
        "id": "t1",
        "repo": "r",
        "title": "x",
        "status": "ready",
        "priority": "high",
    }
    state = TaskQueueState(
        version=1,
        tasks=[Task.from_dict(task_dict)],
    )
    store.save_task_queue(state)

    written = json.loads(store.task_queue_results_mirror_path().read_text())
    expected = build_dashboard_payload([state.tasks[0].to_dict()])
    # generated_at is iso_now() and will differ; compare structure minus that.
    written.pop("generated_at", None)
    expected.pop("generated_at", None)
    assert written == expected


def test_save_task_queue_is_idempotent(store: FileStore):
    state = TaskQueueState(
        version=1,
        tasks=[Task(id="t1", repo="r", title="x", status="ready")],
    )
    store.save_task_queue(state)
    yaml_a = store.task_queue_path().read_bytes()
    store.save_task_queue(state)
    yaml_b = store.task_queue_path().read_bytes()
    assert yaml_a == yaml_b


# ──────────────────────────────────────────────────────────────────────
# FileStore: audit events
# ──────────────────────────────────────────────────────────────────────


def test_append_audit_event_creates_jsonl(store: FileStore):
    event = AuditEvent(
        id="evt-1",
        at="2026-04-29T13:00:00+00:00",
        actor_id="u-1",
        action="task.transition",
        subject_kind="task",
        subject_id="t-1",
        before={"status": "ready"},
        after={"status": "in_progress"},
        reason="task started",
    )
    store.append_audit_event(event)

    path = store.audit_log_path()
    assert path.exists()
    line = path.read_text().splitlines()[0]
    payload = json.loads(line)
    assert payload["id"] == "evt-1"
    assert payload["action"] == "task.transition"


def test_append_audit_event_appends_multiple(store: FileStore):
    for i in range(5):
        store.append_audit_event(
            AuditEvent(
                id=f"evt-{i}",
                action="task.transition",
                subject_kind="task",
                subject_id=f"t-{i}",
            )
        )
    events = store.read_audit_events()
    assert [e.id for e in events] == [f"evt-{i}" for i in range(5)]


def test_read_audit_events_missing_file_returns_empty(store: FileStore):
    assert store.read_audit_events() == []


def test_read_audit_events_skips_torn_lines(store: FileStore):
    path = store.audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"id": "good-1", "action": "x", "subject_kind": "task", "subject_id": "t"}\n'
        '{not valid json\n'
        '{"id": "good-2", "action": "y", "subject_kind": "task", "subject_id": "t"}\n'
    )
    events = store.read_audit_events()
    assert [e.id for e in events] == ["good-1", "good-2"]


# ──────────────────────────────────────────────────────────────────────
# FileStore: locks
# ──────────────────────────────────────────────────────────────────────


def test_lock_blocks_concurrent_holders(store: FileStore):
    """A second non-blocking acquire must raise."""
    holder_acquired = threading.Event()
    holder_release = threading.Event()

    def _hold() -> None:
        with store.lock("task-queue"):
            holder_acquired.set()
            holder_release.wait(5.0)

    thread = threading.Thread(target=_hold)
    thread.start()
    try:
        assert holder_acquired.wait(2.0)
        with pytest.raises(BlockingIOError):
            with store.lock("task-queue", blocking=False):
                pass  # pragma: no cover
    finally:
        holder_release.set()
        thread.join()


def test_lock_distinct_resources_do_not_block(store: FileStore):
    with store.lock("a", blocking=False):
        with store.lock("b", blocking=False):
            pass


def test_lock_sanitizes_resource_name(store: FileStore):
    """Awkward characters in resource names must not produce invalid paths."""
    with store.lock("queue with spaces / slashes"):
        # The sidecar file sits under results/.locks/...
        lock_dir = store.audit_log_path().parent / ".locks"
        files = list(lock_dir.iterdir())
        assert len(files) == 1
        assert all(c not in files[0].name for c in (" ", "/"))


# ──────────────────────────────────────────────────────────────────────
# get_store factory
# ──────────────────────────────────────────────────────────────────────


def test_get_store_returns_file_store_by_default(tmp_path: Path):
    s = get_store(root=tmp_path)
    assert isinstance(s, FileStore)
    assert s.root == tmp_path


def test_get_store_uses_default_root_when_none():
    s = get_store()
    assert isinstance(s, FileStore)
    # Default root resolves to the back-office repo root.
    assert s.root.name == "back-office"
