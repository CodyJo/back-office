"""Phase 6 dashboard payloads + endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backoffice.agents import AgentRegistry
from backoffice.dashboard_data import (
    build_agents_payload,
    build_audit_events_payload,
    build_runs_payload,
    refresh_all,
)
from backoffice.domain import AuditEvent, Run, iso_now
from backoffice.store import FileStore


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


def test_agents_payload_empty(store: FileStore):
    payload = build_agents_payload(store)
    assert payload["summary"]["total"] == 0
    assert payload["agents"] == []
    assert "by_status" in payload["summary"]


def test_agents_payload_includes_registered(store: FileStore):
    reg = AgentRegistry(store=store)
    reg.create(name="fix-agent", role="fixer", agent_id="agent-fix")
    reg.create(name="po", role="product_owner", agent_id="agent-po")
    reg.pause("agent-po")

    payload = build_agents_payload(store)
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["by_status"]["active"] == 1
    assert payload["summary"]["by_status"]["paused"] == 1


def test_runs_payload_summarizes_state(store: FileStore):
    store.create_run(Run(id="r1", task_id="t1", agent_id="a", state="running", started_at=iso_now()))
    store.create_run(Run(id="r2", task_id="t1", agent_id="a", state="succeeded"))
    store.create_run(Run(id="r3", task_id="t2", agent_id="b", state="failed"))

    payload = build_runs_payload(store)
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["active"] == 1
    assert payload["summary"]["by_state"]["running"] == 1
    assert payload["summary"]["by_state"]["succeeded"] == 1
    assert payload["summary"]["by_state"]["failed"] == 1
    assert len(payload["recent"]) == 3
    assert len(payload["active"]) == 1


def test_audit_events_payload_tail(store: FileStore):
    for i in range(5):
        store.append_audit_event(
            AuditEvent(
                id=f"evt-{i}",
                action="task.transition",
                subject_kind="task",
                subject_id=f"t-{i}",
            )
        )
    payload = build_audit_events_payload(store, tail=3)
    assert payload["summary"]["total"] == 5
    assert payload["summary"]["shown"] == 3
    assert [e["id"] for e in payload["events"]] == ["evt-2", "evt-3", "evt-4"]


def test_refresh_all_writes_three_files(store: FileStore, tmp_path: Path):
    paths = refresh_all(store=store, dashboard_dir=tmp_path / "dashboard")
    for kind in ("agents", "runs", "audit"):
        assert paths[kind].exists()
        json.loads(paths[kind].read_text())  # parses


def test_runs_payload_empty(store: FileStore):
    payload = build_runs_payload(store)
    assert payload["summary"]["total"] == 0
    assert payload["active"] == []
    assert payload["recent"] == []


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


def test_agents_endpoint_returns_payload(tmp_path: Path):
    """End-to-end: server endpoint reflects what's in the registry."""
    from io import BytesIO

    store = FileStore(root=tmp_path)
    AgentRegistry(store=store).create(name="x", agent_id="x")

    from backoffice.server import DashboardHandler

    captured: list[tuple[int, bytes]] = []

    class _Stub(DashboardHandler):
        _root = tmp_path
        _target_repo = ""
        _allowed_origins = {"http://x"}
        _api_key = ""

        def __init__(self):
            # Don't call super; we don't have a real socket. Stub
            # internals just enough for handler methods.
            self.headers = {"Content-Length": "0"}
            self.path = "/api/agents"
            self.command = "GET"
            self.wfile = BytesIO()

        def send_response(self, code: int, message: str | None = None) -> None:
            captured.append((code, b""))

        def send_header(self, *_a, **_kw) -> None:
            pass

        def end_headers(self) -> None:
            pass

    handler = _Stub()
    handler._handle_agents_get()
    body = handler.wfile.getvalue()
    payload = json.loads(body.decode())
    assert payload["summary"]["total"] == 1
    assert payload["agents"][0]["id"] == "x"
