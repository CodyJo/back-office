"""Tests for Phase 10 workspace lifecycle + PR provenance."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.store import FileStore
from backoffice.workspaces import (
    PRGuardError,
    WorkspaceRegistry,
    can_open_pr,
    pr_body,
)


@pytest.fixture
def reg(tmp_path: Path) -> WorkspaceRegistry:
    return WorkspaceRegistry(store=FileStore(root=tmp_path))


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────


def test_create_persists_workspace(reg: WorkspaceRegistry):
    ws = reg.create(
        task_id="t1",
        repo="back-office",
        branch="back-office/preview/job-1",
    )
    loaded = reg.get(ws.id)
    assert loaded is not None
    assert loaded.task_id == "t1"
    assert loaded.branch == "back-office/preview/job-1"


def test_list_returns_all(reg: WorkspaceRegistry):
    reg.create(task_id="t1", repo="r", branch="b1")
    reg.create(task_id="t1", repo="r", branch="b2")
    assert len(reg.list()) == 2


def test_attach_test_results_passed(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    updated = reg.attach_test_results(ws.id, passed=True, ref="run-42")
    assert updated.test_results_ref == "run-42"
    assert updated.metadata["test_results"]["passed"] is True


def test_attach_test_results_failed_persists(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    updated = reg.attach_test_results(ws.id, passed=False, ref="run-bad")
    assert updated.metadata["test_results"]["passed"] is False


def test_retire_workspace(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    retired = reg.retire(ws.id)
    assert retired.retired_at


def test_retired_workspace_blocked_from_pr(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    retired = reg.retire(ws.id)
    ok, reason = can_open_pr(retired)
    assert not ok
    assert reason == "workspace_retired"


def test_failed_tests_block_pr(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    ws_failed = reg.attach_test_results(ws.id, passed=False)
    ok, reason = can_open_pr(ws_failed)
    assert not ok
    assert reason == "tests_failed"


def test_passed_tests_permit_pr(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    ws_passed = reg.attach_test_results(ws.id, passed=True)
    ok, _ = can_open_pr(ws_passed)
    assert ok


def test_no_test_results_permits_pr(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    ok, _ = can_open_pr(ws)
    assert ok  # not attaching tests is allowed; manual verification


def test_create_emits_audit_event(reg: WorkspaceRegistry):
    reg.create(task_id="t1", repo="r", branch="b")
    events = reg.store.read_audit_events()
    assert any(e.action == "workspace.created" for e in events)


def test_retire_emits_audit_event(reg: WorkspaceRegistry):
    ws = reg.create(task_id="t1", repo="r", branch="b")
    reg.retire(ws.id)
    events = reg.store.read_audit_events()
    assert any(e.action == "workspace.retired" for e in events)


# ──────────────────────────────────────────────────────────────────────
# PR body rendering
# ──────────────────────────────────────────────────────────────────────


def test_pr_body_contains_provenance():
    body = pr_body(
        task_id="back-office:fix-foo:20260429",
        task_title="Fix foo",
        repo="back-office",
        run_id="run-abc",
        approval_id="appr-xyz",
        workspace_id="ws-123",
        branch="back-office/preview/job-1",
        test_results_passed=True,
    )
    assert "back-office:fix-foo:20260429" in body
    assert "back-office" in body
    assert "run-abc" in body
    assert "appr-xyz" in body
    assert "ws-123" in body
    assert "back-office/preview/job-1" in body
    assert "Tests: passed" in body
    assert "Back Office" in body
    assert "GitHub review before merge" in body


def test_pr_body_evidence_links():
    body = pr_body(
        task_id="t1",
        evidence_links=["https://example/findings/1", "https://example/runs/abc"],
    )
    assert "https://example/findings/1" in body
    assert "https://example/runs/abc" in body
    assert "### Evidence" in body


def test_pr_body_extra_sections():
    body = pr_body(
        task_id="t1",
        extra_sections=[("Summary", "Refactored foo for clarity"),
                        ("Testing", "make test passes")],
    )
    assert "### Summary" in body
    assert "Refactored foo for clarity" in body
    assert "### Testing" in body


def test_pr_body_refuses_failing_tests():
    with pytest.raises(PRGuardError):
        pr_body(task_id="t1", test_results_passed=False)


def test_pr_body_handles_unknown_test_state():
    body = pr_body(task_id="t1", test_results_passed=None)
    assert "manual verification" in body.lower()


def test_pr_body_minimal():
    body = pr_body(task_id="t1")
    # Must still include the provenance heading and footer.
    assert "Back Office provenance" in body
    assert "GitHub review" in body
