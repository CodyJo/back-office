# Portfolio Engineering Standard

## Purpose

Set one minimum engineering baseline for the Cody Jo portfolio so repo quality is enforced consistently without forcing unrelated products into one codebase.

## Applies To

Primary user-facing web apps under `/home/merm/projects`:

- `fuel`
- `certstudy`
- `selah`
- `thenewbeautifulme`
- `cordivent`
- `continuum`
- `pattern`
- future apps built on the same Next.js platform

## Required Shared Package Policy

All `@codyjo/*` frontend packages should resolve from:

- `/home/merm/projects/shared/packages`

They should not be maintained as long-lived per-app vendored copies.

## Required Scripts

Every production app must expose:

- `dev`
- `build`
- `lint`
- `test`
- `typecheck`

## Required Frontend Baseline

Every production app should have:

- privacy-respecting analytics only
- privacy page
- accessibility statement page
- skip link in the root layout
- shared app-shell primitives unless a documented exception exists
- consistent auth, theme, and settings conventions where the workflow is structurally the same

## Required Test Baseline

Every production app must pass:

- lint
- typecheck
- unit/integration tests
- build

Every production app should also have smoke e2e coverage for:

- sign-in or sign-up
- navigation
- one core product flow

## Shared Platform Direction

The shared frontend platform should live in `/home/merm/projects/shared/packages` and include:

- existing shared packages (`auth`, `theme`, `ui`, `storage`, `crypto`, `api-client`, `whats-new`, `account-sync`)
- `@codyjo/app-config`
- `@codyjo/app-shell`
- shared service contracts where the same client-side behavior exists across products

## Product Boundary Rule

Share platform concerns, not product semantics.

Good sharing targets:

- app configuration
- navigation shell
- onboarding shell
- session timeout
- PWA prompt behavior
- settings scaffolding
- analytics adapters
- export/download helpers

Bad sharing targets:

- nutrition logic
- spaced-repetition logic
- scripture/tarot/event-specific workflows
- app-specific domain data models unless the semantics are truly the same

## Enforcement

Back Office should treat the following as portfolio drift signals:

- vendored `@codyjo/*` packages
- Next/React version skew beyond the approved baseline
- missing baseline scripts
- missing skip link
- missing privacy page
- missing accessibility statement page
- missing Playwright smoke coverage
- reimplementation of shared shell components where a shared package exists

## Current Tooling

The first enforcement script lives at:

- [`scripts/portfolio_drift_audit.py`](/home/merm/projects/back-office/scripts/portfolio_drift_audit.py)

This should evolve into a normal Back Office audit/check step over time.

The current shared-package model is:

- `/home/merm/projects/shared/packages` is the only approved source of truth for shared frontend packages
- checked-in app-local mirrors such as `vendor/shared-packages` or repo-local `packages/` are treated as drift and should be removed
- CI should receive the `shared` repo directly instead of rebuilding mirror copies inside app repos
