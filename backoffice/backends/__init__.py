"""Backend registry — loads configured backends, returns the right one.

Usage::

    from backoffice.backends import get_backend, get_all_backends

    claude = get_backend("claude", {"command": "claude", "model": "haiku"})
    all_backends = get_all_backends(config["agent_backends"])
"""
from __future__ import annotations

from backoffice.backends.claude import ClaudeBackend
from backoffice.backends.codex import CodexBackend

BACKEND_CLASSES: dict[str, type] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
}


def get_backend(name: str, config: dict) -> "ClaudeBackend | CodexBackend":
    """Return a single backend instance by name."""
    cls = BACKEND_CLASSES.get(name)
    if not cls:
        raise ValueError(f"Unknown backend: {name}")
    return cls(config)


def get_all_backends(backends_config: dict) -> dict[str, "ClaudeBackend | CodexBackend"]:
    """Return all enabled backends from the full backends config dict."""
    result = {}
    for name, cfg in backends_config.items():
        if cfg.get("enabled", True):
            result[name] = get_backend(name, cfg)
    return result
