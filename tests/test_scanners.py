"""Tests for backoffice.scanners (Phase 1 deterministic scanner foundation)."""
from __future__ import annotations

import json
import os

import pytest

from backoffice.scanners import discovery, runner, severity, tools


# ──────────────────────────────────────────────────────────────────────
# severity
# ──────────────────────────────────────────────────────────────────────


class TestCanonicalizeSeverity:
    def test_literal_match(self):
        assert severity.canonicalize_severity("ERROR", severity.SEMGREP_SEVERITY) == "high"

    def test_case_insensitive_lookup(self):
        assert severity.canonicalize_severity("error", severity.SEMGREP_SEVERITY) == "high"

    def test_unknown_falls_back_to_default(self):
        assert severity.canonicalize_severity("BANANA", severity.SEMGREP_SEVERITY) == "low"

    def test_npm_moderate_maps_to_medium(self):
        assert severity.canonicalize_severity("moderate", severity.NPM_AUDIT_SEVERITY) == "medium"

    def test_bandit_high(self):
        assert severity.canonicalize_severity("HIGH", severity.BANDIT_SEVERITY) == "high"


class TestRuffSeverity:
    def test_security_prefix_high(self):
        assert severity.ruff_severity("S101") == "high"

    def test_pyflakes_medium(self):
        assert severity.ruff_severity("F401") == "medium"

    def test_syntax_error_high(self):
        assert severity.ruff_severity("E901") == "high"

    def test_style_low(self):
        assert severity.ruff_severity("E501") == "low"

    def test_naming_info(self):
        assert severity.ruff_severity("N801") == "info"

    def test_empty_falls_back(self):
        assert severity.ruff_severity("") == "info"


class TestRuffCategory:
    def test_security_prefix_security(self):
        assert severity.ruff_category("S101") == "security"

    def test_style_lint_error(self):
        assert severity.ruff_category("E501") == "lint-error"

    def test_default_code_quality(self):
        assert severity.ruff_category("XYZ123") == "code-quality"


class TestMeetsMinSeverity:
    def test_critical_meets_high(self):
        assert severity.meets_min_severity("critical", "high")

    def test_high_meets_high(self):
        assert severity.meets_min_severity("high", "high")

    def test_low_does_not_meet_high(self):
        assert not severity.meets_min_severity("low", "high")

    def test_low_passes_when_min_is_info(self):
        assert severity.meets_min_severity("low", "info")

    def test_unknown_blocked(self):
        assert not severity.meets_min_severity("banana", "low")


# ──────────────────────────────────────────────────────────────────────
# discovery
# ──────────────────────────────────────────────────────────────────────


