"""Example plugin used by Phase 12 tests.

Lives under tests/ on purpose — Back Office itself ships zero
production plugins; the loader is the contract, not the catalog.
"""
from __future__ import annotations

from backoffice.adapters.base import (
    AdapterCancelResult,
    AdapterContext,
    AdapterHandle,
    AdapterStatus,
)
from backoffice.domain import Agent, Run, Task


class SampleAdapter:
    name = "sample_plugin"

    def invoke(self, *, agent: Agent, task: Task, run: Run, context: AdapterContext) -> AdapterHandle:
        return AdapterHandle(adapter_type=self.name, handle=f"sample:{run.id}")

    def status(self, *, run: Run, handle: AdapterHandle) -> AdapterStatus:
        return AdapterStatus(state="succeeded", exit_code=0, output_summary="from sample plugin")

    def cancel(self, *, run: Run, handle: AdapterHandle) -> AdapterCancelResult:
        return AdapterCancelResult(cancelled=True)


def hello() -> str:
    return "hello from sample plugin"
