# Current Email Audit

Date: 2026-03-24

## Scope

- Fuel (`fuel.codyjo.com`)
- CertStudy (`study.codyjo.com`)
- Selah (`www.selahscripture.com`)
- Tarot (`www.thenewbeautifulme.com`)
- Cordivent (`www.cordivent.com`)
- Cody Jo Method (`www.codyjo.com`)
- Auth Service (`auth-service`) as an existing shared auth/email code path

## Current State Summary

| Product | Current mail code path before this pass | Auth/code flows found | Status after this pass |
| --- | --- | --- | --- |
| Fuel | `lambda/api/index.mjs` direct `fetch('https://api.resend.com/emails')` | register verification, forgot-password code, verify-email, resend-verification UI | Postal-first adapter added, Fuel resend route fixed, reset flow aligned to code-based backend |
| CertStudy | `lambda/api/index.mjs` direct Resend call | register verification, forgot-password code, verify-email, resend-verification | Postal-first adapter added |
| Selah | `lambda/api/index.mjs` direct Resend call | register verification, forgot-password code, verify-email, resend-verification | Postal-first adapter added |
| Tarot | `lambda/api/index.mjs` + `lambda/api/admin.mjs` direct Resend calls | register verification, forgot-password code, verify-email, resend-verification, admin reset | Postal-first adapter added |
| Cordivent | `lambda/api/index.mjs` + `lambda/scheduler/index.mjs` direct Resend calls | register verification, forgot-password code, verify-email, resend-verification, invites, scheduled sequences | Postal-first adapter added |
| Cody Jo Method | No auth/email sending path found in `codyjo.com` repo | none found | documented only; no code change required in this repo pass |
| Auth Service | `lambda/api/index.mjs` + `lambda/api/admin.mjs` direct Resend calls | register verification, forgot-password code, resend-verification, admin reset | Postal-first adapter added and app branding expanded |

## Fuel Root Cause Findings

### 1. Missing resend-verification route

- UI path: `src/components/EmailVerificationBanner.tsx` calls `resendVerification()` in `src/lib/api.ts`
- API call: `POST /api/auth/resend-verification`
- Backend before fix: `lambda/api/index.mjs` did not expose `/api/auth/resend-verification` in:
  - path-to-method CORS resolution
  - main route dispatch
  - auth handler set
- Result: Fuel verification-code resend was wired in the frontend but absent from the lambda.

### 2. Forgot/reset flow contract mismatch

- Frontend before fix:
  - `src/app/forgot-password/page.tsx` promised a reset link
  - `src/app/reset-password/page.tsx` expected `token` query param and posted `{ token, password }`
  - `src/lib/api.ts` posted `{ token, password }`
- Backend actual contract:
  - `lambda/api/index.mjs` generated a 6-digit code
  - `POST /api/auth/reset-password` expected `{ email, code, newPassword }`
- Result: Fuel password-reset email could send, but the reset UI did not match the API contract.

### 3. Provider/config drift

- Before this pass, Fuel only exposed `RESEND_API_KEY` in Terraform/Lambda env.
- There was no Postal-ready config boundary for:
  - provider selection
  - Postal base URL
  - Postal per-product credentials
  - product-aligned `From` address
  - reply-to handling

## Per-Repo Code Paths Audited

### Fuel

- `lambda/api/index.mjs`
- `src/lib/api.ts`
- `src/app/forgot-password/page.tsx`
- `src/app/reset-password/page.tsx`
- `src/components/EmailVerificationBanner.tsx`
- `terraform/lambda.tf`
- `terraform/variables.tf`

### CertStudy

- `lambda/api/index.mjs`
- `src/lib/api.ts`
- `src/app/forgot-password/page.tsx`
- `src/app/reset-password/page.tsx`
- `terraform/lambda.tf`
- `terraform/variables.tf`

### Selah

- `lambda/api/index.mjs`
- `src/components/EmailVerificationBanner.tsx`
- `src/app/forgot-password/page.tsx`
- `src/app/reset-password/page.tsx`
- `terraform/lambda.tf`
- `terraform/variables.tf`

### Tarot

- `lambda/api/index.mjs`
- `lambda/api/admin.mjs`
- `src/lib/api.ts`
- `src/components/EmailVerificationBanner.tsx`
- `terraform/lambda.tf`
- `terraform/variables.tf`

### Cordivent

- `lambda/api/index.mjs`
- `lambda/scheduler/index.mjs`
- `src/app/settings/page.tsx`
- `src/app/forgot-password/page.tsx`
- `src/app/reset-password/page.tsx`
- `terraform/lambda.tf`
- `terraform/scheduler.tf`
- `terraform/variables.tf`

### Auth Service

- `lambda/api/index.mjs`
- `lambda/api/admin.mjs`
- `terraform/lambda.tf`
- `terraform/variables.tf`

## Assumptions

- Postal API delivery will use `POST /api/v1/send/message` with `html_body` and `plain_body`.
- Per-product sender identity should use clean `mail.` subdomains, not shared `noreply@codyjo.com`.
- Cody Jo Method currently has no app auth/email path in-repo, so this pass only documents its target sender/domain and rollout requirements.
- Resend fallback is intentionally retained behind `EMAIL_PROVIDER` for rollback until Postal DNS, credentials, and delivery validation are complete.
