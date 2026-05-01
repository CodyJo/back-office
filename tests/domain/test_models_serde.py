"""Round-trip tests for backoffice.domain.models."""
from __future__ import annotations

import pytest

from backoffice.domain import (
    ACTOR_KINDS,
    AGENT_ROLES,
    AGENT_STATUSES,
    APPROVAL_STATES,
    RUN_STATES,
    TASK_STATES,
    Actor,
    AdapterConfig,
    Agent,
    Approval,
    AuditEvent,
    CostEvent,
    HistoryEntry,
    Run,
    Task,
    Workspace,
)


# ──────────────────────────────────────────────────────────────────────
# Sanity: registries are non-empty and contain expected keys
# ──────────────────────────────────────────────────────────────────────


def test_state_registries_are_non_empty():
    assert "proposed" in TASK_STATES
    assert "checked_out" in TASK_STATES  # net-new
    assert "failed" in TASK_STATES  # net-new
    assert "cancelled" in TASK_STATES
    assert "running" in RUN_STATES
    assert "succeeded" in RUN_STATES
    assert "approved" in APPROVAL_STATES
    assert "scanner" in AGENT_ROLES
    assert "active" in AGENT_STATUSES
    assert "operator" in ACTOR_KINDS


def test_legacy_task_states_are_all_recognized():
    """Every status used by backoffice.tasks today must be a valid TASK_STATES entry."""
    from backoffice.tasks import STATUS_ORDER

    for status in STATUS_ORDER:
        assert status in TASK_STATES, f"legacy status {status!r} dropped from TASK_STATES"


# ──────────────────────────────────────────────────────────────────────
# HistoryEntry
# ──────────────────────────────────────────────────────────────────────


def test_history_entry_round_trip():
    raw = {
        "status": "ready",
        "at": "2026-04-29T12:00:00+00:00",
        "by": "operator",
        "note": "approved",
    }
    h = HistoryEntry.from_dict(raw)
    assert h.to_dict() == raw


def test_history_entry_handles_missing_fields():
    h = HistoryEntry.from_dict({"status": "proposed"})
    assert h.status == "proposed"
    assert h.at == ""
    assert h.by == ""
    assert h.note == ""


def test_history_entry_handles_non_dict():
    h = HistoryEntry.from_dict(None)
    assert h.status == ""


# ──────────────────────────────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────────────────────────────


def _full_task_dict() -> dict:
    """A maximalist task dict — exercises every canonical field plus extras."""
    return {
        "id": "back-office:fix-foo:20260429-120000",
        "repo": "back-office",
        "title": "Fix foo",
        "status": "ready",
        "priority": "high",
        "category": "bugfix",
        "task_type": "finding_fix",
        "owner": "operator",
        "created_by": "dashboard",
        "created_at": "2026-04-29T12:00:00+00:00",
        "updated_at": "2026-04-29T12:30:00+00:00",
        "notes": "details",
        "product_key": "back-office",
        "target_path": "/home/merm/projects/back-office",
        "handoff_required": True,
        "verification_command": "make test",
        "repo_handoff_path": "/home/merm/projects/back-office/docs/HANDOFF.md",
        "acceptance_criteria": ["one", "two"],
        "audits_required": ["qa", "product"],
        "history": [
            {"status": "pending_approval", "at": "2026-04-29T12:00:00+00:00", "by": "dashboard", "note": "queued"},
            {"status": "ready", "at": "2026-04-29T12:30:00+00:00", "by": "operator", "note": "approved"},
        ],
        "approval": {
            "approved_at": "2026-04-29T12:30:00+00:00",
            "approved_by": "operator",
            "note": "lgtm",
        },
        "source_finding": {
            "hash": "abc123",
            "id": "QA-1",
            "department": "qa",
            "severity": "high",
            "category": "bug",
            "file": "foo.py",
            "line": 42,
            "fixable_by_agent": True,
        },
        "pr": {
            "url": "https://github.com/cody/back-office/pull/1",
            "title": "Review: Fix foo",
            "branch": "feature/fix-foo",
            "created_at": "2026-04-29T13:00:00+00:00",
        },
    }


