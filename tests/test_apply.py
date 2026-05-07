"""Tests for backoffice.apply (Phase 2 safe-apply framework)."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from backoffice.apply import runner, strategies, verifier


# ──────────────────────────────────────────────────────────────────────
# strategies — resolver
# ──────────────────────────────────────────────────────────────────────


class TestResolveStrategy:
    def test_ruff_fixable_resolves_ruff_fix(self):
        s = strategies.resolve_strategy({"source_tool": "ruff", "fixable_by_agent": True})
        assert s.name == "ruff-fix"
        assert s.kind == "deterministic"

    def test_npm_audit_fixable_resolves_npm_audit_fix(self):
        s = strategies.resolve_strategy({"source_tool": "npm-audit", "fixable_by_agent": True})
        assert s.name == "npm-audit-fix"

    def test_semgrep_fixable_resolves_semgrep_autofix(self):
        s = strategies.resolve_strategy({"source_tool": "semgrep", "fixable_by_agent": True})
        assert s.name == "semgrep-autofix"

    def test_unknown_source_with_fixable_falls_to_ai(self):
        s = strategies.resolve_strategy({"source_tool": "ai-agent", "fixable_by_agent": True})
        assert s.name == "ai-delegate"

    def test_not_fixable_falls_to_manual(self):
        s = strategies.resolve_strategy({"source_tool": "gitleaks", "fixable_by_agent": False})
        assert s.name == "manual"

    def test_missing_source_tool_with_fixable_is_ai(self):
        s = strategies.resolve_strategy({"fixable_by_agent": True})
        assert s.name == "ai-delegate"


# ──────────────────────────────────────────────────────────────────────
# verifier
# ──────────────────────────────────────────────────────────────────────


class TestVerifier:
    def test_empty_commands_record_none(self, tmp_path):
        result = verifier.verify(str(tmp_path), "", "")
        assert result.lint_passed is None
        assert result.tests_passed is None
        assert result.is_clean()

    def test_passing_commands(self, tmp_path):
        result = verifier.verify(str(tmp_path), "true", "true")
        assert result.lint_passed is True
        assert result.tests_passed is True

    def test_failing_lint_marks_unclean(self, tmp_path):
        result = verifier.verify(str(tmp_path), "false", "true")
        assert result.lint_passed is False
        assert result.tests_passed is True
        assert not result.is_clean()

    def test_missing_binary_records_failure(self, tmp_path):
        result = verifier.verify(str(tmp_path), "/nonexistent/binary-xyz", "")
        assert result.lint_passed is False


# ──────────────────────────────────────────────────────────────────────
# Worktree helpers (real git, in tmp_path)
# ──────────────────────────────────────────────────────────────────────


def _init_repo(tmp_path) -> str:
    repo = tmp_path / "src"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "app.py").write_text("import json\n\nx = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return str(repo)


@pytest.fixture
def repo(tmp_path):
    return _init_repo(tmp_path)


# ──────────────────────────────────────────────────────────────────────
# apply_finding — happy paths via stubbed strategies
# ──────────────────────────────────────────────────────────────────────


def _stub_strategy(success: bool, files=("app.py",), error=""):
    """Build a FixStrategy that mutates the worktree predictably."""
    def _apply(ctx):
        if success:
            (open(os.path.join(ctx.repo_path, "app.py"), "a")).write("# stub edit\n")
            return strategies.ApplyResult(True, files_changed=list(files), summary="stub")
        return strategies.ApplyResult(False, error=error)
    return strategies.FixStrategy(name="stub", kind="deterministic",
                                  description="test stub", apply=_apply)


class TestApplyFinding:
    def test_dry_run_does_not_leave_branch(self, repo, monkeypatch):
        monkeypatch.setattr(runner, "resolve_strategy", lambda f: _stub_strategy(True))
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F1", "title": "test", "fixable_by_agent": True}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=True, auto_commit_allowed=True,
        )
        assert outcome.status == "dry-run"
        # Branch should be deleted on dry-run cleanup
        branches = subprocess.run(
            ["git", "-C", repo, "branch"], capture_output=True, text=True,
        ).stdout
        assert "back-office/apply" not in branches

    def test_apply_commits_to_branch(self, repo, monkeypatch):
        monkeypatch.setattr(runner, "resolve_strategy", lambda f: _stub_strategy(True))
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F2", "title": "real", "fixable_by_agent": True}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=False, auto_commit_allowed=True,
        )
        assert outcome.status == "applied"
        assert outcome.branch
        branches = subprocess.run(
            ["git", "-C", repo, "branch"], capture_output=True, text=True,
        ).stdout
        assert outcome.branch.split("/", 2)[-1] in branches.replace(" ", "")

    def test_test_regression_rolls_back(self, repo, monkeypatch):
        # pre-verify: tests pass; post-verify: tests fail
        call_count = {"n": 0}
        def fake_verify(path, lint, test):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return verifier.VerifyResult(lint_passed=True, tests_passed=True, output="")
            return verifier.VerifyResult(lint_passed=True, tests_passed=False, output="failed")
        monkeypatch.setattr(runner, "verify", fake_verify)
        monkeypatch.setattr(runner, "resolve_strategy", lambda f: _stub_strategy(True))
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F3", "title": "regress", "fixable_by_agent": True}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=False, auto_commit_allowed=True,
        )
        assert outcome.status == "rolled-back"
        branches = subprocess.run(
            ["git", "-C", repo, "branch"], capture_output=True, text=True,
        ).stdout
        # branch should be deleted on rollback
        assert outcome.branch.split("/", 2)[-1] not in branches.replace(" ", "")

    def test_apply_failure_cleans_up(self, repo, monkeypatch):
        monkeypatch.setattr(runner, "resolve_strategy",
                            lambda f: _stub_strategy(False, error="no-op"))
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F4", "title": "noop", "fixable_by_agent": True}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=False, auto_commit_allowed=True,
        )
        assert outcome.status == "failed"
        assert "no-op" in outcome.reason

    def test_manual_strategy_is_skipped(self, repo, monkeypatch):
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F5", "title": "secret", "source_tool": "gitleaks", "fixable_by_agent": False}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=False, auto_commit_allowed=True,
        )
        assert outcome.status == "skipped"
        assert outcome.reason == "not-auto-fixable"

    def test_uncommitted_when_auto_commit_blocked(self, repo, monkeypatch):
        monkeypatch.setattr(runner, "resolve_strategy", lambda f: _stub_strategy(True))
        monkeypatch.setattr(runner, "_record", lambda o: None)
        finding = {"id": "F6", "title": "block", "fixable_by_agent": True}
        outcome = runner.apply_finding(
            finding, target_name="t", target_path=repo,
            lint_command="true", test_command="true",
            dry_run=False, auto_commit_allowed=False,
        )
        assert outcome.status == "applied-uncommitted"


# ──────────────────────────────────────────────────────────────────────
# Selection logic
# ──────────────────────────────────────────────────────────────────────


def _f(**kw):
    return {"id": kw["id"], "severity": kw.get("severity", "high"),
            "source_tool": kw.get("source_tool", ""), "title": kw["id"],
            "category": kw.get("category", "security")}


class TestSelect:
    def test_finding_id_filter(self):
        out = runner._select(
            [_f(id="A"), _f(id="B")],
            finding_id="B", source_tool=None, severity="info", max_changes=10,
        )
        assert [f["id"] for f in out] == ["B"]

    def test_severity_floor(self):
        out = runner._select(
            [_f(id="hi", severity="high"), _f(id="lo", severity="low")],
            finding_id=None, source_tool=None, severity="medium", max_changes=10,
        )
        assert [f["id"] for f in out] == ["hi"]

    def test_max_changes_cap(self):
        many = [_f(id=f"f{i}", severity="high") for i in range(10)]
        out = runner._select(many, finding_id=None, source_tool=None,
                             severity="info", max_changes=3)
        assert len(out) == 3

    def test_source_tool_filter(self):
        out = runner._select(
            [_f(id="r", source_tool="ruff"), _f(id="n", source_tool="npm-audit")],
            finding_id=None, source_tool="ruff", severity="info", max_changes=10,
        )
        assert [f["id"] for f in out] == ["r"]

    def test_scanner_status_excluded(self):
        out = runner._select(
            [_f(id="real", severity="high"), _f(id="status", severity="info", category="scanner-status")],
            finding_id=None, source_tool=None, severity="info", max_changes=10,
        )
        assert [f["id"] for f in out] == ["real"]
