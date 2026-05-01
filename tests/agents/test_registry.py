"""Tests for the AgentRegistry."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.agents import AgentNotFound, AgentRegistry, sync_from_config
from backoffice.store import FileStore


@pytest.fixture
def registry(tmp_path: Path) -> AgentRegistry:
    store = FileStore(root=tmp_path)
    return AgentRegistry(store=store)


def test_create_returns_agent_with_id(registry: AgentRegistry):
    a = registry.create(name="fix-agent", role="fixer", adapter_type="process")
    assert a.id
    assert a.name == "fix-agent"
    assert a.status == "active"


def test_create_persists_and_lists(registry: AgentRegistry):
    a = registry.create(name="fix-agent", role="fixer")
    listed = registry.list()
    assert any(x.id == a.id for x in listed)


def test_create_rejects_unknown_role(registry: AgentRegistry):
    with pytest.raises(ValueError):
        registry.create(name="bad", role="nope")


def test_create_with_explicit_id_is_idempotent_only_via_get(registry: AgentRegistry):
    registry.create(agent_id="agent-fix", name="x")
    with pytest.raises(ValueError):
        registry.create(agent_id="agent-fix", name="x")


def test_get_returns_none_for_missing(registry: AgentRegistry):
    assert registry.get("missing") is None


def test_pause_and_resume_round_trip(registry: AgentRegistry):
    registry.create(name="x", agent_id="agent-x")
    paused = registry.pause("agent-x")
    assert paused.status == "paused"
    assert paused.paused_at
    resumed = registry.resume("agent-x")
    assert resumed.status == "active"
    assert resumed.paused_at == ""


def test_pause_idempotent(registry: AgentRegistry):
    registry.create(name="x", agent_id="agent-x")
    registry.pause("agent-x")
    again = registry.pause("agent-x")  # must not raise
    assert again.status == "paused"


def test_retire_marks_status(registry: AgentRegistry):
    registry.create(name="x", agent_id="agent-x")
    retired = registry.retire("agent-x")
    assert retired.status == "retired"


def test_pause_unknown_raises(registry: AgentRegistry):
    with pytest.raises(AgentNotFound):
        registry.pause("missing")


def test_create_emits_audit_event(registry: AgentRegistry):
    a = registry.create(name="x", agent_id="agent-x")
    events = registry.store.read_audit_events()
    assert any(e.action == "agent.created" and e.subject_id == a.id for e in events)


def test_pause_emits_audit_event(registry: AgentRegistry):
    registry.create(name="x", agent_id="agent-x")
    registry.pause("agent-x")
    events = registry.store.read_audit_events()
    assert any(e.action == "agent.paused" for e in events)


# ──────────────────────────────────────────────────────────────────────
# Config sync
# ──────────────────────────────────────────────────────────────────────


def test_sync_from_config_creates_missing_agents(registry: AgentRegistry):
    raw = {
        "fix-agent": {"role": "fixer", "adapter_type": "process",
                      "adapter_config": {"command": "bash agents/fix-bugs.sh"}},
        "product-owner": {"role": "product_owner", "adapter_type": "noop"},
    }
    out = sync_from_config(raw, registry=registry)
    assert {a.name for a in out} == {"fix-agent", "product-owner"}
    assert {a.id for a in registry.list()} == {a.id for a in out}


def test_sync_from_config_updates_existing(registry: AgentRegistry):
    raw = {"fix-agent": {"role": "fixer", "adapter_type": "process"}}
    sync_from_config(raw, registry=registry)
    raw["fix-agent"]["description"] = "now has docs"
    sync_from_config(raw, registry=registry)
    listed = registry.list()
    assert len(listed) == 1
    assert listed[0].description == "now has docs"


def test_sync_from_config_handles_list_form(registry: AgentRegistry):
    raw = [{"name": "fix-agent", "role": "fixer"}]
    out = sync_from_config(raw, registry=registry)
    assert len(out) == 1
    assert out[0].name == "fix-agent"


def test_sync_from_config_skips_garbage(registry: AgentRegistry):
    raw = {"good": {"role": "fixer"}, "bad": "not-a-dict"}
    out = sync_from_config(raw, registry=registry)
    assert {a.name for a in out} == {"good"}
