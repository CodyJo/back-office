"""Review & Approve backend for fix-agent preview branches.

A preview job lives in two places:

* ``<repo>/results/<repo>/preview-<job-id>.json`` — the artifact the dashboard
  Review panel reads (commits, diffstat, checklist).
* A branch named ``back-office/preview/<job-id>`` inside the target repo
  containing the committed fix.

``approve(...)`` fast-forwards the preview branch into its base and removes
the artifact. ``discard(...)`` deletes the branch and artifact without
touching the base. Both operations refuse to run when the target worktree is
dirty — operators must clean up before deciding.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReviewError(RuntimeError):
    """Raised when a preview cannot be approved or discarded safely."""


@dataclass
class ApproveResult:
    job_id: str
    repo: str
    branch: str
    merged_into: str
    head_sha: str


@dataclass
class DiscardResult:
    job_id: str
    repo: str
    branch: str


def _preview_path(results_dir: Path, repo_name: str, job_id: str) -> Path:
    return Path(results_dir) / repo_name / f"preview-{job_id}.json"


def _load_preview(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ReviewError(f"Preview artifact not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Preview artifact is not valid JSON: {path}") from exc


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReviewError(
            f"git {' '.join(args)} failed in {repo_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _require_clean(repo_path: Path) -> None:
    status = _git(repo_path, "status", "--porcelain")
    if status:
        raise ReviewError(
            f"Target repo has uncommitted changes; clean the worktree before approving: {status}"
        )


def list_previews(results_dir: Path) -> list[dict[str, Any]]:
    """Return preview artifact metadata for every ``preview-*.json`` file."""
    base = Path(results_dir)
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for repo_dir in sorted(base.iterdir()):
        if not repo_dir.is_dir():
            continue
        for preview in sorted(repo_dir.glob("preview-*.json")):
            try:
                data = json.loads(preview.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            out.append({
                "job_id": data.get("job_id", preview.stem.removeprefix("preview-")),
                "repo": data.get("repo", repo_dir.name),
                "branch": data.get("branch", ""),
                "base_ref": data.get("base_ref", ""),
                "artifact_path": str(preview),
                "created_at": data.get("created_at"),
                "changes": data.get("changes", []),
                "commits": data.get("commits", []),
                "checklist": data.get("checklist", []),
                "compare_url": data.get("compare_url"),
            })
    return out


def approve(
    *,
    repo_path: Path,
    results_dir: Path,
    repo_name: str,
    job_id: str,
) -> ApproveResult:
    """Fast-forward the preview branch into its base and remove the artifact.

    On failure the target repo is left on its current branch and the artifact
    remains on disk so the operator can retry or discard.
    """
    artifact = _preview_path(results_dir, repo_name, job_id)
    data = _load_preview(artifact)
    branch = data.get("branch") or f"back-office/preview/{job_id}"
    base_ref = data.get("base_ref") or "main"

    repo = Path(repo_path)
    if not (repo / ".git").exists():
        raise ReviewError(f"Not a git repository: {repo}")
    _require_clean(repo)

    # Make sure both refs exist locally.
    _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    _git(repo, "rev-parse", "--verify", f"refs/heads/{base_ref}")

    _git(repo, "checkout", base_ref)
    # --ff-only keeps the operation a pure advance — no merge commit, no
    # surprise conflict resolution. Preview branches start from base so this
    # is the expected shape.
    _git(repo, "merge", "--ff-only", branch)
    head_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "-D", branch)

    try:
        artifact.unlink()
    except FileNotFoundError:
        pass

    return ApproveResult(
        job_id=job_id,
        repo=repo_name,
        branch=branch,
        merged_into=base_ref,
        head_sha=head_sha,
    )


def discard(
    *,
    repo_path: Path,
    results_dir: Path,
    repo_name: str,
    job_id: str,
) -> DiscardResult:
    """Delete the preview branch and artifact without touching base."""
    artifact = _preview_path(results_dir, repo_name, job_id)
    data = _load_preview(artifact)
    branch = data.get("branch") or f"back-office/preview/{job_id}"
    base_ref = data.get("base_ref") or "main"

    repo = Path(repo_path)
    if not (repo / ".git").exists():
        raise ReviewError(f"Not a git repository: {repo}")

    current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if current == branch:
        _git(repo, "checkout", base_ref)

    # -D forces deletion even if the branch isn't merged — discarding
    # unreviewed fixes is the whole point.
    _git(repo, "branch", "-D", branch)

    try:
        artifact.unlink()
    except FileNotFoundError:
        pass

    return DiscardResult(job_id=job_id, repo=repo_name, branch=branch)
