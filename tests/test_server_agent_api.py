"""Integration tests for the wired Phase 9 agent endpoints.

These exercise the routing + auth + body-handling paths in
``backoffice.server`` rather than the pure handler functions in
``backoffice.agent_api``. The handler functions themselves are
covered by ``tests/test_agent_api.py``.
"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from backoffice.agents import AgentRegistry
from backoffice.auth import issue_token
from backoffice.domain import Run
from backoffice.server import DashboardHandler
from backoffice.store import FileStore


_OPERATOR_KEY = "test-operator-key"


def _seed_task(store: FileStore, task_id: str = "t1", status: str = "ready") -> None:
    raw = {
        "version": 1,
        "tasks": [{
            "id": task_id,
            "repo": "back-office",
            "title": "x",
            "status": status,
            "priority": "medium",
            "history": [],
        }],
    }
    path = store.task_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated root + minimal config so server handlers
    can call load_config() without blowing up."""
    monkeypatch.setenv("BACK_OFFICE_ROOT", str(tmp_path))
    cfg = tmp_path / "config" / "backoffice.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "runner:\n  command: claude\n  mode: claude-print\n"
        "deploy:\n  provider: bunny\n  bunny:\n    storage_zone: x\n"
        "targets: {}\n"
    )
    monkeypatch.setenv("BACK_OFFICE_CONFIG", str(cfg))
    return tmp_path


def _build_handler(
    root: Path,
    *,
    body: dict | None = None,
    path: str = "/",
    bearer: str = "",
    method: str = "POST",
):
    """Construct a DashboardHandler stub with the given request shape."""

    raw_body = json.dumps(body or {}).encode()
    captured: list[tuple[int, bytes]] = []

    class _Stub(DashboardHandler):
        _root = root
        _target_repo = ""
        _allowed_origins = {"http://localhost:8070"}
        _api_key = _OPERATOR_KEY

        def __init__(self):
            self.headers = {
                "Content-Length": str(len(raw_body)),
                "Origin": "http://localhost:8070",
            }
            if bearer:
                self.headers["Authorization"] = f"Bearer {bearer}"
            self.path = path
            self.command = method
            self.rfile = BytesIO(raw_body)
            self.wfile = BytesIO()

        def send_response(self, code: int, message: str | None = None) -> None:
            captured.append((code, b""))

        def send_header(self, *_a, **_kw) -> None:
            pass

        def end_headers(self) -> None:
            pass

    handler = _Stub()
    handler._captured = captured  # for inspection
    return handler


def _response(handler):
    """Pull the (code, parsed-json) pair out of the handler."""
    code = handler._captured[0][0] if handler._captured else 500
    body_bytes = handler.wfile.getvalue()
    payload = json.loads(body_bytes.decode()) if body_bytes else {}
    return code, payload


# ──────────────────────────────────────────────────────────────────────
# Wired endpoint behavior
# ──────────────────────────────────────────────────────────────────────


