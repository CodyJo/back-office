"""Tests for BunnyStorage provider."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

from backoffice.sync.providers.bunny import BunnyStorage
from backoffice.sync.providers.base import StorageProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_storage(zone="my-zone", region="ny", key="test-key"):
    return BunnyStorage(storage_zone=zone, storage_region=region, access_key=key)


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------

def test_bunny_storage_is_storage_provider():
    s = _make_storage()
    assert isinstance(s, StorageProvider)


# ---------------------------------------------------------------------------
# upload_file — happy path
# ---------------------------------------------------------------------------

def test_upload_file_sends_put_request(tmp_path):
    """upload_file should issue an HTTP PUT to the correct BunnyCDN URL."""
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html></html>")

    responses = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    captured = []

    def fake_urlopen(request):
        captured.append(request)
        return FakeResponse()

    import urllib.request
    with patch.object(urllib.request, "urlopen", fake_urlopen):
        s = _make_storage(zone="myzone", region="la", key="secret")
        s.upload_file("ignored-bucket", str(local_file), "subdir/index.html",
                      "text/html", "no-cache")

    assert len(captured) == 1
    req = captured[0]
    assert req.get_method() == "PUT"
    assert req.full_url == "https://la.storage.bunnycdn.com/myzone/subdir/index.html"


def test_upload_file_sets_access_key_header(tmp_path):
    """upload_file must include the AccessKey header with the configured key."""
    local_file = tmp_path / "style.css"
    local_file.write_bytes(b"body{}")

    captured = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (captured.append(req), FakeResponse())[1]):
        s = _make_storage(key="my-secret-key")
        s.upload_file("bucket", str(local_file), "style.css", "text/css", "max-age=3600")

    req = captured[0]
    assert req.get_header("Accesskey") == "my-secret-key"


def test_upload_file_sets_content_type_header(tmp_path):
    """upload_file must pass the content_type as Content-Type header."""
    local_file = tmp_path / "data.json"
    local_file.write_bytes(b"{}")

    captured = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (captured.append(req), FakeResponse())[1]):
        s = _make_storage()
        s.upload_file("bucket", str(local_file), "data.json", "application/json", "no-cache")

    req = captured[0]
    assert req.get_header("Content-type") == "application/json"


def test_upload_file_bucket_param_ignored(tmp_path):
    """The bucket parameter is accepted for interface compatibility but ignored."""
    local_file = tmp_path / "file.txt"
    local_file.write_bytes(b"hello")

    captured = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (captured.append(req), FakeResponse())[1]):
        s = _make_storage(zone="correct-zone", region="de")
        s.upload_file("wrong-bucket-should-be-ignored", str(local_file), "file.txt",
                      "text/plain", "no-cache")

    assert "correct-zone" in captured[0].full_url
    assert "wrong-bucket-should-be-ignored" not in captured[0].full_url


# ---------------------------------------------------------------------------
# upload_file — env var fallback
# ---------------------------------------------------------------------------

def test_upload_file_uses_env_var_when_access_key_is_none(tmp_path, monkeypatch):
    """When access_key=None, BunnyStorage must fall back to BUNNY_STORAGE_KEY env var."""
    monkeypatch.setenv("BUNNY_STORAGE_KEY", "env-secret")

    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html></html>")

    captured = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (captured.append(req), FakeResponse())[1]):
        s = BunnyStorage(storage_zone="zone", storage_region="ny", access_key=None)
        s.upload_file("bucket", str(local_file), "index.html", "text/html", "no-cache")

    assert captured[0].get_header("Accesskey") == "env-secret"


def test_init_raises_when_no_key_and_no_env_var(monkeypatch):
    """BunnyStorage must raise ValueError at construction when no key is available."""
    monkeypatch.delenv("BUNNY_STORAGE_KEY", raising=False)
    with pytest.raises(ValueError, match="BUNNY_STORAGE_KEY"):
        BunnyStorage(storage_zone="zone", storage_region="ny", access_key=None)


# ---------------------------------------------------------------------------
# upload_files
# ---------------------------------------------------------------------------

def test_upload_files_iterates_all_mappings(tmp_path):
    """upload_files should call upload_file for each mapping in the list."""
    f1 = tmp_path / "a.html"
    f2 = tmp_path / "b.json"
    f1.write_bytes(b"<html></html>")
    f2.write_bytes(b"{}")

    upload_calls = []

    s = _make_storage()
    original_upload = s.upload_file

    def recording_upload(bucket, local_path, remote_key, content_type, cache_control):
        upload_calls.append((bucket, local_path, remote_key, content_type, cache_control))

    s.upload_file = recording_upload

    mappings = [
        {"bucket": "b", "local_path": str(f1), "remote_key": "a.html",
         "content_type": "text/html", "cache_control": "no-cache"},
        {"bucket": "b", "local_path": str(f2), "remote_key": "b.json",
         "content_type": "application/json", "cache_control": "no-cache"},
    ]
    s.upload_files(mappings)

    assert len(upload_calls) == 2
    assert upload_calls[0][2] == "a.html"
    assert upload_calls[1][2] == "b.json"


def test_upload_files_empty_list_is_noop():
    """upload_files with an empty list should not raise or call upload_file."""
    s = _make_storage()
    called = []
    s.upload_file = lambda *a, **kw: called.append(a)
    s.upload_files([])
    assert called == []


# ---------------------------------------------------------------------------
# sync_directory
# ---------------------------------------------------------------------------

def test_sync_directory_uploads_all_files(tmp_path):
    """sync_directory should recursively walk and upload every file found."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "index.html").write_bytes(b"<html></html>")
    (tmp_path / "sub" / "data.json").write_bytes(b"{}")

    upload_calls = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (upload_calls.append(req), FakeResponse())[1]):
        s = _make_storage(zone="myzone", region="ny")
        s.sync_directory("ignored-bucket", str(tmp_path), "prefix/")

    uploaded_urls = {r.full_url for r in upload_calls}
    assert any("index.html" in u for u in uploaded_urls)
    assert any("data.json" in u for u in uploaded_urls)
    assert len(upload_calls) == 2


