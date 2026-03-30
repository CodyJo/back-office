# AWS to Bunny Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all AWS infrastructure (S3, CloudFront, CodeBuild, Terraform) with Bunny.net equivalents (Storage Zones, Pull Zones, Magic Containers) using DustBunny CLI as the management tool.

**Architecture:** New `BunnyStorage` and `BunnyCDN` providers implement the existing `StorageProvider`/`CDNProvider` abstractions. Storage uploads use `urllib.request` HTTP PUT. CDN purge shells out to `dustbunny pz purge`. Config switches from `deploy.aws` to `deploy.bunny`. A Fastify webhook container on Magic Containers replaces CodeBuild CI/CD.

**Tech Stack:** Python 3.12, urllib.request (stdlib), DustBunny CLI (Node.js), Fastify, Docker

**Spec:** `docs/superpowers/specs/2026-03-29-aws-to-bunny-migration-design.md`

---

## Parallelization Map

Tasks 1 and 3 are independent and SHOULD be run in parallel.
Task 2 depends on Task 1 (appends to same files).
Task 4 depends on Tasks 2 + 3.
Task 5 depends on Task 4.
Task 6 depends on Task 5.

```
 Task 1 (BunnyStorage) ── Task 2 (BunnyCDN) ──┐
                                                ├── Task 4 (Config + factory + engine) ── Task 5 (Teardown) ── Task 6 (Docs)
 Task 3 (CI webhook server) ──────────────────┘
```

---

## Chunk 1: Provider Layer

### Task 1: BunnyStorage Provider

**Files:**
- Create: `backoffice/sync/providers/bunny.py`
- Test: `tests/test_bunny_provider.py`
- Reference: `backoffice/sync/providers/base.py` (StorageProvider interface)
- Reference: `backoffice/sync/providers/aws.py` (pattern to follow for retry logic)

- [ ] **Step 1: Write failing tests for BunnyStorage**

Create `tests/test_bunny_provider.py` with tests for all three StorageProvider methods:

```python
"""Tests for Bunny storage and CDN providers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from backoffice.sync.providers.bunny import BunnyStorage


class TestBunnyStorageUploadFile:
    """Test BunnyStorage.upload_file()."""

    @patch("backoffice.sync.providers.bunny.urlopen")
    def test_upload_sends_put_with_access_key(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(b"<h1>Dashboard</h1>")
            f.flush()
            local_path = f.name

        try:
            storage = BunnyStorage(
                storage_zone="admin-codyjo",
                storage_region="ny",
                access_key="test-key-123",
            )
            storage.upload_file(
                bucket="admin-codyjo",
                local_path=local_path,
                remote_key="dashboard/index.html",
                content_type="text/html",
                cache_control="no-cache",
            )

            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert req.method == "PUT"
            assert "ny.storage.bunnycdn.com" in req.full_url
            assert "/admin-codyjo/dashboard/index.html" in req.full_url
            assert req.get_header("Accesskey") == "test-key-123"
            assert req.get_header("Content-type") == "text/html"
        finally:
            os.unlink(local_path)

    @patch("backoffice.sync.providers.bunny.urlopen")
    def test_upload_file_reads_file_content(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b'{"score": 95}')
            f.flush()
            local_path = f.name

        try:
            storage = BunnyStorage(
                storage_zone="admin-codyjo",
                storage_region="ny",
                access_key="test-key",
            )
            storage.upload_file(
                bucket="admin-codyjo",
                local_path=local_path,
                remote_key="data.json",
                content_type="application/json",
                cache_control="no-cache",
            )

            req = mock_urlopen.call_args[0][0]
            assert req.data == b'{"score": 95}'
        finally:
            os.unlink(local_path)


class TestBunnyStorageUploadFiles:
    """Test BunnyStorage.upload_files()."""

    @patch("backoffice.sync.providers.bunny.urlopen")
    def test_upload_files_iterates_mappings(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(b"<h1>test</h1>")
            f.flush()
            path1 = f.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"{}")
            f.flush()
            path2 = f.name

        try:
            storage = BunnyStorage(
                storage_zone="zone",
                storage_region="ny",
                access_key="key",
            )
            storage.upload_files([
                {
                    "bucket": "zone",
                    "local_path": path1,
                    "remote_key": "a.html",
                    "content_type": "text/html",
                    "cache_control": "no-cache",
                },
                {
                    "bucket": "zone",
                    "local_path": path2,
                    "remote_key": "b.json",
                    "content_type": "application/json",
                    "cache_control": "no-cache",
                },
            ])

            assert mock_urlopen.call_count == 2
        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestBunnyStorageSyncDirectory:
    """Test BunnyStorage.sync_directory()."""

    @patch("backoffice.sync.providers.bunny.urlopen")
    def test_sync_directory_uploads_all_files(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.json").write_text('{"a": 1}')
            (Path(tmpdir) / "sub").mkdir()
            (Path(tmpdir) / "sub" / "b.json").write_text('{"b": 2}')

            storage = BunnyStorage(
                storage_zone="zone",
                storage_region="ny",
                access_key="key",
            )
            storage.sync_directory(
                bucket="zone",
                local_dir=tmpdir,
                remote_prefix="results/regression",
                delete=False,
            )

            assert mock_urlopen.call_count == 2
            urls = [mock_urlopen.call_args_list[i][0][0].full_url for i in range(2)]
            url_str = " ".join(urls)
            assert "results/regression/a.json" in url_str
            assert "results/regression/sub/b.json" in url_str


class TestBunnyStorageAccessKeyFromEnv:
    """Test that access key falls back to BUNNY_STORAGE_KEY env var."""

    @patch("backoffice.sync.providers.bunny.urlopen")
    @patch.dict(os.environ, {"BUNNY_STORAGE_KEY": "env-key-456"})
    def test_uses_env_var_when_no_key_provided(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(b"test")
            f.flush()
            local_path = f.name

        try:
            storage = BunnyStorage(
                storage_zone="zone",
                storage_region="ny",
                access_key=None,
            )
            storage.upload_file(
                bucket="zone",
                local_path=local_path,
                remote_key="test.html",
                content_type="text/html",
                cache_control="no-cache",
            )

            req = mock_urlopen.call_args[0][0]
            assert req.get_header("Accesskey") == "env-key-456"
        finally:
            os.unlink(local_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bunny_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backoffice.sync.providers.bunny'`

