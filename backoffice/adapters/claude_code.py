"""ClaudeCodeAdapter — runs an approved task through Claude Code in a
controlled, isolated workspace.

Safety rules (also enforced by tests):

* Refuses to invoke unless ``adapter_config.command`` is set. By
  default in tests/CI this points at a fake binary so no real Claude
  Code call is made.
* Writes a structured run log to ``results/runs/<run-id>.log`` so
  the audit trail captures stdout/stderr in addition to the structured
  Run record.
* Refuses if the agent is not active.
* Refuses if no ``approval_id`` is on the run (i.e. the work was not
  approved by an operator).

The adapter does not commit, push, or merge — those are downstream
flows. Phase 10 hardens workspace creation; this phase keeps the
working tree separation simple (cwd defaults to the target repo).
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from backoffice.adapters.base import (
    AdapterCancelResult,
    AdapterContext,
    AdapterHandle,
    AdapterStatus,
    InvocationDenied,
)
from backoffice.domain import Agent, Run, Task

logger = logging.getLogger(__name__)


DEFAULT_PROMPT_TEMPLATE = """\
# Task
{title}

## Repo
{repo}

## Acceptance criteria
{acceptance}

## Allowed scope
{allowed_scope}

## Disallowed actions
- Do not auto-merge or push to main.
- Do not modify CI/CD pipelines.
- Do not exfiltrate secrets.

## Test command
{test_command}

## Output
Provide a concise summary of what changed and why.
"""


@dataclass
class _Record:
    state: str
    exit_code: int | None
    output_summary: str
    error: str
    log_path: str


class ClaudeCodeAdapter:
    name = "claude_code"

    _records: dict[str, _Record] = {}
    _records_lock = threading.Lock()

    # Run-log directory is set by the host; tests override via
    # ``run_log_dir`` in adapter_config. Otherwise we default to
    # the current working directory's ``results/runs/`` for safety.
    DEFAULT_RUN_LOG_SUBDIR = Path("results") / "runs"

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
        if not run.approval_id:
            raise InvocationDenied(
                "claude_code adapter refuses to invoke without an approval_id on the run"
            )

        cfg = agent.adapter_config or {}
        cmd_raw = cfg.get("command", "")
        if isinstance(cmd_raw, list):
            cmd: list[str] = list(cmd_raw)
        elif isinstance(cmd_raw, str) and cmd_raw.strip():
            cmd = shlex.split(cmd_raw)
        else:
            raise InvocationDenied(
                "claude_code adapter requires adapter_config.command "
                "(use a fake command in tests; default disabled by config)"
            )

        # Refuse to act against the back-office working tree itself.
        # ``adapter_config.refuse_against`` lists path prefixes that
        # must not match the target repo path.
        target = (context.target_repo_path or "").rstrip("/")
        for forbidden in cfg.get("refuse_against") or []:
            if target and target.startswith(str(forbidden).rstrip("/")):
                raise InvocationDenied(
                    f"claude_code adapter refuses to run against {target!r} "
                    f"(matches refuse_against entry {forbidden!r})"
                )

        prompt = self._render_prompt(task, context, cfg)
        timeout = context.timeout_seconds or int(cfg.get("timeout_seconds", 0)) or None
        env = self._resolve_env(context.env_allowlist)
        log_path = self._log_path(cfg, run)

        if context.dry_run or cfg.get("dry_run"):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(f"[dry-run]\nprompt:\n{prompt}\n")
            handle_id = f"claude:dryrun:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _Record(
                    state="succeeded",
                    exit_code=0,
                    output_summary="dry-run",
                    error="",
                    log_path=str(log_path),
                )
            return AdapterHandle(
                adapter_type="claude_code",
                handle=handle_id,
                metadata={"prompt_preview": prompt[:512], "log_path": str(log_path)},
            )

        # Stream the prompt over stdin so we don't have to interpolate
        # into shell args. Write logs directly.
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                cmd,
                cwd=context.target_repo_path or None,
                env=env,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(f"[timeout]\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}\n")
            handle_id = f"claude:timeout:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _Record(
                    state="timed_out",
                    exit_code=None,
                    output_summary=(exc.stdout or "")[:1024] if exc.stdout else "",
                    error=f"timeout after {timeout}s",
                    log_path=str(log_path),
                )
            return AdapterHandle(adapter_type="claude_code", handle=handle_id, metadata={"log_path": str(log_path)})
        except (OSError, FileNotFoundError) as exc:
            log_path.write_text(f"[error] failed to launch: {exc}\n")
            handle_id = f"claude:error:{run.id}"
            with self._records_lock:
                self._records[handle_id] = _Record(
                    state="failed",
                    exit_code=None,
                    output_summary="",
                    error=f"failed to launch: {exc}",
                    log_path=str(log_path),
                )
            return AdapterHandle(adapter_type="claude_code", handle=handle_id, metadata={"log_path": str(log_path)})

        log_path.write_text(
            f"[exit={completed.returncode}]\nstdout:\n{completed.stdout or ''}\n"
            f"stderr:\n{completed.stderr or ''}\n"
        )
        state = "succeeded" if completed.returncode == 0 else "failed"
        handle_id = f"claude:{run.id}"
        with self._records_lock:
            self._records[handle_id] = _Record(
                state=state,
                exit_code=completed.returncode,
                output_summary=(completed.stdout or "")[:4096],
                error=(completed.stderr or "")[:4096],
                log_path=str(log_path),
            )
        return AdapterHandle(
            adapter_type="claude_code",
            handle=handle_id,
            metadata={"log_path": str(log_path), "command": cmd},
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
            artifacts=[{"kind": "run-log", "path": record.log_path}],
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

    # ------------------------------------------------------------------

    @staticmethod
    def _render_prompt(task: Task, context: AdapterContext, cfg: dict) -> str:
        if context.prompt:
            return context.prompt
        template = str(cfg.get("prompt_template_text") or DEFAULT_PROMPT_TEMPLATE)
        return template.format(
            title=task.title or "(no title)",
            repo=task.repo or "(unknown repo)",
            acceptance="\n".join(f"- {c}" for c in task.acceptance_criteria) or "- (none specified)",
            allowed_scope=", ".join(cfg.get("allowed_files") or ["(repo root)"]),
            test_command=task.verification_command or cfg.get("test_command") or "(none)",
        )

    def _log_path(self, cfg: dict, run: Run) -> Path:
        explicit = cfg.get("run_log_dir")
        if explicit:
            base = Path(explicit)
        else:
            base = Path.cwd() / self.DEFAULT_RUN_LOG_SUBDIR
        return base / f"{run.id}.log"

    @staticmethod
    def _resolve_env(allowlist: list[str]) -> dict[str, str]:
        keys = set(allowlist) | {"PATH"}
        return {k: os.environ[k] for k in keys if k in os.environ}
