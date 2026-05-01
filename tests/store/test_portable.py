"""Tests for Phase 11 export / import."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backoffice.agents import AgentRegistry
from backoffice.portable import (
    REDACTED,
    ExportSelection,
    apply_payload,
    export_json,
    export_payload,
    validate_payload,
)
from backoffice.routines import Routine, Scheduler
from backoffice.store import FileStore


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


# ──────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────


def test_export_includes_agents_and_routines(store: FileStore):
    AgentRegistry(store=store).create(name="fix-agent", agent_id="agent-fix", role="fixer")
    Scheduler(store=store).upsert(
        Routine(id="r1", name="x", trigger_kind="manual", action_kind="noop")
    )
    payload = export_payload(store=store, config_payload={})
    assert payload["version"] == 1
    assert any(a["id"] == "agent-fix" for a in payload["resources"]["agents"])
    assert any(r["id"] == "r1" for r in payload["resources"]["routines"])


def test_export_redacts_sensitive_keys(store: FileStore):
    payload = export_payload(
        store=store,
        config_payload={
            "deploy": {
                "bunny": {
                    "dashboard_targets": [
                        {"cdn_id": "1", "api_key": "shhhh", "storage_token": "also-shhhh"}
                    ],
                },
            },
            "budgets": [
                {"id": "b1", "scope": "global", "hard_limit_usd": 100, "secret_note": "xyz"},
            ],
        },
    )
    dt = payload["resources"]["dashboard_targets"][0]
    assert dt["api_key"] == REDACTED
    assert dt["storage_token"] == REDACTED
    assert dt["cdn_id"] == "1"  # non-sensitive preserved
    b = payload["resources"]["budgets"][0]
    assert b["secret_note"] == REDACTED
    assert b["hard_limit_usd"] == 100


def test_export_redacts_nested_sensitive_keys(store: FileStore):
    """Sensitive keys nested in dicts must be redacted recursively."""
    AgentRegistry(store=store).create(
        name="x",
        agent_id="x",
        adapter_config={"command": "x", "credentials": {"api_token": "secret-y"}},
    )
    payload = export_payload(store=store, config_payload={})
    cfg = payload["resources"]["agents"][0]["adapter_config"]
    assert cfg["credentials"] == REDACTED  # whole credentials key redacted


def test_export_is_deterministic(store: FileStore):
    AgentRegistry(store=store).create(name="b", agent_id="b")
    AgentRegistry(store=store).create(name="a", agent_id="a")
    p1 = export_payload(store=store, config_payload={})
    p2 = export_payload(store=store, config_payload={})
    # Sorted by id, so same output every time.
    assert export_json(p1) == export_json(p2)
    assert [a["id"] for a in p1["resources"]["agents"]] == ["a", "b"]


def test_export_selection_filters(store: FileStore):
    AgentRegistry(store=store).create(name="x", agent_id="x")
    payload = export_payload(
        store=store,
        config_payload={},
        selection=ExportSelection(
            include_agents=False,
            include_routines=True,
            include_budgets=False,
            include_dashboard_targets=False,
            include_autonomy=False,
        ),
    )
    assert "agents" not in payload["resources"]
    assert "routines" in payload["resources"]
    assert "budgets" not in payload["resources"]


def test_export_includes_autonomy_blocks(store: FileStore):
    payload = export_payload(
        store=store,
        config_payload={
            "targets": {
                "back-office": {"autonomy": {"allow_fix": True, "deploy_mode": "disabled"}},
                "no-autonomy": {"path": "/x"},
            },
        },
    )
    autonomy = payload["resources"]["autonomy"]
    assert "back-office" in autonomy
    assert autonomy["back-office"]["allow_fix"] is True


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────


def test_validate_rejects_non_object():
    assert validate_payload("nope") == ["payload is not an object"]


def test_validate_rejects_wrong_version():
    errors = validate_payload({"version": 99, "resources": {}})
    assert any("unsupported export version" in e for e in errors)


def test_validate_rejects_missing_resources():
    errors = validate_payload({"version": 1})
    assert any("resources" in e for e in errors)


def test_validate_passes_minimal_valid():
    assert validate_payload({"version": 1, "resources": {}}) == []


# ──────────────────────────────────────────────────────────────────────
# Import (dry-run + apply)
# ──────────────────────────────────────────────────────────────────────


def test_dry_run_reports_additions(store: FileStore):
    payload = {
        "version": 1,
        "resources": {
            "agents": [{"id": "agent-x", "name": "x", "role": "fixer"}],
            "routines": [{"id": "r1", "name": "x", "trigger_kind": "manual", "action_kind": "noop"}],
        },
    }
    plan = apply_payload(payload, store=store, dry_run=True)
    assert plan.ok
    assert plan.additions["agents"] == ["agent-x"]
    assert plan.additions["routines"] == ["r1"]
    # Dry-run did not actually create anything.
    assert AgentRegistry(store=store).get("agent-x") is None


def test_apply_creates_resources(store: FileStore):
    payload = {
        "version": 1,
        "resources": {
            "agents": [{"id": "agent-x", "name": "x", "role": "fixer"}],
        },
    }
    plan = apply_payload(payload, store=store, dry_run=False)
    assert plan.additions["agents"] == ["agent-x"]
    assert AgentRegistry(store=store).get("agent-x") is not None


def test_apply_reports_unchanged(store: FileStore):
    AgentRegistry(store=store).create(
        name="x", agent_id="agent-x", role="fixer", adapter_type="process"
    )
    payload = {
        "version": 1,
        "resources": {
            "agents": [
                {
                    "id": "agent-x",
                    "name": "x",
                    "role": "fixer",
                    "adapter_type": "process",
                    "description": "",
                }
            ],
        },
    }
    plan = apply_payload(payload, store=store, dry_run=True)
    assert "agent-x" in plan.unchanged["agents"]
    assert plan.additions["agents"] == []


def test_apply_reports_conflict_without_overwrite(store: FileStore):
    AgentRegistry(store=store).create(name="orig", agent_id="agent-x", role="fixer")
    payload = {
        "version": 1,
        "resources": {
            "agents": [{"id": "agent-x", "name": "renamed", "role": "fixer"}],
        },
    }
    plan = apply_payload(payload, store=store, dry_run=False, overwrite=False)
    assert "agent-x" in plan.conflicts["agents"]
    assert AgentRegistry(store=store).get("agent-x").name == "orig"


def test_apply_overwrites_when_requested(store: FileStore):
    AgentRegistry(store=store).create(name="orig", agent_id="agent-x", role="fixer")
    payload = {
        "version": 1,
        "resources": {
            "agents": [{"id": "agent-x", "name": "renamed", "role": "fixer"}],
        },
    }
    apply_payload(payload, store=store, dry_run=False, overwrite=True)
    assert AgentRegistry(store=store).get("agent-x").name == "renamed"


def test_apply_strips_redacted_placeholders(store: FileStore):
    payload = {
        "version": 1,
        "resources": {
            "agents": [
                {
                    "id": "agent-x",
                    "name": "x",
                    "adapter_config": {"command": "x", "api_key": REDACTED},
                }
            ],
        },
    }
    apply_payload(payload, store=store, dry_run=False)
    cfg = AgentRegistry(store=store).get("agent-x").adapter_config
    # REDACTED placeholders are converted to empty strings, never kept.
    assert cfg.get("api_key") == ""


def test_export_then_import_round_trip(store: FileStore, tmp_path: Path):
    """Export produces valid input for apply_payload."""
    AgentRegistry(store=store).create(name="x", agent_id="agent-x", role="fixer")
    Scheduler(store=store).upsert(
        Routine(id="r1", name="x", trigger_kind="manual", action_kind="noop")
    )

    payload = export_payload(store=store, config_payload={})
    text = export_json(payload)
    parsed = json.loads(text)

    # Apply to a fresh store.
    fresh = FileStore(root=tmp_path / "fresh")
    plan = apply_payload(parsed, store=fresh, dry_run=False)
    assert plan.ok
    assert AgentRegistry(store=fresh).get("agent-x") is not None
    assert Scheduler(store=fresh).get("r1") is not None


def test_apply_invalid_payload_returns_errors(store: FileStore):
    plan = apply_payload({"version": 99}, store=store, dry_run=True)
    assert plan.errors
    assert not plan.ok