def test_checkout_route_authenticates_agent_token(isolated_root: Path):
    store = FileStore(root=isolated_root)
    _seed_task(store)
    AgentRegistry(store=store).create(name="fix-agent", agent_id="agent-fix")
    token = issue_token(store, agent_id="agent-fix")

    handler = _build_handler(
        isolated_root,
        path="/api/tasks/t1/checkout",
        body={"adapter_type": "noop"},
        bearer=token,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["ok"] is True
    assert payload["run"]["agent_id"] == "agent-fix"


def test_checkout_route_rejects_missing_token(isolated_root: Path):
    handler = _build_handler(
        isolated_root,
        path="/api/tasks/t1/checkout",
        body={},
        bearer="",
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 401
    assert "missing_token" in payload["error"]


def test_checkout_route_rejects_operator_key_as_agent(isolated_root: Path):
    """Operator key authenticates operators, not agents.
    The handler must refuse to treat it as an agent token so cross-
    role auth confusion is impossible."""
    handler = _build_handler(
        isolated_root,
        path="/api/tasks/t1/checkout",
        body={},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 401
    assert "operator_key_not_agent" in payload["error"]


def test_run_log_route_cross_agent_denied(isolated_root: Path):
    store = FileStore(root=isolated_root)
    AgentRegistry(store=store).create(name="agent-a", agent_id="agent-a")
    AgentRegistry(store=store).create(name="agent-b", agent_id="agent-b")
    token_a = issue_token(store, agent_id="agent-a")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-b", state="running"))

    handler = _build_handler(
        isolated_root,
        path="/api/runs/r1/log",
        body={"message": "evil"},
        bearer=token_a,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 403
    assert "cross_agent" in payload["error"]


def test_run_cost_route_records_event(isolated_root: Path):
    store = FileStore(root=isolated_root)
    AgentRegistry(store=store).create(name="fix", agent_id="agent-fix")
    token = issue_token(store, agent_id="agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))

    handler = _build_handler(
        isolated_root,
        path="/api/runs/r1/cost",
        body={"provider": "anthropic", "model": "x", "estimated_cost_usd": 0.01},
        bearer=token,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["cost_event"]["estimated_cost_usd"] == 0.01


def test_ready_for_review_route_transitions_task(isolated_root: Path):
    store = FileStore(root=isolated_root)
    _seed_task(store, status="in_progress")
    AgentRegistry(store=store).create(name="fix", agent_id="agent-fix")
    token = issue_token(store, agent_id="agent-fix")
    store.create_run(Run(id="r1", task_id="t1", agent_id="agent-fix", state="running"))

    handler = _build_handler(
        isolated_root,
        path="/api/runs/r1/ready-for-review",
        body={},
        bearer=token,
    )
    handler.do_POST()
    code, _ = _response(handler)
    assert code == 200
    task = store.get_task("t1")
    assert task is not None
    assert task.status == "ready_for_review"


def test_request_approval_with_operator_key(isolated_root: Path):
    """Operator key bypass on the approval-request route."""
    store = FileStore(root=isolated_root)
    _seed_task(store)
    handler = _build_handler(
        isolated_root,
        path="/api/approvals/request",
        body={"task_id": "t1", "scope": "plan"},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["state"] == "requested"


def test_decide_approval_requires_operator(isolated_root: Path):
    store = FileStore(root=isolated_root)
    AgentRegistry(store=store).create(name="fix", agent_id="agent-fix")
    token = issue_token(store, agent_id="agent-fix")

    # Agent token alone — must be denied.
    handler = _build_handler(
        isolated_root,
        path="/api/approvals/appr-x/decide",
        body={"decision": "approved"},
        bearer=token,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 403
    assert payload["error"] == "operator_only"


def test_decide_approval_with_operator_key(isolated_root: Path):
    handler = _build_handler(
        isolated_root,
        path="/api/approvals/appr-x/decide",
        body={"decision": "approved", "by": "alice"},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["state"] == "approved"


# ──────────────────────────────────────────────────────────────────────
# Token management endpoints
# ──────────────────────────────────────────────────────────────────────


def test_tokens_issue_requires_operator_key(isolated_root: Path):
    handler = _build_handler(
        isolated_root,
        path="/api/tokens/issue",
        body={"agent_id": "agent-fix"},
        bearer="",
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 401
    assert payload["error"] == "operator_only"


def test_tokens_issue_returns_plaintext_once(isolated_root: Path):
    handler = _build_handler(
        isolated_root,
        path="/api/tokens/issue",
        body={"agent_id": "agent-fix"},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["token"].startswith("bo-")
    assert payload["agent_id"] == "agent-fix"
    assert "warning" in payload


def test_tokens_revoke_returns_count_when_agent_id(isolated_root: Path):
    store = FileStore(root=isolated_root)
    issue_token(store, agent_id="agent-fix")
    issue_token(store, agent_id="agent-fix")
    handler = _build_handler(
        isolated_root,
        path="/api/tokens/revoke",
        body={"agent_id": "agent-fix"},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 200
    assert payload["revoked"] == 2


def test_tokens_revoke_requires_some_identifier(isolated_root: Path):
    handler = _build_handler(
        isolated_root,
        path="/api/tokens/revoke",
        body={},
        bearer=_OPERATOR_KEY,
    )
    handler.do_POST()
    code, payload = _response(handler)
    assert code == 400


def test_tokens_list_excludes_plaintext(isolated_root: Path):
    """The list endpoint must never reveal a plaintext token."""
    store = FileStore(root=isolated_root)
    plaintext = issue_token(store, agent_id="agent-fix")
    handler = _build_handler(
        isolated_root,
        path="/api/tokens",
        body=None,
        bearer=_OPERATOR_KEY,
        method="GET",
    )
    handler.do_GET()
    code, payload = _response(handler)
    assert code == 200
    serialized = json.dumps(payload)
    assert plaintext not in serialized
    assert any(t["agent_id"] == "agent-fix" for t in payload["tokens"])
