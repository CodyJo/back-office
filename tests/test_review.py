"""Tests for backoffice.review — approve/discard flow for preview jobs.

The review module operates on preview branches created by ``fix-bugs.sh
--preview``. It merges the branch into its base on approve, or deletes the
branch and the preview artifact on discard. Operates on a real tmp git repo.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from backoffice.review import (
    ApproveResult,
    DiscardResult,
    ReviewError,
    approve,
    discard,
    list_previews,
)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def repo_with_preview(tmp_path):
    """Target repo with a preview branch and a results/ preview artifact."""
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("print('hi')\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "init")

    _git(repo, "checkout", "-b", "back-office/preview/pv-1")
    (repo / "a.py").write_text("print('hi, world')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fix: FIND-001")
    _git(repo, "checkout", "main")

    results_dir = tmp_path / "results" / "target"
    results_dir.mkdir(parents=True)
    preview = results_dir / "preview-pv-1.json"
    preview.write_text(json.dumps({
        "version": 1,
        "job_id": "pv-1",
        "repo": "target",
        "branch": "back-office/preview/pv-1",
        "base_ref": "main",
        "changes": [{"file": "a.py", "insertions": 1, "deletions": 1}],
        "commits": [{"sha": "deadbeef", "subject": "fix: FIND-001"}],
        "checklist": [],
    }))

    return {
        "repo_path": repo,
        "results_dir": tmp_path / "results",
        "job_id": "pv-1",
        "preview_path": preview,
    }


def test_list_previews_returns_artifacts(repo_with_preview):
    out = list_previews(repo_with_preview["results_dir"])
    assert len(out) == 1
    entry = out[0]
    assert entry["job_id"] == "pv-1"
    assert entry["repo"] == "target"
    assert entry["branch"] == "back-office/preview/pv-1"


def test_approve_fast_forwards_base_and_removes_artifact(repo_with_preview):
    result = approve(
        repo_path=repo_with_preview["repo_path"],
        results_dir=repo_with_preview["results_dir"],
        repo_name="target",
        job_id="pv-1",
    )
    assert isinstance(result, ApproveResult)
    assert result.merged_into == "main"
    # Base now contains the fix
    assert "hi, world" in (repo_with_preview["repo_path"] / "a.py").read_text()
    # Preview artifact removed after approval
    assert not repo_with_preview["preview_path"].exists()
    # Preview branch deleted
    branches = subprocess.check_output(
        ["git", "branch"], cwd=str(repo_with_preview["repo_path"]), text=True)
    assert "back-office/preview/pv-1" not in branches


def test_discard_deletes_branch_and_artifact(repo_with_preview):
    result = discard(
        repo_path=repo_with_preview["repo_path"],
        results_dir=repo_with_preview["results_dir"],
        repo_name="target",
        job_id="pv-1",
    )
    assert isinstance(result, DiscardResult)
    # Base file unchanged
    assert (repo_with_preview["repo_path"] / "a.py").read_text() == "print('hi')\n"
    # Branch + artifact gone
    branches = subprocess.check_output(
        ["git", "branch"], cwd=str(repo_with_preview["repo_path"]), text=True)
    assert "back-office/preview/pv-1" not in branches
    assert not repo_with_preview["preview_path"].exists()


def test_approve_missing_preview_raises(tmp_path):
    (tmp_path / "results" / "target").mkdir(parents=True)
    with pytest.raises(ReviewError):
        approve(
            repo_path=tmp_path / "nope",
            results_dir=tmp_path / "results",
            repo_name="target",
            job_id="missing",
        )


def test_approve_dirty_worktree_raises(repo_with_preview):
    # Introduce a dirty change on main
    (repo_with_preview["repo_path"] / "a.py").write_text("uncommitted\n")
    with pytest.raises(ReviewError):
        approve(
            repo_path=repo_with_preview["repo_path"],
            results_dir=repo_with_preview["results_dir"],
            repo_name="target",
            job_id="pv-1",
        )
