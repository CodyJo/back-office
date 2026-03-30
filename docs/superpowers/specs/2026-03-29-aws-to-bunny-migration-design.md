# AWS to Bunny Migration — Full Back Office Exit

**Date:** 2026-03-29
**Status:** Approved

## Overview

Complete migration of the Back Office infrastructure from AWS to Bunny.net. Replaces S3, CloudFront, CodeBuild, cost guardrails, and all Terraform with Bunny Storage Zones, Pull Zones, Magic Containers, and DNS — managed via DustBunny CLI at `~/projects/dustbunny`.

## Motivation

- CloudFront invalidation costs are $1,307/mo — the dominant AWS expense
- Bunny Pull Zone cache purging is free
- All other Cody Jo apps (Fuel, Selah, CertStudy, TNBM) are already migrating to Bunny
- Consolidates infrastructure onto a single platform

## Architecture

### Before (AWS)

```
GitHub push → CodeBuild → sync-dashboard.sh → S3 bucket → CloudFront CDN
                                                              ↓
                                                    admin.codyjo.com
                                                    www.codyjo.com
```

### After (Bunny)

```
GitHub push → webhook → Magic Container (back-office-ci)
                              ↓ (on main, after tests pass)
                        python -m backoffice sync
                              ↓
                        Bunny Storage Zone (HTTP PUT)
                              ↓
                        Bunny Pull Zone (purge via dustbunny)
                              ↓
                    admin.codyjo.com  /  www.codyjo.com
                    (DNS already on Bunny)
```

## Component Design

### 1. Provider Layer

**New file: `backoffice/sync/providers/bunny.py`**

`BunnyStorage(StorageProvider)`:
- Uploads files to Bunny Storage Zone via HTTP PUT to `https://{region}.storage.bunnycdn.com/{zone}/{path}`
- Auth via `AccessKey` header (from config or `BUNNY_STORAGE_KEY` env var)
- `upload_file()` — single PUT request with Content-Type header
- `upload_files()` — iterates upload_file for each mapping
- `sync_directory()` — walks local dir, uploads each file, optionally deletes remote files not present locally

`BunnyCDN(CDNProvider)`:
- Purges Pull Zone cache by shelling out to `dustbunny pz purge <pullZoneId>`
- `invalidate(distribution_id, paths)` — accepts the base class signature; `distribution_id` is semantically a Pull Zone ID for Bunny targets, `paths` is ignored (Bunny purge is always zone-wide and free). No path-collapsing logic needed.
- Uses `urllib.request` (stdlib) to avoid adding an HTTP dependency

**HTTP client:** `BunnyStorage` uses `urllib.request` (stdlib) for PUT uploads — no new dependency needed. Retry logic is self-contained in the provider (same pattern as `aws.py`).

**Modified: `backoffice/sync/providers/__init__.py`**

`get_providers()` gains a `"bunny"` branch that instantiates `BunnyStorage` and `BunnyCDN`.

### 2. Configuration

**Updated: `DeployConfig`** — replace `aws: AWSConfig` with `bunny: BunnyConfig`, change default `provider` to `"bunny"`. `AWSConfig` is deleted.

**New dataclass: `BunnyConfig`**
- `storage_zone: str` — storage zone name
- `storage_region: str` — region code (e.g., `"ny"`)
- `storage_key: str | None` — access key (falls back to `BUNNY_STORAGE_KEY` env var)
- `dashboard_targets: list[DashboardTarget]`

**Updated: `DashboardTarget`** — simplified for Bunny-only:
- `pull_zone_id: str` — Bunny Pull Zone ID (replaces `distribution_id`)
- `base_path`, `subdomain`, `filter_repo`, `allow_public_read` — unchanged
- `bucket` field removed — storage zone name lives on `BunnyConfig`, not per-target (all targets share one zone, differentiated by `base_path`)

Since this is a big-bang migration, all AWS references are removed in the same changeset. The frozen dataclass fields are renamed, and all call sites (engine, tests, config loader) are updated together.

The `BunnyStorage` provider gets the storage zone name from `BunnyConfig` (passed at construction time), not from individual targets. The engine passes `base_path` per target for upload key prefixing.

**New: `config/backoffice.bunny.example.yaml`**
```yaml
deploy:
  provider: bunny
  bunny:
    storage_zone: "admin-codyjo"
    storage_region: "ny"
    dashboard_targets:
      - pull_zone_id: "123456"
        subdomain: "admin.codyjo.com"
      - pull_zone_id: "789012"
        base_path: "back-office/dashboard"
        subdomain: "www.codyjo.com"
```

YAML field names match the `DashboardTarget` dataclass directly — no mapping needed in the config loader.

### 3. CI/CD — Magic Container Webhook Server

Single container `back-office-ci` following the standard Cody Jo Bunny app pattern:

**Fastify server (port 3000):**
- `GET /health` — health probe (registered first)
- `POST /webhook` — GitHub webhook receiver, verifies `X-Hub-Signature-256`, runs pipeline

**Pipeline on webhook receive:**
1. Clone repo at pushed commit (shallow clone)
2. Install Python deps + DustBunny
3. Run checks: `ruff check`, `pytest`, `bash -n` on shell scripts
4. If push to main and checks pass: `python -m backoffice sync`
5. Post commit status back via GitHub API

