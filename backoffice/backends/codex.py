"""Codex CLI backend adapter.

Wraps ``codex exec -`` (stdin-text mode) behind the common Backend interface.
"""
from __future__ import annotations

import shutil
import subprocess

from backoffice.backends.base import (
    Backend,
    Capabilities,
    HealthStatus,
    InvocationResult,
    LimitState,
)


class CodexBackend(Backend):
    name = "codex"

    def __init__(self, config: dict):
        self.command = config.get("command", "codex")
        self.model = config.get("model", "")
        self.mode = config.get("mode", "stdin-text")
        self.budget = config.get("local_budget", {}) or {}

    def health_check(self) -> HealthStatus:
        binary = self.command.split()[0] if self.command else "codex"
        if shutil.which(binary):
            return HealthStatus(
                backend=self.name, healthy=True, message=f"{binary} found on PATH"
            )
        return HealthStatus(
            backend=self.name, healthy=False, message=f"{binary} not found on PATH"
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(
            read_files=True,
            search_code=True,
            edit_files=True,
            write_files=True,
            run_shell=True,
            structured_output=True,
            multi_file_refactor=False,
            long_context_reasoning=False,
            subagents=False,
            commit_changes=True,
        )

    def check_limits(self) -> LimitState:
        health = self.health_check()
        return LimitState(
            backend=self.name,
            status="healthy" if health.healthy else "unavailable",
            supports_structured_output=True,
            context_window_tokens=self.budget.get("max_context_tokens", 150000),
            rate_limit_state="unknown",
            usage_state="unknown",
            recommended_parallelism=self.budget.get("max_parallel_tasks", 4),
            notes=["Usage state from local budget config, not live telemetry"],
        )

    def build_command(
        self, prompt: str, tools: list[str], repo_dir: str
    ) -> list[str]:
        parts = self.command.split()
        parts.extend([
            "-s", "workspace-write",
            "-a", "never",
            "exec", "-",
            "--cd", repo_dir,
            "--add-dir", repo_dir,
        ])
        return parts

    def invoke(
        self, prompt: str, tools: list[str], repo_dir: str
    ) -> InvocationResult:
        cmd = self.build_command(prompt, tools, repo_dir)
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=600,
            )
            return InvocationResult(
                success=result.returncode == 0,
                output=result.stdout,
                exit_code=result.returncode,
                backend=self.name,
                error=result.stderr,
            )
        except subprocess.TimeoutExpired:
            return InvocationResult(
                success=False,
                output="",
                exit_code=-1,
                backend=self.name,
                error="Timeout after 600s",
            )
        except Exception as e:
            return InvocationResult(
                success=False,
                output="",
                exit_code=-1,
                backend=self.name,
                error=str(e),
            )
