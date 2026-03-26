# Postal Migration Plan

Date: 2026-03-24

## Target Architecture

- One shared self-hosted Postal deployment
- One Postal organization/operator footprint
- Separate Postal server credential per product where possible
- Product-aligned `From` domains:
  - Fuel: `no-reply@mail.fuel.codyjo.com`
  - CertStudy: `no-reply@mail.study.codyjo.com`
  - Selah: `no-reply@mail.selahscripture.com`
  - Tarot: `no-reply@mail.thenewbeautifulme.com`
  - Cordivent: `no-reply@mail.cordivent.com`
  - Cody Jo Method: `no-reply@mail.codyjo.com`

## Code Strategy Implemented

- Added a small `email-provider.mjs` adapter in each server-side repo touched by transactional email.
- The adapter resolves:
  - `EMAIL_PROVIDER=postal`
  - `EMAIL_PROVIDER=resend`
  - automatic fallback to `resend` when Postal credentials are absent
- Each lambda now sends through the adapter rather than calling Resend directly.

## Config Contract

- `EMAIL_PROVIDER`
- `EMAIL_POSTAL_BASE_URL`
- `EMAIL_POSTAL_SERVER_KEY`
- `EMAIL_FROM_NAME`
- `EMAIL_FROM_ADDRESS`
- `EMAIL_REPLY_TO`
- Existing `RESEND_API_KEY` remains for rollback

## Credential Strategy

- Recommended steady state:
  - one Postal deployment
  - one Postal server or credential set per product
  - each product repo/deploy receives only its own Postal server key
- Current code shape:
  - app repos accept one Postal key each via env/Terraform wiring
  - auth-service accepts one Postal key for the shared service path
  - Resend fallback remains available until Postal is proven in production

## Webhook Strategy

- This pass prepares clean provider boundaries but does not add webhook consumers yet.
- Recommended next webhook set:
  - delivery
  - bounce
  - complaint
  - suppression or failure events
- Recommended landing point:
  - a dedicated webhook lambda or lightweight shared mail-events handler
  - DynamoDB or S3 append-only event log

## Rollback Plan

- Keep Postal config deployed but set `EMAIL_PROVIDER=resend` if:
  - DNS validation is incomplete
  - Postal API auth fails
  - deliverability is degraded
  - bounce/reputation behavior looks unsafe
- Because the adapter preserves Resend compatibility, rollback is env-only for the touched code paths.

## Phased Rollout Order

1. Fuel
2. CertStudy
3. Selah
4. Tarot
5. Cordivent
6. Cody Jo Method

## Product Change Matrix

| Product | Entry point | Target sender | Required code change | Required config change |
| --- | --- | --- | --- | --- |
| Fuel | `lambda/api/index.mjs` | `no-reply@mail.fuel.codyjo.com` | done | pending Postal secrets/DNS |
| CertStudy | `lambda/api/index.mjs` | `no-reply@mail.study.codyjo.com` | done | pending Postal secrets/DNS |
| Selah | `lambda/api/index.mjs` | `no-reply@mail.selahscripture.com` | done | pending Postal secrets/DNS |
| Tarot | `lambda/api/index.mjs`, `lambda/api/admin.mjs` | `no-reply@mail.thenewbeautifulme.com` | done | pending Postal secrets/DNS |
| Cordivent | `lambda/api/index.mjs`, `lambda/scheduler/index.mjs` | `no-reply@mail.cordivent.com` | done | pending Postal secrets/DNS |
| Cody Jo Method | no app email sender found | `no-reply@mail.codyjo.com` | not applicable in current repo state | pending app surface if mail is later added |

## Why Postal API Instead Of SMTP

- The existing code already uses `fetch`-based provider calls inside lambdas.
- Postal API was the lowest-friction path to keep per-product control without introducing SMTP client dependencies into every repo tonight.
- SMTP remains a future option if operationally preferred, but it was not the fastest safe migration path for the existing code layout.
