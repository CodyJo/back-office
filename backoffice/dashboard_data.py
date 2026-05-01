"""Dashboard data generators for agents, runs, audit events.

Phase 6 introduces three new dashboard JSON payloads consumed by
``dashboard/index.html`` (Phase 6 also adds the cards). The
generators read from :class:`backoffice.store.FileStore` so the
existing department / matrix / approval-queue dashboard surfaces
remain untouched.

Outputs:

* ``dashboard/agents-data.json``       — agent registry snapshot
* ``dashboard/runs-data.json``         — recent runs + active runs
* ``dashboard/audit-events.json``      — last N audit events

Routine generation is via :func:`refresh_all`, which the existing
``backoffice.workflow.refresh_dashboard_artifacts`` may call. For
phase 6 we expose them but don't auto-wire the workflow.
"""
from __future__ import annotations

import logging
from pathlib import Path

from backoffice.store import FileStore
from backoffice.store.atomic import atomic_write_json

logger = logging.getLogger(__name__)


_AGENTS_FILE = "agents-data.json"
_RUNS_FILE = "runs-data.json"
_AUDIT_FILE = "audit-events.json"

_RUN_ACTIVE = frozenset({"created", "queued", "starting", "running"})
_AUDIT_TAIL = 200


# ──────────────────────────────────────────────────────────────────────
# Builders (pure)
# ──────────────────────────────────────────────────────────────────────


def build_agents_payload(store: FileStore) -> dict:
    from backoffice.agents import AgentRegistry  # local — avoids cycle

    registry = AgentRegistry(store=store)
    agents = registry.list()
    by_status: dict[str, int] = {"active": 0, "paused": 0, "retired": 0}
    items: list[dict] = []
    for a in agents:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        items.append({
            "id": a.id,
            "name": a.name,
            "role": a.role,
            "adapter_type": a.adapter_type,
            "status": a.status,
            "description": a.description,
            "paused_at": a.paused_at,
            "updated_at": a.updated_at,
        })
    return {
        "summary": {"total": len(items), "by_status": by_status},
        "agents": items,
    }


def build_runs_payload(store: FileStore, *, max_recent: int = 50) -> dict:
    runs = store.list_runs()
    runs_sorted = sorted(runs, key=lambda r: r.started_at or r.id, reverse=True)
    active = [r for r in runs_sorted if r.state in _RUN_ACTIVE]
    recent = runs_sorted[:max_recent]
    by_state: dict[str, int] = {}
    for r in runs_sorted:
        by_state[r.state] = by_state.get(r.state, 0) + 1
    return {
        "summary": {
            "total": len(runs_sorted),
            "active": len(active),
            "by_state": by_state,
        },
        "active": [r.to_dict() for r in active],
        "recent": [r.to_dict() for r in recent],
    }


def build_audit_events_payload(store: FileStore, *, tail: int = _AUDIT_TAIL) -> dict:
    events = store.read_audit_events()
    tail_events = events[-tail:] if tail else events
    return {
        "summary": {"total": len(events), "shown": len(tail_events)},
        "events": [e.to_dict() for e in tail_events],
    }


# ──────────────────────────────────────────────────────────────────────
# Writers
# ──────────────────────────────────────────────────────────────────────


def write_agents(store: FileStore, dashboard_dir: Path | None = None) -> Path:
    target = (dashboard_dir or _default_dashboard_dir(store)) / _AGENTS_FILE
    atomic_write_json(target, build_agents_payload(store))
    return target


def write_runs(store: FileStore, dashboard_dir: Path | None = None) -> Path:
    target = (dashboard_dir or _default_dashboard_dir(store)) / _RUNS_FILE
    atomic_write_json(target, build_runs_payload(store))
    return target


def write_audit_events(store: FileStore, dashboard_dir: Path | None = None) -> Path:
    target = (dashboard_dir or _default_dashboard_dir(store)) / _AUDIT_FILE
    atomic_write_json(target, build_audit_events_payload(store))
    return target


def refresh_all(store: FileStore | None = None, dashboard_dir: Path | None = None) -> dict[str, Path]:
    """Regenerate all Phase 6 dashboard payloads."""
    store = store or FileStore()
    dest = dashboard_dir or _default_dashboard_dir(store)
    return {
        "agents": write_agents(store, dest),
        "runs": write_runs(store, dest),
        "audit": write_audit_events(store, dest),
    }


def _default_dashboard_dir(store: FileStore) -> Path:
    # FileStore tracks dashboard_dir privately; we recompute relative
    # to root so callers don't have to dig into the implementation.
    return Path(store.task_queue_dashboard_mirror_path()).parent
