"""Compatibility helpers between legacy artifacts and domain models.

Phase 1 wires nothing — these helpers exist so later phases (and
tests) can synthesize typed views over the existing JSON/YAML files
without ever rewriting them.

Two main responsibilities here:

* **Task ↔ legacy queue dict.** ``task_from_legacy`` / ``task_to_legacy``
  round-trip a row of ``config/task-queue.yaml`` losslessly.
* **Approval synthesis.** ``approval_from_task_dict`` builds an
  :class:`~backoffice.domain.models.Approval` view of the inline
  ``task["approval"]`` dict that today carries
  ``{approved_at, approved_by, note}``.

Workspace synthesis from preview artifacts is also provided since
``backoffice/preview.py`` is the closest thing we have to a Workspace
record today.
"""
from __future__ import annotations

from backoffice.domain.models import (
    Approval,
    Task,
    Workspace,
)


# ──────────────────────────────────────────────────────────────────────
# Task ↔ legacy queue dict
# ──────────────────────────────────────────────────────────────────────


def task_from_legacy(raw: dict) -> Task:
    """Build a :class:`Task` from a row of ``config/task-queue.yaml``.

    Inverse of :func:`task_to_legacy`. Unknown keys land in
    ``Task.extras`` so round-trips are exact even when upstream adds
    fields.
    """
    return Task.from_dict(raw)


def task_to_legacy(task: Task) -> dict:
    """Reverse of :func:`task_from_legacy`.

    Output keys match what :func:`backoffice.tasks.ensure_task_defaults`
    emits, plus any preserved extras.
    """
    return task.to_dict()


# ──────────────────────────────────────────────────────────────────────
# Approval synthesis
# ──────────────────────────────────────────────────────────────────────


def approval_from_task_dict(raw: dict) -> Approval | None:
    """Synthesize an :class:`Approval` from a legacy task dict.

    Returns ``None`` when the task has no approval information.

    Heuristics (kept conservative — when in doubt, return ``None`` and
    let the caller fall back to the legacy ``task["approval"]`` dict):

    * ``status == "pending_approval"`` ⇒ ``Approval(state="requested")``
      with ``requested_by``/``requested_at`` from the latest matching
      history entry.
    * ``task["approval"]`` contains ``approved_at`` + ``approved_by`` ⇒
      ``Approval(state="approved", decided_by=..., decided_at=...,
      reason=note)``. This matches what ``/api/tasks/approve`` writes.
    * Otherwise ⇒ ``None``.
    """
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status", ""))
    approval_raw = raw.get("approval") or {}
    if not isinstance(approval_raw, dict):
        approval_raw = {}

    task_id = str(raw.get("id", ""))

    if "approved_at" in approval_raw and "approved_by" in approval_raw:
        return Approval(
            id="",  # synthesized; later phases assign stable ids
            task_id=task_id,
            scope="plan",
            state="approved",
            requested_by=str(raw.get("created_by", "")),
            requested_at=_first_history_at(raw, "pending_approval") or str(raw.get("created_at", "")),
            decided_by=str(approval_raw.get("approved_by", "")),
            decided_at=str(approval_raw.get("approved_at", "")),
            reason=str(approval_raw.get("note", "")),
        )

    if status == "pending_approval":
        # Find the timestamp at which the task entered pending_approval.
        at = _first_history_at(raw, "pending_approval") or str(raw.get("created_at", ""))
        return Approval(
            id="",
            task_id=task_id,
            scope="plan",
            state="requested",
            requested_by=str(raw.get("created_by", "")),
            requested_at=at,
        )

    if status == "cancelled":
        # Cancellation today is ambiguous — could be a rejection of an
        # outstanding request, or a post-approval cancel. Return None
        # rather than guess; callers can read ``task["history"]`` for
        # the human-authored note.
        return None

    return None


def _first_history_at(raw: dict, status: str) -> str | None:
    history = raw.get("history") or []
    if not isinstance(history, list):
        return None
    for entry in history:
        if isinstance(entry, dict) and entry.get("status") == status:
            at = entry.get("at")
            if isinstance(at, str) and at:
                return at
    return None


# ──────────────────────────────────────────────────────────────────────
# Workspace synthesis from preview artifacts
# ──────────────────────────────────────────────────────────────────────


def workspace_from_preview(raw: dict, *, task_id: str = "") -> Workspace:
    """Synthesize a :class:`Workspace` from a ``preview-<job-id>.json``.

    Maps the existing preview artifact (built by
    :func:`backoffice.preview.build_preview`) onto the new Workspace
    model. The artifact's ``job_id`` becomes the workspace ``id`` so
    later phases can persist them without renumbering.
    """
    if not isinstance(raw, dict):
        raise TypeError(
            f"workspace_from_preview expected a mapping, got {type(raw).__name__}"
        )
    return Workspace(
        id=str(raw.get("job_id", "")),
        task_id=task_id,
        repo=str(raw.get("repo", "")),
        kind="branch",
        branch=str(raw.get("branch", "")),
        base_ref=str(raw.get("base_ref", "")),
        base_sha=str(raw.get("base_sha", "")),
        head_sha=str(raw.get("head_sha", "")),
        worktree_path="",
        created_at=str(raw.get("created_at", "")),
        updated_at=str(raw.get("created_at", "")),
        retired_at="",
        test_results_ref="",
        metadata={
            "compare_url": raw.get("compare_url"),
            "commits": raw.get("commits") or [],
            "changes": raw.get("changes") or [],
            "checklist": raw.get("checklist") or [],
        },
    )
