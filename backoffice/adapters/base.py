"""Adapter contract.

An adapter is the thing that actually executes work for an agent. The
contract is intentionally tiny:

* :meth:`Adapter.invoke` — start work; return an opaque handle.
* :meth:`Adapter.status` — poll progress.
* :meth:`Adapter.cancel` — stop work.

Adapters do **not** mutate Back Office state directly. The control
plane decides when to record runs, audit events, costs, and approvals.
Adapters report.

See ``docs/architecture/target-state.md`` §4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backoffice.domain import Agent, Run, Task


# ──────────────────────────────────────────────────────────────────────
# Value objects
# ──────────────────────────────────────────────────────────────────────


@dataclass
class AdapterContext:
    """Per-invocation context passed to :meth:`Adapter.invoke`.

    Exists so adapters never have to reach into globals to find the
    target repo path, the prompt template, the dry-run flag, etc.
    """

    target_repo_path: str = ""
    prompt: str = ""
    timeout_seconds: int = 0
    env_allowlist: list[str] = field(default_factory=list)
    cwd_strategy: str = "repo"  # repo | worktree | sandbox
    dry_run: bool = False
    extras: dict = field(default_factory=dict)


@dataclass
class AdapterHandle:
    """Opaque token returned by :meth:`Adapter.invoke`.

    The control plane stores it on the :class:`Run` and replays it
    when polling status or cancelling.
    """

    adapter_type: str
    handle: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class AdapterStatus:
    """Snapshot of an adapter run's current state.

    ``state`` aligns with :data:`backoffice.domain.RUN_STATES`.
    """

    state: str  # created | queued | starting | running | succeeded | failed | cancelled | timed_out
    exit_code: int | None = None
    output_summary: str = ""
    error: str = ""
    artifacts: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AdapterCancelResult:
    cancelled: bool
    reason: str = ""


class InvocationDenied(RuntimeError):
    """Adapter refused to start (paused agent, missing approval, etc.)."""


# ──────────────────────────────────────────────────────────────────────
# Adapter contract
# ──────────────────────────────────────────────────────────────────────


@runtime_checkable
class Adapter(Protocol):
    """Adapter protocol. All concrete adapters must implement this."""

    name: str

    def invoke(
        self,
        *,
        agent: Agent,
        task: Task,
        run: Run,
        context: AdapterContext,
    ) -> AdapterHandle: ...

    def status(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterStatus: ...

    def cancel(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterCancelResult: ...
