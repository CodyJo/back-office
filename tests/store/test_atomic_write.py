"""Tests for atomic write helpers and ``LockFile``."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
import yaml

from backoffice.store.atomic import (
    LockFile,
    append_jsonl_line,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    atomic_write_yaml,
    lock_path,
)


# ──────────────────────────────────────────────────────────────────────
# Round-trip and byte-level compatibility
# ──────────────────────────────────────────────────────────────────────


def test_atomic_write_bytes_creates_file_and_parent(tmp_path: Path):
    target = tmp_path / "deeper" / "out.bin"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_atomic_write_text_round_trip(tmp_path: Path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello\nworld\n")
    assert target.read_text() == "hello\nworld\n"


def test_atomic_write_json_matches_legacy_format(tmp_path: Path):
    """Bytes must match the legacy
    ``Path.write_text(json.dumps(p, indent=2, default=str) + "\\n")`` pattern."""
    payload = {"version": 1, "tasks": [{"id": "x", "n": 1}]}
    legacy = json.dumps(payload, indent=2, default=str) + "\n"

    target = tmp_path / "queue.json"
    atomic_write_json(target, payload)
    assert target.read_text() == legacy


def test_atomic_write_json_serializes_path_with_default_str(tmp_path: Path):
    target = tmp_path / "out.json"
    atomic_write_json(target, {"p": Path("/tmp/x")})
    payload = json.loads(target.read_text())
    assert payload["p"] == "/tmp/x"


def test_atomic_write_yaml_matches_legacy_format(tmp_path: Path):
    """Bytes must match ``yaml.safe_dump(payload, sort_keys=False)``."""
    payload = {"version": 1, "tasks": [{"id": "x", "n": 1}]}
    legacy = yaml.safe_dump(payload, sort_keys=False)

    target = tmp_path / "queue.yaml"
    atomic_write_yaml(target, payload)
    assert target.read_text() == legacy


# ──────────────────────────────────────────────────────────────────────
# Atomicity
# ──────────────────────────────────────────────────────────────────────


def test_atomic_write_does_not_leave_tempfile_on_success(tmp_path: Path):
    target = tmp_path / "out.json"
    atomic_write_json(target, {"x": 1})
    siblings = list(tmp_path.iterdir())
    # Only the destination, no leaked .tmp file.
    assert siblings == [target]


def test_atomic_write_cleans_up_tempfile_on_failure(monkeypatch, tmp_path: Path):
    """If os.replace fails, the tempfile must be removed."""
    target = tmp_path / "out.json"

    def _boom(_a, _b):
        raise OSError("simulated rename failure")

    monkeypatch.setattr("backoffice.store.atomic.os.replace", _boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        atomic_write_json(target, {"x": 1})

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_preserves_previous_content_on_failure(monkeypatch, tmp_path: Path):
    target = tmp_path / "out.json"
    atomic_write_json(target, {"version": 1})
    original_bytes = target.read_bytes()

    def _boom(_a, _b):
        raise OSError("simulated")

    monkeypatch.setattr("backoffice.store.atomic.os.replace", _boom)
    with pytest.raises(OSError):
        atomic_write_json(target, {"version": 2})

    assert target.read_bytes() == original_bytes


# ──────────────────────────────────────────────────────────────────────
# Concurrency: many concurrent atomic writes always leave valid bytes
# ──────────────────────────────────────────────────────────────────────


def test_concurrent_atomic_writes_always_yield_parseable_json(tmp_path: Path):
    """Many parallel writers, no shared lock, must never tear a write.

    ``os.replace`` is atomic at the kernel level, so every reader
    observes either the previous bytes or the next bytes — never a
    partial mix. We test the invariant by hammering from threads (the
    syscall releases the GIL) and reading concurrently.
    """
    target = tmp_path / "queue.json"
    atomic_write_json(target, {"version": 1, "writer": -1, "iter": -1})

    workers = 4
    iters_per_worker = 50
    stop_reader = threading.Event()
    reader_failures: list[str] = []

    def _hammer(idx: int) -> None:
        for i in range(iters_per_worker):
            atomic_write_json(target, {"version": 1, "writer": idx, "iter": i})

    def _read_loop() -> None:
        # Continuously parse the file. Any non-parseable observation is
        # a torn write and a test failure.
        while not stop_reader.is_set():
            try:
                payload = json.loads(target.read_text())
                assert payload.get("version") == 1
            except json.JSONDecodeError as exc:  # pragma: no cover
                reader_failures.append(str(exc))
                return
            except FileNotFoundError:  # pragma: no cover
                # Should not happen; os.replace is in-place.
                reader_failures.append("file disappeared")
                return

    reader = threading.Thread(target=_read_loop)
    reader.start()
    threads = [threading.Thread(target=_hammer, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop_reader.set()
    reader.join(timeout=2.0)

    assert reader_failures == [], reader_failures
    payload = json.loads(target.read_text())
    assert payload["version"] == 1
    assert 0 <= payload["writer"] < workers


# ──────────────────────────────────────────────────────────────────────
# append_jsonl_line
# ──────────────────────────────────────────────────────────────────────


def test_append_jsonl_creates_file_and_appends(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    append_jsonl_line(target, {"a": 1})
    append_jsonl_line(target, {"b": 2})
    lines = [json.loads(line) for line in target.read_text().splitlines()]
    assert lines == [{"a": 1}, {"b": 2}]


def test_append_jsonl_concurrent_keeps_all_lines(tmp_path: Path):
    """Two threads appending must not lose lines or interleave mid-line
    on payloads under PIPE_BUF. POSIX guarantees atomic O_APPEND writes
    below that threshold."""
    target = tmp_path / "events.jsonl"
    target.touch()

    def hammer(prefix: str) -> None:
        for i in range(200):
            append_jsonl_line(target, {"prefix": prefix, "i": i})

    t1 = threading.Thread(target=hammer, args=("a",))
    t2 = threading.Thread(target=hammer, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    lines = target.read_text().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert len(parsed) == 400
    assert sum(1 for p in parsed if p["prefix"] == "a") == 200
    assert sum(1 for p in parsed if p["prefix"] == "b") == 200


# ──────────────────────────────────────────────────────────────────────
# LockFile
# ──────────────────────────────────────────────────────────────────────


def test_lockfile_basic_acquire_release(tmp_path: Path):
    lock_file = tmp_path / "x.lock"
    with LockFile(lock_file):
        assert lock_file.exists()
    # Sidecar file is preserved on release; that's intentional.
    assert lock_file.exists()


def test_lockfile_non_blocking_raises_when_held(tmp_path: Path):
    """A second non-blocking holder must raise BlockingIOError."""
    lock_file = tmp_path / "x.lock"
    holder_acquired = threading.Event()
    holder_release = threading.Event()
    error_seen: list[BaseException] = []

    def _hold() -> None:
        try:
            with LockFile(lock_file):
                holder_acquired.set()
                holder_release.wait(5.0)
        except BaseException as exc:  # pragma: no cover - debugging only
            error_seen.append(exc)

    thread = threading.Thread(target=_hold)
    thread.start()
    try:
        assert holder_acquired.wait(2.0)
        with pytest.raises(BlockingIOError):
            with LockFile(lock_file, blocking=False):
                pass  # pragma: no cover - should never reach
    finally:
        holder_release.set()
        thread.join()

    assert error_seen == []


def test_lockfile_blocking_waits_for_holder(tmp_path: Path):
    """A blocking acquire must wait until the holder releases, then succeed."""
    lock_file = tmp_path / "x.lock"
    holder_release = threading.Event()
    second_acquired = threading.Event()

    def _holder() -> None:
        with LockFile(lock_file):
            holder_release.wait(5.0)

    def _waiter() -> None:
        with LockFile(lock_file, blocking=True):
            second_acquired.set()

    holder = threading.Thread(target=_holder)
    holder.start()
    # Give the holder time to acquire.
    time.sleep(0.05)

    waiter = threading.Thread(target=_waiter)
    waiter.start()
    # Waiter must not have made progress yet.
    assert not second_acquired.is_set()

    holder_release.set()
    holder.join()
    waiter.join(timeout=5.0)
    assert second_acquired.is_set()


def test_lock_path_helper_is_a_context_manager(tmp_path: Path):
    lock_file = tmp_path / "ctx.lock"
    with lock_path(lock_file) as held:
        assert isinstance(held, LockFile)


def test_lockfile_releases_on_inner_exception(tmp_path: Path):
    lock_file = tmp_path / "x.lock"
    with pytest.raises(RuntimeError):
        with LockFile(lock_file):
            raise RuntimeError("boom")
    # Lock must be free now.
    with LockFile(lock_file, blocking=False):
        pass


def test_lockfile_close_is_safe_if_never_entered(tmp_path: Path):
    lock = LockFile(tmp_path / "x.lock")
    lock.__exit__(None, None, None)


def test_lockfile_accepts_unusual_paths(tmp_path: Path):
    weird = tmp_path / "spaces and slashes.lock"
    with LockFile(weird):
        assert weird.exists()
    os.unlink(weird)