class TestDiscoverTools:
    def test_python_includes_python_tools(self, tmp_path):
        result = discovery.discover_tools(str(tmp_path), "python")
        for tool in ("semgrep", "ruff", "bandit", "pip-audit", "gitleaks"):
            assert tool in result

    def test_typescript_includes_npm_audit(self, tmp_path):
        result = discovery.discover_tools(str(tmp_path), "typescript")
        assert "npm-audit" in result
        assert "semgrep" in result
        assert "gitleaks" in result

    def test_unknown_language_uses_default(self, tmp_path):
        result = discovery.discover_tools(str(tmp_path), "brainfuck")
        assert "semgrep" in result
        assert "gitleaks" in result

    def test_empty_language_still_runs_gitleaks(self, tmp_path):
        result = discovery.discover_tools(str(tmp_path), "")
        assert "gitleaks" in result

    def test_package_json_marker_adds_npm_audit(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        result = discovery.discover_tools(str(tmp_path), "python")
        assert "npm-audit" in result
        assert "ruff" in result

    def test_pyproject_marker_adds_python_tools(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        result = discovery.discover_tools(str(tmp_path), "")
        assert "ruff" in result
        assert "bandit" in result
        assert "pip-audit" in result

    def test_polyglot_language_string(self, tmp_path):
        result = discovery.discover_tools(str(tmp_path), "python,typescript")
        assert "ruff" in result
        assert "npm-audit" in result

    def test_no_duplicates(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        result = discovery.discover_tools(str(tmp_path), "python,typescript")
        assert len(result) == len(set(result))

    def test_subdirectory_marker_detected(self, tmp_path):
        sub = tmp_path / "frontend"
        sub.mkdir()
        (sub / "package.json").write_text("{}")
        result = discovery.discover_tools(str(tmp_path), "python")
        assert "npm-audit" in result


# ──────────────────────────────────────────────────────────────────────
# tool adapters (subprocess-mocked)
# ──────────────────────────────────────────────────────────────────────


def _ctx(tmp_path) -> discovery.ScannerContext:
    return discovery.ScannerContext(
        repo_name="test-repo",
        repo_path=str(tmp_path),
        language="python",
        tools=[],
    )


class TestRunRuff:
    def test_missing_binary_returns_status_finding(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: None)
        result = tools.run_ruff(_ctx(tmp_path))
        assert result.status == "skipped_missing_tool"
        assert len(result.findings) == 1
        assert result.findings[0]["category"] == "scanner-status"
        assert result.findings[0]["severity"] == "info"

    def test_parses_findings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/ruff")
        ruff_output = json.dumps([
            {
                "code": "S101",
                "filename": str(tmp_path / "src/app.py"),
                "location": {"row": 10, "column": 1},
                "message": "Use of assert",
                "fix": None,
            },
            {
                "code": "E501",
                "filename": str(tmp_path / "src/app.py"),
                "location": {"row": 12, "column": 1},
                "message": "Line too long",
                "fix": {"applicability": "Safe"},
            },
        ])
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (1, ruff_output, ""))
        result = tools.run_ruff(_ctx(tmp_path))
        assert result.status == "ok"
        assert len(result.findings) == 2
        sec = next(f for f in result.findings if f["rule_id"] == "S101")
        assert sec["severity"] == "high"
        assert sec["category"] == "security"
        line_long = next(f for f in result.findings if f["rule_id"] == "E501")
        assert line_long["severity"] == "low"
        assert line_long["fixable_by_agent"] is True

    def test_handles_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/ruff")
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (0, "not json", ""))
        result = tools.run_ruff(_ctx(tmp_path))
        assert result.status == "failed"


class TestRunBandit:
    def test_missing_binary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: None)
        result = tools.run_bandit(_ctx(tmp_path))
        assert result.status == "skipped_missing_tool"

    def test_parses_high_severity(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/bandit")
        bandit_output = json.dumps({
            "results": [
                {
                    "filename": str(tmp_path / "app.py"),
                    "test_id": "B602",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "issue_text": "subprocess with shell=True",
                    "line_number": 5,
                    "code": "subprocess.call(cmd, shell=True)",
                }
            ]
        })
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (1, bandit_output, ""))
        result = tools.run_bandit(_ctx(tmp_path))
        assert result.status == "ok"
        assert result.findings[0]["severity"] == "high"
        assert result.findings[0]["category"] == "security"

    def test_low_high_confidence_promoted_to_medium(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/bandit")
        bandit_output = json.dumps({
            "results": [
                {
                    "filename": str(tmp_path / "app.py"),
                    "test_id": "B105",
                    "issue_severity": "LOW",
                    "issue_confidence": "HIGH",
                    "issue_text": "possible secret",
                    "line_number": 5,
                }
            ]
        })
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (1, bandit_output, ""))
        result = tools.run_bandit(_ctx(tmp_path))
        assert result.findings[0]["severity"] == "medium"


class TestRunPipAudit:
    def test_no_targets_when_no_python_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/pip-audit")
        result = tools.run_pip_audit(_ctx(tmp_path))
        assert result.status == "skipped_no_targets"

    def test_parses_vulnerability(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("requests==2.0.0\n")
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/pip-audit")
        pa_output = json.dumps({
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.0.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2018-0001",
                            "fix_versions": ["2.20.0"],
                            "description": "Cookie leak",
                        }
                    ],
                }
            ]
        })
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (0, pa_output, ""))
        result = tools.run_pip_audit(_ctx(tmp_path))
        assert result.status == "ok"
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f["severity"] == "high"
        assert f["fixable_by_agent"] is True
        assert "2.20.0" in f["fix_suggestion"]


