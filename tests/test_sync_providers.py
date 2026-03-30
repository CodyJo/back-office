"""Tests for backoffice.sync.providers."""
from __future__ import annotations

import pytest

from backoffice.sync.providers.base import CDNProvider, StorageProvider


def test_storage_provider_is_abstract():
    with pytest.raises(TypeError):
        StorageProvider()


def test_cdn_provider_is_abstract():
    with pytest.raises(TypeError):
        CDNProvider()


class FakeStorage(StorageProvider):
    def __init__(self):
        self.uploads = []

    def upload_file(self, bucket, local_path, remote_key, content_type, cache_control):
        self.uploads.append((bucket, local_path, remote_key, content_type))

    def upload_files(self, file_mappings):
        for m in file_mappings:
            self.upload_file(m["bucket"], m["local_path"], m["remote_key"],
                           m["content_type"], m["cache_control"])

    def sync_directory(self, bucket, local_dir, remote_prefix, delete=False):
        pass


class FakeCDN(CDNProvider):
    def __init__(self):
        self.invalidations = []

    def invalidate(self, distribution_id, paths):
        self.invalidations.append({"dist": distribution_id, "paths": paths})


def test_fake_storage_satisfies_interface():
    s = FakeStorage()
    s.upload_file("my-bucket", "/tmp/a.html", "a.html", "text/html", "no-cache")
    assert len(s.uploads) == 1


def test_fake_cdn_satisfies_interface():
    c = FakeCDN()
    c.invalidate("EXXXXX", ["/index.html"])
    assert len(c.invalidations) == 1