- [ ] **Step 3: Implement BunnyStorage**

Create `backoffice/sync/providers/bunny.py`:

```python
"""Bunny.net Storage Zone + Pull Zone (CDN) provider implementation."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from backoffice.sync.providers.base import CDNProvider, StorageProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 1


def _retry(fn, *args, **kwargs):
    """Retry fn up to MAX_RETRIES times with exponential backoff."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("Retry %d/%d after %.1fs: %s",
                             attempt + 1, MAX_RETRIES, wait, exc)
                time.sleep(wait)
    raise last_exc


class BunnyStorage(StorageProvider):
    """Upload files to a Bunny.net Storage Zone via HTTP PUT."""

    def __init__(self, storage_zone: str, storage_region: str,
                 access_key: str | None = None) -> None:
        self._zone = storage_zone
        self._region = storage_region
        self._access_key = access_key or os.environ.get("BUNNY_STORAGE_KEY", "")

    def upload_file(self, bucket: str, local_path: str, remote_key: str,
                    content_type: str, cache_control: str) -> None:
        data = Path(local_path).read_bytes()
        url = f"https://{self._region}.storage.bunnycdn.com/{self._zone}/{remote_key}"
        req = Request(url, data=data, method="PUT")
        req.add_header("AccessKey", self._access_key)
        req.add_header("Content-Type", content_type)

        def _do_upload():
            with urlopen(req):
                pass

        _retry(_do_upload)
        logger.info("Uploaded %s -> bunny://%s/%s",
                    Path(local_path).name, self._zone, remote_key)

    def upload_files(self, file_mappings: list[dict]) -> None:
        for m in file_mappings:
            self.upload_file(
                m["bucket"], m["local_path"], m["remote_key"],
                m["content_type"], m["cache_control"],
            )

    def sync_directory(self, bucket: str, local_dir: str,
                       remote_prefix: str, delete: bool = False) -> None:
        local = Path(local_dir)
        for file_path in sorted(local.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(local)
            remote_key = f"{remote_prefix}/{relative}" if remote_prefix else str(relative)
            self.upload_file(
                bucket=bucket,
                local_path=str(file_path),
                remote_key=remote_key,
                content_type="application/json",
                cache_control="no-cache, no-store, must-revalidate",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bunny_provider.py::TestBunnyStorageUploadFile -v && python -m pytest tests/test_bunny_provider.py::TestBunnyStorageUploadFiles -v && python -m pytest tests/test_bunny_provider.py::TestBunnyStorageSyncDirectory -v && python -m pytest tests/test_bunny_provider.py::TestBunnyStorageAccessKeyFromEnv -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backoffice/sync/providers/bunny.py tests/test_bunny_provider.py
git commit -m "feat: add BunnyStorage provider with tests

HTTP PUT uploads to Bunny Storage Zone via urllib.request.
Implements StorageProvider interface (upload_file, upload_files,
sync_directory). Access key from config or BUNNY_STORAGE_KEY env var."
```

---

### Task 2: BunnyCDN Provider

