"""CLI wrapper for backoffice.preview — exercised end-to-end against a real tmp git repo."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "target"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("print('hi')\n")
    _git(r, "add", "a.py")
    _git(r, "commit", "-m", "init")

    _git(r, "checkout", "-b", "back-office/preview/pv-1")
    (r / "a.py").write_text("print('hi, world')\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "fix: FIND-001")

    return r


def test_preview_cli_writes_json(repo, tmp_path):
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps([
        {"id": "FIND-001", "severity": "high", "title": "t", "file": "a.py",
         "line": 1, "trust_class": "objective"},
    ]))
    out_path = tmp_path / "preview.json"

    result = subprocess.run(
        [
            sys.executable, "-m", "backoffice", "preview",
            "--repo-path", str(repo),
            "--repo-name", "target",
            "--job-id", "pv-1",
            "--branch", "back-office/preview/pv-1",
            "--base-ref", "main",
            "--findings", str(findings_path),
            "--out", str(out_path),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out_path.exists()

    data = json.loads(out_path.read_text())
    assert data["job_id"] == "pv-1"
    assert data["repo"] == "target"
    assert data["branch"] == "back-office/preview/pv-1"
    assert data["base_ref"] == "main"
    assert {c["file"] for c in data["changes"]} == {"a.py"}
    assert [item["finding_id"] for item in data["checklist"]] == ["FIND-001"]


def test_preview_cli_derives_remote_when_not_provided(repo, tmp_path):
    _git(repo, "remote", "add", "origin", "git@github.com:cody/target.git")
    findings_path = tmp_path / "findings.json"
    findings_path.write_text("[]")
    out_path = tmp_path / "preview.json"

    result = subprocess.run(
        [
            sys.executable, "-m", "backoffice", "preview",
            "--repo-path", str(repo),
            "--repo-name", "target",
            "--job-id", "pv-1",
            "--branch", "back-office/preview/pv-1",
            "--base-ref", "main",
            "--findings", str(findings_path),
            "--out", str(out_path),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(out_path.read_text())
    assert data["compare_url"] == \
        "https://github.com/cody/target/compare/main...back-office/preview/pv-1"
