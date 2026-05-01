"""Storage abstraction for Back Office.

The ``Store`` base class fronts every read and write that needs
crash-safety, audit, or future portability. Phase 2 ships one
implementation: :class:`backoffice.store.file_store.FileStore`. Later
phases may add SQLite/Postgres without changing call sites.

Today's call sites continue to read and write the same files
(``config/task-queue.yaml``, ``results/task-queue.json``, etc.). The
store does not invent new artifacts in this phase; it just gives
callers one cohesive API.

See ``docs/architecture/target-state.md`` §5.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from backoffice.domain import AuditEvent, Run, Task


# ──────────────────────────────────────────────────────────────────────
# Aggregate value objects
# ──────────────────────────────────────────────────────────────────────


@dataclass
class TaskQueueState:
    """In-memory representation of ``config/task-queue.yaml``.

    ``tasks`` are :class:`backoffice.domain.Task` instances; round-trip
    is lossless against the legacy ``ensure_task_defaults`` output.
    """

    version: int = 1
    tasks: list[Task] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "TaskQueueState":
        if not isinstance(raw, dict):
            return cls()
        version = int(raw.get("version", 1) or 1)
        tasks_raw = raw.get("tasks") or []
        if not isinstance(tasks_raw, list):
            tasks_raw = []
        tasks = [Task.from_dict(t) for t in tasks_raw if isinstance(t, dict)]
        extras = {k: v for k, v in raw.items() if k not in {"version", "tasks"}}
        return cls(version=version, tasks=tasks, extras=extras)

    def to_dict(self) -> dict:
        out: dict = {
            "version": self.version,
            "tasks": [t.to_dict() for t in self.tasks],
        }
        for k, v in self.extras.items():
            if k not in out:
                out[k] = v
        return out


# ──────────────────────────────────────────────────────────────────────
# Checkout result types
# ──────────────────────────────────────────────────────────────────────


# Reason codes for ``CheckoutConflict``. Stable strings so callers can
# pattern-match without depending on exception class hierarchies.
CHECKOUT_REASON_TASK_NOT_FOUND = "task_not_found"
CHECKOUT_REASON_WRONG_STATE = "wrong_state"
CHECKOUT_REASON_ALREADY_RUNNING = "already_running"


@dataclass(frozen=True)
class CheckoutConflict:
    """Structured failure for :meth:`Store.checkout_task`.

    ``held_by_*`` fields are populated only for ``already_running``
    conflicts; the other reason codes leave them empty.
    """

    task_id: str
    reason: str
    held_by_agent_id: str = ""
    held_by_run_id: str = ""
    current_state: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "reason": self.reason,
            "held_by_agent_id": self.held_by_agent_id,
            "held_by_run_id": self.held_by_run_id,
            "current_state": self.current_state,
        }


@dataclass(frozen=True)
class CheckoutResult:
    """Discriminated-union return type for :meth:`Store.checkout_task`.

    Exactly one of ``run`` and ``conflict`` is set. Use :attr:`ok` to
    branch ergonomically::

        result = store.checkout_task(task_id, agent_id="agent-fix")
        if result.ok:
            run = result.run
        else:
            log.warn("conflict: %s", result.conflict.reason)
    """

    run: Run | None = None
    resumed: bool = False
    conflict: CheckoutConflict | None = None

    @property
    def ok(self) -> bool:
        return self.run is not None and self.conflict is None


class TaskNotFound(LookupError):
    """Raised by :meth:`Store.transition_task` when the id is unknown."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"task not found: {task_id!r}")


# ──────────────────────────────────────────────────────────────────────
# Store base class
# ──────────────────────────────────────────────────────────────────────


class Store(ABC):
    """Storage facade.

    All concrete stores must implement these methods. Higher-level
    helpers (history pruning, ledger compaction, etc.) live in
    :mod:`backoffice.store.file_store` so they can share the atomic
    write helpers.
    """

    # ---- introspection ----------------------------------------------

    @property
    @abstractmethod
    def root(self) -> Path:
        """The Back Office root directory used to compute file paths."""

    # ---- task queue --------------------------------------------------

    @abstractmethod
    def load_task_queue(self) -> TaskQueueState:
        """Read the current queue state. Missing/corrupt → empty state."""

    @abstractmethod
    def save_task_queue(self, state: TaskQueueState) -> None:
        """Persist the queue and refresh dashboard mirrors."""

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None:
        """Return one task by id, or ``None`` if not found."""

    @abstractmethod
    def transition_task(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str,
        reason: str = "",
    ) -> Task:
        """Atomically validate + apply a task state transition.

        Refuses illegal transitions via
        :class:`backoffice.domain.IllegalTransition`. Appends an entry
        to ``task["history"]`` and emits one ``task.transition`` audit
        event. Returns the updated task.
        """

    @abstractmethod
    def checkout_task(
        self,
        task_id: str,
        *,
        agent_id: str,
        adapter_type: str = "",
        approval_id: str = "",
    ) -> CheckoutResult:
        """Atomically claim *task_id* for *agent_id*.

        On success: creates a new :class:`Run`, transitions the task
        to ``checked_out``, sets ``task.current_run_id``, emits two
        audit events (run.created + task.transition), and returns
        ``CheckoutResult(run=run)``.

        Resume semantics: if the task already has an active run for
        the same ``agent_id``, returns ``CheckoutResult(run=existing,
        resumed=True)`` without creating a new run.

        Conflict cases return ``CheckoutResult(conflict=...)`` with a
        stable reason code; the caller decides whether to retry.
        """

    # ---- runs --------------------------------------------------------

    @abstractmethod
    def create_run(self, run: Run) -> Run:
        """Persist a new run record. Idempotent on identical writes."""

    @abstractmethod
    def get_run(self, run_id: str) -> Run | None:
        """Load a run by id, or ``None`` if not found."""

    @abstractmethod
    def list_runs(self, *, task_id: str | None = None) -> list[Run]:
        """List runs, optionally filtered by task id."""

    # ---- audit -------------------------------------------------------

    @abstractmethod
    def append_audit_event(self, event: AuditEvent) -> None:
        """Append one event to the audit log (JSONL)."""

    @abstractmethod
    def read_audit_events(self) -> list[AuditEvent]:
        """Return all audit events in insertion order."""

    # ---- locks -------------------------------------------------------

    @abstractmethod
    def lock(
        self,
        resource: str,
        *,
        exclusive: bool = True,
        blocking: bool = True,
    ) -> AbstractContextManager:
        """Acquire an advisory lock scoped to *resource*."""

    # ---- path inspection (file-store specific helpers) ---------------

    @abstractmethod
    def task_queue_path(self) -> Path:
        """Authoritative on-disk path for the task queue."""

    @abstractmethod
    def task_queue_results_mirror_path(self) -> Path:
        """``results/task-queue.json`` mirror path."""

    @abstractmethod
    def task_queue_dashboard_mirror_path(self) -> Path:
        """``dashboard/task-queue.json`` mirror path."""

    @abstractmethod
    def audit_log_path(self) -> Path:
        """JSONL audit-event log path."""

    @abstractmethod
    def runs_dir(self) -> Path:
        """Directory containing per-run JSON records."""