class TestRunNpmAudit:
    def test_no_targets_without_package_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/npm")
        result = tools.run_npm_audit(_ctx(tmp_path))
        assert result.status == "skipped_no_targets"

    def test_parses_vulnerability_severity(self, tmp_path, monkeypatch):
        (tmp_path / "package.json").write_text("{}")
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/npm")
        npm_output = json.dumps({
            "vulnerabilities": {
                "lodash": {
                    "name": "lodash",
                    "severity": "moderate",
                    "via": [{"title": "Prototype Pollution", "source": 1234}],
                    "fixAvailable": True,
                },
                "evil-pkg": {
                    "name": "evil-pkg",
                    "severity": "critical",
                    "via": [{"title": "RCE"}],
                    "fixAvailable": False,
                },
            }
        })
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (1, npm_output, ""))
        result = tools.run_npm_audit(_ctx(tmp_path))
        assert result.status == "ok"
        sevs = {f["rule_id"]: f["severity"] for f in result.findings}
        assert sevs["lodash"] == "medium"
        assert sevs["evil-pkg"] == "critical"


class TestRunSemgrep:
    def test_missing_binary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: None)
        result = tools.run_semgrep(_ctx(tmp_path))
        assert result.status == "skipped_missing_tool"

    def test_parses_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/semgrep")
        sg_output = json.dumps({
            "results": [
                {
                    "check_id": "python.django.security.injection.sql.sql-injection",
                    "path": str(tmp_path / "views.py"),
                    "start": {"line": 42},
                    "extra": {
                        "severity": "ERROR",
                        "message": "Possible SQL injection",
                        "lines": "cursor.run_query(query)",
                    },
                }
            ]
        })
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (0, sg_output, ""))
        result = tools.run_semgrep(_ctx(tmp_path))
        assert result.status == "ok"
        assert result.findings[0]["severity"] == "high"
        assert result.findings[0]["category"] == "security"


