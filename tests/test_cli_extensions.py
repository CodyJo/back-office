"""Smoke tests for the new CLI subcommands.

These don't replace the per-module test suites; they verify the CLI
plumbing is wired so ``python -m backoffice {agents,routines,budgets,
tokens,runs,export,import}`` actually dispatches to the right module.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backoffice.__main__ import _dispatch_extension


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run CLI dispatchers against a temporary BACK_OFFICE_ROOT."""
    monkeypatch.setenv("BACK_OFFICE_ROOT", str(tmp_path))
    # Minimal config so load_config() works in extensions that need it.
    cfg = tmp_path / "config" / "backoffice.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "runner:\n  command: claude\n  mode: claude-print\n"
        "deploy:\n  provider: bunny\n  bunny:\n    storage_zone: x\n"
        "targets: {}\n"
    )
    monkeypatch.setenv("BACK_OFFICE_CONFIG", str(cfg))
    return tmp_path


def test_agents_list_empty(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("agents", ["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no agents" in out


def test_agents_create_then_list(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension(
        "agents",
        ["create", "--name", "fix-agent", "--role", "fixer", "--id", "agent-fix"],
    )
    assert rc == 0
    rc = _dispatch_extension("agents", ["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent-fix" in out


def test_routines_list_empty(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("routines", ["list"])
    assert rc == 0
    assert "no routines" in capsys.readouterr().out


def test_budgets_list_empty(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("budgets", ["list"])
    assert rc == 0
    assert "no budgets" in capsys.readouterr().out


def test_budgets_spend_zero(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("budgets", ["spend"])
    assert rc == 0
    assert "total: $0" in capsys.readouterr().out


def test_tokens_issue_then_list(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("tokens", ["issue", "--agent-id", "agent-fix"])
    assert rc == 0
    plaintext = capsys.readouterr().out.strip()
    assert plaintext.startswith("bo-")
    rc = _dispatch_extension("tokens", ["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent-fix" in out
    # Plaintext must never appear in the listing.
    assert plaintext not in out


def test_runs_list_empty(isolated_root: Path, capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("runs", ["list"])
    assert rc == 0
    assert "no runs" in capsys.readouterr().out


def test_export_round_trips(isolated_root: Path, capsys: pytest.CaptureFixture, tmp_path: Path):
    out_path = tmp_path / "export.json"
    rc = _dispatch_extension("export", ["--out", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["version"] == 1
    assert "resources" in payload


def test_import_dry_run(isolated_root: Path, capsys: pytest.CaptureFixture, tmp_path: Path):
    payload_path = tmp_path / "in.json"
    payload_path.write_text(json.dumps({
        "version": 1,
        "resources": {
            "agents": [{"id": "agent-x", "name": "x", "role": "fixer"}],
        },
    }))
    rc = _dispatch_extension("import", [str(payload_path)])  # dry-run by default
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent-x" in out


def test_unknown_extension_returns_2(capsys: pytest.CaptureFixture):
    rc = _dispatch_extension("does-not-exist", [])
    assert rc == 2
