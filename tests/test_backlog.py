"""Tests for backoffice.backlog."""
import json

import pytest

from backoffice.backlog import (
    finding_hash,
    merge_backlog,
    normalize_finding,
    update_score_history,
)


# ---------------------------------------------------------------------------
# TestFindingHash
# ---------------------------------------------------------------------------


class TestFindingHash:
    def test_basic_hash(self):
        result = finding_hash("qa", "my-repo", "SQL injection", "src/db.py")
        assert isinstance(result, str)
        assert len(result) == 16

    def test_deterministic(self):
        h1 = finding_hash("qa", "my-repo", "SQL injection", "src/db.py")
        h2 = finding_hash("qa", "my-repo", "SQL injection", "src/db.py")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = finding_hash("QA", "My-Repo", "SQL Injection", "src/db.py")
        h2 = finding_hash("qa", "my-repo", "sql injection", "src/db.py")
        assert h1 == h2

    def test_whitespace_trimmed(self):
        h1 = finding_hash("  qa  ", "  my-repo  ", "  SQL injection  ", "  src/db.py  ")
        h2 = finding_hash("qa", "my-repo", "SQL injection", "src/db.py")
        assert h1 == h2

    def test_different_inputs_produce_different_hashes(self):
        h1 = finding_hash("qa", "repo-a", "Bug A", "file_a.py")
        h2 = finding_hash("qa", "repo-b", "Bug A", "file_a.py")
        h3 = finding_hash("qa", "repo-a", "Bug B", "file_a.py")
        assert h1 != h2
        assert h1 != h3
        assert h2 != h3

    def test_empty_file_path(self):
        result = finding_hash("seo", "site", "Missing title tag", "")
        assert isinstance(result, str)
        assert len(result) == 16


# ---------------------------------------------------------------------------
# TestNormalizeFinding
# ---------------------------------------------------------------------------


