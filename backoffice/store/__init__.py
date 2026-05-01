"""Storage layer for Back Office.

Phase 2 introduces this layer without removing legacy direct-write
paths. Existing modules continue to work unchanged; new code paths and
the migrated ``backoffice.tasks.save_payload`` route through these
helpers for crash safety.

See ``docs/architecture/phased-roadmap.md`` Phase 2.
"""
from pathlib import Path

from backoffice.store.atomic import (
    LockFile,
    append_jsonl_line,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    atomic_write_yaml,
    lock_path,
)
from backoffice.store.base import (
    CHECKOUT_REASON_ALREADY_RUNNING,
    CHECKOUT_REASON_TASK_NOT_FOUND,
    CHECKOUT_REASON_WRONG_STATE,
    CheckoutConflict,
    CheckoutResult,
    Store,
    TaskNotFound,
    TaskQueueState,
)
from backoffice.store.file_store import FileStore


def get_store(root: Path | str | None = None) -> Store:
    """Return the default Back Office store.

    Currently always a :class:`FileStore`. Later phases may switch on
    a config flag to return a SQLite or Postgres-backed store.
    """
    return FileStore(root=root)


__all__ = [
    "CHECKOUT_REASON_ALREADY_RUNNING",
    "CHECKOUT_REASON_TASK_NOT_FOUND",
    "CHECKOUT_REASON_WRONG_STATE",
    "CheckoutConflict",
    "CheckoutResult",
    "FileStore",
    "LockFile",
    "Store",
    "TaskNotFound",
    "TaskQueueState",
    "append_jsonl_line",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "atomic_write_yaml",
    "get_store",
    "lock_path",
]
