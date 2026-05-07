"""Tests for backoffice.scanners.scan_state (incremental scanning)."""
from __future__ import annotations

import subprocess

import pytest

from backoffice.scanners import scan_state


def _git_init(repo_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_path, check=True)
    (repo_path / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_path, check=True)


def _git_commit(repo_path, content):
    (repo_path / "f.txt").write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "edit"], cwd=repo_path, check=True)


class TestHeadSha:
    def test_returns_sha_for_git_repo(self, tmp_path):
        _git_init(tmp_path)
        sha = scan_state.head_sha(str(tmp_path))
        assert sha and len(sha) == 40

    def test_returns_none_for_non_git_dir(self, tmp_path):
        assert scan_state.head_sha(str(tmp_path)) is None


class TestUpdateAndGet:
    def test_round_trip(self, tmp_path):
        scan_state.update(str(tmp_path), target="repo", scope="qa", sha="abc123", finding_count=5)
        record = scan_state.get(str(tmp_path), "repo", "qa")
        assert record is not None
        assert record.head_sha == "abc123"
        assert record.finding_count == 5

    def test_get_missing_returns_none(self, tmp_path):
        assert scan_state.get(str(tmp_path), "repo", "qa") is None

    def test_update_with_empty_sha_is_noop(self, tmp_path):
        scan_state.update(str(tmp_path), target="r", scope="qa", sha="", finding_count=0)
        assert scan_state.get(str(tmp_path), "r", "qa") is None

    def test_separate_scopes_kept_distinct(self, tmp_path):
        scan_state.update(str(tmp_path), target="r", scope="qa", sha="aaa", finding_count=1)
        scan_state.update(str(tmp_path), target="r", scope="seo", sha="bbb", finding_count=2)
        assert scan_state.get(str(tmp_path), "r", "qa").head_sha == "aaa"
        assert scan_state.get(str(tmp_path), "r", "seo").head_sha == "bbb"


class TestShouldSkip:
    def test_no_git_means_no_skip(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        skip, reason = scan_state.should_skip(
            str(results), target="r", scope="qa", repo_path=str(tmp_path / "no-git"),
        )
        assert skip is False
        assert reason == "no-git-head"

    def test_no_prior_state_means_no_skip(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        results = tmp_path / "results"
        results.mkdir()
        skip, _ = scan_state.should_skip(str(results), target="r", scope="qa", repo_path=str(repo))
        assert skip is False

    def test_skip_when_sha_unchanged(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        sha = scan_state.head_sha(str(repo))
        results = tmp_path / "results"
        results.mkdir()
        scan_state.update(str(results), target="r", scope="qa", sha=sha, finding_count=3)
        skip, reason = scan_state.should_skip(str(results), target="r", scope="qa", repo_path=str(repo))
        assert skip is True
        assert reason.startswith("unchanged-since-")

    def test_no_skip_when_sha_changed(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        old_sha = scan_state.head_sha(str(repo))
        results = tmp_path / "results"
        results.mkdir()
        scan_state.update(str(results), target="r", scope="qa", sha=old_sha, finding_count=3)
        _git_commit(repo, "b\n")
        skip, reason = scan_state.should_skip(str(results), target="r", scope="qa", repo_path=str(repo))
        assert skip is False
        assert reason.startswith("sha-changed:")
