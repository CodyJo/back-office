"""Agent-facing API surface (Phase 9 wire-through).

Exposes a small, scoped HTTP surface so registered agents can:

* checkout a task atomically;
* append run log lines;
* report cost events;
* mark a run / task ready-for-review;
* request approvals.

Authentication uses **per-agent tokens** (``Authorization: Bearer
bo-...``) issued via ``python -m backoffice tokens issue``. Cross-agent
mutations are denied — an agent can only mutate its own runs.

The functions here are pure-ish helpers that the HTTP server (server.py
/ api_server.py) calls. They take parsed JSON bodies and return
``(status_code, response_dict)`` tuples.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from backoffice.auth import (
    SCOPE_CHECKOUT,
    SCOPE_REQUEST_APPROVAL,
    SCOPE_RUN_COST,
    SCOPE_RUN_LOG,
    SCOPE_RUN_READY,
    AuthResult,
    authorize,
)
from backoffice.budgets import (
    BLOCK,
    Budget,
    evaluate as evaluate_budget,
    list_cost_events,
    record_cost,
)
from backoffice.domain import (
    AuditEvent,
    iso_now,
)
from backoffice.domain.state_machines import (
    is_legal_task_transition,
    transition_run,
)
from backoffice.store import FileStore

logger = logging.getLogger(__name__)


def _err(code: int, error: str, **extra) -> tuple[int, dict[str, Any]]:
    return code, {"error": error, **extra}


def _audit(store: FileStore, action: str, subject_kind: str, subject_id: str,
           actor: str, before: dict | None = None, after: dict | None = None,
           reason: str = "") -> None:
    try:
        store.append_audit_event(
            AuditEvent(
                id=f"evt-{uuid.uuid4().hex[:12]}",
                at=iso_now(),
                actor_id=actor,
                action=action,
                subject_kind=subject_kind,
                subject_id=subject_id,
                before=before,
                after=after,
                reason=reason,
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to emit %s audit event", action)


# ──────────────────────────────────────────────────────────────────────
# Endpoint handlers
# ──────────────────────────────────────────────────────────────────────


def handle_checkout(
    store: FileStore,
    auth: AuthResult,
    *,
    task_id: str,
    body: dict | None,
    budgets: list[Budget] | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/tasks/<id>/checkout — agent claims a task."""
    body = body or {}
    allowed, reason = authorize(auth, required_scope=SCOPE_CHECKOUT)
    if not allowed:
        return _err(401, reason)

    if not task_id:
        return _err(400, "missing_task_id")

    # Optional budget gate: if budgets are configured the caller can
    # block the checkout when over hard limit.
    if budgets:
        cost_events = list_cost_events(store)
        decision = evaluate_budget(budgets, cost_events, agent_id=auth.agent_id)
        if decision.state == BLOCK:
            return 402, {
                "error": "budget_blocked",
                "spent_usd": decision.spent_usd,
                "limit_usd": decision.limit_usd,
                "budget_id": decision.budget_id,
                "reason": decision.reason,
            }

    result = store.checkout_task(
        task_id,
        agent_id=auth.agent_id,
        adapter_type=str(body.get("adapter_type", "")),
        approval_id=str(body.get("approval_id", "")),
    )
    if result.ok:
        return 200, {
            "ok": True,
            "resumed": result.resumed,
            "run": result.run.to_dict() if result.run else None,
        }
    if result.conflict is None:
        return 500, {"error": "unknown_checkout_failure"}
    code = 404 if result.conflict.reason == "task_not_found" else 409
    return code, {
        "error": result.conflict.reason,
        "conflict": result.conflict.to_dict(),
    }