**Files:**
- Modify: `backoffice/sync/providers/bunny.py` (add BunnyCDN class)
- Test: `tests/test_bunny_provider.py` (add BunnyCDN tests)
- Reference: `backoffice/sync/providers/base.py:22-24` (CDNProvider interface)

- [ ] **Step 1: Write failing tests for BunnyCDN**

Append to `tests/test_bunny_provider.py`:

```python
from backoffice.sync.providers.bunny import BunnyCDN


class TestBunnyCDNInvalidate:
    """Test BunnyCDN.invalidate() shells out to dustbunny."""

    @patch("backoffice.sync.providers.bunny.subprocess.run")
    def test_invalidate_calls_dustbunny_pz_purge(self, mock_run):
        cdn = BunnyCDN(dustbunny_bin="/usr/local/bin/dustbunny")
        cdn.invalidate("123456", ["/*"])

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["/usr/local/bin/dustbunny", "pz", "purge", "123456"]

    @patch("backoffice.sync.providers.bunny.subprocess.run")
    def test_invalidate_ignores_paths(self, mock_run):
        """Bunny purge is zone-wide; paths param is accepted but ignored."""
        cdn = BunnyCDN(dustbunny_bin="dustbunny")
        cdn.invalidate("789", ["/foo/*", "/bar/*"])

        cmd = mock_run.call_args[0][0]
        # Only pull zone ID, no path args
        assert cmd == ["dustbunny", "pz", "purge", "789"]

    @patch("backoffice.sync.providers.bunny.subprocess.run")
    def test_invalidate_skips_empty_distribution_id(self, mock_run):
        cdn = BunnyCDN(dustbunny_bin="dustbunny")
        cdn.invalidate("", ["/*"])

        mock_run.assert_not_called()

    @patch("backoffice.sync.providers.bunny.subprocess.run")
    def test_invalidate_uses_default_dustbunny_path(self, mock_run):
        cdn = BunnyCDN()
        cdn.invalidate("999", ["/*"])

        cmd = mock_run.call_args[0][0]
        assert "dustbunny" in cmd[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bunny_provider.py::TestBunnyCDNInvalidate -v`
Expected: FAIL with `ImportError: cannot import name 'BunnyCDN'`

- [ ] **Step 3: Implement BunnyCDN**

Append to `backoffice/sync/providers/bunny.py` (add `import subprocess` near top):

```python
import subprocess


class BunnyCDN(CDNProvider):
    """Purge Bunny Pull Zone cache via DustBunny CLI."""

    def __init__(self, dustbunny_bin: str | None = None) -> None:
        self._bin = dustbunny_bin or os.environ.get(
            "DUSTBUNNY_BIN",
            str(Path.home() / "projects" / "dustbunny" / "bin" / "dustbunny.mjs"),
        )

    def invalidate(self, distribution_id: str, paths: list[str]) -> None:
        if not distribution_id:
            return
        pull_zone_id = distribution_id  # semantic mapping
        cmd = [self._bin, "pz", "purge", pull_zone_id]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Purged Pull Zone %s", pull_zone_id)
        except Exception as exc:
            logger.warning("Pull Zone purge failed for %s: %s",
                         pull_zone_id, exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bunny_provider.py::TestBunnyCDNInvalidate -v`
Expected: All PASS

- [ ] **Step 5: Run full provider test suite**

Run: `python -m pytest tests/test_bunny_provider.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backoffice/sync/providers/bunny.py tests/test_bunny_provider.py
git commit -m "feat: add BunnyCDN provider with tests

Shells out to dustbunny pz purge for cache invalidation.
Implements CDNProvider interface. Paths param ignored since
Bunny purge is zone-wide and free."
```

---

## Chunk 2: CI Webhook Server

### Task 3: CI/CD Magic Container Webhook Server

**Files:**
- Create: `ci/package.json`
- Create: `ci/server.mjs`
- Create: `ci/Dockerfile`
- Create: `ci/pipeline.mjs`
- Create: `ci/.env.example`
- Create: `ci/server.test.mjs`
- Reference: `buildspec-ci.yml` (current CI steps to replicate)
- Reference: `buildspec-cd.yml` (current CD steps to replicate)

- [ ] **Step 1: Create ci/package.json**

```json
{
  "name": "back-office-ci",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "engines": { "node": ">=18" },
  "scripts": {
    "start": "node server.mjs",
    "test": "node --test server.test.mjs"
  },
  "dependencies": {
    "fastify": "^5.0.0"
  }
}
```

- [ ] **Step 2: Create ci/server.mjs — health + webhook endpoints**

