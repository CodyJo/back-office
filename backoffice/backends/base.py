"""Abstract backend interface and shared data structures.

Every AI backend (Claude, Codex, etc.) implements the Backend ABC so the
orchestrator can health-check, capability-match, and invoke them uniformly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class HealthStatus:
    backend: str
    healthy: bool
    message: str = ""


@dataclass
class Capabilities:
    read_files: bool = False
    search_code: bool = False
    edit_files: bool = False
    write_files: bool = False
    run_shell: bool = False
    structured_output: bool = False
    multi_file_refactor: bool = False
    long_context_reasoning: bool = False
    subagents: bool = False
    commit_changes: bool = False


@dataclass
class LimitState:
    backend: str
    status: str  # healthy | degraded | unavailable
    supports_structured_output: bool = False
    context_window_tokens: int = 0
    rate_limit_state: str = "unknown"  # ok | near_limit | limited | unknown
    usage_state: str = "unknown"  # ok | near_plan_limit | limited | unknown
    recommended_parallelism: int = 1
    notes: list[str] = field(default_factory=list)


@dataclass
class InvocationResult:
    success: bool
    output: str
    exit_code: int = 0
    backend: str = ""
    error: str = ""


class Backend(ABC):
    """Abstract base for all AI backends."""

    name: str

    @abstractmethod
    def health_check(self) -> HealthStatus: ...

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def check_limits(self) -> LimitState: ...

    @abstractmethod
    def build_command(self, prompt: str, tools: list[str], repo_dir: str) -> list[str]: ...

    @abstractmethod
    def invoke(self, prompt: str, tools: list[str], repo_dir: str) -> InvocationResult: ...