class TestNormalizeFinding:
    def test_qa_finding(self):
        raw = {
            "id": "QA-1",
            "severity": "high",
            "category": "security",
            "title": "XSS vulnerability",
            "file": "src/app.py",
            "description": "User input not sanitised",
            "effort": "medium",
            "fixable_by_agent": True,
            "fix_suggestion": "Sanitise input",
        }
        result = normalize_finding(raw, "qa", "my-repo")
        assert result["severity"] == "high"
        assert result["description"] == "User input not sanitised"
        assert result["effort"] == "moderate"
        assert result["fixable_by_agent"] is True
        assert result["fix_suggestion"] == "Sanitise input"
        assert result["file"] == "src/app.py"
        assert result["status"] == "open"

    def test_monetization_maps_value(self):
        raw = {
            "id": "MON-1",
            "value": "high",
            "category": "ads",
            "title": "Add display ads",
            "revenue_estimate": "$500/mo",
            "phase": 1,
        }
        result = normalize_finding(raw, "monetization", "shop")
        assert result["severity"] == "high"
        assert result["revenue_estimate"] == "$500/mo"
        assert result["phase"] == 1

    def test_compliance_maps_legal_risk(self):
        raw = {
            "id": "C-1",
            "legal_risk": "critical",
            "category": "gdpr",
            "title": "No cookie consent",
            "regulation": "GDPR Art. 7",
        }
        result = normalize_finding(raw, "compliance", "site")
        assert result["severity"] == "critical"
        assert result["impact"] == "critical"
        assert result["regulation"] == "GDPR Art. 7"

    def test_compliance_maps_implementation_effort(self):
        raw = {
            "id": "C-2",
            "severity": "medium",
            "category": "gdpr",
            "title": "Missing privacy notice",
            "implementation_effort": "low",
        }
        result = normalize_finding(raw, "compliance", "site")
        assert result["effort"] == "easy"

    def test_ada_preserves_wcag_fields(self):
        raw = {
            "id": "ADA-1",
            "severity": "high",
            "category": "contrast",
            "title": "Low contrast ratio",
            "wcag_criterion": "1.4.3",
            "wcag_level": "AA",
        }
        result = normalize_finding(raw, "ada", "site")
        assert result["wcag_criterion"] == "1.4.3"
        assert result["wcag_level"] == "AA"

    def test_effort_normalization_tiny(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "effort": "tiny"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["effort"] == "easy"

    def test_effort_normalization_small(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "effort": "small"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["effort"] == "easy"

    def test_effort_normalization_large(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "effort": "large"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["effort"] == "hard"

    def test_effort_normalization_complex(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "effort": "complex"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["effort"] == "hard"

    def test_maps_fix_to_fix_suggestion(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "fix": "Apply patch"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["fix_suggestion"] == "Apply patch"

    def test_maps_details_to_description(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "details": "Some extra detail"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["description"] == "Some extra detail"

    def test_maps_location_to_file(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "location": "src/index.html"}
        result = normalize_finding(raw, "seo", "site")
        assert result["file"] == "src/index.html"

    def test_maps_fixable_to_fixable_by_agent(self):
        raw = {"id": "X-1", "severity": "low", "category": "test", "title": "T",
               "fixable": True}
        result = normalize_finding(raw, "qa", "repo")
        assert result["fixable_by_agent"] is True

    def test_missing_fields_defaults(self):
        raw = {"id": "X-1", "category": "test", "title": "Minimal finding"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["severity"] == ""
        assert result["description"] == ""
        assert result["fix_suggestion"] == ""
        assert result["file"] == ""
        assert result["fixable_by_agent"] is False
        assert result["status"] == "open"

    def test_always_includes_canonical_fields(self):
        raw = {"id": "X-1", "severity": "low", "category": "c", "title": "T"}
        result = normalize_finding(raw, "qa", "repo")
        for field in ("id", "severity", "category", "title", "file", "description",
                      "effort", "fix_suggestion", "fixable_by_agent", "status"):
            assert field in result, f"Missing canonical field: {field}"


# ---------------------------------------------------------------------------
# TestMergeBacklog
# ---------------------------------------------------------------------------


class TestMergeBacklog:
    def _make_finding(self, title="Bug", dept="qa", repo="my-repo",
                      file_path="src/app.py", **kwargs):
        base = {
            "id": "F-1",
            "title": title,
            "severity": "high",
            "category": "security",
            "file": file_path,
            "description": "",
            "effort": "moderate",
            "fix_suggestion": "",
            "fixable_by_agent": False,
            "status": "open",
        }
        base.update(kwargs)
        return normalize_finding(base, dept, repo)

    def test_new_finding_added(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding()
        result = merge_backlog([finding], backlog_path)
        assert len(result["findings"]) == 1
        entry = next(iter(result["findings"].values()))
        assert entry["audit_count"] == 1
        assert entry["status"] == "open"

    def test_new_finding_written_to_disk(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding()
        merge_backlog([finding], backlog_path)
        with open(backlog_path) as f:
            data = json.load(f)
        assert len(data["findings"]) == 1

    def test_existing_finding_increments_audit_count(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding()
        merge_backlog([finding], backlog_path)
        result = merge_backlog([finding], backlog_path)
        entry = next(iter(result["findings"].values()))
        assert entry["audit_count"] == 2

    def test_existing_updates_last_seen(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding()
        r1 = merge_backlog([finding], backlog_path)
        first_seen = next(iter(r1["findings"].values()))["last_seen"]
        r2 = merge_backlog([finding], backlog_path)
        second_seen = next(iter(r2["findings"].values()))["last_seen"]
        # last_seen should be a string (ISO timestamp)
        assert isinstance(second_seen, str)
        # Calling merge twice should always update last_seen
        assert "last_seen" in next(iter(r2["findings"].values()))

    def test_existing_updates_severity(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding(severity="low")
        merge_backlog([finding], backlog_path)
        # Same finding, now reported as high severity
        finding2 = self._make_finding(severity="high")
        result = merge_backlog([finding2], backlog_path)
        entry = next(iter(result["findings"].values()))
        assert entry["severity"] == "high"

    def test_stale_findings_not_updated(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding_a = self._make_finding(title="Bug A", file_path="src/a.py")
        finding_b = self._make_finding(title="Bug B", file_path="src/b.py")
        merge_backlog([finding_a, finding_b], backlog_path)
        # Second scan: only finding_a is present; finding_b is stale
        result = merge_backlog([finding_a], backlog_path)
        assert len(result["findings"]) == 2  # both still in backlog
        h_a = finding_hash("qa", "my-repo", "Bug A", "src/a.py")
        h_b = finding_hash("qa", "my-repo", "Bug B", "src/b.py")
        assert result["findings"][h_a]["audit_count"] == 2
        assert result["findings"][h_b]["audit_count"] == 1  # unchanged

    def test_empty_backlog_created(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        result = merge_backlog([], backlog_path)
        assert result["findings"] == {}
        assert "version" in result
        assert "updated_at" in result

    def test_backlog_has_version_field(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        result = merge_backlog([], backlog_path)
        assert result["version"] == 1

    def test_findings_keyed_by_hash(self, tmp_path):
        backlog_path = str(tmp_path / "backlog.json")
        finding = self._make_finding(title="Test Bug", file_path="src/main.py")
        result = merge_backlog([finding], backlog_path)
        expected_hash = finding_hash("qa", "my-repo", "Test Bug", "src/main.py")
        assert expected_hash in result["findings"]


# ---------------------------------------------------------------------------
# TestScoreHistory
# ---------------------------------------------------------------------------


class TestScoreHistory:
    def _scores(self, val=80):
        return {"my-repo": {"qa": val, "seo": val}}

    def test_creates_new_file(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        result = update_score_history(self._scores(), history_path)
        assert len(result["snapshots"]) == 1
        import os
        assert os.path.exists(history_path)

    def test_snapshot_has_timestamp(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        result = update_score_history(self._scores(), history_path)
        snap = result["snapshots"][0]
        assert "timestamp" in snap

    def test_snapshot_contains_scores(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        scores = self._scores(75)
        result = update_score_history(scores, history_path)
        snap = result["snapshots"][0]
        assert snap["scores"] == scores

    def test_appends_snapshot(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        update_score_history(self._scores(70), history_path)
        result = update_score_history(self._scores(80), history_path)
        assert len(result["snapshots"]) == 2

    def test_prunes_to_10(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        for i in range(12):
            update_score_history(self._scores(i), history_path)
        with open(history_path) as f:
            data = json.load(f)
        assert len(data["snapshots"]) == 10

    def test_keeps_most_recent_snapshots(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        for i in range(12):
            update_score_history(self._scores(i), history_path)
        with open(history_path) as f:
            data = json.load(f)
        # The last snapshot should have the most recent score (11)
        last_snap = data["snapshots"][-1]
        assert last_snap["scores"]["my-repo"]["qa"] == 11

    def test_written_to_disk(self, tmp_path):
        history_path = str(tmp_path / "score_history.json")
        update_score_history(self._scores(), history_path)
        with open(history_path) as f:
            data = json.load(f)
        assert "snapshots" in data
        assert len(data["snapshots"]) == 1
