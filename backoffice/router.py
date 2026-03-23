"""Task router — assigns work to the best available backend.

Uses live health/limit checks and capability matching to decide which
backend should handle each task type, with automatic fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backoffice.backends.base import Backend, LimitState

logger = logging.getLogger(__name__)

TASK_TYPES: dict[str, dict[str, list[str]]] = {
    "prioritize_backlog": {
        "requires": ["long_context_reasoning"],
        "prefers": ["structured_output"],
    },
    "audit_repo": {
        "requires": ["read_files", "search_code", "run_shell"],
        "prefers": ["long_context_reasoning"],
    },
    "fix_finding": {
        "requires": ["read_files", "edit_files", "run_shell", "commit_changes"],
        "prefers": [],
    },
    "implement_feature": {
        "requires": ["read_files", "write_files", "edit_files", "run_shell", "commit_changes"],
        "prefers": ["subagents"],
    },
    "verify_changes": {
        "requires": ["run_shell"],
        "prefers": [],
    },
    "summarize_cycle": {
        "requires": ["structured_output"],
        "prefers": ["long_context_reasoning"],
    },
}


@dataclass
class Assignment:
    task_type: str
    assigned_backend: str
    fallback_backend: str | None
    reason: str
    limit_basis: dict
    confidence: str  # high | medium | low


class Router:
    """Routes tasks to backends based on capabilities and live health."""

    def __init__(self, backends: dict[str, Backend], policy: dict):
        self.backends = backends
        self.policy = policy
        self._limit_cache: dict[str, LimitState] = {}

    def refresh_limits(self) -> None:
        """Re-check health and limits for all backends."""
        self._limit_cache = {}
        for name, backend in self.backends.items():
            self._limit_cache[name] = backend.check_limits()
            logger.info(
                "Backend %s: status=%s, parallelism=%d",
                name,
                self._limit_cache[name].status,
                self._limit_cache[name].recommended_parallelism,
            )

    def _can_handle(self, backend_name: str, task_type: str) -> bool:
        """Check if a backend is available and has required capabilities."""
        if backend_name not in self.backends:
            return False
        limits = self._limit_cache.get(backend_name)
        if not limits or limits.status == "unavailable":
            return False
        caps = self.backends[backend_name].capabilities()
        reqs = TASK_TYPES.get(task_type, {}).get("requires", [])
        return all(getattr(caps, req, False) for req in reqs)

    def assign(self, task_type: str, context: dict | None = None) -> Assignment:
        """Pick the best backend for a task type, with fallback."""
        if not self._limit_cache:
            self.refresh_limits()

        # Determine preference order from policy
        preferred = self.policy.get(
            f"prefer_{task_type}",
            self.policy.get("fallback_order", {}).get(task_type, []),
        )
        if not preferred:
            preferred = list(self.backends.keys())

        for name in preferred:
            if self._can_handle(name, task_type):
                fallback = next(
                    (n for n in preferred if n != name and self._can_handle(n, task_type)),
                    None,
                )
                limits = self._limit_cache.get(
                    name, LimitState(backend=name, status="unknown")
                )
                return Assignment(
                    task_type=task_type,
                    assigned_backend=name,
                    fallback_backend=fallback,
                    reason=f"{name} healthy and capable for {task_type}",
                    limit_basis={
                        name: f"status={limits.status}, rate={limits.rate_limit_state}"
                    },
                    confidence="high" if limits.status == "healthy" else "medium",
                )

        return Assignment(
            task_type=task_type,
            assigned_backend="",
            fallback_backend=None,
            reason=f"No backend available for {task_type}",
            limit_basis={
                n: f"status={self._limit_cache.get(n, LimitState(backend=n, status='unknown')).status}"
                for n in self.backends
            },
            confidence="low",
        )
