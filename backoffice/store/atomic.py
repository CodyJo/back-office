"""Atomic file writes and POSIX file locks.

These helpers exist so the rest of Back Office can stop hand-rolling
``open(path, 'w')`` with no crash safety. The contract is small but
strict:

* **No torn writes.** Every helper writes to a sibling temporary file
  in the destination directory, ``fsync``-es it, then ``os.replace``-es
  it onto the target path. Readers either see the prior bytes or the
  new bytes; never a partial mix.
* **Byte-compatible output.** ``atomic_write_json`` and
  ``atomic_write_yaml`` produce the same bytes as the legacy
  ``Path.write_text(json.dumps(..., indent=2, default=str) + "\n")``
  and ``yaml.safe_dump(payload, fh, sort_keys=False)`` patterns
  scattered through ``backoffice/``. Drop-in replacement.
* **Locks scoped to a sidecar file.** ``LockFile`` opens
  ``<path>.lock`` (creating it if needed) and calls ``fcntl.flock``.
  This avoids holding a lock on the data file itself, which is
  important because we ``os.replace`` over the data file.

Phase 2 introduces these helpers without removing any existing writer.
Selected call sites (e.g. ``backoffice.tasks.save_payload``) are
re-routed in the same phase to gain crash-safety; the helpers remain
generally useful.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml

# ──────────────────────────────────────────────────────────────────────
# Atomic write primitives
# ──────────────────────────────────────────────────────────────────────


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Replace *path* with *data* atomically.

    Strategy: write to a tempfile in the same directory (so
    ``os.replace`` can rename across the same filesystem), ``fsync`` the
    tempfile, ``os.replace`` it onto the destination, then ``fsync`` the
    parent directory so the rename hits stable storage.

    The parent directory is created if it does not exist.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.",
        suffix=".tmp",
        dir=str(dest.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        # Best-effort cleanup; never mask the original exception.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise

    # Fsync the parent dir so the rename is durable.
    try:
        dir_fd = os.open(str(dest.parent), os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Atomic-write a text payload."""
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int = 2,
    ensure_trailing_newline: bool = True,
    sort_keys: bool = False,
    default: Any = str,
) -> None:
    """Atomic-write *payload* as pretty-printed JSON.

    Defaults match the legacy
    ``json.dumps(payload, indent=2, default=str) + "\\n"`` pattern so
    callers can swap in this helper without changing on-disk bytes.
    """
    text = json.dumps(payload, indent=indent, sort_keys=sort_keys, default=default)
    if ensure_trailing_newline and not text.endswith("\n"):
        text += "\n"
    atomic_write_text(path, text)


def atomic_write_yaml(
    path: Path | str,
    payload: Any,
    *,
    sort_keys: bool = False,
) -> None:
    """Atomic-write *payload* as YAML.

    Defaults match ``yaml.safe_dump(payload, handle, sort_keys=False)``.
    """
    text = yaml.safe_dump(payload, sort_keys=sort_keys)
    atomic_write_text(path, text)


def append_jsonl_line(path: Path | str, payload: Any, *, default: Any = str) -> None:
    """Append one JSON-encoded line to *path*.

    Uses ``O_APPEND`` for atomicity of the append itself. A torn append
    is impossible on POSIX for writes smaller than ``PIPE_BUF`` (4096
    bytes); for larger payloads readers may observe partial lines.
    Most audit/ledger entries are well under that limit.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, default=default) + "\n"
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


# ──────────────────────────────────────────────────────────────────────
# File locks
# ──────────────────────────────────────────────────────────────────────


class LockFile:
    """A POSIX advisory lock backed by a sidecar file.

    Use as a context manager::

        with LockFile(results_dir / ".queue.lock"):
            # critical section: read-modify-write a queue file
            ...

    * ``exclusive`` (default ``True``) acquires ``LOCK_EX``; ``False``
      acquires ``LOCK_SH``.
    * ``blocking`` (default ``True``) waits for the lock; ``False``
      raises :class:`BlockingIOError` immediately if the lock is held.

    The sidecar file is created on demand and intentionally not
    deleted on release — multiple holders should agree on one path,
    and unlinking would race.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        exclusive: bool = True,
        blocking: bool = True,
    ) -> None:
        self.path = Path(path)
        self.exclusive = exclusive
        self.blocking = blocking
        self._fd: int | None = None

    def __enter__(self) -> "LockFile":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        op = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        if not self.blocking:
            op |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, op)
        except BlockingIOError:
            os.close(fd)
            raise
        except OSError as exc:
            os.close(fd)
            # On some platforms LOCK_NB returns EWOULDBLOCK as a generic
            # OSError. Re-raise as BlockingIOError for caller clarity.
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise BlockingIOError(exc.errno, exc.strerror, str(self.path)) from exc
            raise
        self._fd = fd
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def lock_path(
    path: Path | str,
    *,
    exclusive: bool = True,
    blocking: bool = True,
) -> Iterator[LockFile]:
    """Convenience wrapper: ``with lock_path(p): ...``."""
    lock = LockFile(path, exclusive=exclusive, blocking=blocking)
    with lock as held:
        yield held
