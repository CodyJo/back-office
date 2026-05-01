"""Audit log rotation.

``results/audit-events.jsonl`` grows without bound. Production
deployments rotate it to ``results/audit-events-<ts>.jsonl`` once it
exceeds a configurable size threshold.

This module provides one entrypoint: :func:`maybe_rotate`. It is
safe to call from any path; the work is constant-time when no
rotation is needed.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB


def maybe_rotate(path: Path | str, *, max_bytes: int | None = None) -> Path | None:
    """Rotate *path* if it is larger than *max_bytes*.

    When *max_bytes* is ``None`` the module-level
    :data:`DEFAULT_MAX_BYTES` is read at call time, so tests can
    override it via ``monkeypatch``.
    """
    target = Path(path)
    if not target.exists():
        return None
    try:
        size = target.stat().st_size
    except OSError:
        return None
    threshold = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    if size <= threshold:
        return None

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rotated = target.with_name(f"{target.stem}-{ts}{target.suffix}")
    try:
        os.replace(target, rotated)
    except OSError as exc:
        logger.warning("audit rotation failed %s -> %s: %s", target, rotated, exc)
        return None
    logger.info("rotated audit log %s -> %s (%d bytes)", target.name, rotated.name, size)
    # Touch a fresh empty file so subsequent appends keep working.
    target.touch()
    return rotated
