"""Adapter contract + built-in adapters.

Phase 4 introduces the :class:`Adapter` protocol and the first three
implementations:

* :class:`backoffice.adapters.noop.NoopAdapter` — deterministic test fake.
* :class:`backoffice.adapters.process.ProcessAdapter` — runs a configured
  shell command with timeout + env allowlist; today's ``agents/*.sh``
  flow through here.
* :class:`backoffice.adapters.legacy_backend.LegacyBackendAdapter` — wraps
  ``backoffice.backends.Backend`` so the existing claude/codex routing
  continues to work while the agent registry comes online.

Phase 5 adds the Claude Code adapter on top of this contract.

See ``docs/architecture/target-state.md`` §4.
"""
from backoffice.adapters.base import (
    Adapter,
    AdapterCancelResult,
    AdapterContext,
    AdapterHandle,
    AdapterStatus,
    InvocationDenied,
)
from backoffice.adapters.claude_code import ClaudeCodeAdapter
from backoffice.adapters.legacy_backend import LegacyBackendAdapter
from backoffice.adapters.noop import NoopAdapter
from backoffice.adapters.process import ProcessAdapter

__all__ = [
    "Adapter",
    "AdapterCancelResult",
    "AdapterContext",
    "AdapterHandle",
    "AdapterStatus",
    "ClaudeCodeAdapter",
    "InvocationDenied",
    "LegacyBackendAdapter",
    "NoopAdapter",
    "ProcessAdapter",
    "registry",
]


# Adapter type → factory mapping. Plugins (Phase 12) extend this.
_REGISTRY: dict[str, type[Adapter]] = {}


def register(adapter_type: str, factory: type[Adapter]) -> None:
    """Register an adapter class under *adapter_type*."""
    _REGISTRY[adapter_type] = factory


def get(adapter_type: str) -> type[Adapter] | None:
    return _REGISTRY.get(adapter_type)


def registry() -> dict[str, type[Adapter]]:
    """Return a snapshot of the adapter registry."""
    return dict(_REGISTRY)


# Built-in registrations
register("noop", NoopAdapter)
register("process", ProcessAdapter)
register("legacy_backend", LegacyBackendAdapter)
register("claude_code", ClaudeCodeAdapter)
