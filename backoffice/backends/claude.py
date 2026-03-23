"""Claude CLI backend adapter.

Wraps ``claude --print`` invocations behind the common Backend interface.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from backoffice.backends.base import (
    Backend,
    Capabilities,
    HealthStatus,
    InvocationResult,
    LimitState,
)


class ClaudeBackend(Backend):
    name = "claude"

    def __init__(self, config: dict):
        self.command = config.get("command", "claude")
        self.model = config.get("model", "haiku")
        self.mode = config.get("mode", "claude-print")
        self.budget = config.get("local_budget", {}) or {}

    def health_check(self) -> HealthStatus:
        binary = self.command.split()[0] if self.command else "claude"
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
            multi_file_refactor=True,
            long_context_reasoning=True,
            subagents=True,
            commit_changes=True,
        )

    def check_limits(self) -> LimitState:
        health = self.health_check()
        return LimitState(
            backend=self.name,
            status="healthy" if health.healthy else "unavailable",
            supports_structured_output=True,
            context_window_tokens=self.budget.get("max_context_tokens", 200000),
            rate_limit_state="unknown",  # Claude CLI doesn't expose this
            usage_state="unknown",
            recommended_parallelism=self.budget.get("max_parallel_tasks", 2),
            notes=["Usage state from local budget config, not live telemetry"],
        )

    def build_command(
        self, prompt: str, tools: list[str], repo_dir: str
    ) -> list[str]:
        parts = self.command.split()
        if self.model and "--model" not in self.command:
            parts.extend(["--model", self.model])
        parts.append("--print")
        if tools:
            parts.extend(["--allowedTools", ",".join(tools)])
        parts.extend(["--add-dir", repo_dir])
        return parts

    def invoke(
        self, prompt: str, tools: list[str], repo_dir: str
    ) -> InvocationResult:
        cmd = self.build_command(prompt, tools, repo_dir)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                env=env,
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
