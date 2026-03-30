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
- Purges Pull Zone cache by shelling out to `dustbunny pull-zones purge --pull-zone-id {id}`
- `invalidate(pull_zone_id, paths)` — runs purge command. Bunny purge is free, so no need for the path-collapsing logic that AWS required.

**Modified: `backoffice/sync/providers/__init__.py`**

`get_providers()` gains a `"bunny"` branch that instantiates `BunnyStorage` and `BunnyCDN`.

### 2. Configuration

**New dataclass: `BunnyConfig`**
- `storage_zone: str` — storage zone name
- `storage_region: str` — region code (e.g., `"ny"`)
- `storage_key: str | None` — access key (falls back to `BUNNY_STORAGE_KEY` env var)
- `dashboard_targets: list[DashboardTarget]`

**Updated: `DashboardTarget`**
- `pull_zone_id: str` replaces `distribution_id` for Bunny targets
- `storage_zone: str` replaces `bucket` for Bunny targets
- Fields are provider-agnostic where possible

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
- `dustbunny dns set` to point `admin.codyjo.com` at the Pull Zone
- `dustbunny dns set` to point `www.codyjo.com` at the Pull Zone
- DustBunny's `set` command updates existing records (no duplicates)

### 5. SyncEngine Changes

Minimal changes:
- `from_config()` reads `deploy.bunny` when provider is `"bunny"`
- `_remote_sync_allowed()` drops `CODEBUILD_BUILD_ID` check, adds Bunny container environment detection
- Log messages updated (no more `s3://` references)
- `_invalidation_paths()` simplification — Bunny purge is free, no need for wildcard collapsing

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
| `backoffice/config.py` | Add `BunnyConfig`, update `DeployConfig` |
| `backoffice/sync/providers/__init__.py` | Add `"bunny"` branch |
| `backoffice/sync/engine.py` | Update factory + gate |
| `Makefile` | Remove CodeBuild refs, update deploy targets |
| `scripts/sync-dashboard.sh` | Update for Bunny config |
| `CLAUDE.md` | Update architecture docs |

## Infrastructure Setup (One-Time)

Run via DustBunny CLI:

1. `dustbunny pull-zones create` — create storage-backed Pull Zones
2. `dustbunny pull-zones hostnames add` — attach custom domains
3. `dustbunny pull-zones ssl activate` — enable SSL per hostname
4. `dustbunny dns set` — point domains at Pull Zones
5. `dustbunny apps create` — deploy CI container
6. `dustbunny env set` — configure container secrets
7. Configure GitHub webhook to point at container URL

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
- **Pull Zone management:** create, hostnames, SSL, purge
- **DNS:** record updates
- **Magic Containers:** app create, update, env set
- **Not used for:** storage uploads (direct HTTP PUT from Python is simpler)
