"""LegacyBackendAdapter — wraps the existing ``backoffice.backends.Backend``.

Lets an agent registered with ``adapter_type=legacy_backend`` keep
using the production claude/codex backends until callers migrate to
the Phase 5 ``claude_code`` adapter.

The wrapped backend's ``invoke()`` is synchronous and returns an
:class:`InvocationResult`; we materialize it into an :class:`AdapterStatus`
on the next ``status()`` call.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from backoffice.adapters.base import (
    AdapterCancelResult,
    AdapterContext,
    AdapterHandle,
    AdapterStatus,
    InvocationDenied,
)
from backoffice.domain import Agent, Run, Task


@dataclass
class _BackendRecord:
    state: str
    exit_code: int | None = None
    output_summary: str = ""
    error: str = ""


class LegacyBackendAdapter:
    name = "legacy_backend"

    _records: dict[str, _BackendRecord] = {}
    _records_lock = threading.Lock()

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

        cfg = agent.adapter_config or {}
        backend_name = str(cfg.get("backend") or "")
        if not backend_name:
            raise InvocationDenied("legacy_backend adapter requires adapter_config.backend")

        from backoffice.backends import get_backend  # local — keeps backends optional

        backend = get_backend(
            backend_name,
            {
                "command": cfg.get("command", ""),
                "model": cfg.get("model", ""),
                "mode": cfg.get("mode", ""),
                "local_budget": cfg.get("local_budget", {}),
            },
        )
        if context.dry_run:
            handle_id = f"legacy:{backend_name}:dryrun:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _BackendRecord(
                    state="succeeded",
                    exit_code=0,
                    output_summary="dry-run",
                )
            return AdapterHandle(adapter_type="legacy_backend", handle=handle_id)

        result = backend.invoke(
            context.prompt,
            list(cfg.get("tools", []) or []),
            context.target_repo_path,
        )
        state = "succeeded" if result.success else "failed"
        handle_id = f"legacy:{backend_name}:{run.id}"
        with self._records_lock:
            self._records[handle_id] = _BackendRecord(
                state=state,
                exit_code=result.exit_code,
                output_summary=(result.output or "")[:4096],
                error=(result.error or "")[:4096],
            )
        return AdapterHandle(
            adapter_type="legacy_backend",
            handle=handle_id,
            metadata={"backend": backend_name},
        )

    def status(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterStatus:
        with self._records_lock:
            record = self._records.get(handle.handle)
        if record is None:
            return AdapterStatus(state="failed", error="unknown handle")
        return AdapterStatus(
            state=record.state,
            exit_code=record.exit_code,
            output_summary=record.output_summary,
            error=record.error,
        )

    def cancel(
        self,
        *,
        run: Run,
        handle: AdapterHandle,
    ) -> AdapterCancelResult:
        with self._records_lock:
            record = self._records.get(handle.handle)
        if record is None:
            return AdapterCancelResult(cancelled=False, reason="unknown handle")
        return AdapterCancelResult(cancelled=False, reason=f"already {record.state}")