def test_task_round_trip_full():
    raw = _full_task_dict()
    task = Task.from_dict(raw)
    assert task.id == raw["id"]
    assert task.status == "ready"
    assert len(task.history) == 2
    assert task.history[0].status == "pending_approval"
    out = task.to_dict()
    assert out == raw


def test_task_round_trip_with_extras():
    raw = _full_task_dict()
    raw["future_field"] = {"hello": "world"}
    raw["another_extra"] = ["a", "b"]
    task = Task.from_dict(raw)
    assert task.extras["future_field"] == {"hello": "world"}
    assert task.extras["another_extra"] == ["a", "b"]
    assert task.to_dict() == raw


def test_task_round_trip_minimal_pending_approval():
    """A real task seeded by /api/tasks/queue-finding has empty payloads."""
    raw = {
        "id": "x",
        "repo": "back-office",
        "title": "t",
        "status": "pending_approval",
        "priority": "medium",
        "category": "review",
        "task_type": "finding_fix",
        "owner": "",
        "created_by": "dashboard",
        "created_at": "2026-04-29T00:00:00+00:00",
        "updated_at": "2026-04-29T00:00:00+00:00",
        "notes": "",
        "product_key": "back-office",
        "target_path": "/home/merm/projects/back-office",
        "handoff_required": True,
        "verification_command": "",
        "repo_handoff_path": "",
        "acceptance_criteria": [],
        "audits_required": [],
        "history": [],
        "approval": {},
        "source_finding": {},
        "pr": {},
    }
    task = Task.from_dict(raw)
    assert task.to_dict() == raw


def test_task_from_dict_rejects_non_mapping():
    with pytest.raises(TypeError):
        Task.from_dict("not a dict")  # type: ignore[arg-type]


def test_task_handles_history_garbage_gracefully():
    """Non-dict entries in history are filtered, not raised."""
    raw = {
        "id": "x",
        "repo": "r",
        "title": "t",
        "history": [
            {"status": "ready", "at": "now", "by": "x", "note": ""},
            "not-a-dict",  # garbage
            None,
        ],
    }
    task = Task.from_dict(raw)
    assert len(task.history) == 1
    assert task.history[0].status == "ready"


def test_task_handles_none_collection_fields():
    raw = {
        "id": "x",
        "repo": "r",
        "title": "t",
        "history": None,
        "acceptance_criteria": None,
        "audits_required": None,
        "approval": None,
        "source_finding": None,
        "pr": None,
    }
    task = Task.from_dict(raw)
    assert task.history == []
    assert task.acceptance_criteria == []
    assert task.audits_required == []
    assert task.approval == {}


# ──────────────────────────────────────────────────────────────────────
# Run / Approval / CostEvent / Workspace / Agent / Actor / AuditEvent
# ──────────────────────────────────────────────────────────────────────


def test_run_round_trip():
    raw = {
        "id": "run-1",
        "task_id": "task-1",
        "agent_id": "agent-fix",
        "adapter_type": "process",
        "adapter_handle": "pid:42",
        "workspace_id": "ws-1",
        "approval_id": "appr-1",
        "state": "running",
        "started_at": "2026-04-29T13:00:00+00:00",
        "ended_at": "",
        "exit_code": None,
        "duration_ms": None,
        "prompt_ref": "prompts/fix-bugs.md",
        "output_summary": "",
        "artifacts": [{"kind": "log", "path": "results/runs/run-1.log", "sha256": "abc"}],
        "cost": {"estimated_cost_usd": 0.0},
        "error": "",
        "metadata": {"foo": "bar"},
    }
    run = Run.from_dict(raw)
    assert run.state == "running"
    assert run.to_dict() == raw


def test_run_with_extras():
    raw = {"id": "r", "state": "queued", "future_field": "value"}
    run = Run.from_dict(raw)
    assert run.extras == {"future_field": "value"}
    out = run.to_dict()
    assert out["future_field"] == "value"