def test_sync_directory_uses_remote_prefix(tmp_path):
    """Files uploaded via sync_directory should be prefixed with remote_prefix."""
    (tmp_path / "page.html").write_bytes(b"hi")

    captured = []

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    import urllib.request
    with patch.object(urllib.request, "urlopen", lambda req: (captured.append(req), FakeResponse())[1]):
        s = _make_storage(zone="z", region="sg")
        s.sync_directory("b", str(tmp_path), "myprefix")

    assert any("myprefix" in r.full_url for r in captured)


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

def test_upload_file_retries_on_failure(tmp_path):
    """upload_file should retry up to MAX_RETRIES times on transient errors."""
    local_file = tmp_path / "retry.html"
    local_file.write_bytes(b"content")

    attempt_count = [0]

    class FakeResponse:
        status = 201
        def read(self):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def flaky_urlopen(req):
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise OSError("connection reset")
        return FakeResponse()

    import urllib.request
    with patch.object(urllib.request, "urlopen", flaky_urlopen):
        with patch("time.sleep"):  # speed up test
            s = _make_storage()
            s.upload_file("bucket", str(local_file), "retry.html", "text/html", "no-cache")

    assert attempt_count[0] == 3


def test_upload_file_raises_after_max_retries(tmp_path):
    """upload_file should re-raise the last exception after exhausting retries."""
    local_file = tmp_path / "fail.html"
    local_file.write_bytes(b"content")

    import urllib.request
    with patch.object(urllib.request, "urlopen", side_effect=OSError("always fails")):
        with patch("time.sleep"):
            s = _make_storage()
            with pytest.raises(OSError, match="always fails"):
                s.upload_file("bucket", str(local_file), "fail.html", "text/html", "no-cache")
