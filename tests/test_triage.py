"""Tests for backoffice.scanners.triage (Haiku triage layer)."""
from __future__ import annotations

from backoffice.scanners import triage


class TestTriageGating:
    def test_no_api_key_returns_empty_overrides(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        out = triage.triage_finding({"title": "x", "severity": "high"}, target="t")
        assert out == {}

    def test_budget_blocked_returns_empty_overrides(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        monkeypatch.setattr("backoffice.scanners.triage.has_sdk", lambda: True)
        monkeypatch.setattr("backoffice.scanners.triage.budget_blocked", lambda *a, **k: True)
        out = triage.triage_finding({"title": "x"}, target="t")
        assert out == {}


class TestTriagePayload:
    def test_skips_scanner_status_findings(self, monkeypatch):
        monkeypatch.setattr(triage, "triage_finding", lambda f, target: {"severity": "low"})
        payload = {"findings": [
            {"id": "S1", "category": "scanner-status", "severity": "info"},
            {"id": "F1", "category": "code-quality", "severity": "high"},
        ]}
        out = triage.triage_payload(payload, target="t", max_findings=10)
        # status finding untouched
        assert out["findings"][0]["severity"] == "info"
        # real finding triaged → severity downgraded as overrides ranked higher
        # (low > high in rank means severity stays high — only downgrades allowed)
        assert out["findings"][1]["severity"] == "low"

    def test_severity_never_upgraded(self, monkeypatch):
        # triage tries to upgrade low → critical; runner must refuse
        monkeypatch.setattr(triage, "triage_finding", lambda f, target: {"severity": "critical"})
        payload = {"findings": [{"id": "F1", "category": "code-quality", "severity": "low"}]}
        out = triage.triage_payload(payload, target="t")
        assert out["findings"][0]["severity"] == "low"

    def test_max_findings_cap(self, monkeypatch):
        call_count = {"n": 0}
        def _t(f, target):
            call_count["n"] += 1
            return {"ai_confidence": "high"}
        monkeypatch.setattr(triage, "triage_finding", _t)
        payload = {"findings": [
            {"id": f"F{i}", "category": "code-quality", "severity": "high"} for i in range(20)
        ]}
        triage.triage_payload(payload, target="t", max_findings=5)
        assert call_count["n"] == 5

    def test_records_triaged_count(self, monkeypatch):
        monkeypatch.setattr(triage, "triage_finding", lambda f, target: {"ai_confidence": "high"})
        payload = {"findings": [{"id": "F1", "category": "code-quality", "severity": "high"}]}
        out = triage.triage_payload(payload, target="t")
        assert out["summary"]["haiku_triaged_count"] == 1


class TestIsEnabled:
    def test_default_off(self):
        from backoffice.config import ScanConfig
        assert triage.is_enabled(ScanConfig()) is False

    def test_explicit_on(self):
        from backoffice.config import ScanConfig
        assert triage.is_enabled(ScanConfig(haiku_triage=True)) is True
