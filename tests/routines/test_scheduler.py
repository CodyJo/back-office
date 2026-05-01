"""Tests for Phase 8 routines + scheduler."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backoffice.budgets import Budget
from backoffice.domain import CostEvent
from backoffice.routines import Routine, Scheduler, from_config
from backoffice.store import FileStore


@pytest.fixture
def scheduler(tmp_path: Path) -> Scheduler:
    return Scheduler(store=FileStore(root=tmp_path))


def _routine(scheduler: Scheduler, **overrides) -> Routine:
    base = dict(
        id="r-test",
        name="t",
        trigger_kind="manual",
        action_kind="noop",
    )
    base.update(overrides)
    routine = Routine(**base)
    return scheduler.upsert(routine)


def test_run_now_fires_handler(scheduler: Scheduler):
    _routine(scheduler)
    result = scheduler.run_now("r-test")
    assert result["state"] == "fired"
    assert result["result"]["noop"] is True


def test_paused_routine_does_not_fire(scheduler: Scheduler):
    _routine(scheduler, paused=True)
    result = scheduler.run_now("r-test")
    assert result["state"] == "paused"


def test_pause_then_resume(scheduler: Scheduler):
    _routine(scheduler)
    scheduler.pause("r-test")
    assert scheduler.run_now("r-test")["state"] == "paused"
    scheduler.resume("r-test")
    assert scheduler.run_now("r-test")["state"] == "fired"


def test_unknown_routine_raises(scheduler: Scheduler):
    with pytest.raises(LookupError):
        scheduler.run_now("missing")


def test_run_now_records_last_run(scheduler: Scheduler):
    _routine(scheduler)
    scheduler.run_now("r-test")
    r = scheduler.get("r-test")
    assert r is not None
    assert r.last_run_at


def test_invalid_routine_construction():
    with pytest.raises(ValueError):
        Routine(id="r", name="n", trigger_kind="nope")
    with pytest.raises(ValueError):
        Routine(id="r", name="n", action_kind="nope")


def test_run_due_now_fires_when_interval_elapsed(scheduler: Scheduler):
    _routine(
        scheduler,
        id="r-cron",
        trigger_kind="cron",
        trigger={"interval_seconds": 60},
    )
    # Without last_run_at, should fire immediately.
    results = scheduler.run_due_now()
    assert len(results) == 1
    assert results[0]["state"] == "fired"


def test_run_due_now_skips_when_too_soon(scheduler: Scheduler):
    _routine(
        scheduler,
        id="r-cron",
        trigger_kind="cron",
        trigger={"interval_seconds": 600},
    )
    # First fire stamps last_run_at to now.
    scheduler.run_due_now()
    # Second fire: too soon.
    results = scheduler.run_due_now()
    assert results == []


def test_run_due_now_fires_again_after_interval(scheduler: Scheduler):
    """Set last_run_at explicitly so we don't depend on real time."""
    routine = Routine(
        id="r-cron",
        name="t",
        trigger_kind="cron",
        trigger={"interval_seconds": 60},
        action_kind="noop",
        last_run_at="2026-01-01T00:00:00+00:00",
    )
    scheduler.upsert(routine)
    later = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    results = scheduler.run_due_now(now=later)
    assert len(results) == 1
    assert results[0]["state"] == "fired"


def test_run_due_now_skips_paused_routines(scheduler: Scheduler):
    _routine(
        scheduler,
        id="r-cron",
        trigger_kind="cron",
        trigger={"interval_seconds": 60},
        paused=True,
    )
    assert scheduler.run_due_now() == []


def test_budget_blocks_run(scheduler: Scheduler):
    _routine(scheduler, budget_id="b1")
    budgets = [Budget(id="b1", scope="global", hard_limit_usd=1.0)]
    cost_events = [CostEvent(id="e", estimated_cost_usd=2.0)]
    result = scheduler.run_now("r-test", budgets=budgets, cost_events=cost_events)
    assert result["state"] == "blocked"


def test_budget_warn_does_not_block(scheduler: Scheduler):
    _routine(scheduler, budget_id="b1")
    budgets = [Budget(id="b1", scope="global", soft_limit_usd=0.5, hard_limit_usd=10.0)]
    cost_events = [CostEvent(id="e", estimated_cost_usd=1.0)]
    result = scheduler.run_now("r-test", budgets=budgets, cost_events=cost_events)
    assert result["state"] == "fired"


def test_unknown_action_kind_returns_no_handler(scheduler: Scheduler):
    _routine(scheduler, action_kind="run_agent")
    # Default scheduler only registers noop; run_agent unhandled.
    result = scheduler.run_now("r-test")
    assert result["state"] == "no_handler"


def test_handler_exception_is_captured(scheduler: Scheduler):
    def boom(r, now):
        raise RuntimeError("kaboom")
    scheduler.register_handler("noop", boom)
    _routine(scheduler)
    result = scheduler.run_now("r-test")
    assert result["state"] == "error"
    assert "kaboom" in result["error"]


def test_audit_event_emitted_on_fire(scheduler: Scheduler):
    _routine(scheduler)
    scheduler.run_now("r-test")
    events = scheduler.store.read_audit_events()
    assert any(e.action == "routine.run" for e in events)


# ──────────────────────────────────────────────────────────────────────
# Config bridge
# ──────────────────────────────────────────────────────────────────────


def test_from_config_creates_routines(scheduler: Scheduler):
    raw = [
        {
            "id": "audit-portfolio",
            "name": "Hourly portfolio audit",
            "trigger_kind": "cron",
            "trigger": {"interval_seconds": 3600},
            "action_kind": "noop",
        }
    ]
    out = from_config(raw, scheduler=scheduler)
    assert len(out) == 1
    assert scheduler.get("audit-portfolio") is not None


def test_from_config_drops_invalid(scheduler: Scheduler):
    raw = [
        {"id": "good", "name": "x", "trigger_kind": "manual", "action_kind": "noop"},
        {"id": "bad", "name": "y", "trigger_kind": "what"},
    ]
    out = from_config(raw, scheduler=scheduler)
    assert [r.id for r in out] == ["good"]
