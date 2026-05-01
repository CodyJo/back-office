"""ProcessAdapter — runs a configured shell command in a subprocess.

Wraps today's ``agents/*.sh`` flows so they become first-class
:class:`Adapter` invocations. Supports:

* ``timeout_seconds`` — enforced via ``subprocess.run(timeout=...)``.
* ``env_allowlist`` — only the named environment variables propagate
  to the child; everything else is dropped.
* ``cwd_strategy`` — ``repo`` (default) cds to the target repo path;
  ``sandbox`` runs in a temp directory; ``worktree`` is reserved for
  Phase 10 (currently behaves like ``repo``).
* ``dry_run`` — log the command instead of executing.

Adapter does not commit, push, or merge — those are the caller's
business.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
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

logger = logging.getLogger(__name__)


@dataclass
class _ProcessRecord:
    """Tracks a launched subprocess plus its result. Module-level
    state is intentional — adapters need to remember handles across
    invoke()/status()/cancel() calls in the same process."""

    proc: subprocess.Popen | None
    state: str  # running | succeeded | failed | cancelled | timed_out
    exit_code: int | None = None
    output_summary: str = ""
    error: str = ""


class ProcessAdapter:
    name = "process"

    # ``handle.handle`` strings map to records here. Process-local; if
    # the host process dies, in-flight handles vanish — that's fine
    # because the run lifecycle is owned by Back Office, not the adapter.
    _records: dict[str, _ProcessRecord] = {}
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

        cmd = self._resolve_command(agent, context)
        if not cmd:
            raise InvocationDenied("process adapter requires adapter_config.command")

        cwd = self._resolve_cwd(context)
        env = self._resolve_env(context.env_allowlist)
        timeout = context.timeout_seconds or None

        if context.dry_run:
            logger.info("ProcessAdapter dry-run: %s (cwd=%s)", cmd, cwd)
            handle_id = f"process:dryrun:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _ProcessRecord(
                    proc=None,
                    state="succeeded",
                    exit_code=0,
                    output_summary="dry-run",
                )
            return AdapterHandle(adapter_type="process", handle=handle_id)

        try:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            handle_id = f"process:timeout:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _ProcessRecord(
                    proc=None,
                    state="timed_out",
                    exit_code=None,
                    output_summary=str(exc.stdout or "")[:1024],
                    error=f"timeout after {timeout}s",
                )
            return AdapterHandle(adapter_type="process", handle=handle_id)
        except (OSError, FileNotFoundError) as exc:
            handle_id = f"process:error:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _ProcessRecord(
                    proc=None,
                    state="failed",
                    exit_code=None,
                    output_summary="",
                    error=f"failed to launch: {exc}",
                )
            return AdapterHandle(adapter_type="process", handle=handle_id)

        state = "succeeded" if completed.returncode == 0 else "failed"
        handle_id = f"process:{run.id}"
        with self._records_lock:
            self._records[handle_id] = _ProcessRecord(
                proc=None,
                state=state,
                exit_code=completed.returncode,
                output_summary=(completed.stdout or "")[:4096],
                error=(completed.stderr or "")[:4096],
            )
        return AdapterHandle(
            adapter_type="process",
            handle=handle_id,
            metadata={"command": cmd if isinstance(cmd, list) else [cmd]},
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
        # ProcessAdapter today runs synchronously inside invoke(), so
        # by the time cancel() is callable the process has already
        # finished. We surface that honestly.
        with self._records_lock:
            record = self._records.get(handle.handle)
        if record is None:
            return AdapterCancelResult(cancelled=False, reason="unknown handle")
        if record.state == "running":
            return AdapterCancelResult(
                cancelled=False, reason="cancellation not supported for synchronous runs"
            )
        return AdapterCancelResult(cancelled=False, reason=f"already {record.state}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_command(agent: Agent, context: AdapterContext) -> list[str]:
        cfg = agent.adapter_config or {}
        cmd_raw = cfg.get("command", "")
        args = list(cfg.get("args", []) or [])
        if isinstance(cmd_raw, list):
            return [*cmd_raw, *args]
        if isinstance(cmd_raw, str) and cmd_raw.strip():
            base = shlex.split(cmd_raw)
            return [*base, *args]
        return []

    @staticmethod
    def _resolve_cwd(context: AdapterContext) -> str | None:
        if context.cwd_strategy == "sandbox":
            return tempfile.mkdtemp(prefix="bo-process-")
        return context.target_repo_path or None

    @staticmethod
    def _resolve_env(allowlist: list[str]) -> dict[str, str]:
        # Always allow PATH so children can find executables.
        keys = set(allowlist) | {"PATH"}
        return {k: os.environ[k] for k in keys if k in os.environ}