def test_approval_round_trip():
    raw = {
        "id": "appr-1",
        "task_id": "task-1",
        "scope": "plan",
        "state": "approved",
        "requested_by": "dashboard",
        "requested_at": "2026-04-29T12:00:00+00:00",
        "decided_by": "operator",
        "decided_at": "2026-04-29T12:30:00+00:00",
        "reason": "lgtm",
        "expires_at": "",
        "policy_basis": "fix",
        "audit_event_id": "evt-1",
    }
    a = Approval.from_dict(raw)
    assert a.to_dict() == raw


def test_cost_event_round_trip():
    raw = {
        "id": "cost-1",
        "run_id": "run-1",
        "task_id": "task-1",
        "agent_id": "agent-fix",
        "target": "back-office",
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "input_tokens": 1000,
        "output_tokens": 200,
        "total_tokens": 1200,
        "estimated_cost_usd": 0.05,
        "verified": False,
        "source": "estimate",
        "timestamp": "2026-04-29T13:00:00+00:00",
    }
    c = CostEvent.from_dict(raw)
    assert c.to_dict() == raw


def test_workspace_round_trip():
    raw = {
        "id": "ws-1",
        "task_id": "task-1",
        "repo": "back-office",
        "kind": "branch",
        "branch": "back-office/preview/job-123",
        "base_ref": "main",
        "base_sha": "abc",
        "head_sha": "def",
        "worktree_path": "",
        "created_at": "2026-04-29T13:00:00+00:00",
        "updated_at": "2026-04-29T13:00:00+00:00",
        "retired_at": "",
        "test_results_ref": "",
        "metadata": {"commits": []},
    }
    w = Workspace.from_dict(raw)
    assert w.to_dict() == raw


def test_agent_round_trip():
    raw = {
        "id": "agent-fix",
        "name": "fix-agent",
        "role": "fixer",
        "description": "Auto-remediates QA findings",
        "adapter_type": "process",
        "adapter_config": {"command": "bash agents/fix-bugs.sh"},
        "status": "active",
        "paused_at": "",
        "budget_id": "",
        "metadata": {"team": "ops"},
        "created_at": "2026-04-29T00:00:00+00:00",
        "updated_at": "2026-04-29T00:00:00+00:00",
    }
    a = Agent.from_dict(raw)
    assert a.to_dict() == raw


def test_adapter_config_round_trip():
    raw = {
        "agent_id": "agent-fix",
        "adapter_type": "process",
        "command": "bash agents/fix-bugs.sh",
        "args": ["--preview"],
        "env_allowlist": ["PATH", "HOME"],
        "cwd_strategy": "worktree",
        "timeout_seconds": 1800,
        "prompt_template": "agents/prompts/fix-bugs.md",
        "dry_run_default": False,
        "metadata": {},
    }
    a = AdapterConfig.from_dict(raw)
    assert a.to_dict() == raw


def test_actor_round_trip():
    raw = {"id": "u-1", "kind": "operator", "display_name": "Cody", "agent_id": ""}
    actor = Actor.from_dict(raw)
    assert actor.to_dict() == raw


def test_audit_event_round_trip():
    raw = {
        "id": "evt-1",
        "at": "2026-04-29T13:00:00+00:00",
        "actor_id": "u-1",
        "action": "task.transition",
        "subject_kind": "task",
        "subject_id": "task-1",
        "before": {"status": "ready"},
        "after": {"status": "in_progress"},
        "reason": "Task started",
        "metadata": {},
    }
    e = AuditEvent.from_dict(raw)
    assert e.to_dict() == raw


@pytest.mark.parametrize(
    "cls",
    [Task, Run, Approval, CostEvent, Workspace, Agent, AdapterConfig, Actor, AuditEvent],
)
def test_default_constructed_round_trip(cls):
    """A default-constructed instance must round-trip without raising."""
    instance = cls()
    out = instance.to_dict()
    assert isinstance(out, dict)
    rebuilt = cls.from_dict(out)
    assert rebuilt.to_dict() == out