class TestRunGitleaks:
    def test_missing_binary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: None)
        result = tools.run_gitleaks(_ctx(tmp_path))
        assert result.status == "skipped_missing_tool"

    def test_no_leaks_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/gitleaks")
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (0, "", ""))
        result = tools.run_gitleaks(_ctx(tmp_path))
        assert result.status == "ok"
        assert result.findings == []

    def test_parses_secret(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_which", lambda _b: "/usr/bin/gitleaks")
        gl_output = json.dumps([
            {
                "RuleID": "aws-access-key",
                "Description": "AWS Access Key detected",
                "File": "secrets.env",
                "StartLine": 3,
                "Commit": "abcdef1234567890",
                "Secret": "REDACTED",
            }
        ])
        monkeypatch.setattr(tools, "_run", lambda *a, **k: (1, gl_output, ""))
        result = tools.run_gitleaks(_ctx(tmp_path))
        assert result.status == "ok"
        f = result.findings[0]
        assert f["severity"] == "critical"
        assert f["category"] == "security"
        assert "abcdef12" in f["title"]


# ──────────────────────────────────────────────────────────────────────
# runner
# ──────────────────────────────────────────────────────────────────────


def _stub_result(tool: str, findings: list[dict], status: str = "ok") -> tools.ScannerResult:
    return tools.ScannerResult(tool=tool, status=status, findings=findings)


def _f(*, title: str, severity: str = "high", file: str = "x.py", tool: str = "ruff") -> dict:
    return {
        "id": f"DET-{tool}-{title}",
        "title": title,
        "severity": severity,
        "category": "code-quality",
        "file": file,
        "line": 1,
        "description": title,
        "evidence": "",
        "fix_suggestion": "",
        "fixable_by_agent": False,
        "effort": "easy",
        "trust_class": "objective",
        "source_tool": tool,
        "rule_id": title,
    }


class TestRunScan:
    def test_writes_output_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", [_f(title="x", severity="high")]),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        results_dir = tmp_path / "results"
        runner.run_scan("repo", str(repo), "python", str(results_dir))
        out = results_dir / "repo" / "qa-deterministic-findings.json"
        assert out.exists()
        payload = json.loads(out.read_text())
        assert payload["repo_name"] == "repo"
        assert payload["scanner"] == "deterministic"
        assert payload["summary"]["total"] == 1

    def test_dedup_by_id_within_scan(self, tmp_path, monkeypatch):
        """Same finding id from two adapters is deduped (defensive — shouldn't happen)."""
        dup = _f(title="same-title", file="same.py", severity="high")
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff", "semgrep"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", [dup]),
        )
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "semgrep",
            lambda ctx: _stub_result("semgrep", [dict(dup)]),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan("repo", str(repo), "python", str(tmp_path / "results"))
        assert payload["summary"]["total"] == 1

    def test_same_rule_different_lines_kept_distinct(self, tmp_path, monkeypatch):
        """Two ruff hits of the same rule on different lines must NOT collapse."""
        f1 = _f(title="E501 Line too long (95 > 88)", file="app.py", severity="low")
        f1["id"] = "DET-ruff-E501-app.py-10"
        f1["line"] = 10
        f2 = _f(title="E501 Line too long (95 > 88)", file="app.py", severity="low")
        f2["id"] = "DET-ruff-E501-app.py-20"
        f2["line"] = 20
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", [f1, f2]),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan(
            "repo", str(repo), "python", str(tmp_path / "results"),
            min_severity="info",
        )
        assert payload["summary"]["total"] == 2

    def test_min_severity_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", [
                _f(title="lo", severity="low"),
                _f(title="hi", severity="high"),
            ]),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan(
            "repo", str(repo), "python", str(tmp_path / "results"),
            min_severity="high",
        )
        titles = [f["title"] for f in payload["findings"]]
        assert "hi" in titles
        assert "lo" not in titles

    def test_max_findings_cap(self, tmp_path, monkeypatch):
        many = [_f(title=f"t{i}", file=f"f{i}.py", severity="medium") for i in range(50)]
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", many),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan(
            "repo", str(repo), "python", str(tmp_path / "results"),
            max_findings=10,
        )
        assert payload["summary"]["total"] == 10

    def test_scanner_status_findings_always_included(self, tmp_path, monkeypatch):
        status_only = _f(title="ruff not installed", severity="info")
        status_only["category"] = "scanner-status"
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result(
                "ruff",
                [status_only, _f(title="lo", severity="low")],
                status="skipped_missing_tool",
            ),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan(
            "repo", str(repo), "python", str(tmp_path / "results"),
            min_severity="critical",
        )
        titles = [f["title"] for f in payload["findings"]]
        assert "ruff not installed" in titles
        assert "lo" not in titles

    def test_scanner_status_excluded_from_severity_totals(self, tmp_path, monkeypatch):
        """Status findings are coverage-gap metadata, not findings against the repo."""
        status = _f(title="ruff not installed", severity="info")
        status["category"] = "scanner-status"
        real = _f(title="real bug", severity="high", file="a.py")
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", [status, real], status="skipped_missing_tool"),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = runner.run_scan("repo", str(repo), "python", str(tmp_path / "results"))
        summary = payload["summary"]
        assert summary["total"] == 1, "total counts only real findings"
        assert summary["info"] == 0, "info-severity status finding must not inflate info count"
        assert summary["high"] == 1
        assert summary["scanner_status_count"] == 1

    def test_invalid_repo_path_raises(self, tmp_path):
        with pytest.raises(ValueError):
            runner.run_scan("repo", str(tmp_path / "missing"), "python", str(tmp_path / "results"))

    def test_concurrent_scan_is_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runner, "discover_tools", lambda _p, _l: ["ruff"])
        monkeypatch.setitem(
            runner.SCANNER_DISPATCH, "ruff",
            lambda ctx: _stub_result("ruff", []),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        results_dir = tmp_path / "results"
        from backoffice.store.atomic import LockFile
        (results_dir / "repo").mkdir(parents=True)
        with LockFile(results_dir / "repo" / ".det-scan-qa.lock", blocking=False):
            with pytest.raises(RuntimeError):
                runner.run_scan("repo", str(repo), "python", str(results_dir))


# ──────────────────────────────────────────────────────────────────────
# aggregate.py merge behavior
# ──────────────────────────────────────────────────────────────────────


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _make_repo_with_findings(tmp_path, *, ai_findings, det_findings=None):
    """Set up tmp_path/results/repo/ with the given fixture data."""
    results_dir = tmp_path / "results"
    repo_dir = results_dir / "test-repo"
    repo_dir.mkdir(parents=True)
    _write_json(str(repo_dir / "findings.json"), {
        "scan_id": "ai-1",
        "scanned_at": "2026-05-06T10:00:00Z",
        "summary": {
            "total": len(ai_findings),
            "critical": 0,
            "high": sum(1 for f in ai_findings if f["severity"] == "high"),
            "medium": 0,
            "low": 0,
            "info": 0,
        },
        "findings": ai_findings,
    })
    if det_findings is not None:
        _write_json(str(repo_dir / "qa-deterministic-findings.json"), {
            "scan_id": "det-1",
            "scanned_at": "2026-05-06T10:01:00Z",
            "scanner": "deterministic",
            "summary": {"total": len(det_findings)},
            "scanner_status": [
                {"tool": "ruff", "status": "ok", "tool_version": "", "finding_count": len(det_findings), "error": ""}
            ],
            "findings": det_findings,
        })
    return results_dir


class TestAggregateQaMerge:
    def test_no_deterministic_file_is_no_op(self, tmp_path):
        from backoffice.aggregate import aggregate_qa
        results_dir = _make_repo_with_findings(tmp_path, ai_findings=[
            {"id": "AI1", "severity": "high", "title": "AI bug", "file": "a.py", "category": "x"},
        ])
        out = aggregate_qa(str(results_dir), str(tmp_path / "dash"))
        assert out["repos"][0]["summary"]["total"] == 1
        assert "scanner_status" not in out["repos"][0]

    def test_distinct_deterministic_findings_appended(self, tmp_path):
        from backoffice.aggregate import aggregate_qa
        results_dir = _make_repo_with_findings(
            tmp_path,
            ai_findings=[{"id": "AI1", "severity": "high", "title": "AI bug", "file": "a.py", "category": "x"}],
            det_findings=[_f(title="ruff finding", severity="medium", file="b.py")],
        )
        out = aggregate_qa(str(results_dir), str(tmp_path / "dash"))
        repo = out["repos"][0]
        assert repo["summary"]["total"] == 2
        titles = {f["title"] for f in repo["findings"]}
        assert {"AI bug", "ruff finding"} <= titles
        assert "scanner_status" in repo

    def test_duplicate_title_and_file_deduped(self, tmp_path):
        from backoffice.aggregate import aggregate_qa
        results_dir = _make_repo_with_findings(
            tmp_path,
            ai_findings=[{"id": "AI1", "severity": "high", "title": "Same Title", "file": "x.py", "category": "x"}],
            det_findings=[_f(title="Same Title", severity="medium", file="x.py")],
        )
        out = aggregate_qa(str(results_dir), str(tmp_path / "dash"))
        assert out["repos"][0]["summary"]["total"] == 1

    def test_summary_severities_recomputed_after_merge(self, tmp_path):
        from backoffice.aggregate import aggregate_qa
        results_dir = _make_repo_with_findings(
            tmp_path,
            ai_findings=[{"id": "AI1", "severity": "high", "title": "ai", "file": "a.py", "category": "x"}],
            det_findings=[_f(title="det", severity="medium", file="b.py")],
        )
        out = aggregate_qa(str(results_dir), str(tmp_path / "dash"))
        summary = out["repos"][0]["summary"]
        assert summary["total"] == 2
        assert summary["high"] == 1
        assert summary["medium"] == 1

    def test_deterministic_only_when_ai_missing(self, tmp_path):
        """Repos that haven't had an AI scan still surface deterministic findings."""
        from backoffice.aggregate import aggregate_qa
        results_dir = tmp_path / "results"
        repo_dir = results_dir / "test-repo"
        repo_dir.mkdir(parents=True)
        _write_json(str(repo_dir / "qa-deterministic-findings.json"), {
            "scan_id": "det-1",
            "scanned_at": "2026-05-06T10:00:00Z",
            "scanner": "deterministic",
            "summary": {"total": 1},
            "scanner_status": [],
            "findings": [_f(title="alone", severity="high", file="a.py")],
        })
        out = aggregate_qa(str(results_dir), str(tmp_path / "dash"))
        assert out["repos"][0]["summary"]["total"] == 1
        assert out["repos"][0]["findings"][0]["title"] == "alone"
