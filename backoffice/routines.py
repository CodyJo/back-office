"""Routines & heartbeats.

Phase 8 introduces a tiny scheduler model. A :class:`Routine` is a
named pair of (trigger, action) that:

* Can be triggered manually (``trigger_kind="manual"``).
* Can be scheduled with a cron-like expression (``trigger_kind="cron"``)
  — Phase 8 ships parsing + due-checks; the actual wake-up loop is
  deliberately small and runs in the existing process via
  :meth:`Scheduler.run_due_now`.
* Respects pause state and budget gates.
* Emits one ``routine.run`` audit event per fire.

Triggers and actions are kept declarative; today's overnight loop
(``scripts/overnight.sh``) becomes one routine alongside others.
This phase does not replace overnight.sh — it provides the model so
operators can add lightweight schedules without writing shell.

See ``docs/architecture/target-state.md`` §3.8.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backoffice.domain import AuditEvent, iso_now
from backoffice.store import FileStore
from backoffice.store.atomic import atomic_write_json

logger = logging.getLogger(__name__)


VALID_TRIGGER_KINDS = ("manual", "cron", "on_task_created", "on_approval_granted", "webhook")
VALID_ACTION_KINDS = (
    "enqueue_audit",
    "enqueue_task",
    "run_agent",
    "sync_dashboard",
    "noop",  # for tests
)


# ──────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Routine:
    id: str
    name: str
    description: str = ""
    trigger_kind: str = "manual"
    trigger: dict = field(default_factory=dict)
    action_kind: str = "noop"
    action: dict = field(default_factory=dict)
    paused: bool = False
    budget_id: str = ""
    last_run_at: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.trigger_kind not in VALID_TRIGGER_KINDS:
            raise ValueError(f"invalid trigger_kind {self.trigger_kind!r}")
        if self.action_kind not in VALID_ACTION_KINDS:
            raise ValueError(f"invalid action_kind {self.action_kind!r}")

    @classmethod
    def from_dict(cls, raw: dict) -> "Routine":
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            trigger_kind=str(raw.get("trigger_kind", "manual")),
            trigger=dict(raw.get("trigger", {}) or {}),
            action_kind=str(raw.get("action_kind", "noop")),
            action=dict(raw.get("action", {}) or {}),
            paused=bool(raw.get("paused", False)),
            budget_id=str(raw.get("budget_id", "")),
            last_run_at=str(raw.get("last_run_at", "")),
            metadata=dict(raw.get("metadata", {}) or {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_kind": self.trigger_kind,
            "trigger": dict(self.trigger),
            "action_kind": self.action_kind,
            "action": dict(self.action),
            "paused": self.paused,
            "budget_id": self.budget_id,
            "last_run_at": self.last_run_at,
            "metadata": dict(self.metadata),
        }


# ──────────────────────────────────────────────────────────────────────
# Scheduler
# ──────────────────────────────────────────────────────────────────────


# Action handler signature: (routine, now_iso) -> dict (result metadata)
ActionHandler = Callable[[Routine, str], dict[str, Any]]


class Scheduler:
    """Lightweight in-process scheduler.

    Persists routines as JSON under ``results/routines/<id>.json`` via
    :class:`backoffice.store.FileStore`. This phase does not run a
    long-lived loop — operators (or routines like the overnight loop)
    call :meth:`run_due_now` periodically to fire matured triggers.
    """

    def __init__(self, store: FileStore | None = None):
        self.store = store or FileStore()
        self._handlers: dict[str, ActionHandler] = {}
        # Built-in noop handler keeps tests deterministic.
        self.register_handler("noop", _noop_handler)

    # ----- paths ------------------------------------------------------

    def routines_dir(self) -> Path:
        return self.store.runs_dir().parent / "routines"

    def _routine_path(self, routine_id: str) -> Path:
        if not routine_id or "/" in routine_id or ".." in routine_id:
            raise ValueError(f"invalid routine id: {routine_id!r}")
        return self.routines_dir() / f"{routine_id}.json"

    # ----- CRUD -------------------------------------------------------

    def list(self) -> list[Routine]:
        d = self.routines_dir()
        if not d.exists():
            return []
        out: list[Routine] = []
        for path in sorted(d.glob("*.json")):
            try:
                import json
                payload = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                out.append(Routine.from_dict(payload))
        return out

    def get(self, routine_id: str) -> Routine | None:
        path = self._routine_path(routine_id)
        if not path.exists():
            return None
        try:
            import json
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return Routine.from_dict(payload) if isinstance(payload, dict) else None

    def upsert(self, routine: Routine, *, actor: str = "operator") -> Routine:
        atomic_write_json(self._routine_path(routine.id), routine.to_dict())
        self._audit("routine.upserted", routine.id, after=routine.to_dict(), actor=actor)
        return routine

    def pause(self, routine_id: str, *, actor: str = "operator") -> Routine:
        r = self._require(routine_id)
        if r.paused:
            return r
        r.paused = True
        atomic_write_json(self._routine_path(r.id), r.to_dict())
        self._audit("routine.paused", r.id, after={"paused": True}, actor=actor)
        return r

    def resume(self, routine_id: str, *, actor: str = "operator") -> Routine:
        r = self._require(routine_id)
        if not r.paused:
            return r
        r.paused = False
        atomic_write_json(self._routine_path(r.id), r.to_dict())
        self._audit("routine.resumed", r.id, after={"paused": False}, actor=actor)
        return r

    # ----- handlers ---------------------------------------------------

    def register_handler(self, action_kind: str, handler: ActionHandler) -> None:
        if action_kind not in VALID_ACTION_KINDS:
            raise ValueError(f"invalid action_kind {action_kind!r}")
        self._handlers[action_kind] = handler

    # ----- firing -----------------------------------------------------

    def run_now(
        self,
        routine_id: str,
        *,
        actor: str = "operator",
        budgets: list | None = None,
        cost_events: list | None = None,
    ) -> dict[str, Any]:
        """Fire *routine_id* immediately.

        Returns a result dict with ``state ∈ {fired, paused, blocked, error, no_handler}``.
        Honors pause state and any matching hard-limit budget.
        """
        r = self._require(routine_id)
        return self._fire(r, actor=actor, budgets=budgets, cost_events=cost_events)

    def run_due_now(
        self,
        *,
        now: datetime | None = None,
        actor: str = "scheduler",
        budgets: list | None = None,
        cost_events: list | None = None,
    ) -> list[dict[str, Any]]:
        """Fire every cron-triggered routine whose schedule is due.

        Manual / event-driven routines are ignored here — they fire
        from their own callers.
        """
        now = now or datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        for r in self.list():
            if r.paused:
                continue
            if r.trigger_kind != "cron":
                continue
            interval = int(r.trigger.get("interval_seconds", 0) or 0)
            if interval <= 0:
                continue
            last = _parse_iso(r.last_run_at)
            if last is None or (now - last).total_seconds() >= interval:
                results.append(self._fire(r, actor=actor, budgets=budgets, cost_events=cost_events))
        return results

    # ----- internals --------------------------------------------------

    def _fire(
        self,
        r: Routine,
        *,
        actor: str,
        budgets: list | None,
        cost_events: list | None,
    ) -> dict[str, Any]:
        if r.paused:
            return {"routine_id": r.id, "state": "paused"}

        # Budget gate (if configured).
        if r.budget_id and budgets is not None and cost_events is not None:
            from backoffice.budgets import BLOCK, evaluate  # local
            decision = evaluate(budgets, cost_events)
            if decision.state == BLOCK:
                self._audit(
                    "routine.blocked",
                    r.id,
                    after={"budget_id": decision.budget_id, "reason": decision.reason},
                    actor=actor,
                )
                return {"routine_id": r.id, "state": "blocked", "reason": decision.reason}

        handler = self._handlers.get(r.action_kind)
        if handler is None:
            return {"routine_id": r.id, "state": "no_handler"}

        try:
            result = handler(r, iso_now())
        except Exception as exc:  # noqa: BLE001
            logger.exception("routine %s handler failed", r.id)
            self._audit("routine.error", r.id, after={"error": str(exc)}, actor=actor)
            return {"routine_id": r.id, "state": "error", "error": str(exc)}

        r.last_run_at = iso_now()
        atomic_write_json(self._routine_path(r.id), r.to_dict())
        self._audit("routine.run", r.id, after={"action_kind": r.action_kind, "result": result}, actor=actor)
        return {"routine_id": r.id, "state": "fired", "result": result}

    def _require(self, routine_id: str) -> Routine:
        r = self.get(routine_id)
        if r is None:
            raise LookupError(f"routine not found: {routine_id!r}")
        return r

    def _audit(
        self,
        action: str,
        routine_id: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        actor: str,
    ) -> None:
        try:
            self.store.append_audit_event(
                AuditEvent(
                    at=iso_now(),
                    actor_id=actor,
                    action=action,
                    subject_kind="routine",
                    subject_id=routine_id,
                    before=before,
                    after=after,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to emit %s audit event", action)


# ──────────────────────────────────────────────────────────────────────
# Built-in noop handler
# ──────────────────────────────────────────────────────────────────────


def _noop_handler(routine: Routine, now: str) -> dict[str, Any]:
    return {"noop": True, "now": now, "name": routine.name}


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────
# Config bridge
# ──────────────────────────────────────────────────────────────────────


def from_config(raw_routines: dict | list | None, scheduler: Scheduler | None = None) -> list[Routine]:
    """Reconcile the ``routines:`` config block with stored routines."""
    if scheduler is None:
        scheduler = Scheduler()
    out: list[Routine] = []
    declarations: list[dict] = []
    if isinstance(raw_routines, list):
        declarations = [d for d in raw_routines if isinstance(d, dict)]
    elif isinstance(raw_routines, dict):
        for rid, body in raw_routines.items():
            if isinstance(body, dict):
                declarations.append({"id": rid, **body})
    for decl in declarations:
        try:
            r = Routine(
                id=str(decl.get("id") or f"routine-{uuid.uuid4().hex[:8]}"),
                name=str(decl.get("name", decl.get("id", ""))),
                description=str(decl.get("description", "")),
                trigger_kind=str(decl.get("trigger_kind", "manual")),
                trigger=dict(decl.get("trigger", {}) or {}),
                action_kind=str(decl.get("action_kind", "noop")),
                action=dict(decl.get("action", {}) or {}),
                paused=bool(decl.get("paused", False)),
                budget_id=str(decl.get("budget_id", "")),
                metadata=dict(decl.get("metadata", {}) or {}),
            )
        except ValueError as exc:
            logger.warning("ignoring invalid routine %s: %s", decl, exc)
            continue
        scheduler.upsert(r, actor="config")
        out.append(r)
    return out
