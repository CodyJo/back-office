"""Tests for Phase 7 cost & budget tracking."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.budgets import (
    ALLOW,
    BLOCK,
    WARN,
    Budget,
    BudgetDecision,
    cost_breakdown,
    evaluate,
    from_config,
    list_cost_events,
    record_cost,
    total_cost,
)
from backoffice.domain import CostEvent
from backoffice.store import FileStore


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


def test_record_cost_appends_jsonl(store: FileStore):
    e = record_cost(
        store,
        provider="anthropic",
        model="claude-opus-4-7",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_usd=0.02,
        run_id="r1",
        task_id="t1",
        agent_id="agent-fix",
        target="back-office",
    )
    assert e.total_tokens == 150
    events = list_cost_events(store)
    assert len(events) == 1
    assert events[0].run_id == "r1"
    assert events[0].source == "estimate"
    assert events[0].verified is False


def test_record_cost_appends_multiple_events(store: FileStore):
    for i in range(3):
        record_cost(store, provider="anthropic", model="x",
                    estimated_cost_usd=1.0, run_id=f"r{i}")
    events = list_cost_events(store)
    assert len(events) == 3
    assert total_cost(events) == 3.0


def test_cost_breakdown_groups(store: FileStore):
    record_cost(store, provider="anthropic", model="x",
                estimated_cost_usd=1.0, agent_id="a1", target="back-office")
    record_cost(store, provider="anthropic", model="x",
                estimated_cost_usd=2.0, agent_id="a1", target="codyjo.com")
    record_cost(store, provider="openai", model="y",
                estimated_cost_usd=3.0, agent_id="a2", target="codyjo.com")
    events = list_cost_events(store)
    breakdown = cost_breakdown(events)
    assert breakdown["by_agent"] == {"a1": 3.0, "a2": 3.0}
    assert breakdown["by_target"] == {"back-office": 1.0, "codyjo.com": 5.0}
    assert breakdown["by_provider"] == {"anthropic": 3.0, "openai": 3.0}


# ──────────────────────────────────────────────────────────────────────
# Budget validation
# ──────────────────────────────────────────────────────────────────────


def test_budget_rejects_invalid_scope():
    with pytest.raises(ValueError):
        Budget(id="b1", scope="universe", soft_limit_usd=1.0)


def test_budget_rejects_invalid_period():
    with pytest.raises(ValueError):
        Budget(id="b1", scope="global", period="quarterly")


def test_budget_rejects_missing_scope_id_for_non_global():
    with pytest.raises(ValueError):
        Budget(id="b1", scope="agent", scope_id="", soft_limit_usd=1.0)


# ──────────────────────────────────────────────────────────────────────
# Budget evaluation
# ──────────────────────────────────────────────────────────────────────


def _ev(amount: float, **kw) -> CostEvent:
    return CostEvent(id="x", estimated_cost_usd=amount, **kw)


def test_evaluate_allow_when_no_budgets():
    decision = evaluate([], [], agent_id="a1")
    assert decision.state == ALLOW
    assert decision.ok


def test_evaluate_warn_at_soft_limit():
    budgets = [Budget(id="b1", scope="global", soft_limit_usd=10.0, hard_limit_usd=20.0)]
    events = [_ev(15.0)]
    decision = evaluate(budgets, events)
    assert decision.state == WARN
    assert decision.spent_usd == 15.0
    assert decision.limit_usd == 10.0
    assert decision.ok  # warn is still ok


def test_evaluate_block_at_hard_limit():
    budgets = [Budget(id="b1", scope="global", soft_limit_usd=10.0, hard_limit_usd=20.0)]
    events = [_ev(20.0)]
    decision = evaluate(budgets, events)
    assert decision.state == BLOCK
    assert not decision.ok
    assert decision.budget_id == "b1"


def test_evaluate_scope_filtering():
    budgets = [Budget(id="agent-budget", scope="agent", scope_id="a1", hard_limit_usd=5.0)]
    events = [
        _ev(3.0, agent_id="a1"),
        _ev(10.0, agent_id="a2"),  # not agent-a1, irrelevant
    ]
    decision = evaluate(budgets, events, agent_id="a1")
    assert decision.state == ALLOW
    assert decision.spent_usd == 3.0


def test_evaluate_block_takes_precedence_over_warn():
    budgets = [
        Budget(id="b-soft", scope="global", soft_limit_usd=1.0),
        Budget(id="b-hard", scope="agent", scope_id="a1", hard_limit_usd=5.0),
    ]
    events = [_ev(6.0, agent_id="a1")]
    decision = evaluate(budgets, events, agent_id="a1")
    assert decision.state == BLOCK
    assert decision.budget_id == "b-hard"


def test_evaluate_target_scope():
    budgets = [Budget(id="b1", scope="target", scope_id="codyjo.com", hard_limit_usd=10.0)]
    events = [_ev(15.0, target="codyjo.com")]
    decision = evaluate(budgets, events, target="codyjo.com")
    assert decision.state == BLOCK


def test_evaluate_no_matching_budget_yields_allow():
    budgets = [Budget(id="b1", scope="agent", scope_id="other", hard_limit_usd=1.0)]
    events = [_ev(1000.0, agent_id="other")]
    decision = evaluate(budgets, events, agent_id="me")
    assert decision.state == ALLOW


def test_decision_serializable_and_useful():
    decision = BudgetDecision(state=BLOCK, spent_usd=20.0, limit_usd=10.0, budget_id="b1", reason="hard_limit:global:")
    assert not decision.ok
    assert decision.state == BLOCK


# ──────────────────────────────────────────────────────────────────────
# Config parsing
# ──────────────────────────────────────────────────────────────────────


def test_from_config_list_form():
    raw = [
        {"id": "global-cap", "scope": "global", "soft_limit_usd": 50, "hard_limit_usd": 100},
        {"id": "fix-agent", "scope": "agent", "scope_id": "agent-fix", "hard_limit_usd": 5},
    ]
    out = from_config(raw)
    assert len(out) == 2
    assert out[0].id == "global-cap"
    assert out[1].scope_id == "agent-fix"


def test_from_config_dict_form():
    raw = {
        "global-cap": {"scope": "global", "hard_limit_usd": 100},
    }
    out = from_config(raw)
    assert len(out) == 1
    assert out[0].id == "global-cap"


def test_from_config_drops_invalid():
    raw = [
        {"id": "good", "scope": "global", "soft_limit_usd": 1.0},
        {"id": "bad", "scope": "nope"},
    ]
    out = from_config(raw)
    assert [b.id for b in out] == ["good"]
