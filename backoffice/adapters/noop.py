"""NoopAdapter — deterministic adapter for tests.

Returns a synthetic ``succeeded`` status without spawning anything.
Used by Phase 4+ tests that exercise the registry/checkout/run loop
without depending on Claude/Codex installation.
"""
from __future__ import annotations

from backoffice.adapters.base import (
    AdapterCancelResult,
    AdapterContext,
    AdapterHandle,
    AdapterStatus,
    InvocationDenied,
)
from backoffice.domain import Agent, Run, Task


class NoopAdapter:
    name = "noop"

    def __init__(self, *, default_status: str = "succeeded") -> None:
        self.default_status = default_status

    def invoke(
        self,
        *,
        agent: Agent,
        task: Task,
        run: Run,
        context: AdapterContext,
    ) -> AdapterHandle:
        if agent.status != "active":
            raise InvocationDenied(f"agent {agent.id!r} is not active (status={agent.status!r})")
        return AdapterHandle(
            adapter_type="noop",
            handle=f"noop:{run.id}",
            metadata={"task_id": task.id, "dry_run": context.dry_run},
        )

    def status(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterStatus:
        return AdapterStatus(
            state=self.default_status,
            exit_code=0 if self.default_status == "succeeded" else 1,
            output_summary=f"noop adapter for run {run.id}",
        )

    def cancel(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterCancelResult:
        return AdapterCancelResult(cancelled=True, reason="noop")
