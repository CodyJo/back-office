"""Smoke test for POST /api/tasks/apply-fix.

Validates the endpoint plumbing without spinning up the HTTP server:
- task lookup
- state-machine guard (must be in 'ready')
- task-type guard (must be 'finding_fix')
- finding lookup from results files
- dry-run path (state unchanged, outcome recorded)
- real-apply path (state transitions to ready_for_review on success)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from backoffice.apply.runner import ApplyOutcome


def _make_handler_for_task(monkeypatch, tmp_path, task, finding=None):
    """Return a stub handler bound just enough to call _handle_task_apply_fix."""
    from backoffice import server

    handler = server.DashboardHandler.__new__(server.DashboardHandler)
    handler._root = str(tmp_path)
    handler._json_response = MagicMock()
    handler._read_body = lambda: {}  # overridden per-test
    handler._guard_transition = MagicMock(return_value=True)
    handler._save_task_queue = MagicMock(return_value={})
    handler._emit_task_transition_audit = MagicMock()

    fake_context = MagicMock()
    fake_context.payload = {"tasks": [task]}
    fake_context.targets = {}
    handler._task_queue_context = lambda: fake_context

    # Mock the finding loader
    if finding is not None:
        monkeypatch.setattr("backoffice.apply.runner._load_findings",
                            lambda *_a, **_k: [finding])
    else:
        monkeypatch.setattr("backoffice.apply.runner._load_findings",
                            lambda *_a, **_k: [])

    # Mock load_config to give us a usable target
    cfg = MagicMock()
    cfg.root = tmp_path
    target = MagicMock()
    target.path = str(tmp_path / "target-repo")
    target.lint_command = ""
    target.test_command = ""
    target.autonomy.allow_fix = True
    target.autonomy.require_clean_worktree = False
    target.autonomy.allow_auto_commit = True
    cfg.targets = {task["repo"]: target}
    monkeypatch.setattr("backoffice.config.load_config", lambda: cfg)

    # Mock _worktree_is_clean
    monkeypatch.setattr(server, "_worktree_is_clean", lambda _p: True)

    return handler


class TestApplyFixEndpoint:
    def test_missing_id_returns_400(self, tmp_path, monkeypatch):
        from backoffice import server
        handler = _make_handler_for_task(monkeypatch, tmp_path,
                                         task={"id": "T1", "repo": "r", "status": "ready"})
        handler._read_body = lambda: {}
        handler._handle_task_apply_fix()
        handler._json_response.assert_called_once()
        code, body = handler._json_response.call_args[0]
        assert code == 400
        assert "id" in body["error"]

    def test_task_not_found_returns_404(self, tmp_path, monkeypatch):
        handler = _make_handler_for_task(monkeypatch, tmp_path,
                                         task={"id": "T1", "repo": "r", "status": "ready"})
        handler._read_body = lambda: {"id": "DOES-NOT-EXIST"}
        handler._handle_task_apply_fix()
        code, _ = handler._json_response.call_args[0]
        assert code == 404

    def test_wrong_task_type_returns_409(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "ready", "task_type": "product_suggestion"}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task)
        handler._read_body = lambda: {"id": "T1"}
        handler._handle_task_apply_fix()
        code, body = handler._json_response.call_args[0]
        assert code == 409
        assert "finding_fix" in body["error"]

    def test_wrong_state_returns_409(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "pending_approval", "task_type": "finding_fix",
                "source_finding": {"id": "F1"}}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task)
        handler._read_body = lambda: {"id": "T1"}
        handler._handle_task_apply_fix()
        code, body = handler._json_response.call_args[0]
        assert code == 409
        assert "ready" in body["error"]

    def test_finding_not_found_returns_404(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "ready", "task_type": "finding_fix",
                "source_finding": {"id": "F-MISSING"}}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task, finding=None)
        handler._read_body = lambda: {"id": "T1"}
        (tmp_path / "target-repo").mkdir()
        handler._handle_task_apply_fix()
        code, _ = handler._json_response.call_args[0]
        assert code == 404

    def test_dry_run_records_outcome_without_state_change(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "ready", "task_type": "finding_fix",
                "source_finding": {"id": "F1"}}
        finding = {"id": "F1", "title": "x", "fixable_by_agent": True, "source_tool": "ruff"}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task, finding=finding)
        handler._read_body = lambda: {"id": "T1", "dry_run": True}
        (tmp_path / "target-repo").mkdir()

        # Stub apply_finding to return a dry-run outcome
        outcome = ApplyOutcome(
            finding_id="F1", finding_title="x", target="r", strategy="ruff-fix",
            status="dry-run", reason="dry-run-ok", branch="back-office/apply/r-F1-abc",
            files_changed=["app.py"], diff_excerpt="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n",
        )
        monkeypatch.setattr("backoffice.apply.runner.apply_finding",
                            lambda *_a, **_k: outcome)
        # state-machine guard not called for dry-run
        handler._guard_transition.return_value = True

        handler._handle_task_apply_fix()
        code, body = handler._json_response.call_args[0]
        assert code == 200
        assert body["dry_run"] is True
        assert body["outcome"]["status"] == "dry-run"
        # state stays at 'ready' on dry-run
        assert task["status"] == "ready"
        # apply_runs got an entry
        assert len(task["apply_runs"]) == 1
        assert task["apply_runs"][0]["outcome"]["status"] == "dry-run"

    def test_real_apply_success_transitions_to_ready_for_review(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "ready", "task_type": "finding_fix",
                "source_finding": {"id": "F1"}}
        finding = {"id": "F1", "title": "x", "fixable_by_agent": True, "source_tool": "ruff"}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task, finding=finding)
        handler._read_body = lambda: {"id": "T1", "dry_run": False}
        (tmp_path / "target-repo").mkdir()

        outcome = ApplyOutcome(
            finding_id="F1", finding_title="x", target="r", strategy="ruff-fix",
            status="applied", reason="committed-to-branch",
            branch="back-office/apply/r-F1-abc",
            files_changed=["app.py"], diff_excerpt="...",
        )
        monkeypatch.setattr("backoffice.apply.runner.apply_finding",
                            lambda *_a, **_k: outcome)

        handler._handle_task_apply_fix()
        code, body = handler._json_response.call_args[0]
        assert code == 200
        assert task["status"] == "ready_for_review"
        assert task["branch"] == "back-office/apply/r-F1-abc"

    def test_real_apply_rollback_transitions_to_blocked(self, tmp_path, monkeypatch):
        task = {"id": "T1", "repo": "r", "status": "ready", "task_type": "finding_fix",
                "source_finding": {"id": "F1"}}
        finding = {"id": "F1", "title": "x", "fixable_by_agent": True, "source_tool": "ruff"}
        handler = _make_handler_for_task(monkeypatch, tmp_path, task=task, finding=finding)
        handler._read_body = lambda: {"id": "T1", "dry_run": False}
        (tmp_path / "target-repo").mkdir()

        outcome = ApplyOutcome(
            finding_id="F1", finding_title="x", target="r", strategy="ruff-fix",
            status="rolled-back", reason="verify-regressed",
        )
        monkeypatch.setattr("backoffice.apply.runner.apply_finding",
                            lambda *_a, **_k: outcome)

        handler._handle_task_apply_fix()
        assert task["status"] == "blocked"
