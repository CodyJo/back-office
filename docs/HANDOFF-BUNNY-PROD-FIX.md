# Production Fix Handoff: Bunny Pull Zone Configuration

**Date:** 2026-03-31
**Status:** RESOLVED - both sites serving again through Bunny
**Priority:** P0

## Current State

- `admin.codyjo.com` -> `200 OK`
- `www.codyjo.com` -> `200 OK`

## What Happened

1. During AWS-to-Bunny migration, admin.codyjo.com was added to the **existing** pull zone 5582774 (codyjo-www) which also serves www.codyjo.com
2. Back-office dashboard files were uploaded to storage zone `codyjo-www-origin`, overwriting the www site's index.html
3. To fix, we created a **separate** storage zone and pull zone for admin:
   - Storage Zone: `admin-codyjo-backoffice` (ID 1445163, password: `1c267a39-74df-4ced-8f33091ee311-f85b-4006`)
   - Pull Zone: `admin-codyjo-backoffice` (ID 5603475)
4. Back-office files were uploaded to the new storage zone successfully
5. admin.codyjo.com hostname was moved to the new pull zone
6. DNS was updated: `admin CNAME admin-codyjo-backoffice.b-cdn.net`
7. SSL was activated

**But:** The pull zone origin was set to `https://admin-codyjo-backoffice.b-cdn.net/` which is the pull zone's own CDN hostname -- creating a loop (508). It should be linked directly to the storage zone.

**And:** The back-office files were deleted from `codyjo-www-origin` storage zone to clean up www, but the original www site content (the codyjo.com marketing site) may have also been lost or was never in that storage zone.

## Resolution Applied On 2026-03-31

### 1. Fixed admin.codyjo.com (508 Loop)

The existing pull zone did not need to be recreated. Updating it to storage-backed mode fixed the loop immediately:

```bash
curl -fsS -X POST \
  -H "AccessKey: $BUNNY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"OriginUrl":"","OriginType":2,"StorageZoneId":1445163}' \
  "https://api.bunny.net/pullzone/5603475"
```

Verified result:
- pull zone `5603475` now reports `OriginType: 2`
- `StorageZoneId: 1445163`
- `OriginUrl: ""`
- `OriginLinkValue: "admin-codyjo-backoffice"`
- live `curl -I https://admin.codyjo.com/` returned `200` on 2026-03-31

### 2. Restored www.codyjo.com (404)

The `codyjo-www-origin` storage zone still contained most of the site, but the root `index.html` was missing, which caused the 404 at `/`.

Recovery was a normal gated Bunny release from the `codyjo.com` repo:

```bash
cd /home/merm/projects/codyjo.com
npm run release:bunny
```

That release ran:
- `npm run check`
- `npm test`
- `npm run build`
- `npm run verify:dist`
- Bunny Storage upload
- Bunny pull-zone purge
- smoke test against `https://www.codyjo.com/`

Verified result:
- storage zone `1440489` now contains root `index.html`
- `curl -I https://www.codyjo.com/` returned `200` on 2026-03-31
- `curl https://www.codyjo.com/health` returned the expected `OK` page

## What Was Fixed

### 1. admin.codyjo.com

Current good state:
- Pull Zone `5603475`
- Storage Zone `1445163`
- Hostname `admin.codyjo.com`
- SSL active
- Serving dashboard HTML from Bunny Storage

### 2. www.codyjo.com

Current good state:
- Pull Zone `5582774`
- Storage Zone `1440489`
- Hostname `www.codyjo.com`
- Root `index.html` restored by release from `/home/merm/projects/codyjo.com`

### 3. Update back-office config after fix

No pull zone ID change was needed. `config/backoffice.yaml` already points at:
- `storage_zone: admin-codyjo-backoffice`
- `cdn_id: 5603475`

`BUNNY_STORAGE_KEY` still needs to be set to the admin storage key when running a real sync:

```bash
BUNNY_STORAGE_KEY=... BACK_OFFICE_ENABLE_REMOTE_SYNC=1 python3 -m backoffice sync
```

## Bunny Resource Inventory

| Resource | ID | Name | Purpose |
|---|---|---|---|
| DNS Zone | 759174 | codyjo.com | All DNS records |
| Storage Zone | 1440489 | codyjo-www-origin | www.codyjo.com content |
| Pull Zone | 5582774 | codyjo-www | Serves www.codyjo.com |
| Storage Zone | 1445163 | admin-codyjo-backoffice | Back-office dashboard |
| Pull Zone | 5603475 | admin-codyjo-backoffice | Serves admin.codyjo.com |
| Storage Key (www) | - | eaec4a48-9b1c-43ea-... | For codyjo-www-origin |
| Storage Key (admin) | - | 1c267a39-74df-4ced-... | For admin-codyjo-backoffice |

## DNS Records (codyjo.com zone 759174)

- `admin` CNAME `admin-codyjo-backoffice.b-cdn.net`
- `www` CNAME `codyjo-www.b-cdn.net` (unchanged)

## Files Changed This Session

All committed on main branch:
```
git log --oneline origin/main..HEAD
```