**Container spec:**
```json
{
  "name": "back-office-ci",
  "runtimeType": "shared",
  "containerTemplates": [{
    "name": "app",
    "imagePullPolicy": "always",
    "endpoints": [{
      "displayName": "back-office-ci-cdn",
      "type": "cdn",
      "cdn": { "portMappings": [{ "containerPort": 3000 }] }
    }],
    "probes": {
      "startup": { "type": "http", "http": { "path": "/health", "port": 3000 } },
      "readiness": { "type": "http", "http": { "path": "/health", "port": 3000 } },
      "liveness": { "type": "http", "http": { "path": "/health", "port": 3000 } }
    },
    "environmentVariables": [
      { "name": "BUNNY_CI", "value": "1" },
      { "name": "GITHUB_WEBHOOK_SECRET" },
      { "name": "GITHUB_TOKEN" },
      { "name": "BUNNY_STORAGE_KEY" },
      { "name": "BUNNY_API_KEY" }
    ]
  }]
}
```

**Image versioning:** Tags increment (`v1`, `v2`, ...), never reuse `latest` for redeploys (per Bunny caching behavior).

**Source location:** `ci/` directory containing the Fastify app, Dockerfile, and pipeline runner.

### 4. DNS Updates

Both domains already have DNS on Bunny. Updates via DustBunny:
- `dustbunny dns set <zoneId> admin <type> <pullZoneHostname> [ttl]`
- `dustbunny dns set <zoneId> www <type> <pullZoneHostname> [ttl]`
- DustBunny's `set` command updates existing records (no duplicates)

### 5. SyncEngine Changes

**`from_config()` update:**
```python
if config.deploy.provider == "bunny":
    storage, cdn = get_providers(config)
    targets = config.deploy.bunny.dashboard_targets
```
Config loader gains `_build_bunny_config()` and `_build_bunny_dashboard_targets()` to parse the `deploy.bunny` YAML block, mirroring the existing `_build_dashboard_targets()` for AWS.

**`_remote_sync_allowed()` update:**
- Drop `CODEBUILD_BUILD_ID` check
- Add `BUNNY_CI` env var check (set explicitly in the Magic Container's `environmentVariables`)
- Keep `BACK_OFFICE_ENABLE_REMOTE_SYNC` as the local opt-in

**Also update:** `backoffice/server.py` which has its own `CODEBUILD_BUILD_ID` check for the remote-sync gate.

**`NotificationsConfig.sync_to_s3`** — rename to `sync_to_storage` (provider-agnostic).

**Log messages** — remove `s3://` references, use generic "storage" language.

**`_invalidation_paths()`** — simplify; Bunny purge is free and zone-wide.

### 6. Teardown

**Deleted:**
| Path | Reason |
|---|---|
| `terraform/` (entire dir) | CodeBuild, cost guardrails — all AWS |
| `buildspec-ci.yml` | Replaced by Magic Container |
| `buildspec-cd.yml` | Replaced by Magic Container |
| `backoffice/sync/providers/aws.py` | Replaced by `bunny.py` |
| `config/backoffice.codebuild.example.yaml` | Replaced by `backoffice.bunny.example.yaml` |

**Modified:**
| Path | Change |
|---|---|
| `backoffice/config.py` | Add `BunnyConfig`, rename `DashboardTarget` fields, add `_build_bunny_config()`, rename `sync_to_s3` → `sync_to_storage` |
| `backoffice/sync/providers/__init__.py` | Add `"bunny"` branch |
| `backoffice/sync/engine.py` | Update `from_config()`, `_remote_sync_allowed()`, log messages |
| `backoffice/server.py` | Update `CODEBUILD_BUILD_ID` gate to `BUNNY_CI` |
| `Makefile` | Remove `CODEBUILD_BUILD_ID` guards, update deploy targets |
| `scripts/sync-dashboard.sh` | Update for Bunny config |
| `scripts/quick-sync.sh`, `scripts/job-status.sh` | Update or remove AWS-specific logic |
| `tests/test_sync_engine.py` | Update all `DashboardTarget` constructions to new field names |
| `CLAUDE.md` | Update architecture docs |

## Infrastructure Setup (One-Time)

Run via DustBunny CLI:

1. Create Bunny Storage Zone (via Bunny dashboard — DustBunny does not have storage zone management)
2. `dustbunny pz create <name> <storageZoneOriginUrl>` — create Pull Zone backed by storage zone
3. `dustbunny pz hostname <pullZoneId> <hostname>` — attach custom domains
4. `dustbunny pz ssl <pullZoneId> <hostname>` — enable SSL per hostname
5. `dustbunny dns set <zoneId> <name> <type> <value> [ttl]` — point domains at Pull Zones
6. `dustbunny app create back-office-ci <namespace/name:tag> <registryId> 3000` — deploy CI container
7. `dustbunny env sync <appId> <envFile>` — configure container secrets
8. Configure GitHub webhook to point at container URL

## Test Plan

1. Unit tests for `BunnyStorage` and `BunnyCDN` providers (mock HTTP calls and DustBunny CLI)
2. Local dry-run sync against Bunny Storage Zone
3. Live sync with `BACK_OFFICE_ENABLE_REMOTE_SYNC=1`, verify dashboard loads via Pull Zone
4. Push a test commit, verify webhook container runs pipeline and deploys
5. Verify DNS resolution for both domains
6. Tear down AWS resources after validation

## Migration Strategy

Big bang cutover: build the Bunny provider, test end-to-end, flip the config, update DNS, delete AWS resources. No parallel running period.

## DustBunny Usage

DustBunny (`~/projects/dustbunny`) is used as a CLI tool throughout:
- **Pull Zone management:** `pz create`, `pz hostname`, `pz ssl`, `pz purge`
- **DNS:** `dns set` (updates existing records, no duplicates)
- **Magic Containers:** `app create`, `app apply`, `env sync`
- **Not used for:** storage zone creation (use Bunny dashboard) or storage uploads (direct HTTP PUT via `urllib.request` from Python)