def handle_run_log(
    store: FileStore,
    auth: AuthResult,
    *,
    run_id: str,
    body: dict | None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/runs/<id>/log — agent appends a structured log entry."""
    body = body or {}
    run = store.get_run(run_id)
    if run is None:
        return _err(404, "run_not_found", run_id=run_id)
    allowed, reason = authorize(
        auth,
        required_scope=SCOPE_RUN_LOG,
        target_agent_id=run.agent_id,
    )
    if not allowed:
        return _err(403, reason)

    line = str(body.get("message") or "").strip()
    level = str(body.get("level") or "info")
    if not line:
        return _err(400, "missing_message")

    _audit(
        store,
        "run.log",
        "run",
        run_id,
        f"agent:{auth.agent_id}",
        after={"level": level, "message": line[:1024]},
    )
    return 200, {"ok": True}


def handle_run_cost(
    store: FileStore,
    auth: AuthResult,
    *,
    run_id: str,
    body: dict | None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/runs/<id>/cost — agent reports a cost event."""
    body = body or {}
    run = store.get_run(run_id)
    if run is None:
        return _err(404, "run_not_found", run_id=run_id)
    allowed, reason = authorize(
        auth,
        required_scope=SCOPE_RUN_COST,
        target_agent_id=run.agent_id,
    )
    if not allowed:
        return _err(403, reason)

    try:
        event = record_cost(
            store,
            provider=str(body.get("provider", "")),
            model=str(body.get("model", "")),
            input_tokens=int(body.get("input_tokens", 0) or 0),
            output_tokens=int(body.get("output_tokens", 0) or 0),
            estimated_cost_usd=float(body.get("estimated_cost_usd", 0.0) or 0.0),
            verified=bool(body.get("verified", False)),
            source=str(body.get("source", "adapter_reported")),
            run_id=run_id,
            task_id=run.task_id,
            agent_id=auth.agent_id,
            target=str(body.get("target") or "") or None,
        )
    except (TypeError, ValueError) as exc:
        return _err(400, "invalid_payload", detail=str(exc))

    return 200, {"ok": True, "cost_event": event.to_dict()}


def handle_run_ready_for_review(
    store: FileStore,
    auth: AuthResult,
    *,
    run_id: str,
    body: dict | None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/runs/<id>/ready-for-review — agent declares a run done."""
    body = body or {}
    run = store.get_run(run_id)
    if run is None:
        return _err(404, "run_not_found", run_id=run_id)
    allowed, reason = authorize(
        auth,
        required_scope=SCOPE_RUN_READY,
        target_agent_id=run.agent_id,
    )
    if not allowed:
        return _err(403, reason)

    # Move the run to succeeded if it isn't terminal yet, then move
    # the task to ready_for_review.
    try:
        new_run = transition_run(run, "succeeded", reason="ready_for_review")
    except ValueError:
        new_run = run  # already terminal — keep current state
    store.create_run(new_run)  # atomic_write_json — overwrites in place

    task = store.get_task(run.task_id)
    if task is None:
        return _err(404, "task_not_found", task_id=run.task_id)

    if not is_legal_task_transition(task.status, "ready_for_review"):
        return _err(
            409,
            "illegal_task_transition",
            from_state=task.status,
            to_state="ready_for_review",
        )
    store.transition_task(
        task.id,
        "ready_for_review",
        actor=f"agent:{auth.agent_id}",
        reason=str(body.get("note") or "marked ready by agent"),
    )
    return 200, {"ok": True, "run_id": new_run.id, "task_id": task.id}


def handle_run_cancel(
    store: FileStore,
    auth: AuthResult,
    *,
    run_id: str,
    body: dict | None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/runs/<id>/cancel — agent cancels its own run."""
    body = body or {}
    run = store.get_run(run_id)
    if run is None:
        return _err(404, "run_not_found", run_id=run_id)
    allowed, reason = authorize(
        auth,
        required_scope=SCOPE_RUN_LOG,  # any agent-mutating scope suffices
        target_agent_id=run.agent_id,
    )
    if not allowed:
        return _err(403, reason)
    try:
        new_run = transition_run(run, "cancelled", reason=str(body.get("reason") or ""))
    except ValueError:
        return _err(409, "run_already_terminal", state=run.state)
    store.create_run(new_run)
    _audit(
        store,
        "run.cancelled",
        "run",
        run_id,
        f"agent:{auth.agent_id}",
        before={"state": run.state},
        after={"state": new_run.state},
    )
    return 200, {"ok": True}


def handle_request_approval(
    store: FileStore,
    auth: AuthResult,
    *,
    body: dict | None,
) -> tuple[int, dict[str, Any]]:
    """POST /api/approvals/request — agent or operator requests an approval."""
    body = body or {}
    allowed, reason = authorize(auth, required_scope=SCOPE_REQUEST_APPROVAL)
    if not allowed:
        return _err(403, reason)
    task_id = str(body.get("task_id") or "")
    scope = str(body.get("scope") or "plan")
    note = str(body.get("note") or "")
    if not task_id:
        return _err(400, "missing_task_id")
    if store.get_task(task_id) is None:
        return _err(404, "task_not_found", task_id=task_id)

    approval_id = f"appr-{uuid.uuid4().hex[:12]}"
    _audit(
        store,
        "approval.requested",
        "approval",
        approval_id,
        f"agent:{auth.agent_id}" if auth.agent_id else "operator",
        after={
            "task_id": task_id,
            "scope": scope,
            "requested_by": auth.agent_id,
            "note": note,
        },
    )
    return 200, {
        "ok": True,
        "approval_id": approval_id,
        "task_id": task_id,
        "scope": scope,
        "state": "requested",
    }


def handle_decide_approval(
    store: FileStore,
    auth: AuthResult,
    *,
    approval_id: str,
    body: dict | None,
    operator_authenticated: bool = False,
) -> tuple[int, dict[str, Any]]:
    """POST /api/approvals/<id>/decide — operator approves or rejects.

    Only operator-authenticated callers may decide; agents request,
    operators decide.
    """
    if not operator_authenticated:
        return _err(403, "operator_only")

    body = body or {}
    decision = str(body.get("decision") or "").lower()
    if decision not in {"approved", "rejected"}:
        return _err(400, "invalid_decision",
                    legal=["approved", "rejected"])

    note = str(body.get("note") or "")
    actor = str(body.get("by") or "operator")

    _audit(
        store,
        f"approval.{decision}",
        "approval",
        approval_id,
        actor,
        after={"state": decision, "note": note},
    )
    return 200, {
        "ok": True,
        "approval_id": approval_id,
        "state": decision,
    }