```javascript
import Fastify from 'fastify';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { runPipeline } from './pipeline.mjs';

const app = Fastify({ logger: true });

// Health probe — registered FIRST per Bunny convention
app.get('/health', async () => ({ status: 'ok' }));

// GitHub webhook receiver
app.post('/webhook', async (request, reply) => {
  const sig = request.headers['x-hub-signature-256'];
  const event = request.headers['x-github-event'];
  const body = JSON.stringify(request.body);

  if (!verifySignature(body, sig)) {
    return reply.code(401).send({ error: 'Invalid signature' });
  }

  const payload = request.body;

  if (event === 'push') {
    const ref = payload.ref || '';
    const sha = payload.after || '';
    const repo = payload.repository?.clone_url || '';
    const isMain = ref === 'refs/heads/main';

    // Run pipeline async — don't block the webhook response
    runPipeline({ repo, sha, ref, isMain }).catch(err => {
      app.log.error({ err, sha }, 'Pipeline failed');
    });

    return { accepted: true, sha, isMain };
  }

  return { accepted: false, event };
});

function verifySignature(payload, signature) {
  if (!signature || !process.env.GITHUB_WEBHOOK_SECRET) return false;
  const expected = 'sha256=' + createHmac('sha256', process.env.GITHUB_WEBHOOK_SECRET)
    .update(payload)
    .digest('hex');
  try {
    return timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
  } catch {
    return false;
  }
}

const port = parseInt(process.env.PORT || '3000', 10);
app.listen({ port, host: '0.0.0.0' }).then(() => {
  app.log.info(`back-office-ci listening on :${port}`);
});

export { app, verifySignature };
```

- [ ] **Step 3: Create ci/pipeline.mjs — build/test/deploy runner**

Uses `execFileSync` (not `execSync`) to avoid shell injection from webhook payloads:

```javascript
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const GITHUB_API = 'https://api.github.com';

export async function runPipeline({ repo, sha, ref, isMain }) {
  const workdir = mkdtempSync(join(tmpdir(), 'bo-ci-'));
  let status = 'success';
  let description = 'All checks passed';

  try {
    await postStatus(sha, 'pending', 'Running checks...');

    const branch = ref.replace('refs/heads/', '');

    // Clone — execFileSync prevents injection via repo/branch values
    execFileSync('git', ['clone', '--depth', '1', '--branch', branch, repo, workdir],
      { stdio: 'pipe', timeout: 120_000 });

    // Install Python deps
    execFileSync('pip', ['install', '-r', 'requirements.txt'],
      { cwd: workdir, stdio: 'pipe', timeout: 120_000 });

    // Lint
    execFileSync('ruff', ['check', '.'],
      { cwd: workdir, stdio: 'pipe', timeout: 60_000 });

    // Test
    execFileSync('python', ['-m', 'pytest', 'tests/', '-v'],
      { cwd: workdir, stdio: 'pipe', timeout: 300_000 });

    // Deploy (main branch only)
    if (isMain) {
      execFileSync('python', ['-m', 'backoffice', 'sync'], {
        cwd: workdir,
        stdio: 'pipe',
        timeout: 300_000,
        env: { ...process.env, BACK_OFFICE_ENABLE_REMOTE_SYNC: '1', BUNNY_CI: '1' },
      });
      description = 'Checks passed, dashboard deployed';
    }
  } catch (err) {
    status = 'failure';
    description = (err.message || 'Pipeline failed').slice(0, 140);
  } finally {
    await postStatus(sha, status, description);
    rmSync(workdir, { recursive: true, force: true });
  }
}

async function postStatus(sha, state, description) {
  const token = process.env.GITHUB_TOKEN;
  if (!token || !sha) return;

  const url = `${GITHUB_API}/repos/CodyJo/back-office/statuses/${sha}`;
  await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `token ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      state,
      description,
      context: 'back-office-ci',
    }),
  });
}
```

- [ ] **Step 4: Create ci/Dockerfile**

```dockerfile
FROM node:18-slim

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv git bash curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install DustBunny globally
RUN npm install -g dustbunny

# Install CI server deps
COPY package.json ./
RUN npm install --production

COPY . .

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "server.mjs"]
```

- [ ] **Step 5: Create ci/.env.example**

```
BUNNY_CI=1
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_TOKEN=ghp_your_github_pat
BUNNY_STORAGE_KEY=your_bunny_storage_key
BUNNY_API_KEY=your_bunny_api_key
```

- [ ] **Step 6: Create ci/server.test.mjs — basic tests**

```javascript
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';

// Set required env before importing
process.env.GITHUB_WEBHOOK_SECRET = 'test-secret';

import { app, verifySignature } from './server.mjs';

describe('health endpoint', () => {
  it('returns ok', async () => {
    const res = await app.inject({ method: 'GET', url: '/health' });
    assert.equal(res.statusCode, 200);
    assert.deepEqual(JSON.parse(res.payload), { status: 'ok' });
  });
});

