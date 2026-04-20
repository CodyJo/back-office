"""Tests for backoffice.overnight_state — loop state helpers.

Splits three concerns out of overnight.sh's shell helpers:

1. ExecutionLedger: append-only JSONL of per-decision records
   (why a fix was attempted, why a feature was skipped, what gate
   allowed/blocked it, what rollback tag was taken, etc.)

2. FailureMemory: reads the structured history and returns the set of
   (repo, title) items that failed in the last N cycles, so the
   overnight loop can exclude them from the next plan even if the
   Product Owner agent re-nominates them.

3. Quarantine: flags a repo if the last N consecutive cycles triggered
   a rollback on that repo; the loop must skip all work against it
   until an operator clears the flag.

Together these make the overnight loop inspectable (ledger),
non-thrashing (memory), and self-limiting (quarantine) without
changing the existing shell orchestration surface.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backoffice.overnight_state import (
    ExecutionLedger,
    FailureMemory,
    Quarantine,
    LedgerRecord,
)


# ──────────────────────────────────────────────────────────────────────────────
# ExecutionLedger — append-only JSONL
# ──────────────────────────────────────────────────────────────────────────────

def test_ledger_append_writes_jsonl(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.jsonl")
    ledger.append(LedgerRecord(
        cycle_id="overnight-20260101-000000",
        action="fix",
        target="selah",
        allow=True,
        reason="policy:allow_fix",
        detail={"title": "XSS in /search", "severity": "high"},
    ))
    ledger.append(LedgerRecord(
        cycle_id="overnight-20260101-000000",
        action="fix",
        target="pe-bootstrap",
        allow=False,
        reason="block:allow_fix=false",
        detail={"title": "missing validation"},
    ))

    lines = (tmp_path / "ledger.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["target"] == "selah"
    assert first["allow"] is True
    assert first["reason"] == "policy:allow_fix"
    assert first["detail"]["severity"] == "high"
    assert first["timestamp"]  # ISO8601 string


def test_ledger_read_returns_records(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.jsonl")
    for i in range(3):
        ledger.append(LedgerRecord(
            cycle_id=f"overnight-{i:05d}",
            action="deploy",
            target="selah",
            allow=False,
            reason="block:deploy_mode=disabled",
        ))

    records = list(ledger.read())
    assert len(records) == 3
    assert [r.cycle_id for r in records] == [
        "overnight-00000", "overnight-00001", "overnight-00002"
    ]


def test_ledger_read_tolerates_malformed_lines(tmp_path):
    """A corrupt line must not stop the operator from inspecting the rest."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '{"cycle_id":"a","action":"fix","target":"selah","allow":true,'
        '"reason":"ok","timestamp":"2026-01-01T00:00:00"}\n'
        'this is not json\n'
        '{"cycle_id":"b","action":"fix","target":"selah","allow":false,'
        '"reason":"block","timestamp":"2026-01-02T00:00:00"}\n'
    )
    ledger = ExecutionLedger(path)
    records = list(ledger.read())
    assert [r.cycle_id for r in records] == ["a", "b"]


def test_ledger_filter_by_target(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.jsonl")
    ledger.append(LedgerRecord(
        cycle_id="c1", action="fix", target="selah",
        allow=True, reason="ok",
    ))
    ledger.append(LedgerRecord(
        cycle_id="c1", action="fix", target="pattern",
        allow=True, reason="ok",
    ))
    filtered = list(ledger.read(target="selah"))
    assert len(filtered) == 1
    assert filtered[0].target == "selah"


# ──────────────────────────────────────────────────────────────────────────────
# FailureMemory — repeated-failure backoff
# ──────────────────────────────────────────────────────────────────────────────

def _history(cycles):
    return {"cycles": cycles}


def test_failure_memory_returns_items_failed_in_last_n_cycles(tmp_path):
    history_path = tmp_path / "overnight-history.json"
    history_path.write_text(json.dumps(_history([
        {"cycle_id": "c1", "failed_items": [
            {"repo": "selah", "title": "XSS"},
        ]},
        {"cycle_id": "c2", "failed_items": [
            {"repo": "selah", "title": "XSS"},
            {"repo": "pattern", "title": "race condition"},
        ]},
    ])))
    mem = FailureMemory(history_path, window=2)
    blocked = mem.blocked_items()
    assert ("selah", "XSS") in blocked
    assert ("pattern", "race condition") in blocked


def test_failure_memory_respects_window(tmp_path):
    history_path = tmp_path / "overnight-history.json"
    history_path.write_text(json.dumps(_history([
        {"cycle_id": "old", "failed_items": [
            {"repo": "selah", "title": "old-bug"},
        ]},
        {"cycle_id": "c1", "failed_items": []},
        {"cycle_id": "c2", "failed_items": [
            {"repo": "selah", "title": "new-bug"},
        ]},
    ])))
    mem = FailureMemory(history_path, window=2)
    blocked = mem.blocked_items()
    assert ("selah", "new-bug") in blocked
    assert ("selah", "old-bug") not in blocked  # outside window


def test_failure_memory_should_skip():
    mem = FailureMemory.__new__(FailureMemory)
    mem._blocked = {("selah", "xss")}
    assert mem.should_skip("selah", "xss") is True
    assert mem.should_skip("selah", "XSS") is True  # case-insensitive
    assert mem.should_skip("selah", "other") is False


def test_failure_memory_handles_missing_history(tmp_path):
    mem = FailureMemory(tmp_path / "missing.json", window=2)
    assert mem.blocked_items() == set()


# ──────────────────────────────────────────────────────────────────────────────
# Quarantine — repos with persistent rollbacks
# ──────────────────────────────────────────────────────────────────────────────

def test_quarantine_flags_repo_after_n_consecutive_rollbacks(tmp_path):
    history_path = tmp_path / "overnight-history.json"
    history_path.write_text(json.dumps(_history([
        {"cycle_id": "c1", "rollback_repos": ["selah"]},
        {"cycle_id": "c2", "rollback_repos": ["selah", "pattern"]},
        {"cycle_id": "c3", "rollback_repos": ["selah"]},
    ])))
    q = Quarantine(history_path, threshold=3)
    flagged = q.flagged()
    assert "selah" in flagged
    assert "pattern" not in flagged


def test_quarantine_resets_on_healthy_cycle(tmp_path):
    history_path = tmp_path / "overnight-history.json"
    history_path.write_text(json.dumps(_history([
        {"cycle_id": "c1", "rollback_repos": ["selah"]},
        {"cycle_id": "c2", "rollback_repos": ["selah"]},
        {"cycle_id": "c3", "rollback_repos": []},  # broke the streak
        {"cycle_id": "c4", "rollback_repos": ["selah"]},
    ])))
    q = Quarantine(history_path, threshold=3)
    assert "selah" not in q.flagged()


def test_quarantine_respects_manual_override(tmp_path):
    history_path = tmp_path / "overnight-history.json"
    history_path.write_text(json.dumps(_history([
        {"cycle_id": "c1", "rollback_repos": ["selah"]},
        {"cycle_id": "c2", "rollback_repos": ["selah"]},
        {"cycle_id": "c3", "rollback_repos": ["selah"]},
    ])))
    override_path = tmp_path / "quarantine-clear.json"
    override_path.write_text(json.dumps({"cleared": ["selah"]}))

    q = Quarantine(history_path, threshold=3, overrides_path=override_path)
    assert "selah" not in q.flagged()


def test_quarantine_handles_missing_history(tmp_path):
    q = Quarantine(tmp_path / "missing.json", threshold=3)
    assert q.flagged() == set()
