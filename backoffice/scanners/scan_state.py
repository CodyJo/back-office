"""Per-(target, scope) git SHA tracking so unchanged repos can be skipped.

The deterministic scanner takes 5-30s per repo and is free, but at 12
targets that's still minutes per overnight cycle. Most cycles touch 1-2
repos. This module records the HEAD SHA of the last successful scan
per (target, scope) and lets callers skip when no commits have landed.

Storage: ``results/scan-state.json`` (single JSON map). Atomic writes,
sidecar lock, safe under concurrent scans.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backoffice.store.atomic import LockFile, atomic_write_json
from backoffice.workflow import iso_now, read_json

logger = logging.getLogger(__name__)

STATE_FILENAME = "scan-state.json"


@dataclass
class ScanState:
    """One persisted record per (target, scope) pair."""
    target: str
    scope: str  # e.g. "qa-deterministic", "seo-deterministic"
    head_sha: str
    scanned_at: str
    finding_count: int


def _state_path(results_dir: str) -> Path:
    return Path(results_dir) / STATE_FILENAME


def _key(target: str, scope: str) -> str:
    return f"{target}:{scope}"


def head_sha(repo_path: str) -> Optional[str]:
    """Return the current HEAD SHA, or None if not a git repo."""
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def load_state(results_dir: str) -> dict[str, dict]:
    """Return the full state map ({key: record-dict})."""
    data = read_json(str(_state_path(results_dir)))
    if not isinstance(data, dict):
        return {}
    return data


def get(results_dir: str, target: str, scope: str) -> Optional[ScanState]:
    record = load_state(results_dir).get(_key(target, scope))
    if not isinstance(record, dict):
        return None
    return ScanState(
        target=record.get("target", target),
        scope=record.get("scope", scope),
        head_sha=record.get("head_sha", ""),
        scanned_at=record.get("scanned_at", ""),
        finding_count=int(record.get("finding_count", 0) or 0),
    )


def update(
    results_dir: str,
    *,
    target: str,
    scope: str,
    sha: str,
    finding_count: int,
) -> None:
    """Atomically record a successful scan's state."""
    if not sha:
        return
    path = _state_path(results_dir)
    lock_path = path.with_name(path.name + ".lock")
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    with LockFile(lock_path):
        state = load_state(results_dir)
        state[_key(target, scope)] = {
            "target": target,
            "scope": scope,
            "head_sha": sha,
            "scanned_at": iso_now(),
            "finding_count": int(finding_count),
        }
        atomic_write_json(path, state)


def should_skip(
    results_dir: str,
    *,
    target: str,
    scope: str,
    repo_path: str,
) -> tuple[bool, str]:
    """Decide whether to skip a scan based on SHA equality.

    Returns ``(skip, reason)``. Skip == False is the safe default —
    when in doubt (no .git, no prior state, force flag) we run the scan.
    """
    current = head_sha(repo_path)
    if not current:
        return False, "no-git-head"
    prior = get(results_dir, target, scope)
    if prior is None:
        return False, "no-prior-scan"
    if prior.head_sha != current:
        return False, f"sha-changed:{prior.head_sha[:8]}->{current[:8]}"
    return True, f"unchanged-since-{prior.scanned_at[:19]}"
