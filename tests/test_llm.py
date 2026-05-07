"""Tests for backoffice.llm.{client, cost_estimator}."""
from __future__ import annotations

from backoffice.llm import client, cost_estimator


class TestCostEstimator:
    def test_haiku_cheaper_than_sonnet_per_token(self):
        haiku = cost_estimator.estimate_cost(model="haiku", input_tokens=1_000_000, output_tokens=0)
        sonnet = cost_estimator.estimate_cost(model="sonnet", input_tokens=1_000_000, output_tokens=0)
        assert haiku < sonnet

    def test_sonnet_cheaper_than_opus(self):
        sonnet = cost_estimator.estimate_cost(model="sonnet", input_tokens=1_000_000, output_tokens=0)
        opus = cost_estimator.estimate_cost(model="opus", input_tokens=1_000_000, output_tokens=0)
        assert sonnet < opus

    def test_cache_read_is_much_cheaper_than_input(self):
        full = cost_estimator.estimate_cost(model="sonnet", input_tokens=1_000_000)
        cached = cost_estimator.estimate_cost(model="sonnet", cache_read_tokens=1_000_000)
        assert cached < full / 5  # cache reads are ~10% of input

    def test_unknown_model_falls_back_to_sonnet(self):
        cost = cost_estimator.estimate_cost(model="unknown-model", input_tokens=1_000_000)
        sonnet = cost_estimator.estimate_cost(model="sonnet", input_tokens=1_000_000)
        assert cost == sonnet

    def test_zero_tokens_zero_cost(self):
        assert cost_estimator.estimate_cost(model="sonnet") == 0.0

    def test_project_dept_cost_caches_after_first_call(self):
        proj = cost_estimator.project_dept_scan_cost(
            model="sonnet",
            system_prompt_tokens=10_000,
            user_prompt_tokens=1_000,
            output_tokens=2_000,
            targets=12,
        )
        assert proj["targets"] == 12
        # Per-subsequent should be much cheaper than first
        assert proj["per_subsequent_usd"] < proj["first_call_usd"]


class TestClient:
    def test_no_api_key_returns_structured_error(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = client.call_anthropic(system_prompt="x", user_prompt="y")
        assert result.error == "no-api-key"
        assert result.text == ""

    def test_get_model_for_tier(self):
        assert client.get_model_for_tier("haiku") == client.HAIKU
        assert client.get_model_for_tier("sonnet") == client.SONNET
        assert client.get_model_for_tier("opus") == client.OPUS

    def test_get_model_for_tier_passes_through_unknown(self):
        assert client.get_model_for_tier("custom-model") == "custom-model"

    def test_has_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
        assert client.has_api_key() is True
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        assert client.has_api_key() is False
