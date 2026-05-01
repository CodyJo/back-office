"""Approval synthesis + Task round-trip against real legacy data.

These tests load ``config/task-queue.yaml`` (the live queue) and the
fixture above, exercising the round-trip helpers against
representative shapes: empty approvals, approved tasks, mentor plans,
and product suggestions.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backoffice.domain.compat import (
    approval_from_task_dict,
    task_from_legacy,
    task_to_legacy,
    workspace_from_preview,
)
from backoffice.tasks import ensure_task_defaults


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_QUEUE = REPO_ROOT / "config" / "task-queue.yaml"


# ──────────────────────────────────────────────────────────────────────
# Round-trip against the live config/task-queue.yaml (if present)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not LIVE_QUEUE.exists(), reason="config/task-queue.yaml not present")
def test_live_queue_round_trips():
    raw = yaml.safe_load(LIVE_QUEUE.read_text()) or {}
    tasks = raw.get("tasks") or []
    assert tasks, "expected the live queue to have at least one task"

    for legacy in tasks:
        # ensure_task_defaults() is what backoffice.tasks puts on disk.
        # We compare to that canonicalized form, not the raw YAML row,
        # because YAML may omit defaults.
        canonical = ensure_task_defaults(legacy, targets={})
        task = task_from_legacy(canonical)
        out = task_to_legacy(task)
        assert out == canonical, f"round-trip mismatch for task {legacy.get('id')!r}"


@pytest.mark.skipif(not LIVE_QUEUE.exists(), reason="config/task-queue.yaml not present")
def test_live_queue_task_models_have_no_unexpected_keys():
    """Every key in canonical legacy tasks must land in either a
    canonical Task field or in extras. No drops."""
    raw = yaml.safe_load(LIVE_QUEUE.read_text()) or {}
    for legacy in raw.get("tasks") or []:
        canonical = ensure_task_defaults(legacy, targets={})
        task = task_from_legacy(canonical)
        out = task.to_dict()
        for key in canonical.keys():
            assert key in out, f"key {key!r} dropped from {legacy.get('id')!r}"


# ──────────────────────────────────────────────────────────────────────
# Approval synthesis
# ──────────────────────────────────────────────────────────────────────


def test_approval_synthesis_pending_approval_is_requested():
    raw = {
        "id": "t-1",
        "repo": "back-office",
        "title": "x",
        "status": "pending_approval",
        "created_by": "dashboard",
        "created_at": "2026-04-29T12:00:00+00:00",
        "history": [
            {"status": "pending_approval", "at": "2026-04-29T12:00:00+00:00", "by": "dashboard", "note": "queued"},
        ],
        "approval": {},
    }
    approval = approval_from_task_dict(raw)
    assert approval is not None
    assert approval.state == "requested"
    assert approval.task_id == "t-1"
    assert approval.requested_by == "dashboard"
    assert approval.requested_at == "2026-04-29T12:00:00+00:00"


def test_approval_synthesis_after_api_approve():
    """Mirrors what backoffice/server.py:_handle_task_approve writes."""
    raw = {
        "id": "t-1",
        "repo": "back-office",
        "title": "x",
        "status": "ready",
        "created_by": "dashboard",
        "created_at": "2026-04-29T12:00:00+00:00",
        "history": [
            {"status": "pending_approval", "at": "2026-04-29T12:00:00+00:00", "by": "dashboard", "note": "queued"},
            {"status": "ready", "at": "2026-04-29T12:30:00+00:00", "by": "operator", "note": "approved"},
        ],
        "approval": {
            "approved_at": "2026-04-29T12:30:00+00:00",
            "approved_by": "operator",
            "note": "lgtm",
        },
    }
    approval = approval_from_task_dict(raw)
    assert approval is not None
    assert approval.state == "approved"
    assert approval.task_id == "t-1"
    assert approval.requested_by == "dashboard"
    assert approval.requested_at == "2026-04-29T12:00:00+00:00"
    assert approval.decided_by == "operator"
    assert approval.decided_at == "2026-04-29T12:30:00+00:00"
    assert approval.reason == "lgtm"


def test_approval_synthesis_returns_none_for_proposed_with_empty_approval():
    raw = {"id": "t-1", "status": "proposed", "approval": {}}
    assert approval_from_task_dict(raw) is None


def test_approval_synthesis_returns_none_for_cancelled():
    """Cancelled is ambiguous; we don't synthesize a fake rejection."""
    raw = {"id": "t-1", "status": "cancelled", "approval": {}}
    assert approval_from_task_dict(raw) is None


def test_approval_synthesis_handles_non_dict_input():
    assert approval_from_task_dict(None) is None  # type: ignore[arg-type]
    assert approval_from_task_dict("nope") is None  # type: ignore[arg-type]


def test_approval_synthesis_handles_non_dict_approval_field():
    raw = {"id": "t-1", "status": "pending_approval", "approval": "not-a-dict"}
    a = approval_from_task_dict(raw)
    assert a is not None
    assert a.state == "requested"


def test_approval_synthesis_preserves_task_payload_separately():
    """Mentor plan tasks store rich payloads on task['approval']. The
    synthesizer must not crash and must not attempt to interpret them
    as approved/rejected — it returns None when the approval shape
    doesn't match a decision (no approved_at/approved_by) and the task
    isn't pending_approval. The raw payload remains on the Task."""
    raw = {
        "id": "t-mentor",
        "status": "in_progress",  # past pending_approval already
        "approval": {
            "mentor_request": {"goal": "renew GCP cert"},
            "mentor_plan": {"summary": "8 weeks"},
        },
    }
    assert approval_from_task_dict(raw) is None
    # And the payload survives on the Task itself.
    task = task_from_legacy({**raw, "repo": "back-office", "title": "Mentor plan"})
    assert task.approval["mentor_request"]["goal"] == "renew GCP cert"
    assert task.approval["mentor_plan"]["summary"] == "8 weeks"


# ──────────────────────────────────────────────────────────────────────
# Workspace synthesis from a real preview artifact
# ──────────────────────────────────────────────────────────────────────


def test_workspace_from_preview_artifact():
    raw = {
        "version": 1,
        "job_id": "fix-20260429-130000",
        "repo": "back-office",
        "branch": "back-office/preview/fix-20260429-130000",
        "base_ref": "main",
        "base_sha": "abc",
        "head_sha": "def",
        "compare_url": "https://github.com/cody/back-office/compare/main...x",
        "changes": [{"file": "foo.py", "insertions": 1, "deletions": 0}],
        "commits": [{"sha": "def", "subject": "fix: foo"}],
        "checklist": [{"finding_id": "QA-1", "severity": "high"}],
        "created_at": "2026-04-29T13:00:00+00:00",
    }
    ws = workspace_from_preview(raw, task_id="t-1")
    assert ws.id == "fix-20260429-130000"
    assert ws.task_id == "t-1"
    assert ws.repo == "back-office"
    assert ws.branch == "back-office/preview/fix-20260429-130000"
    assert ws.base_ref == "main"
    assert ws.base_sha == "abc"
    assert ws.head_sha == "def"
    assert ws.metadata["compare_url"] == raw["compare_url"]
    assert ws.metadata["commits"] == raw["commits"]
    assert ws.metadata["changes"] == raw["changes"]
    assert ws.metadata["checklist"] == raw["checklist"]


def test_workspace_from_preview_rejects_non_mapping():
    with pytest.raises(TypeError):
        workspace_from_preview("not-a-dict", task_id="t-1")  # type: ignore[arg-type]
