"""Tests for backoffice.budget_check facade."""
from __future__ import annotations

from unittest.mock import patch

from backoffice import budget_check
from backoffice.budgets import BLOCK, ALLOW, BudgetDecision


class TestCheckFacade:
    def test_no_budgets_allows(self, monkeypatch):
        # cfg has empty .budgets attr
        class _Cfg:
            budgets = []
        monkeypatch.setattr("backoffice.budget_check.load_config", lambda: _Cfg())
        decision = budget_check.check("any-target", "qa")
        assert decision.state == ALLOW
        assert decision.reason == "no-budgets-configured"

    def test_malformed_budgets_does_not_crash(self, monkeypatch):
        class _Cfg:
            budgets = [{"id": "broken", "scope": "not-a-real-scope"}]
        monkeypatch.setattr("backoffice.budget_check.load_config", lambda: _Cfg())
        decision = budget_check.check("any", "qa")
        assert decision.state == ALLOW

    def test_is_blocked_returns_true_on_block(self, monkeypatch):
        decision = BudgetDecision(state=BLOCK, spent_usd=100.0, limit_usd=50.0,
                                  budget_id="test", reason="hard")
        monkeypatch.setattr(budget_check, "check", lambda *a, **k: decision)
        assert budget_check.is_blocked("any") is True

    def test_is_blocked_returns_false_on_allow(self, monkeypatch):
        decision = BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None)
        monkeypatch.setattr(budget_check, "check", lambda *a, **k: decision)
        assert budget_check.is_blocked("any") is False


class TestCli:
    def test_exit_zero_when_allow(self, monkeypatch, capsys):
        decision = BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None)
        monkeypatch.setattr(budget_check, "check", lambda *a, **k: decision)
        rc = budget_check.main(["my-target"])
        assert rc == 0

    def test_exit_nonzero_when_block(self, monkeypatch, capsys):
        decision = BudgetDecision(state=BLOCK, spent_usd=100.0, limit_usd=50.0,
                                  budget_id="b", reason="hard")
        monkeypatch.setattr(budget_check, "check", lambda *a, **k: decision)
        rc = budget_check.main(["my-target"])
        assert rc == 1
