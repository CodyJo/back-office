# Shared Package Distribution Roadmap

Last updated: March 25, 2026

## Current State

All seven Next.js apps now declare `@codyjo/*` dependencies from `/home/merm/projects/shared/packages`.

Live as of March 25, 2026:
- `fuel`, `certstudy`, `selah`, `thenewbeautifulme`, and `continuum` CodeBuild projects all consume `CodyJo/shared` as a secondary GitHub source exposed as `CODEBUILD_SRC_DIR_shared`.
- no app still requires buildspec fallback copy blocks.
- no checked-in shared-package mirror directories remain in the Next app repos.
- the mirror sync utility has been retired because it no longer matches the delivery model.
- the shared Terraform CodeBuild module release is published as `codebuild-module-v2`.

## Recommended Next Step

The shared-package delivery migration is complete. The remaining portfolio work is product-quality standardization:
1. keep dependency/runtime versions aligned across the Next apps
2. add or maintain baseline Playwright smoke coverage in every production app
3. keep accessibility and privacy statement coverage consistent across the portfolio
4. evolve toward versioned shared-package releases if file-based sharing becomes a bottleneck

## Viable Delivery Options

### Option A: Secondary shared source checkout in CI

Use CodeBuild secondary sources so each app build receives both:
- the app repo
- the `shared` repo

Pros:
- simplest conceptual model
- no package publishing system required
- keeps file-based installs working

Cons:
- CI config becomes multi-source
- private repo auth must be configured correctly in CodeBuild
- Docker builds still need the shared source copied into the container context

### Option B: Package artifact publish step

Build tarballs or publishable package artifacts from `shared`, then have app CI download those artifacts before `npm ci`.

Pros:
- clean separation between source and consumers
- works well for isolated CI environments

Cons:
- requires artifact hosting and versioning discipline
- more release-process work than Option A

### Option C: Private npm registry / package service

Publish `@codyjo/*` to a private registry and replace `file:` dependencies with versioned package references.

Pros:
- standard package-consumption model
- best long-term scaling story

Cons:
- largest ops/setup cost right now
- requires versioning and release automation across all packages

## Recommendation

Option A is now the live delivery model. Revisit Option C only when the shared package set or release cadence makes versioned publishing worth the overhead.
