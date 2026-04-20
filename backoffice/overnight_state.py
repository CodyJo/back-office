"""Loop state helpers for the overnight orchestrator.

Three concerns split out of overnight.sh's shell helpers:

1. :class:`ExecutionLedger` — append-only JSONL of per-decision records
   (why a fix was attempted, why a feature was skipped, what gate allowed
   or blocked it, what rollback tag was taken). The ledger is the audit
   trail operators use to answer "why did the loop do that?".

2. :class:`FailureMemory` — reads the structured history and returns the
   set of ``(repo, title)`` items that failed in the last N cycles, so
   the overnight loop can exclude them from the next plan even if the
   Product Owner agent re-nominates them.

3. :class:`Quarantine` — flags a repo whose last N consecutive cycles
   each triggered a rollback on that repo; the loop must skip all work
   against it until an operator clears the flag via a small override
   file.

The existing shell orchestration calls into these helpers through the
CLI surface; the classes themselves are the unit of test.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


# ──────────────────────────────────────────────────────────────────────────────
# ExecutionLedger
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class LedgerRecord:
    cycle_id: str
    action: str
    target: str
    allow: bool
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def with_timestamp(self) -> "LedgerRecord":
        if self.timestamp:
            return self
        return LedgerRecord(
            cycle_id=self.cycle_id,
            action=self.action,
            target=self.target,
            allow=self.allow,
            reason=self.reason,
            detail=dict(self.detail),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class ExecutionLedger:
    """Append-only JSONL ledger of loop decisions."""

    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)

    def append(self, record: LedgerRecord) -> None:
        stamped = record.with_timestamp()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(stamped)) + "\n")

    def read(self, target: str | None = None) -> Iterator[LedgerRecord]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if target is not None and obj.get("target") != target:
                    continue
                yield LedgerRecord(
                    cycle_id=obj.get("cycle_id", ""),
                    action=obj.get("action", ""),
                    target=obj.get("target", ""),
                    allow=bool(obj.get("allow", False)),
                    reason=obj.get("reason", ""),
                    detail=obj.get("detail") or {},
                    timestamp=obj.get("timestamp", ""),
                )


# ──────────────────────────────────────────────────────────────────────────────
# FailureMemory
# ──────────────────────────────────────────────────────────────────────────────

def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    cycles = data.get("cycles") if isinstance(data, dict) else None
    return list(cycles) if isinstance(cycles, list) else []


class FailureMemory:
    """Tracks items that failed in the last *window* cycles.

    The overnight loop consults :meth:`should_skip` before handing a
    finding to the fix agent; items recently-failed are deferred until
    they fall out of the window.
    """

    def __init__(self, history_path: os.PathLike | str, window: int = 2):
        self.history_path = Path(history_path)
        self.window = max(0, int(window))
        self._blocked = self._compute_blocked()

    def _compute_blocked(self) -> set[tuple[str, str]]:
        cycles = _load_history(self.history_path)
        if not cycles or self.window <= 0:
            return set()
        recent = cycles[-self.window:]
        blocked: set[tuple[str, str]] = set()
        for cycle in recent:
            for item in cycle.get("failed_items") or []:
                repo = str(item.get("repo", ""))
                title = str(item.get("title", ""))
                if repo and title:
                    blocked.add((repo, title))
        return blocked

    def blocked_items(self) -> set[tuple[str, str]]:
        return set(self._blocked)

    def should_skip(self, repo: str, title: str) -> bool:
        r = str(repo).lower()
        t = str(title).lower()
        return any(
            str(br).lower() == r and str(bt).lower() == t
            for br, bt in self._blocked
        )


# ──────────────────────────────────────────────────────────────────────────────
# Quarantine
# ──────────────────────────────────────────────────────────────────────────────

class Quarantine:
    """Flags repos with *threshold* consecutive rollback cycles.

    A manual override file may clear a repo; its format is::

        {"cleared": ["repo-a", "repo-b"]}

    Operators drop that file in place after investigating; the loop
    refuses to touch a flagged repo until it appears.
    """

    def __init__(
        self,
        history_path: os.PathLike | str,
        threshold: int = 3,
        overrides_path: os.PathLike | str | None = None,
    ):
        self.history_path = Path(history_path)
        self.threshold = max(1, int(threshold))
        self.overrides_path = Path(overrides_path) if overrides_path else None

    def _cleared(self) -> set[str]:
        if not self.overrides_path or not self.overrides_path.exists():
            return set()
        try:
            data = json.loads(self.overrides_path.read_text())
        except (OSError, json.JSONDecodeError):
            return set()
        cleared = data.get("cleared") if isinstance(data, dict) else None
        if not isinstance(cleared, list):
            return set()
        return {str(r) for r in cleared}

    def flagged(self) -> set[str]:
        cycles = _load_history(self.history_path)
        if not cycles:
            return set()

        streaks: dict[str, int] = {}
        flagged: set[str] = set()
        for cycle in cycles:
            repos = set(cycle.get("rollback_repos") or [])
            for repo in list(streaks):
                if repo not in repos:
                    streaks[repo] = 0
            for repo in repos:
                streaks[repo] = streaks.get(repo, 0) + 1
                if streaks[repo] >= self.threshold:
                    flagged.add(repo)

        return flagged - self._cleared()
