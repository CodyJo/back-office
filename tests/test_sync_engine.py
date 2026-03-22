"""Tests for backoffice.sync.engine."""
import json
from pathlib import Path

import pytest

from backoffice.config import DashboardTarget
from backoffice.sync.engine import SyncEngine
from backoffice.sync.providers.base import CDNProvider, StorageProvider


class MemoryStorage(StorageProvider):
    def __init__(self):
        self.uploads = []

    def upload_file(self, bucket, local_path, remote_key, content_type, cache_control):
        self.uploads.append({"bucket": bucket, "local_path": local_path,
                            "remote_key": remote_key, "content_type": content_type})

    def upload_files(self, file_mappings):
        for m in file_mappings:
            self.upload_file(m["bucket"], m["local_path"], m["remote_key"],
                           m["content_type"], m["cache_control"])

    def sync_directory(self, bucket, local_dir, remote_prefix, delete=False):
        self.uploads.append({"sync": local_dir, "bucket": bucket, "prefix": remote_prefix})


class MemoryCDN(CDNProvider):
    def __init__(self):
        self.invalidations = []

    def invalidate(self, distribution_id, paths):
        self.invalidations.append({"dist": distribution_id, "paths": paths})


@pytest.fixture
def dashboard_dir(tmp_path):
    d = tmp_path / "dashboard"
    d.mkdir()
    (d / "index.html").write_text("<html>test</html>")
    (d / "qa.html").write_text("<html>qa</html>")
    (d / "qa-data.json").write_text('{"findings":[]}')
    (d / "data.json").write_text('{"findings":[]}')
    (d / "org-data.json").write_text('{}')
    (d / "automation-data.json").write_text('{}')
    (d / "regression-data.json").write_text('{}')
    (d / "local-audit-log.json").write_text('{}')
    (d / "local-audit-log.md").write_text('# log')
    (d / ".jobs.json").write_text('[]')
    (d / ".jobs-history.json").write_text('[]')
    return d


@pytest.fixture
def results_dir(tmp_path):
    r = tmp_path / "results"
    r.mkdir()
    repo = r / "demo"
    repo.mkdir()
    (repo / "findings.json").write_text('{"findings":[]}')
    (repo / "seo-findings.json").write_text('{"findings":[]}')
    return r


def test_dry_run_does_not_upload(dashboard_dir, results_dir):
    storage = MemoryStorage()
    cdn = MemoryCDN()
    target = DashboardTarget(bucket="test-bucket", subdomain="admin.test.com")
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run(dry_run=True)
    assert len(storage.uploads) == 0


def test_allow_public_read_false_skips_public_target(dashboard_dir, results_dir):
    target = DashboardTarget(
        bucket="www.example.com",
        subdomain="www.example.com",
        allow_public_read=False,
    )
    storage = MemoryStorage()
    cdn = MemoryCDN()
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run()
    assert len(storage.uploads) == 0


def test_admin_target_uploads_files(dashboard_dir, results_dir):
    target = DashboardTarget(
        bucket="admin-bucket",
        subdomain="admin.example.com",
        filter_repo=None,
    )
    storage = MemoryStorage()
    cdn = MemoryCDN()
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run()
    assert len(storage.uploads) > 0
    keys = [u["remote_key"] for u in storage.uploads if "remote_key" in u]
    # Should include HTML files
    assert any("index.html" in k for k in keys)
    # Should include aggregated data
    assert any("qa-data.json" in k for k in keys)
    # Should include shared metadata
    assert any("org-data.json" in k for k in keys)
    # Should include job status
    assert any(".jobs.json" in k for k in keys)


def test_per_repo_target_uses_findings(dashboard_dir, results_dir):
    target = DashboardTarget(
        bucket="admin-bucket",
        subdomain="admin.example.com",
        filter_repo="demo",
    )
    storage = MemoryStorage()
    cdn = MemoryCDN()
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run()
    # Should have uploaded files from results/demo/
    local_paths = [u["local_path"] for u in storage.uploads if "local_path" in u]
    assert any("results" in str(p) and "findings.json" in str(p) for p in local_paths)


def test_quick_sync_skips_html(dashboard_dir, results_dir):
    target = DashboardTarget(
        bucket="admin-bucket",
        subdomain="admin.example.com",
        filter_repo="demo",
    )
    storage = MemoryStorage()
    cdn = MemoryCDN()
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run(department="qa")
    keys = [u["remote_key"] for u in storage.uploads if "remote_key" in u]
    # Quick sync should NOT upload HTML
    assert not any("index.html" in k for k in keys)
    # But should upload dept data
    assert any("qa-data.json" in k for k in keys)
    # And shared files
    assert any("org-data.json" in k for k in keys)


def test_base_path_prefix(dashboard_dir, results_dir):
    target = DashboardTarget(
        bucket="www-bucket",
        subdomain="admin.example.com",
        base_path="back-office/dashboard",
        filter_repo=None,
    )
    storage = MemoryStorage()
    cdn = MemoryCDN()
    engine = SyncEngine(
        storage=storage, cdn=cdn,
        dashboard_dir=dashboard_dir, results_dir=results_dir,
        dashboard_targets=[target], skip_gate=True,
    )
    engine.run()
    keys = [u["remote_key"] for u in storage.uploads if "remote_key" in u]
    # All keys should be prefixed
    assert all(k.startswith("back-office/dashboard/") for k in keys)
