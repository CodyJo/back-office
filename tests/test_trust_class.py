"""Tests for trust_class as a first-class concept on findings.

Per MASTER-PROMPT.md §Critical Product Insight, Back Office separates:
  - OBJECTIVE (factual / standards-based): qa, ada, compliance, privacy, cloud-ops
  - ADVISORY (judgment-based / opportunities): monetization, product

Today this distinction is only in prose. These tests drive making it a
schema-level field flowing through normalize_finding → merge_backlog →
aggregate payload, so the Product Owner and dashboard can treat them
differently.
"""
from __future__ import annotations

import json

import pytest

from backoffice.backlog import (
    TRUST_CLASSES,
    DEPARTMENT_TRUST_CLASS,
    merge_backlog,
    normalize_finding,
    trust_class_for,
)


# ──────────────────────────────────────────────────────────────────────────────
# Classification table
# ──────────────────────────────────────────────────────────────────────────────

def test_trust_classes_are_enumerated():
    assert TRUST_CLASSES == ("objective", "advisory")


def test_known_objective_departments():
    for dept in ("qa", "ada", "compliance", "privacy", "cloud-ops"):
        assert trust_class_for(dept) == "objective", dept


def test_known_advisory_departments():
    for dept in ("monetization", "product"):
        assert trust_class_for(dept) == "advisory", dept


def test_seo_is_classified_as_advisory_by_default():
    """SEO has both technical (objective) and strategic (advisory) findings.
    We err on the side of advisory to avoid false urgency; objective SEO
    findings can override per-finding via raw['trust_class']."""
    assert trust_class_for("seo") == "advisory"


def test_unknown_department_falls_back_to_advisory():
    assert trust_class_for("unknown-future-dept") == "advisory"


def test_trust_class_is_stable_data():
    """This mapping is referenced from shell scripts; changes must be explicit."""
    assert DEPARTMENT_TRUST_CLASS["qa"] == "objective"
    assert DEPARTMENT_TRUST_CLASS["monetization"] == "advisory"


# ──────────────────────────────────────────────────────────────────────────────
# normalize_finding
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_finding_tags_qa_as_objective():
    raw = {"title": "XSS in /search", "severity": "high"}
    norm = normalize_finding(raw, "qa", "selah")
    assert norm["trust_class"] == "objective"


def test_normalize_finding_tags_monetization_as_advisory():
    raw = {"title": "Add Pro tier", "severity": "medium"}
    norm = normalize_finding(raw, "monetization", "selah")
    assert norm["trust_class"] == "advisory"


def test_normalize_finding_respects_explicit_trust_class_override():
    """Agents can override per-finding (e.g. an SEO technical check that
    is objectively wrong, not advisory)."""
    raw = {"title": "Missing canonical", "trust_class": "objective"}
    norm = normalize_finding(raw, "seo", "selah")
    assert norm["trust_class"] == "objective"


def test_normalize_finding_rejects_unknown_trust_class():
    raw = {"title": "X", "trust_class": "shrug"}
    with pytest.raises(ValueError, match="trust_class"):
        normalize_finding(raw, "qa", "selah")


# ──────────────────────────────────────────────────────────────────────────────
# Backlog persistence carries trust_class forward
# ──────────────────────────────────────────────────────────────────────────────

def test_merge_backlog_persists_trust_class(tmp_path):
    path = tmp_path / "backlog.json"
    f1 = normalize_finding(
        {"title": "SQL injection", "severity": "critical", "file": "api.py"},
        "qa",
        "selah",
    )
    f2 = normalize_finding(
        {"title": "Add referral link", "severity": "low"},
        "monetization",
        "selah",
    )
    backlog = merge_backlog([f1, f2], str(path))
    stored = list(backlog["findings"].values())

    classes = {e["trust_class"] for e in stored}
    assert classes == {"objective", "advisory"}

    # Each entry also carries the current_finding payload with trust_class.
    for entry in stored:
        assert entry["current_finding"]["trust_class"] == entry["trust_class"]


# ──────────────────────────────────────────────────────────────────────────────
# Aggregate — dashboard payload counts by trust_class
# ──────────────────────────────────────────────────────────────────────────────

def test_count_by_trust_class_splits_findings():
    from backoffice.aggregate import count_by_trust_class
    findings = [
        {"trust_class": "objective", "severity": "high"},
        {"trust_class": "objective", "severity": "medium"},
        {"trust_class": "advisory", "severity": "low"},
    ]
    counts = count_by_trust_class(findings)
    assert counts == {"objective": 2, "advisory": 1}


def test_count_by_trust_class_handles_missing_field():
    from backoffice.aggregate import count_by_trust_class
    findings = [{"severity": "high"}]  # no trust_class
    counts = count_by_trust_class(findings)
    # Missing classification is treated as advisory (conservative: don't
    # inflate the "objective / remediate now" pile).
    assert counts == {"objective": 0, "advisory": 1}


def test_aggregate_department_rollup_includes_trust_class(tmp_path):
    """Department aggregate payload surfaces trust_class_totals for dashboards."""
    from backoffice.aggregate import aggregate_department

    results = tmp_path / "results"
    (results / "selah").mkdir(parents=True)
    (results / "selah" / "findings.json").write_text(json.dumps({
        "scanned_at": "2026-01-01T00:00:00Z",
        "findings": [
            {"title": "XSS", "severity": "high"},
            {"title": "Missing aria-label", "severity": "medium"},
        ],
    }))

    payload = aggregate_department(str(results), "findings.json", "qa")

    assert payload["default_trust_class"] == "objective"
    assert payload["trust_class_totals"] == {"objective": 2, "advisory": 0}

    repo_entry = payload["repos"][0]
    assert repo_entry["trust_class_counts"] == {"objective": 2, "advisory": 0}
    for finding in repo_entry["findings"]:
        assert finding["trust_class"] == "objective"
