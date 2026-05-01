"""Tests for the Phase 9 agent-facing API surface."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backoffice.agent_api import (
    handle_checkout,
    handle_decide_approval,
    handle_request_approval,
    handle_run_cancel,
    handle_run_cost,
    handle_run_log,
    handle_run_ready_for_review,
)
from backoffice.auth import (
    AuthResult,
    authenticate_token,
    issue_token,
)
from backoffice.budgets import Budget
from backoffice.domain import Run
from backoffice.store import FileStore


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


def _seed_task(store: FileStore, task_id: str = "t1", status: str = "ready") -> None:
    raw = {
        "version": 1,
        "tasks": [
            {
                "id": task_id,
                "repo": "back-office",
                "title": "x",
                "status": status,
                "priority": "medium",
                "history": [],
            }
        ],
    }
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _auth_for(store: FileStore, agent_id: str) -> AuthResult:
    token = issue_token(store, agent_id=agent_id)
    return authenticate_token(store, token)


# ──────────────────────────────────────────────────────────────────────
# checkout
# ──────────────────────────────────────────────────────────────────────


def test_checkout_happy_path(store: FileStore):
    _seed_task(store)
    auth = _auth_for(store, "agent-fix")
    code, body = handle_checkout(store, auth, task_id="t1", body={})
    assert code == 200
    assert body["ok"] is True
    assert body["run"]["agent_id"] == "agent-fix"


def test_checkout_unauthorized_returns_401(store: FileStore):
    _seed_task(store)
    code, body = handle_checkout(
        store,
        AuthResult(ok=False, reason="missing_token"),
        task_id="t1",
        body={},
    )
    assert code == 401
    assert body["error"] == "missing_token"


def test_checkout_unknown_task_returns_404(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, body = handle_checkout(store, auth, task_id="missing", body={})
    assert code == 404
    assert body["error"] == "task_not_found"


def test_checkout_already_running_returns_409(store: FileStore):
    _seed_task(store)
    auth_a = _auth_for(store, "agent-a")
    auth_b = _auth_for(store, "agent-b")
    handle_checkout(store, auth_a, task_id="t1", body={})
    code, body = handle_checkout(store, auth_b, task_id="t1", body={})
    assert code == 409
    assert body["error"] == "already_running"
    assert body["conflict"]["held_by_agent_id"] == "agent-a"


def test_checkout_blocked_by_hard_budget(store: FileStore):
    _seed_task(store)
    auth = _auth_for(store, "agent-fix")
    budgets = [Budget(id="b1", scope="global", hard_limit_usd=1.0)]
    # Pre-load a CostEvent that exceeds the budget.
    from backoffice.budgets import record_cost
    record_cost(store, provider="x", model="y", estimated_cost_usd=5.0)
    code, body = handle_checkout(
        store,
        auth,
        task_id="t1",
        body={},
        budgets=budgets,
    )
    assert code == 402
    assert body["error"] == "budget_blocked"


# ──────────────────────────────────────────────────────────────────────
# run log / cost
# ──────────────────────────────────────────────────────────────────────


def test_run_log_appends_audit_event(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_log(store, auth, run_id="r1", body={"message": "hello"})
    assert code == 200
    events = store.read_audit_events()
    assert any(e.action == "run.log" and e.subject_id == "r1" for e in events)


def test_run_log_cross_agent_denied(store: FileStore):
    """Agent A cannot log against agent B's run."""
    auth_a = _auth_for(store, "agent-a")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-b", state="running"))
    code, body = handle_run_log(store, auth_a, run_id="r1", body={"message": "evil"})
    assert code == 403
    assert "cross_agent" in body["error"]


def test_run_log_unknown_run_404(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, body = handle_run_log(store, auth, run_id="missing", body={"message": "x"})
    assert code == 404


def test_run_log_missing_message_400(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_log(store, auth, run_id="r1", body={})
    assert code == 400


def test_run_cost_records_event(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_cost(
        store, auth, run_id="r1",
        body={"provider": "anthropic", "model": "claude-x",
              "input_tokens": 100, "estimated_cost_usd": 0.01},
    )
    assert code == 200
    assert body["cost_event"]["estimated_cost_usd"] == 0.01


def test_run_cost_cross_agent_denied(store: FileStore):
    auth_a = _auth_for(store, "agent-a")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-b", state="running"))
    code, _ = handle_run_cost(store, auth_a, run_id="r1",
                              body={"provider": "x", "model": "y", "estimated_cost_usd": 1})
    assert code == 403


# ──────────────────────────────────────────────────────────────────────
# ready-for-review / cancel
# ──────────────────────────────────────────────────────────────────────


def test_ready_for_review_transitions_task(store: FileStore):
    _seed_task(store, status="in_progress")
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_ready_for_review(store, auth, run_id="r1", body={})
    assert code == 200
    task = store.get_task("t1")
    assert task.status == "ready_for_review"


def test_ready_for_review_illegal_state_returns_409(store: FileStore):
    _seed_task(store, status="done")
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_ready_for_review(store, auth, run_id="r1", body={})
    assert code == 409


def test_run_cancel_marks_run_cancelled(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))
    code, body = handle_run_cancel(store, auth, run_id="r1", body={})
    assert code == 200
    new = store.get_run("r1")
    assert new.state == "cancelled"


def test_run_cancel_already_terminal_returns_409(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="succeeded"))
    code, body = handle_run_cancel(store, auth, run_id="r1", body={})
    assert code == 409


# ──────────────────────────────────────────────────────────────────────
# approvals
# ──────────────────────────────────────────────────────────────────────


def test_request_approval_emits_audit(store: FileStore):
    _seed_task(store)
    auth = _auth_for(store, "agent-fix")
    code, body = handle_request_approval(
        store, auth, body={"task_id": "t1", "scope": "plan"},
    )
    assert code == 200
    assert body["state"] == "requested"
    events = store.read_audit_events()
    assert any(e.action == "approval.requested" for e in events)


def test_request_approval_unknown_task(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, _ = handle_request_approval(store, auth, body={"task_id": "missing"})
    assert code == 404


def test_decide_approval_requires_operator(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, body = handle_decide_approval(
        store, auth, approval_id="appr-x",
        body={"decision": "approved"},
        operator_authenticated=False,
    )
    assert code == 403
    assert body["error"] == "operator_only"


def test_decide_approval_records_decision(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, body = handle_decide_approval(
        store, auth, approval_id="appr-x",
        body={"decision": "approved", "by": "alice"},
        operator_authenticated=True,
    )
    assert code == 200
    assert body["state"] == "approved"
    events = store.read_audit_events()
    assert any(e.action == "approval.approved" for e in events)


def test_decide_approval_invalid_decision(store: FileStore):
    auth = _auth_for(store, "agent-fix")
    code, _ = handle_decide_approval(
        store, auth, approval_id="appr-x",
        body={"decision": "maybe"},
        operator_authenticated=True,
    )
    assert code == 400
