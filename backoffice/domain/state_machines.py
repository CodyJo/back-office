"""Explicit state machines for ``Task``, ``Run``, and ``Approval``.

Each transition table is the authoritative source for legal moves;
``transition_*`` helpers validate moves, set timestamps, and append
audit-shaped history rows.

These helpers are pure: they do not write to storage. Storage code
(Phase 2+) is responsible for persistence and audit-event emission.

Phase 1 introduces these helpers without rewiring any existing call
sites — see ``docs/architecture/phased-roadmap.md`` Phase 1.
"""
from __future__ import annotations

from dataclasses import replace

from backoffice.domain.models import (
    Approval,
    HistoryEntry,
    Run,
    Task,
    iso_now,
)

# ──────────────────────────────────────────────────────────────────────
# Allowed transitions (data, not branches)
# ──────────────────────────────────────────────────────────────────────

# Task: superset of today's de-facto transitions (queue endpoints +
# CLI commands) plus the new ``checked_out`` and ``failed`` states.
# ``proposed`` is the legacy default produced by ``ensure_task_defaults``;
# ``pending_approval`` is the gate before approval; ``approved`` is the
# new explicit "approved-but-not-yet-claimed" state. ``ready`` is kept
# because the existing approve endpoint moves directly to it.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    # ``proposed → in_progress`` is intentional: the legacy CLI
    # (``python -m backoffice tasks start``) accepts that move and
    # several real workflows depend on it. Tasks created with
    # ``status: proposed`` are not gated on approval; the gate is on
    # ``status: pending_approval``.
    "proposed":         frozenset({"pending_approval", "approved", "ready", "in_progress", "cancelled"}),
    "pending_approval": frozenset({"approved", "ready", "cancelled"}),
    "approved":         frozenset({"ready", "queued", "cancelled"}),
    "ready":            frozenset({"queued", "checked_out", "in_progress", "blocked", "cancelled"}),
    "queued":           frozenset({"checked_out", "in_progress", "ready", "cancelled"}),
    # ``checked_out → ready_for_review`` is the agent's "I'm done"
    # path: the work is already on a branch and the agent calls
    # ``/api/runs/<id>/ready-for-review``. ``checked_out → in_progress``
    # remains for agents that want to broadcast active work.
    "checked_out":      frozenset({"in_progress", "ready", "ready_for_review", "failed", "cancelled"}),
    "in_progress":      frozenset({"blocked", "ready_for_review", "failed", "cancelled"}),
    "blocked":          frozenset({"in_progress", "ready_for_review", "cancelled"}),
    "ready_for_review": frozenset({"pr_open", "in_progress", "done", "failed", "cancelled"}),
    "pr_open":          frozenset({"done", "failed", "cancelled"}),
    "done":             frozenset(),
    "failed":           frozenset({"queued", "ready", "cancelled"}),  # retry path
    "cancelled":        frozenset(),
}

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    # Synchronous adapters (process, claude_code, noop) complete in
    # one step — they never surface ``starting`` / ``running``. The
    # short-circuit transitions below let those adapters move from
    # ``created`` or ``queued`` straight to a terminal state. The
    # full sequence remains legal for asynchronous adapters that want
    # to broadcast progress.
    "created":   frozenset({"queued", "starting", "running", "succeeded", "failed", "cancelled"}),
    "queued":    frozenset({"starting", "running", "succeeded", "failed", "cancelled"}),
    "starting":  frozenset({"running", "succeeded", "failed", "cancelled"}),
    "running":   frozenset({"succeeded", "failed", "cancelled", "timed_out"}),
    "succeeded": frozenset(),
    "failed":    frozenset(),
    "cancelled": frozenset(),
    "timed_out": frozenset(),
}

APPROVAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "requested":  frozenset({"approved", "rejected", "expired", "superseded"}),
    "approved":   frozenset({"superseded"}),
    "rejected":   frozenset({"superseded"}),
    "expired":    frozenset({"superseded"}),
    "superseded": frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when a state machine refuses a transition."""

    def __init__(self, kind: str, from_state: str, to_state: str):
        self.kind = kind
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"illegal {kind} transition: {from_state!r} -> {to_state!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# Predicates
# ──────────────────────────────────────────────────────────────────────


def is_legal_task_transition(from_state: str, to_state: str) -> bool:
    if from_state not in TASK_TRANSITIONS:
        return False
    return to_state in TASK_TRANSITIONS[from_state]


def is_legal_run_transition(from_state: str, to_state: str) -> bool:
    if from_state not in RUN_TRANSITIONS:
        return False
    return to_state in RUN_TRANSITIONS[from_state]


def is_legal_approval_transition(from_state: str, to_state: str) -> bool:
    if from_state not in APPROVAL_TRANSITIONS:
        return False
    return to_state in APPROVAL_TRANSITIONS[from_state]


# ──────────────────────────────────────────────────────────────────────
# Transition helpers
# ──────────────────────────────────────────────────────────────────────


def transition_task(
    task: Task,
    to_state: str,
    *,
    actor: str,
    reason: str = "",
    at: str | None = None,
) -> Task:
    """Return a new Task in *to_state*, with one history entry appended.

    Raises :class:`IllegalTransition` if the move is not allowed.
    """
    if not is_legal_task_transition(task.status, to_state):
        raise IllegalTransition("task", task.status, to_state)
    stamp = at or iso_now()
    new_history = list(task.history)
    new_history.append(
        HistoryEntry(status=to_state, at=stamp, by=actor, note=reason or "")
    )
    return replace(
        task,
        status=to_state,
        updated_at=stamp,
        history=new_history,
    )


def transition_run(
    run: Run,
    to_state: str,
    *,
    reason: str = "",
    at: str | None = None,
    exit_code: int | None = None,
) -> Run:
    """Return a new Run in *to_state*. Sets ``ended_at``/``error`` as
    appropriate for terminal transitions.

    Raises :class:`IllegalTransition` if the move is not allowed.
    """
    if not is_legal_run_transition(run.state, to_state):
        raise IllegalTransition("run", run.state, to_state)
    stamp = at or iso_now()
    fields: dict = {"state": to_state}
    if to_state in {"running"} and not run.started_at:
        fields["started_at"] = stamp
    if to_state in {"succeeded", "failed", "cancelled", "timed_out"}:
        fields["ended_at"] = stamp
        if exit_code is not None:
            fields["exit_code"] = int(exit_code)
        if reason and to_state in {"failed", "cancelled", "timed_out"}:
            fields["error"] = reason
    return replace(run, **fields)


def transition_approval(
    approval: Approval,
    to_state: str,
    *,
    decided_by: str = "",
    reason: str = "",
    at: str | None = None,
) -> Approval:
    """Return a new Approval in *to_state*.

    Raises :class:`IllegalTransition` if the move is not allowed.
    Sets ``decided_by`` / ``decided_at`` on approve/reject.
    """
    if not is_legal_approval_transition(approval.state, to_state):
        raise IllegalTransition("approval", approval.state, to_state)
    stamp = at or iso_now()
    fields: dict = {"state": to_state}
    if to_state in {"approved", "rejected"}:
        if decided_by:
            fields["decided_by"] = decided_by
        fields["decided_at"] = stamp
        if reason:
            fields["reason"] = reason
    return replace(approval, **fields)
