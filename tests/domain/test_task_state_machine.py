"""Allowed/illegal transitions for the Task state machine."""
from __future__ import annotations

import pytest

from backoffice.domain import (
    HistoryEntry,
    IllegalTransition,
    TASK_TRANSITIONS,
    Task,
    is_legal_task_transition,
    transition_task,
)


# A handful of moves the existing CLI/HTTP handlers actually do today.
# These must remain legal so Phase 3 can switch them onto transition_task
# without behavior change.
LEGAL_LEGACY_MOVES = [
    ("proposed", "ready"),  # tasks create --status ready
    ("proposed", "pending_approval"),  # legacy creation path
    ("pending_approval", "ready"),  # /api/tasks/approve
    ("pending_approval", "cancelled"),  # /api/tasks/cancel
    ("ready", "in_progress"),  # tasks start
    ("in_progress", "blocked"),  # tasks block
    ("blocked", "in_progress"),  # tasks start (resume)
    ("in_progress", "ready_for_review"),  # tasks review
    ("ready_for_review", "pr_open"),  # /api/tasks/request-pr
    ("pr_open", "done"),  # tasks complete
    ("ready_for_review", "done"),  # tasks complete (no PR path)
    ("ready", "cancelled"),  # tasks cancel
]

# Illegal moves that we want to stop happening. Each was reachable
# today only because update_status() does no validation.
ILLEGAL_LEGACY_MOVES = [
    ("done", "in_progress"),
    ("done", "ready"),
    ("cancelled", "ready"),
    ("cancelled", "in_progress"),
    ("pr_open", "ready"),
    ("ready_for_review", "pending_approval"),
    ("proposed", "done"),
]


@pytest.mark.parametrize("src,dst", LEGAL_LEGACY_MOVES)
def test_legal_legacy_moves_remain_legal(src, dst):
    assert is_legal_task_transition(src, dst), f"{src!r} -> {dst!r} should be legal"


@pytest.mark.parametrize("src,dst", ILLEGAL_LEGACY_MOVES)
def test_illegal_legacy_moves_are_blocked(src, dst):
    assert not is_legal_task_transition(src, dst), f"{src!r} -> {dst!r} should be blocked"


def test_unknown_state_returns_false():
    assert not is_legal_task_transition("not-a-state", "done")
    assert not is_legal_task_transition("ready", "not-a-state")


def test_terminal_states_have_no_outgoing_transitions():
    assert TASK_TRANSITIONS["done"] == frozenset()
    assert TASK_TRANSITIONS["cancelled"] == frozenset()


def test_failed_can_retry():
    """Phase 3+ allows retrying a failed task by re-queueing."""
    assert is_legal_task_transition("failed", "queued")
    assert is_legal_task_transition("failed", "ready")
    assert is_legal_task_transition("failed", "cancelled")


def test_checked_out_is_a_first_class_state():
    """The new ``checked_out`` state must be reachable from approved/queued/ready."""
    assert is_legal_task_transition("ready", "checked_out")
    assert is_legal_task_transition("queued", "checked_out")
    assert is_legal_task_transition("checked_out", "in_progress")
    assert is_legal_task_transition("checked_out", "failed")


# ──────────────────────────────────────────────────────────────────────
# transition_task() helper
# ──────────────────────────────────────────────────────────────────────


def _fresh_task(status: str = "pending_approval") -> Task:
    return Task(
        id="t-1",
        repo="back-office",
        title="Fix foo",
        status=status,
        created_at="2026-04-29T00:00:00+00:00",
        updated_at="2026-04-29T00:00:00+00:00",
    )


def test_transition_task_returns_new_instance_and_appends_history():
    task = _fresh_task("pending_approval")
    new = transition_task(task, "ready", actor="operator", reason="lgtm", at="2026-04-29T12:00:00+00:00")

    # Original unchanged (purity).
    assert task.status == "pending_approval"
    assert task.history == []

    # New instance correct.
    assert new.status == "ready"
    assert new.updated_at == "2026-04-29T12:00:00+00:00"
    assert len(new.history) == 1
    assert new.history[0] == HistoryEntry(
        status="ready", at="2026-04-29T12:00:00+00:00", by="operator", note="lgtm"
    )


def test_transition_task_raises_on_illegal_move():
    task = _fresh_task("done")
    with pytest.raises(IllegalTransition) as exc:
        transition_task(task, "in_progress", actor="operator")
    assert exc.value.kind == "task"
    assert exc.value.from_state == "done"
    assert exc.value.to_state == "in_progress"


def test_transition_task_uses_iso_now_when_not_provided(monkeypatch):
    sentinel = "2030-01-01T00:00:00+00:00"
    monkeypatch.setattr("backoffice.domain.state_machines.iso_now", lambda: sentinel)
    task = _fresh_task("ready")
    new = transition_task(task, "in_progress", actor="operator")
    assert new.updated_at == sentinel
    assert new.history[0].at == sentinel


def test_round_trip_preserves_transitioned_state():
    task = _fresh_task("pending_approval")
    new = transition_task(task, "ready", actor="op", reason="lgtm", at="2026-04-29T12:00:00+00:00")
    rebuilt = Task.from_dict(new.to_dict())
    assert rebuilt.status == "ready"
    assert len(rebuilt.history) == 1
    assert rebuilt.history[0].note == "lgtm"
