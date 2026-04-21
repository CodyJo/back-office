"""Preview artifact generator for the fix agent.

``agents/fix-bugs.sh --preview`` calls :func:`build_preview` after the
agent finishes committing on an isolated branch. The returned dict is
written to ``results/<repo>/preview-<job-id>.json`` and consumed by the
Review & Approve panel in the dashboard.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PreviewInputs:
    repo_path: Path
    repo_name: str
    job_id: str
    branch: str
    base_ref: str
    findings_addressed: list[dict[str, Any]] = field(default_factory=list)
    remote_url: str | None = None


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _rev_parse(repo_path: Path, ref: str) -> str:
    return _git(repo_path, "rev-parse", ref)


def _numstat(repo_path: Path, base: str, head: str) -> list[dict[str, Any]]:
    raw = _git(repo_path, "diff", "--numstat", f"{base}..{head}")
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        ins, dels, path = parts[0], parts[1], parts[2]
        try:
            ins_n = int(ins)
            dels_n = int(dels)
        except ValueError:
            # Binary files report "-\t-\tpath"
            ins_n = 0
            dels_n = 0
        out.append({"file": path, "insertions": ins_n, "deletions": dels_n})
    return out


def _commits(repo_path: Path, base: str, head: str) -> list[dict[str, str]]:
    raw = _git(repo_path, "log", "--format=%H%x1f%s", f"{base}..{head}")
    out: list[dict[str, str]] = []
    for line in raw.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        out.append({"sha": sha, "subject": subject})
    return out


_GITHUB_SSH = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>.+?)(\.git)?$")
_GITHUB_HTTPS = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>.+?)(\.git)?$")


def _compare_url(remote_url: str | None, base_ref: str, head_branch: str) -> str | None:
    if not remote_url:
        return None
    for pat in (_GITHUB_SSH, _GITHUB_HTTPS):
        m = pat.match(remote_url)
        if m:
            return f"https://github.com/{m['owner']}/{m['repo']}/compare/{base_ref}...{head_branch}"
    return None


def _checklist(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for f in findings:
        fid = str(f.get("id", "")) or "UNKNOWN"
        trust = f.get("trust_class", "objective")
        items.append({
            "finding_id": fid,
            "severity": f.get("severity", "info"),
            "trust_class": trust,
            "title": f.get("title", ""),
            "file": f.get("file", ""),
            "line": f.get("line"),
            "verify": (
                "Objective check: confirm the fix compiles, tests pass, and "
                "the referenced file:line shows the change."
                if trust == "objective"
                else "Advisory check: this fix is a judgement call — read the "
                     "diff and confirm it matches intent before approving."
            ),
        })
    return items


def build_preview(inputs: PreviewInputs) -> dict[str, Any]:
    base_sha = _rev_parse(inputs.repo_path, inputs.base_ref)
    head_sha = _rev_parse(inputs.repo_path, "HEAD")
    return {
        "version": 1,
        "job_id": inputs.job_id,
        "repo": inputs.repo_name,
        "branch": inputs.branch,
        "base_ref": inputs.base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "compare_url": _compare_url(inputs.remote_url, inputs.base_ref, inputs.branch),
        "changes": _numstat(inputs.repo_path, base_sha, head_sha),
        "commits": _commits(inputs.repo_path, base_sha, head_sha),
        "checklist": _checklist(inputs.findings_addressed),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
