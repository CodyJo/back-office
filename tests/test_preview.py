"""Unit tests for backoffice.preview — run against a real tmp git repo."""
from __future__ import annotations

import subprocess

import pytest

from backoffice.preview import PreviewInputs, build_preview


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
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=r, text=True).strip()

    _git(r, "checkout", "-b", "back-office/preview/job-123")
    (r / "a.py").write_text("print('hi, world')\n")
    (r / "b.py").write_text("# new\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "fix: FIND-001 FIND-002")
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=r, text=True).strip()

    return {"path": r, "base": base_sha, "head": head_sha}


def test_build_preview_captures_shape(repo):
    findings = [
        {"id": "FIND-001", "severity": "high", "file": "a.py", "line": 1,
         "title": "Missing world", "trust_class": "objective"},
        {"id": "FIND-002", "severity": "low", "file": "b.py",
         "title": "Missing file", "trust_class": "advisory"},
    ]
    out = build_preview(PreviewInputs(
        repo_path=repo["path"],
        repo_name="target",
        job_id="job-123",
        branch="back-office/preview/job-123",
        base_ref="main",
        findings_addressed=findings,
        remote_url="https://github.com/cody/target.git",
    ))

    assert out["job_id"] == "job-123"
    assert out["repo"] == "target"
    assert out["branch"] == "back-office/preview/job-123"
    assert out["base_sha"] == repo["base"]
    assert out["head_sha"] == repo["head"]
    assert {c["file"] for c in out["changes"]} == {"a.py", "b.py"}
    for c in out["changes"]:
        assert "insertions" in c and "deletions" in c

    assert out["compare_url"] == \
        "https://github.com/cody/target/compare/main...back-office/preview/job-123"

    ids = {item["finding_id"] for item in out["checklist"]}
    assert ids == {"FIND-001", "FIND-002"}


def test_build_preview_handles_no_remote(repo):
    out = build_preview(PreviewInputs(
        repo_path=repo["path"],
        repo_name="target",
        job_id="job-123",
        branch="back-office/preview/job-123",
        base_ref="main",
        findings_addressed=[],
        remote_url=None,
    ))
    assert out["compare_url"] is None
    assert out["checklist"] == []
