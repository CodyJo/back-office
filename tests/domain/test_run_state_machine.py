"""Allowed/illegal transitions for the Run and Approval state machines."""
from __future__ import annotations

import pytest

from backoffice.domain import (
    APPROVAL_TRANSITIONS,
    Approval,
    IllegalTransition,
    RUN_TRANSITIONS,
    Run,
    is_legal_approval_transition,
    is_legal_run_transition,
    transition_approval,
    transition_run,
)


# ──────────────────────────────────────────────────────────────────────
# Run state machine
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src,dst",
    [
        ("created", "queued"),
        ("created", "starting"),
        ("queued", "starting"),
        ("starting", "running"),
        ("starting", "failed"),
        ("running", "succeeded"),
        ("running", "failed"),
        ("running", "timed_out"),
        ("running", "cancelled"),
        ("created", "cancelled"),
    ],
)
def test_run_transitions_legal(src, dst):
    assert is_legal_run_transition(src, dst)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("succeeded", "running"),
        ("failed", "running"),
        ("cancelled", "running"),
        ("timed_out", "running"),
        ("succeeded", "created"),
        ("succeeded", "queued"),
    ],
)
def test_run_transitions_illegal(src, dst):
    assert not is_legal_run_transition(src, dst)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("created", "succeeded"),
        ("created", "failed"),
        ("queued", "succeeded"),
        ("queued", "failed"),
        ("starting", "succeeded"),
    ],
)
def test_run_synchronous_short_circuits_are_legal(src, dst):
    """Synchronous adapters complete in one step; the state machine
    must allow it without forcing a fake ``running`` transition."""
    assert is_legal_run_transition(src, dst)


def test_run_terminal_states_have_no_outgoing():
    for terminal in ("succeeded", "failed", "cancelled", "timed_out"):
        assert RUN_TRANSITIONS[terminal] == frozenset(), terminal


def test_transition_run_sets_started_at(monkeypatch):
    monkeypatch.setattr(
        "backoffice.domain.state_machines.iso_now",
        lambda: "2026-04-29T13:00:00+00:00",
    )
    run = Run(id="r1", task_id="t1", state="starting")
    new = transition_run(run, "running")
    assert new.state == "running"
    assert new.started_at == "2026-04-29T13:00:00+00:00"
    assert new.ended_at == ""


def test_transition_run_does_not_overwrite_existing_started_at(monkeypatch):
    monkeypatch.setattr(
        "backoffice.domain.state_machines.iso_now",
        lambda: "2026-04-29T13:00:00+00:00",
    )
    run = Run(
        id="r1",
        task_id="t1",
        state="starting",
        started_at="2026-04-29T12:55:00+00:00",
    )
    new = transition_run(run, "running")
    assert new.started_at == "2026-04-29T12:55:00+00:00"


def test_transition_run_sets_ended_at_and_exit_code(monkeypatch):
    monkeypatch.setattr(
        "backoffice.domain.state_machines.iso_now",
        lambda: "2026-04-29T14:00:00+00:00",
    )
    run = Run(id="r1", task_id="t1", state="running")
    new = transition_run(run, "succeeded", exit_code=0)
    assert new.state == "succeeded"
    assert new.ended_at == "2026-04-29T14:00:00+00:00"
    assert new.exit_code == 0


def test_transition_run_failure_records_error(monkeypatch):
    monkeypatch.setattr(
        "backoffice.domain.state_machines.iso_now",
        lambda: "2026-04-29T14:00:00+00:00",
    )
    run = Run(id="r1", task_id="t1", state="running")
    new = transition_run(run, "failed", reason="boom", exit_code=2)
    assert new.state == "failed"
    assert new.error == "boom"
    assert new.exit_code == 2


def test_transition_run_raises_on_illegal_move():
    run = Run(id="r1", task_id="t1", state="succeeded")
    with pytest.raises(IllegalTransition) as exc:
        transition_run(run, "running")
    assert exc.value.kind == "run"
    assert exc.value.from_state == "succeeded"


# ──────────────────────────────────────────────────────────────────────
# Approval state machine
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src,dst",
    [
        ("requested", "approved"),
        ("requested", "rejected"),
        ("requested", "expired"),
        ("requested", "superseded"),
        ("approved", "superseded"),
        ("rejected", "superseded"),
        ("expired", "superseded"),
    ],
)
def test_approval_transitions_legal(src, dst):
    assert is_legal_approval_transition(src, dst)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("approved", "rejected"),  # decisions are final unless superseded
        ("approved", "requested"),
        ("rejected", "approved"),
        ("superseded", "approved"),
        ("superseded", "rejected"),
    ],
)
def test_approval_transitions_illegal(src, dst):
    assert not is_legal_approval_transition(src, dst)


def test_approval_terminal_states():
    assert APPROVAL_TRANSITIONS["superseded"] == frozenset()


def test_transition_approval_sets_decided_fields(monkeypatch):
    monkeypatch.setattr(
        "backoffice.domain.state_machines.iso_now",
        lambda: "2026-04-29T12:30:00+00:00",
    )
    a = Approval(id="appr-1", task_id="t1", state="requested")
    decided = transition_approval(a, "approved", decided_by="operator", reason="lgtm")
    assert decided.state == "approved"
    assert decided.decided_by == "operator"
    assert decided.decided_at == "2026-04-29T12:30:00+00:00"
    assert decided.reason == "lgtm"


def test_transition_approval_supersede_does_not_set_decided_fields():
    a = Approval(
        id="appr-1",
        task_id="t1",
        state="approved",
        decided_by="operator",
        decided_at="2026-04-29T12:30:00+00:00",
    )
    new = transition_approval(a, "superseded")
    assert new.state == "superseded"
    # Decision fields preserved from original.
    assert new.decided_by == "operator"
    assert new.decided_at == "2026-04-29T12:30:00+00:00"


def test_transition_approval_raises_on_illegal_move():
    a = Approval(id="appr-1", task_id="t1", state="approved")
    with pytest.raises(IllegalTransition) as exc:
        transition_approval(a, "rejected", decided_by="operator")
    assert exc.value.kind == "approval"