describe('webhook endpoint', () => {
  it('rejects missing signature', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/webhook',
      headers: { 'x-github-event': 'push' },
      payload: { ref: 'refs/heads/main' },
    });
    assert.equal(res.statusCode, 401);
  });

  it('accepts valid push event', async () => {
    const body = JSON.stringify({ ref: 'refs/heads/main', after: 'abc123', repository: { clone_url: 'https://github.com/test/test.git' } });
    const sig = 'sha256=' + createHmac('sha256', 'test-secret').update(body).digest('hex');

    const res = await app.inject({
      method: 'POST',
      url: '/webhook',
      headers: {
        'x-github-event': 'push',
        'x-hub-signature-256': sig,
        'content-type': 'application/json',
      },
      payload: body,
    });
    assert.equal(res.statusCode, 200);
    const data = JSON.parse(res.payload);
    assert.equal(data.accepted, true);
    assert.equal(data.isMain, true);
  });
});

describe('verifySignature', () => {
  it('returns true for valid signature', () => {
    const payload = '{"test": true}';
    const sig = 'sha256=' + createHmac('sha256', 'test-secret').update(payload).digest('hex');
    assert.equal(verifySignature(payload, sig), true);
  });

  it('returns false for invalid signature', () => {
    assert.equal(verifySignature('body', 'sha256=wrong'), false);
  });

  it('returns false for missing signature', () => {
    assert.equal(verifySignature('body', undefined), false);
  });
});
```

- [ ] **Step 7: Run CI server tests**

Run: `cd ci && npm install && node --test server.test.mjs`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add ci/
git commit -m "feat: add CI/CD webhook server for Bunny Magic Container

Fastify server receiving GitHub webhooks. Runs lint, tests, and
deploys dashboard on push to main. Replaces CodeBuild CI/CD.
Uses execFileSync to prevent shell injection from webhook payloads.
Follows standard Cody Jo single-container Bunny app pattern."
```

---

## Chunk 3: Config, Factory, Engine, and Test Migration

### Task 4: Config + Provider Factory + Engine Updates

**Files:**
- Modify: `backoffice/config.py:52-59` (DashboardTarget dataclass)
- Modify: `backoffice/config.py:62-65` (AWSConfig → BunnyConfig)
- Modify: `backoffice/config.py:68-71` (DeployConfig)
- Modify: `backoffice/config.py:96-97` (NotificationsConfig.sync_to_s3)
- Modify: `backoffice/config.py:150-164` (_build_dashboard_targets → _build_bunny_dashboard_targets)
- Modify: `backoffice/config.py:207-306` (load_config)
- Modify: `backoffice/sync/providers/__init__.py:11-18` (get_providers)
- Modify: `backoffice/sync/engine.py:32-39` (_remote_sync_allowed)
- Modify: `backoffice/sync/engine.py:73-87` (from_config)
- Modify: `backoffice/sync/engine.py:120,187,193,317,319` (target.bucket refs)
- Modify: `backoffice/sync/engine.py:199,202` (target.distribution_id refs)
- Modify: `backoffice/server.py:118-122` (_local_unattended_allowed)
- Modify: `Makefile:10,18` (CODEBUILD_BUILD_ID guards)
- Modify: `tests/test_sync_engine.py:79,93,110,123-127,140-145,170-174,189-193,212-217`
- Modify: `tests/test_config.py:29-39` (minimal_config fixture — AWS → Bunny YAML)
- Modify: `config/backoffice.example.yaml` (replace AWS config with Bunny config)
- Create: `config/backoffice.bunny.example.yaml`

- [ ] **Step 1: Update DashboardTarget dataclass**

In `backoffice/config.py`, replace the DashboardTarget dataclass (lines 51-58):

```python
# Old:
@dataclass(frozen=True)
class DashboardTarget:
    bucket: str = ""
    base_path: str = ""
    distribution_id: str = ""
    subdomain: str = ""
    filter_repo: str | None = None
    allow_public_read: bool = False

# New:
@dataclass(frozen=True)
class DashboardTarget:
    pull_zone_id: str = ""
    base_path: str = ""
    subdomain: str = ""
    filter_repo: str | None = None
    allow_public_read: bool = False
```

- [ ] **Step 2: Replace AWSConfig with BunnyConfig**

In `backoffice/config.py`, replace AWSConfig (lines 61-64) and update DeployConfig (lines 67-70):

