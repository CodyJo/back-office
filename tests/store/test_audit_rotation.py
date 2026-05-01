"""Tests for production audit log rotation."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.audit_rotation import maybe_rotate
from backoffice.domain import AuditEvent
from backoffice.store import FileStore


def test_no_rotation_when_under_threshold(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    target.write_text("a\n")
    rotated = maybe_rotate(target, max_bytes=1024)
    assert rotated is None
    assert target.exists()


def test_rotation_when_over_threshold(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    target.write_text("x" * 1500)
    rotated = maybe_rotate(target, max_bytes=1024)
    assert rotated is not None
    assert rotated.exists()
    assert rotated != target
    # Original is touched-empty so subsequent writes still work.
    assert target.exists()
    assert target.read_text() == ""


def test_rotation_missing_file_returns_none(tmp_path: Path):
    assert maybe_rotate(tmp_path / "missing.jsonl") is None


def test_filestore_append_triggers_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """FileStore.append_audit_event rotates the log automatically."""
    store = FileStore(root=tmp_path)
    path = store.audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 200)

    # Patch DEFAULT_MAX_BYTES low so the next append rotates.
    import backoffice.audit_rotation as rot
    monkeypatch.setattr(rot, "DEFAULT_MAX_BYTES", 100)

    store.append_audit_event(
        AuditEvent(id="evt-1", action="x", subject_kind="task", subject_id="t")
    )

    rotated = list(path.parent.glob("audit-events-*.jsonl"))
    assert rotated, "expected the pre-existing audit log to rotate"
    contents = path.read_text().strip().splitlines()
    assert len(contents) == 1
