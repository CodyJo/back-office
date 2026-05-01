"""Tests for ``Store.checkout_task``: atomic claim, structured conflicts,
resume semantics, and concurrent contention.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from backoffice.store import (
    CHECKOUT_REASON_ALREADY_RUNNING,
    CHECKOUT_REASON_TASK_NOT_FOUND,
    CHECKOUT_REASON_WRONG_STATE,
    FileStore,
)


def _seed_queue(store: FileStore, tasks: list[dict]) -> None:
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


def test_checkout_creates_run_and_transitions_task(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    result = store.checkout_task("t1", agent_id="agent-fix")
    assert result.ok
    assert result.run is not None
    assert result.resumed is False
    assert result.run.task_id == "t1"
    assert result.run.agent_id == "agent-fix"
    assert result.run.state == "created"

    # Task is now checked out, with a current_run_id pointing at the run.
    task = store.get_task("t1")
    assert task is not None
    assert task.status == "checked_out"
    assert task.current_run_id == result.run.id


def test_checkout_persists_run_record(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    result = store.checkout_task("t1", agent_id="agent-fix")
    assert result.ok
    loaded = store.get_run(result.run.id)
    assert loaded is not None
    assert loaded.id == result.run.id
    assert loaded.task_id == "t1"


def test_checkout_emits_two_audit_events(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.checkout_task("t1", agent_id="agent-fix")
    events = store.read_audit_events()
    actions = [e.action for e in events]
    assert "run.created" in actions
    assert "task.transition" in actions


def test_checkout_records_history_entry(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.checkout_task("t1", agent_id="agent-fix")
    raw = yaml.safe_load(store.task_queue_path().read_text())
    history = raw["tasks"][0]["history"]
    assert any(h["status"] == "checked_out" for h in history)


def test_checkout_from_queued_state_is_legal(store: FileStore):
    _seed_queue(store, [_task("t1", status="queued")])
    result = store.checkout_task("t1", agent_id="agent-fix")
    assert result.ok


# ──────────────────────────────────────────────────────────────────────
# Conflicts
# ──────────────────────────────────────────────────────────────────────


def test_checkout_unknown_task_returns_not_found_conflict(store: FileStore):
    _seed_queue(store, [_task("other")])
    result = store.checkout_task("missing", agent_id="agent-fix")
    assert not result.ok
    assert result.conflict is not None
    assert result.conflict.reason == CHECKOUT_REASON_TASK_NOT_FOUND
    assert result.conflict.task_id == "missing"


def test_checkout_wrong_state_returns_structured_conflict(store: FileStore):
    """Tasks not in ready/queued must yield a wrong_state conflict."""
    for state in ("proposed", "pending_approval", "approved", "in_progress", "blocked",
                  "ready_for_review", "pr_open", "done", "cancelled", "failed"):
        _seed_queue(store, [_task("t1", status=state)])
        result = store.checkout_task("t1", agent_id="agent-fix")
        assert not result.ok, f"checkout from {state!r} unexpectedly succeeded"
        assert result.conflict is not None
        assert result.conflict.reason == CHECKOUT_REASON_WRONG_STATE
        assert result.conflict.current_state == state


def test_checkout_already_running_returns_held_by_conflict(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    first = store.checkout_task("t1", agent_id="agent-a")
    assert first.ok

    second = store.checkout_task("t1", agent_id="agent-b")
    assert not second.ok
    assert second.conflict is not None
    assert second.conflict.reason == CHECKOUT_REASON_ALREADY_RUNNING
    assert second.conflict.held_by_agent_id == "agent-a"
    assert second.conflict.held_by_run_id == first.run.id


def test_checkout_does_not_create_run_on_conflict(store: FileStore):
    _seed_queue(store, [_task("t1", status="done")])
    before = list(store.list_runs())
    result = store.checkout_task("t1", agent_id="agent-fix")
    assert not result.ok
    after = list(store.list_runs())
    assert before == after  # no run created


# ──────────────────────────────────────────────────────────────────────
# Resume semantics
# ──────────────────────────────────────────────────────────────────────


def test_same_agent_resumes_existing_run(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    first = store.checkout_task("t1", agent_id="agent-fix")
    assert first.ok

    second = store.checkout_task("t1", agent_id="agent-fix")
    assert second.ok
    assert second.resumed is True
    assert second.run.id == first.run.id

    # Only one run exists.
    runs = store.list_runs(task_id="t1")
    assert len(runs) == 1


def test_resume_does_not_create_new_audit_for_same_run(store: FileStore):
    _seed_queue(store, [_task("t1", status="ready")])
    store.checkout_task("t1", agent_id="agent-fix")
    after_first = len(store.read_audit_events())
    store.checkout_task("t1", agent_id="agent-fix")
    after_second = len(store.read_audit_events())
    # Resume yields the existing run without re-emitting the audit pair.
    assert after_second == after_first


# ──────────────────────────────────────────────────────────────────────
# Concurrent checkout (the headline Phase 3 acceptance test)
# ──────────────────────────────────────────────────────────────────────


def test_concurrent_checkouts_yield_one_winner_one_conflict(store: FileStore):
    """Two threads racing to checkout the same task: exactly one wins,
    the other receives a structured conflict. No torn run record, no
    duplicate runs.
    """
    _seed_queue(store, [_task("t1", status="ready")])

    barrier = threading.Barrier(2)
    results: list = [None, None]

    def _checkout(idx: int, agent_id: str) -> None:
        barrier.wait()
        results[idx] = store.checkout_task("t1", agent_id=agent_id)

    threads = [
        threading.Thread(target=_checkout, args=(0, "agent-a")),
        threading.Thread(target=_checkout, args=(1, "agent-b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive()

    successes = [r for r in results if r is not None and r.ok]
    conflicts = [r for r in results if r is not None and not r.ok]
    assert len(successes) == 1, f"expected one winner, got {len(successes)}"
    assert len(conflicts) == 1
    assert conflicts[0].conflict.reason == CHECKOUT_REASON_ALREADY_RUNNING

    # Exactly one run exists, owned by the winner.
    runs = store.list_runs(task_id="t1")
    assert len(runs) == 1
    assert runs[0].agent_id == successes[0].run.agent_id


def test_concurrent_checkouts_high_contention(store: FileStore):
    """Eight threads racing on the same task: exactly one wins."""
    _seed_queue(store, [_task("t1", status="ready")])

    barrier = threading.Barrier(8)
    results: list = [None] * 8

    def _checkout(idx: int) -> None:
        barrier.wait()
        results[idx] = store.checkout_task("t1", agent_id=f"agent-{idx}")

    threads = [threading.Thread(target=_checkout, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive()

    successes = [r for r in results if r is not None and r.ok]
    assert len(successes) == 1

    runs = store.list_runs(task_id="t1")
    assert len(runs) == 1


# ──────────────────────────────────────────────────────────────────────
# Stale-pointer recovery
# ──────────────────────────────────────────────────────────────────────


def test_checkout_recovers_when_current_run_pointer_is_stale(store: FileStore):
    """If task.current_run_id points to a run whose state is terminal,
    a new checkout proceeds (the previous run finished without
    clearing the pointer)."""
    from backoffice.domain import Run

    # Hand-craft: task already shows current_run_id pointing at a
    # ``succeeded`` run. We started over after restart and want a fresh checkout.
    finished_run = Run(
        id="run-old",
        task_id="t1",
        agent_id="agent-prior",
        state="succeeded",
    )
    store.create_run(finished_run)
    _seed_queue(
        store,
        [_task("t1", status="ready", current_run_id="run-old")],
    )

    result = store.checkout_task("t1", agent_id="agent-new")
    assert result.ok
    assert result.run.id != "run-old"


def test_checkout_recovers_when_pointer_targets_missing_run(store: FileStore):
    """If task.current_run_id references a run file that no longer
    exists (e.g. operator deleted it), a fresh checkout still works."""
    _seed_queue(
        store,
        [_task("t1", status="ready", current_run_id="run-vanished")],
    )
    result = store.checkout_task("t1", agent_id="agent-new")
    assert result.ok
    assert result.run.id != "run-vanished"


# ──────────────────────────────────────────────────────────────────────
# list_runs
# ──────────────────────────────────────────────────────────────────────


def test_list_runs_filters_by_task_id(store: FileStore):
    from backoffice.domain import Run

    store.create_run(Run(id="r1", task_id="t1", agent_id="a", state="created"))
    store.create_run(Run(id="r2", task_id="t2", agent_id="a", state="created"))
    store.create_run(Run(id="r3", task_id="t1", agent_id="b", state="succeeded"))

    all_runs = store.list_runs()
    assert {r.id for r in all_runs} == {"r1", "r2", "r3"}

    t1_only = store.list_runs(task_id="t1")
    assert {r.id for r in t1_only} == {"r1", "r3"}


def test_list_runs_returns_empty_when_no_runs(store: FileStore):
    assert store.list_runs() == []
