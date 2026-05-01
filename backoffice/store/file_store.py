"""File-backed :class:`~backoffice.store.base.Store` implementation.

Persists exactly the files Back Office uses today:

* ``<root>/config/task-queue.yaml``  — authoritative queue
* ``<root>/results/task-queue.json`` — machine-readable mirror
* ``<root>/dashboard/task-queue.json`` — frontend mirror
* ``<root>/results/audit-events.jsonl`` — audit-event log (new in Phase 2)
* ``<root>/results/.locks/<resource>.lock`` — advisory locks

The dashboard payload format matches
:func:`backoffice.tasks.build_dashboard_payload` so swapping in this
store does not change what the dashboard sees.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backoffice.domain import AuditEvent, Run, Task
from backoffice.domain.state_machines import (
    IllegalTransition,
    is_legal_task_transition,
)
from backoffice.store.atomic import (
    LockFile,
    append_jsonl_line,
    atomic_write_json,
    atomic_write_yaml,
)
from backoffice.store.base import (
    CHECKOUT_REASON_ALREADY_RUNNING,
    CHECKOUT_REASON_TASK_NOT_FOUND,
    CHECKOUT_REASON_WRONG_STATE,
    CheckoutConflict,
    CheckoutResult,
    Store,
    TaskNotFound,
    TaskQueueState,
)


# Run states that still hold the task. Once a run leaves these the
# task can be re-claimed.
_ACTIVE_RUN_STATES: frozenset[str] = frozenset(
    {"created", "queued", "starting", "running"}
)

# Task states a checkout may legitimately start from. Anything else
# yields a structured ``wrong_state`` conflict.
_CHECKOUTABLE_TASK_STATES: frozenset[str] = frozenset(
    {"ready", "queued"}
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"

logger = logging.getLogger(__name__)


_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _safe_filename(resource: str) -> str:
    """Sanitize a resource name into a safe lock filename."""
    cleaned = "".join(c if (c.isalnum() or c in {"-", "_", "."}) else "_" for c in resource)
    return cleaned or "lock"


class FileStore(Store):
    """File-backed store. Default for all Back Office deployments today."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        config_dir: Path | str | None = None,
        results_dir: Path | str | None = None,
        dashboard_dir: Path | str | None = None,
    ) -> None:
        self._root = Path(
            root if root is not None else os.environ.get("BACK_OFFICE_ROOT", _DEFAULT_ROOT)
        )
        self._config_dir = Path(config_dir) if config_dir else self._root / "config"
        self._results_dir = Path(results_dir) if results_dir else self._root / "results"
        self._dashboard_dir = (
            Path(dashboard_dir) if dashboard_dir else self._root / "dashboard"
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def task_queue_path(self) -> Path:
        return self._config_dir / "task-queue.yaml"

    def task_queue_results_mirror_path(self) -> Path:
        return self._results_dir / "task-queue.json"

    def task_queue_dashboard_mirror_path(self) -> Path:
        return self._dashboard_dir / "task-queue.json"

    def audit_log_path(self) -> Path:
        return self._results_dir / "audit-events.jsonl"

    def runs_dir(self) -> Path:
        return self._results_dir / "runs"

    def _lock_dir(self) -> Path:
        return self._results_dir / ".locks"

    # ------------------------------------------------------------------
    # Task queue
    # ------------------------------------------------------------------

    def load_task_queue(self) -> TaskQueueState:
        path = self.task_queue_path()
        if not path.exists():
            return TaskQueueState()
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not read task queue %s: %s", path, exc)
            return TaskQueueState()
        if not isinstance(raw, dict):
            return TaskQueueState()
        return TaskQueueState.from_dict(raw)

    def save_task_queue(self, state: TaskQueueState) -> None:
        """Atomically persist the queue + write both dashboard mirrors.

        Mirror payloads match :func:`backoffice.tasks.build_dashboard_payload`
        byte-for-byte so existing readers see no change.
        """
        # The authoritative YAML stores the canonical Task records.
        atomic_write_yaml(self.task_queue_path(), state.to_dict())

        # Mirror payload is computed lazily to avoid a circular import:
        # backoffice.tasks → backoffice.store → backoffice.tasks.
        from backoffice.tasks import build_dashboard_payload

        # build_dashboard_payload expects raw legacy dicts.
        dashboard_payload = build_dashboard_payload([t.to_dict() for t in state.tasks])

        atomic_write_json(self.task_queue_results_mirror_path(), dashboard_payload)
        atomic_write_json(self.task_queue_dashboard_mirror_path(), dashboard_payload)

    # ------------------------------------------------------------------
    # Surgical task operations (Phase 3)
    # ------------------------------------------------------------------
    #
    # ``transition_task`` and ``checkout_task`` operate on the raw
    # on-disk dict instead of round-tripping through Task to preserve
    # the YAML key order produced by ``ensure_task_defaults``. They
    # hold the queue lock for the whole read-modify-write cycle.

    def get_task(self, task_id: str) -> Task | None:
        raw = self._load_raw_queue()
        for task_dict in raw.get("tasks") or []:
            if isinstance(task_dict, dict) and task_dict.get("id") == task_id:
                return Task.from_dict(task_dict)
        return None

    def transition_task(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str,
        reason: str = "",
    ) -> Task:
        with self.lock("task-queue"):
            raw = self._load_raw_queue()
            task_dict = self._find_task_dict(raw, task_id)
            if task_dict is None:
                raise TaskNotFound(task_id)

            from_state = str(task_dict.get("status", "proposed"))
            if not is_legal_task_transition(from_state, to_state):
                raise IllegalTransition("task", from_state, to_state)

            now = _iso_now()
            task_dict["status"] = to_state
            task_dict["updated_at"] = now
            history = task_dict.setdefault("history", [])
            if not isinstance(history, list):
                history = []
                task_dict["history"] = history
            history.append(
                {"status": to_state, "at": now, "by": actor, "note": reason or ""}
            )

            self._write_raw_queue(raw)

            self.append_audit_event(
                AuditEvent(
                    id=_gen_id("evt"),
                    at=now,
                    actor_id=actor,
                    action="task.transition",
                    subject_kind="task",
                    subject_id=task_id,
                    before={"status": from_state},
                    after={"status": to_state},
                    reason=reason,
                )
            )
            return Task.from_dict(task_dict)

    def checkout_task(
        self,
        task_id: str,
        *,
        agent_id: str,
        adapter_type: str = "",
        approval_id: str = "",
    ) -> CheckoutResult:
        with self.lock("task-queue"):
            raw = self._load_raw_queue()
            task_dict = self._find_task_dict(raw, task_id)
            if task_dict is None:
                return CheckoutResult(
                    conflict=CheckoutConflict(
                        task_id=task_id,
                        reason=CHECKOUT_REASON_TASK_NOT_FOUND,
                    )
                )

            current_state = str(task_dict.get("status", "proposed"))

            # Resume / conflict path: an active run already holds this task.
            existing_run_id = str(task_dict.get("current_run_id", ""))
            if existing_run_id:
                existing_run = self.get_run(existing_run_id)
                if existing_run is not None and existing_run.state in _ACTIVE_RUN_STATES:
                    if existing_run.agent_id == agent_id:
                        return CheckoutResult(run=existing_run, resumed=True)
                    return CheckoutResult(
                        conflict=CheckoutConflict(
                            task_id=task_id,
                            reason=CHECKOUT_REASON_ALREADY_RUNNING,
                            held_by_agent_id=existing_run.agent_id,
                            held_by_run_id=existing_run.id,
                            current_state=current_state,
                        )
                    )
                # Stale pointer: the run is finished or missing. Fall
                # through to a fresh checkout below.

            # State-machine guard: only a small set of states are
            # checkoutable. Everything else gets a structured conflict
            # (instead of an exception) so callers can branch.
            if current_state not in _CHECKOUTABLE_TASK_STATES:
                return CheckoutResult(
                    conflict=CheckoutConflict(
                        task_id=task_id,
                        reason=CHECKOUT_REASON_WRONG_STATE,
                        current_state=current_state,
                    )
                )
            if not is_legal_task_transition(current_state, "checked_out"):
                # Belt-and-suspenders: should never trigger because of
                # the set check above, but keep the explicit guard.
                return CheckoutResult(
                    conflict=CheckoutConflict(
                        task_id=task_id,
                        reason=CHECKOUT_REASON_WRONG_STATE,
                        current_state=current_state,
                    )
                )

            now = _iso_now()
            run_id = _gen_id("run")
            run = Run(
                id=run_id,
                task_id=task_id,
                agent_id=agent_id,
                adapter_type=adapter_type,
                approval_id=approval_id or None,
                state="created",
            )

            # Crash-safe ordering: persist the run BEFORE updating the
            # queue. If we crash after this and before the queue write,
            # the run file is an orphan but the task remains claimable
            # by anyone (including another agent). If we crashed in
            # the other order, the task would be wedged.
            self.create_run(run)

            task_dict["status"] = "checked_out"
            task_dict["updated_at"] = now
            task_dict["current_run_id"] = run_id
            history = task_dict.setdefault("history", [])
            if not isinstance(history, list):
                history = []
                task_dict["history"] = history
            history.append(
                {
                    "status": "checked_out",
                    "at": now,
                    "by": f"agent:{agent_id}" if agent_id else "agent",
                    "note": f"checked out by run {run_id}",
                }
            )

            self._write_raw_queue(raw)

            self.append_audit_event(
                AuditEvent(
                    id=_gen_id("evt"),
                    at=now,
                    actor_id=f"agent:{agent_id}" if agent_id else "agent",
                    action="run.created",
                    subject_kind="run",
                    subject_id=run_id,
                    after={"task_id": task_id, "agent_id": agent_id, "state": "created"},
                    reason="checkout",
                )
            )
            self.append_audit_event(
                AuditEvent(
                    id=_gen_id("evt"),
                    at=now,
                    actor_id=f"agent:{agent_id}" if agent_id else "agent",
                    action="task.transition",
                    subject_kind="task",
                    subject_id=task_id,
                    before={"status": current_state},
                    after={"status": "checked_out", "current_run_id": run_id},
                    reason=f"checkout by {agent_id}",
                )
            )

            return CheckoutResult(run=run)

    # ------------------------------------------------------------------
    # Run records (Phase 3)
    # ------------------------------------------------------------------

    def create_run(self, run: Run) -> Run:
        if not run.id:
            raise ValueError("run.id is required for create_run")
        atomic_write_json(self._run_path(run.id), run.to_dict())
        return run

    def get_run(self, run_id: str) -> Run | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read run %s: %s", path, exc)
            return None
        if not isinstance(payload, dict):
            return None
        return Run.from_dict(payload)

    def list_runs(self, *, task_id: str | None = None) -> list[Run]:
        runs_dir = self.runs_dir()
        if not runs_dir.exists():
            return []
        out: list[Run] = []
        for path in sorted(runs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            run = Run.from_dict(payload)
            if task_id is not None and run.task_id != task_id:
                continue
            out.append(run)
        return out

    def _run_path(self, run_id: str) -> Path:
        # Run ids are generated locally; still pass through the
        # safe-filename helper for defense in depth if a caller passes
        # an id with awkward characters.
        return self.runs_dir() / f"{_safe_filename(run_id)}.json"

    # ------------------------------------------------------------------
    # Raw-queue helpers (kept private — preserves dict key order)
    # ------------------------------------------------------------------

    def _load_raw_queue(self) -> dict:
        path = self.task_queue_path()
        if not path.exists():
            return {"version": 1, "tasks": []}
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not read task queue %s: %s", path, exc)
            return {"version": 1, "tasks": []}
        if not isinstance(raw, dict):
            return {"version": 1, "tasks": []}
        raw.setdefault("version", 1)
        if not isinstance(raw.get("tasks"), list):
            raw["tasks"] = []
        return raw

    def _write_raw_queue(self, raw: dict) -> None:
        # Keep the same multi-file write fan-out as save_task_queue:
        # authoritative YAML + both JSON mirrors.
        from backoffice.tasks import build_dashboard_payload

        atomic_write_yaml(self.task_queue_path(), raw)
        tasks = [t for t in raw.get("tasks", []) if isinstance(t, dict)]
        dashboard_payload = build_dashboard_payload(tasks)
        atomic_write_json(self.task_queue_results_mirror_path(), dashboard_payload)
        atomic_write_json(self.task_queue_dashboard_mirror_path(), dashboard_payload)

    @staticmethod
    def _find_task_dict(raw: dict, task_id: str) -> dict | None:
        for task_dict in raw.get("tasks") or []:
            if isinstance(task_dict, dict) and task_dict.get("id") == task_id:
                return task_dict
        return None

    # ------------------------------------------------------------------
    # Audit events
    # ------------------------------------------------------------------

    def append_audit_event(self, event: AuditEvent) -> None:
        # Best-effort rotation before append. Constant-time when the
        # file is small; rotates and continues when it isn't.
        try:
            from backoffice.audit_rotation import maybe_rotate
            maybe_rotate(self.audit_log_path())
        except Exception:  # noqa: BLE001
            logger.exception("audit rotation check failed; continuing append")
        append_jsonl_line(self.audit_log_path(), event.to_dict())

    def read_audit_events(self) -> list[AuditEvent]:
        path = self.audit_log_path()
        if not path.exists():
            return []
        events: list[AuditEvent] = []
        try:
            with path.open() as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        # Tolerate torn lines without dropping the rest.
                        continue
                    if isinstance(obj, dict):
                        events.append(AuditEvent.from_dict(obj))
        except OSError as exc:
            logger.warning("Could not read audit log %s: %s", path, exc)
            return []
        return events

    # ------------------------------------------------------------------
    # Locks
    # ------------------------------------------------------------------

    def lock(
        self,
        resource: str,
        *,
        exclusive: bool = True,
        blocking: bool = True,
    ) -> AbstractContextManager:
        path = self._lock_dir() / f"{_safe_filename(resource)}.lock"
        return LockFile(path, exclusive=exclusive, blocking=blocking)