```python
# Old:
@dataclass(frozen=True)
class AWSConfig:
    region: str = "us-east-1"
    dashboard_targets: list[DashboardTarget] = field(default_factory=list)

@dataclass(frozen=True)
class DeployConfig:
    provider: str = "aws"
    aws: AWSConfig = field(default_factory=AWSConfig)

# New:
@dataclass(frozen=True)
class BunnyConfig:
    storage_zone: str = ""
    storage_region: str = "ny"
    storage_key: str | None = None
    dashboard_targets: list[DashboardTarget] = field(default_factory=list)

@dataclass(frozen=True)
class DeployConfig:
    provider: str = "bunny"
    bunny: BunnyConfig = field(default_factory=BunnyConfig)
```

- [ ] **Step 3: Rename sync_to_s3 to sync_to_storage**

In `backoffice/config.py`, update NotificationsConfig (line 97):

```python
# Old:
    sync_to_s3: bool = True
# New:
    sync_to_storage: bool = True
```

Search for all references to `sync_to_s3` in the codebase and rename to `sync_to_storage`.

- [ ] **Step 4: Update config loader functions**

Replace `_build_dashboard_targets()` (lines 150-164) with:

```python
def _build_bunny_dashboard_targets(raw_targets: list[dict]) -> list[DashboardTarget]:
    targets = []
    for t in raw_targets:
        targets.append(DashboardTarget(
            pull_zone_id=str(t.get("pull_zone_id", "")),
            base_path=t.get("base_path", ""),
            subdomain=t.get("subdomain", ""),
            filter_repo=t.get("filter_repo"),
            allow_public_read=t.get("allow_public_read", False),
        ))
    return targets
```

In `load_config()`, replace the AWS config parsing (around lines 279-281) with:

```python
bunny_raw = deploy_raw.get("bunny", {}) or {}
bunny_targets = _build_bunny_dashboard_targets(bunny_raw.get("dashboard_targets", []))
bunny_config = BunnyConfig(
    storage_zone=bunny_raw.get("storage_zone", ""),
    storage_region=bunny_raw.get("storage_region", "ny"),
    storage_key=bunny_raw.get("storage_key"),
    dashboard_targets=bunny_targets,
)
deploy = DeployConfig(
    provider=deploy_raw.get("provider", "bunny"),
    bunny=bunny_config,
)
```

- [ ] **Step 5: Update provider factory**

Replace `backoffice/sync/providers/__init__.py` entirely:

```python
"""Provider factory."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backoffice.config import Config

from backoffice.sync.providers.base import CDNProvider, StorageProvider


def get_providers(config: "Config") -> tuple[StorageProvider, CDNProvider]:
    """Create storage and CDN providers from config."""
    provider = config.deploy.provider
    if provider == "bunny":
        from backoffice.sync.providers.bunny import BunnyCDN, BunnyStorage
        bunny = config.deploy.bunny
        return (
            BunnyStorage(bunny.storage_zone, bunny.storage_region, bunny.storage_key),
            BunnyCDN(),
        )
    raise ValueError(f"Unknown deploy provider: {provider}")
```

- [ ] **Step 6: Update SyncEngine.from_config()**

In `backoffice/sync/engine.py`, update `from_config()` (lines 73-87):

```python
@classmethod
def from_config(cls) -> SyncEngine:
    """Build a SyncEngine from the project config file."""
    from backoffice.config import load_config
    from backoffice.sync.providers import get_providers

    config = load_config()
    storage, cdn = get_providers(config)
    return cls(
        storage=storage,
        cdn=cdn,
        dashboard_dir=config.root / "dashboard",
        results_dir=config.root / "results",
        dashboard_targets=config.deploy.bunny.dashboard_targets,
        skip_gate=False,
    )
```

- [ ] **Step 7: Update _remote_sync_allowed()**

In `backoffice/sync/engine.py`, replace `_remote_sync_allowed()` (lines 32-39):

```python
def _remote_sync_allowed() -> bool:
    """Require explicit opt-in for remote sync during local use.

    CI containers set BUNNY_CI=1. Local use requires explicit opt-in.
    """
    if os.environ.get("CI") or os.environ.get("BUNNY_CI"):
        return True
    return os.environ.get("BACK_OFFICE_ENABLE_REMOTE_SYNC", "").lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 8: Update engine target field references**

In `backoffice/sync/engine.py`, update all `target.bucket` and `target.distribution_id` references:

- Line 120: `target.bucket` → `target.subdomain`
- Line 187: `target.bucket` → `target.subdomain`
- Line 193: `bucket = target.bucket` → remove or replace with `zone = ""`  (BunnyStorage ignores bucket param)
- Lines 194-196: Keep `m["bucket"] = zone` for interface compatibility
- Line 199: `if target.distribution_id:` → `if target.pull_zone_id:`
- Line 202: `self.cdn.invalidate(target.distribution_id, paths)` → `self.cdn.invalidate(target.pull_zone_id, paths)`
- Line 317: `target.bucket` → `target.subdomain`
- Line 319: `bucket=target.bucket` → `bucket=""`

- [ ] **Step 9: Update server.py CODEBUILD gate**

In `backoffice/server.py`, update `_local_unattended_allowed()` (lines 118-122):

```python
# Old:
    if os.environ.get("CI") or os.environ.get("CODEBUILD_BUILD_ID"):
