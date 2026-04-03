# Portfolio QA Remediation Planner

> **For agentic workers:** REQUIRED: Use the existing Back Office task queue and approval model. This plan defines a Back Office feature for converting QA findings into risk-based remediation waves rather than acting on severity labels or "AI fixable/easy" tags alone.

**Goal:** Add a first-class Back Office feature that ingests cross-repo QA findings and produces an execution plan grouped into `must_fix_now`, `fix_this_wave`, and `can_defer`, with wave ordering optimized for production risk, architecture leverage, and verification cost.

**Architecture:** Backlog-native planning surface. Start with a documented operating plan and seeded portfolio data, then evolve toward a structured planner that reads existing findings artifacts and emits a normalized remediation plan for dashboard and task queue consumption.

**Tech Stack:** Python (`backoffice/tasks.py`, future planner module), dashboard JSON artifacts, Markdown planning docs

---

## Why This Feature Exists

The current QA queue can surface severity, effort, and fixability, but portfolio execution still needs a higher-order planner that answers:

- which issues must be fixed before shipping anything else,
- which issues should be grouped into a single repo-hardening pass,
- which fixes are blocked on larger architecture changes,
- which lower-severity findings should wait until build and security baselines are stable.

This feature gives Back Office a repeatable way to turn many repo-local findings into a human-reviewable remediation program.

---

## First Seed Data

The first seeded remediation dataset is the March 26, 2026 portfolio QA backlog reviewed in Back Office. The initial recommendation is:

### Wave 1: Must Fix Now

- `back-office`
  - path traversal in product approval endpoint
  - YAML injection in configuration writing
  - `github_repo` validation
  - `target_path` validation
  - lock-file race test cleanup in the same hardening pass
- `auth-service`
  - Unicode-safe email canonicalization for admin allowlist and auth flows
  - registration/email verification flow hardening
  - Secrets Manager error handling
  - lint/test cleanup adjacent to auth hardening
- `continuum`
  - production KMS requirement
  - request size limits
  - content-type validation
  - pagination on memory queries
  - broad API error handling cleanup
  - Next.js security upgrade
- `pe-bootstrap`
  - bare/silent exception handling in auth and secret-loading paths
  - timing-safe passphrase comparison
  - plaintext password handling
  - stricter GCP project-id validation
  - recursion/file I/O safety in classification transforms

### Wave 2: Build / Deployment Reliability

- `cordivent`
  - unresolved shared package imports / build failure
  - CommonJS-in-ESM lint failure
  - dependency advisory remediation
  - image optimization warning cleanup
- `certstudy`
  - React purity/state issues in `SessionTimeout` and `Navigation`
  - failing test mocks
  - Playwright/Vitest separation
  - Next.js security upgrade
  - medium cleanup items adjacent to those changes
- `codyjo.com`
  - vulnerable dependencies
  - blog typecheck failure

### Wave 3: Security Hardening With Product Impact

- `selah`
  - JWT expiration, password policy, login rate limiting, CSP, HSTS
  - remaining auth/privacy hardening items
- `fuel`
  - replace `Math.random()` IDs
  - markdown and API error-surface hardening
- `thenewbeautifulme`
  - hook dependency correctness
  - accessibility and hydration issues
  - DOM prop and image cleanup

### Wave 4: Low-Risk Cleanup

- `analogify`
  - test-only import and formatting cleanup

---

## Feature Shape

### Phase 1: Documented Planner

- [ ] Store this portfolio remediation strategy as a Back Office superpowers plan.
- [ ] Add a Back Office task queue item so the feature is visible in the approval workflow.
- [ ] Treat the March 26, 2026 QA backlog as the first seed dataset.

### Phase 2: Structured Planner Artifact

- [ ] Define a normalized remediation-plan schema, likely JSON mirrored to `results/` and `dashboard/`.
- [ ] Capture per-wave summaries:
  - repo
  - finding ids or titles
  - rationale
  - blocking dependencies
  - expected verification commands
  - approval checkpoint
- [ ] Add server/dashboard read surfaces for the generated plan.

### Phase 3: Automated Recommendation Engine

- [ ] Build a planner that reads findings artifacts from `results/<repo>/`.
- [ ] Group findings by:
  - exploitability / production risk
  - shared root cause
  - build-blocking impact
  - architecture-migration requirement
  - verification leverage
- [ ] Emit proposed waves for human approval instead of auto-executing them.

---

## Acceptance Criteria

- [ ] Back Office has a durable feature-plan document for risk-based QA remediation planning.
- [ ] The task queue contains a Back Office feature entry referencing this plan.
- [ ] The first dataset is captured in a form another agent can reuse without reconstructing context.
- [ ] Future implementation work can extend this plan into a structured artifact and dashboard surface without redefining the product intent.

---

## Initial Notes For Implementation

- The planner should not rely on severity alone.
- `AI fixable` and `easy` are advisory filters, not execution priority.
- Server-side exploitability, auth/session design flaws, and build blockers should outrank low-cost cleanup.
- Large auth-storage changes such as migrating away from localStorage should remain visible but can be marked deferred when they require deeper architecture work.