# New:
    if os.environ.get("CI") or os.environ.get("BUNNY_CI"):
```

- [ ] **Step 10: Update Makefile CODEBUILD guards**

In `Makefile`, lines 10 and 18, replace `CODEBUILD_BUILD_ID` with `BUNNY_CI`:

```makefile
# Line 10 (require_remote_sync):
@test "$$CI" = "true" -o -n "$$BUNNY_CI" -o "$$BACK_OFFICE_ENABLE_REMOTE_SYNC" = "1" \

# Line 18 (require_unattended):
@test "$$CI" = "true" -o -n "$$BUNNY_CI" -o "$$BACK_OFFICE_ENABLE_UNATTENDED" = "1" \
```

- [ ] **Step 11: Update all DashboardTarget constructions in tests**

In `tests/test_sync_engine.py`, update every `DashboardTarget(...)` call:

```python
# Old (line 79):
DashboardTarget(bucket="test-bucket", subdomain="admin.test.com")
# New:
DashboardTarget(subdomain="admin.test.com")

# Old (lines 140-145):
DashboardTarget(bucket="admin-bucket", subdomain="admin.example.com",
                distribution_id="EADMIN123", filter_repo=None)
# New:
DashboardTarget(subdomain="admin.example.com",
                pull_zone_id="EADMIN123", filter_repo=None)

# Old (lines 212-217):
DashboardTarget(bucket="www-bucket", subdomain="admin.example.com",
                base_path="back-office/dashboard",
                distribution_id="EDASH123", filter_repo=None)
# New:
DashboardTarget(subdomain="admin.example.com",
                base_path="back-office/dashboard",
                pull_zone_id="EDASH123", filter_repo=None)
```

Apply the same pattern to ALL DashboardTarget constructions at lines 79, 93, 110, 123-127, 170-174, 189-193. Remove all `bucket=` arguments. Rename all `distribution_id=` to `pull_zone_id=`.

Also update any test assertions referencing `target.bucket` or `target.distribution_id`.

Also check `tests/test_servers.py` for any `CODEBUILD_BUILD_ID` or `DashboardTarget` references and update.

- [ ] **Step 12: Update tests/test_config.py fixture**

In `tests/test_config.py`, update the `minimal_config` fixture (lines 29-39) to use Bunny config:

```python
# Old:
        deploy:
          provider: aws
          aws:
            region: us-west-2
            dashboard_targets: []
        ...
        notifications:
          sync_to_s3: true

# New:
        deploy:
          provider: bunny
          bunny:
            storage_zone: test-zone
            storage_region: ny
            dashboard_targets: []
        ...
        notifications:
          sync_to_storage: true
```

- [ ] **Step 13: Update config/backoffice.example.yaml**

Replace the `deploy:` section (lines 22-35) and `notifications:` section (line 59-60):

```yaml
# Old:
deploy:
  provider: aws
  aws:
    region: us-east-1
    dashboard_targets:
      - bucket: "admin-yoursite-bucket"
        ...
        distribution_id: "XXXXXXXXXXXXXXX"
        ...
notifications:
  sync_to_s3: true

# New:
deploy:
  provider: bunny
  bunny:
    storage_zone: "your-storage-zone"
    storage_region: "ny"
    # storage_key: set via BUNNY_STORAGE_KEY env var
    dashboard_targets:
      - pull_zone_id: "XXXXXXX"
        subdomain: "admin.yoursite.com"
        filter_repo: "yoursite"
        allow_public_read: false
notifications:
  sync_to_storage: true
```

- [ ] **Step 14: Fix s3:// log strings in engine.py**

In `backoffice/sync/engine.py`:
- Line 185-189: Change `"[dry-run] Would upload %s -> s3://%s/%s"` format to `"[dry-run] Would upload %s -> %s/%s"` and use `target.subdomain` instead of `target.bucket`
- Line 317: Change `"Syncing regression logs -> s3://%s/%s"` to `"Syncing regression logs -> %s/%s"` and use `target.subdomain`

- [ ] **Step 15: Create example Bunny config**

Create `config/backoffice.bunny.example.yaml`:

```yaml
# Back Office — Bunny.net deployment configuration
# Copy to config/backoffice.yaml and fill in real values

deploy:
  provider: bunny
  bunny:
    storage_zone: "admin-codyjo"
    storage_region: "ny"
    # storage_key: set via BUNNY_STORAGE_KEY env var
    dashboard_targets:
      - pull_zone_id: "123456"
        subdomain: "admin.codyjo.com"
      - pull_zone_id: "789012"
        base_path: "back-office/dashboard"
        subdomain: "www.codyjo.com"

runner:
  command: "claude --model haiku"
  mode: "claude-print"

notifications:
  sync_to_storage: true
```

- [ ] **Step 16: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS. Fix any remaining failures from field renames in other test files.

- [ ] **Step 17: Commit**

```bash
git add backoffice/config.py backoffice/sync/providers/__init__.py \
  backoffice/sync/engine.py backoffice/server.py Makefile \
  tests/test_sync_engine.py tests/test_servers.py tests/test_tasks.py \
  tests/test_config.py config/backoffice.bunny.example.yaml \
  config/backoffice.example.yaml
git commit -m "feat: switch config and engine from AWS to Bunny

Replace AWSConfig with BunnyConfig, remove DashboardTarget.bucket,
rename distribution_id → pull_zone_id, sync_to_s3 → sync_to_storage.
Update provider factory, sync engine, server gate, Makefile guards.
All tests updated for new field names."
```

---

## Chunk 4: Teardown and Documentation

### Task 5: Delete AWS Infrastructure Files

**Files:**
- Delete: `terraform/` (entire directory)
- Delete: `buildspec-ci.yml`
- Delete: `buildspec-cd.yml`
- Delete: `backoffice/sync/providers/aws.py`
- Delete: `config/backoffice.codebuild.example.yaml`

- [ ] **Step 1: Verify no remaining references to deleted files**

Search for any remaining imports or references:

```bash
grep -rn "aws\.py\|AWSStorage\|AWSCloudFront\|buildspec\|codebuild\.tf\|cost_guardrails\|from.*aws import" \
  backoffice/ tests/ scripts/ Makefile --include="*.py" --include="*.sh" --include="Makefile"
```

Expected: No matches in files that are NOT being deleted. If references remain, fix them first.

- [ ] **Step 2: Delete AWS files**

```bash
rm -f backoffice/sync/providers/aws.py
rm -f buildspec-ci.yml buildspec-cd.yml
rm -f config/backoffice.codebuild.example.yaml
rm -rf terraform/
```

- [ ] **Step 3: Run full test suite to confirm nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove AWS infrastructure files

Delete terraform/, buildspec-ci.yml, buildspec-cd.yml,
aws.py provider, and codebuild example config. All
functionality replaced by Bunny equivalents."
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `Makefile` (dashboard target comment)

- [ ] **Step 1: Update CLAUDE.md**

Replace AWS references throughout:
- "S3 + CloudFront" → "Bunny Storage Zone + Pull Zone"
- "CodeBuild" → "Magic Container webhook server (`ci/`)"
- Remove `buildspec-ci.yml` and `buildspec-cd.yml` from any file references
- Add `ci/` to the project structure section
- Update CI/CD section to describe the webhook container
- Update Data Flow: "pushes to S3 + CloudFront" → "uploads to Bunny Storage + purges Pull Zone"
- Remove `terraform/` from project structure
- Replace "IAM role" section with Bunny auth note
- Remove CloudWatch logs reference
- Update `config/` section: mention `backoffice.bunny.example.yaml`

- [ ] **Step 2: Update Makefile dashboard target comment**

```makefile
# Old:
dashboard: ## Deploy all dashboards to S3
# New:
dashboard: ## Deploy all dashboards to Bunny Storage
```

- [ ] **Step 3: Run tests one final time**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md Makefile
git commit -m "docs: update documentation for Bunny migration

Replace all AWS references with Bunny equivalents in CLAUDE.md.
Add ci/ to project structure. Update CI/CD and data flow sections."
```

---

## Post-Implementation: Infrastructure Setup

After all code is merged, run the one-time infrastructure setup (documented in spec):

1. Create Bunny Storage Zone via Bunny dashboard
2. `dustbunny pz create <name> <storageZoneOriginUrl>`
3. `dustbunny pz hostname <pullZoneId> <hostname>` (for each domain)
4. `dustbunny pz ssl <pullZoneId> <hostname>` (for each domain)
5. `dustbunny dns set <zoneId> <name> <type> <value> [ttl]` (for each domain)
6. Build and push CI container image with versioned tag (`v1`)
7. `dustbunny app create back-office-ci <namespace/name:tag> <registryId> 3000`
8. `dustbunny env sync <appId> ci/.env`
9. Configure GitHub webhook at `https://<ci-container-url>/webhook`
10. Test: push a commit and verify the pipeline runs
