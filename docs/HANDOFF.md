# Back Office Handoff

Last updated: March 25, 2026

## Current Direction

Back Office is centered on a human-centered approval model. The immediate product direction is: findings can be queued from the dashboard for approval, product additions are suggested instead of auto-added, draft GitHub PRs are opened only after explicit approval, and backlog visibility is isolated by product so queue counts do not bleed across repos.

## Completed

- Added local safety defaults so Back Office can be used against `~/projects` without accidental CloudFront cost or unattended execution:
  - `backoffice.sync.engine` now blocks remote publish by default unless `BACK_OFFICE_ENABLE_REMOTE_SYNC=1` is set, while still allowing CI/CodeBuild delivery paths
  - `backoffice.server` now blocks overnight start from the local dashboard unless `BACK_OFFICE_ENABLE_UNATTENDED=1` is set
  - `Makefile` now requires explicit opt-in for:
    - remote publish: `BACK_OFFICE_ENABLE_REMOTE_SYNC=1`
    - auto-fix: `BACK_OFFICE_ENABLE_AUTOFIX=1`
    - unattended workflows: `BACK_OFFICE_ENABLE_UNATTENDED=1`
  - `audit-all` and `audit-all-parallel` now refresh the local dashboard with `python3 -m backoffice refresh` instead of publishing remotely
  - `watch`, `scan-and-fix`, and `full-scan` no longer piggyback remote sync by default
- Added regression coverage for the new local safety defaults:
  - `tests/test_sync_engine.py` verifies remote sync is blocked unless explicitly enabled
  - `tests/test_servers.py` verifies overnight start is blocked by default
- Verified the local safety changes with:
  - `python3 -m pytest tests/test_sync_engine.py tests/test_servers.py tests/test_tasks.py tests/test_backlog.py`
  - `ruff check backoffice/sync/engine.py backoffice/server.py tests/test_sync_engine.py tests/test_servers.py`
- Audited the current GitHub-facing claims against the actual codebase and confirmed the main story is only partially supported:
  - approval queue, task persistence, per-product queue summaries, and draft PR creation are implemented
  - the repo still contains legacy autonomous and auto-fix paths (`overnight`, `watch --auto-fix`, `scan-and-fix`, `full-scan`) that contradict the strongest "nothing runs unattended" and "approval before execution" language in the README
  - GitHub PR creation is implemented, but the dashboard/server path only covers `pending_approval -> ready` and `ready_for_review -> pr_open`; moving work from `ready` to `ready_for_review` still depends on the task CLI or external workflow
  - cost-control claims around bounded CloudFront invalidation are supported in both `backoffice/sync/engine.py` and `backoffice/sync/providers/aws.py`
- Audited the dirty Back Office worktree and separated it into:
  - a coherent approval-workflow feature (`backoffice/tasks.py`, `backoffice/server.py`, `dashboard/index.html`, `tests/test_tasks.py`, `tests/test_servers.py`)
  - a coherent portfolio tooling set (`scripts/sync_shared_packages.py`, `tests/test_sync_shared_packages.py`, `scripts/portfolio_drift_audit.py`, `docs/portfolio-engineering-standard.md`)
  - generated or scratch artifacts that should not be blindly committed (`coverage.json`, `coverage.xml`, `lint-check.json`, `lint-output.json`, `pytest-output.txt`, `ruff-output.json`, one-off audit plans)
- Re-verified the approval workflow changes after the doc refresh with:
  - `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`
- Verified the shared package sync utility with:
  - `python3 -m pytest tests/test_sync_shared_packages.py`
- Refreshed the GitHub-facing documentation to present Back Office as a visibility-first, approval-driven control plane:
  - rewrote `README.md` around dashboard observability, approval queue behavior, GitHub review, and operator control
  - rewrote `docs/WORKFLOW-ARCHITECTURE.md` with deeper architecture detail and multiple diagrams for findings, backlog, queue, and delivery flow
  - rewrote `docs/CICD-REFERENCE.md` to explain CI/CD in the context of queue approval and GitHub review
- Migrated `selah` onto the same `@codyjo/app-config` / `@codyjo/app-shell` consumer pattern as Fuel and CertStudy, then synced vendored packages and verified Selah with targeted tests, typecheck, and a full build.
- Added approval-first task queue primitives in `backoffice/tasks.py`:
  - new statuses for `pending_approval`, `approved`, `queued`, and `pr_open`
  - per-product queue summaries so backlog counts stay isolated by `product_key`
  - helper constructors for queued finding fixes and product suggestions
- Added dashboard server endpoints in `backoffice/server.py` for:
  - queueing a finding from the dashboard into the human approval queue
  - approving or cancelling queued work
  - suggesting a product for approval
  - approving a suggested product and adding it to config
  - creating a draft GitHub PR for approved work so merge still requires GitHub review
- Reworked the dashboard UI in `dashboard/index.html`:
  - finding detail now includes `Queue for Approval`
  - Operations tab now shows `Approval Queue` as the primary decision surface
  - product onboarding now starts as `Suggest Product`, not direct add
  - approval cards surface per-product backlog numbers and explicit approval actions
- Added regression coverage in `tests/test_tasks.py` and `tests/test_servers.py` for the new queue summaries and approval endpoints.
- Verified the approval workflow changes with:
  - `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`

- Extended `@codyjo/app-config` with a shared metadata builder, adopted it in Fuel and CertStudy layouts, and added Fuel's missing accessibility page so the audit baseline closes that gap.
- Ran the first real consumer migration for `fuel` and `certstudy` onto `@codyjo/app-config` / `@codyjo/app-shell`, then verified both apps with targeted tests, typecheck, and full builds.
- Built `@codyjo/app-config` and `@codyjo/app-shell` in `/home/merm/projects/shared`, synced them into vendored app mirrors with `scripts/sync_shared_packages.py`, and confirmed the sync utility with `tests/test_sync_shared_packages.py`.
- Investigated the March 2026 AWS bill spike and confirmed it was not Lambda/runtime cost. `Amazon CloudFront` billed about `USD 1,012.35`, almost entirely from `Invalidations` on `203,470` paths.
- Confirmed the expensive path came from Back Office dashboard syncs targeting distributions `E30Z8D5XMDR1A9` (`admin.codyjo.com`) and `E372ZR95FXKVT5` (`admin.thenewbeautifulme.com`).
- Verified live invalidation batches on March 24, 2026 contained `22-23` file paths each, matching the old per-file invalidation behavior.
- Patched `backoffice/sync/engine.py` so sync invalidations collapse to one wildcard path per target:
  - root target: `/*`
  - prefixed target: `/<prefix>/*`
- Patched `backoffice/sync/providers/aws.py` so any future multi-path invalidation batch is normalized down to a single wildcard before it reaches CloudFront.
- Patched `buildspec-cd.yml` to seed `config/backoffice.yaml` from a tracked CodeBuild-safe config template so deploys no longer depend on the untracked local config file.
- Added `config/backoffice.codebuild.example.yaml` as the tracked CI/CD deploy config source.
- Added regression coverage in `tests/test_sync_engine.py` and `tests/test_sync_providers.py`.
- Verified the sync changes with:
  - `python3 -m pytest tests/test_sync_engine.py tests/test_sync_providers.py`
- Ran `bash /home/merm/projects/back-office/scripts/sync-dashboard.sh` locally on March 24, 2026 and confirmed both dashboard distributions invalidated exactly one path each.
- Audited the other AWS-backed portfolio repos for the same CloudFront invalidation failure mode and documented the result in `docs/COST_GUARDRAILS.md`.
  - `thenewbeautifulme`, `selah`, `fuel`, `certstudy`, `cordivent`, and `codyjo.com` currently invalidate one wildcard path (`/*`) in their CD pipelines, so they do not have the same unbounded per-file invalidation bug.
  - `analogify` invalidates a small fixed path list and already has an AWS budget configured.
- Added account-level billing guardrails in `terraform/cost_guardrails.tf` and applied them live on March 24, 2026:
  - Monthly account budget: `back-office-account-monthly` at `USD 250`
  - Monthly CloudFront budget: `back-office-cloudfront-monthly` at `USD 100`
  - Service-level Cost Anomaly monitor for `SERVICE`
  - Immediate SNS-backed anomaly subscription with `ANOMALY_TOTAL_IMPACT_ABSOLUTE >= USD 20`
  - SNS topic: `back-office-billing-alerts`
- Verified the Terraform changes with:
  - `terraform -chdir=/home/merm/projects/back-office/terraform validate`
  - `terraform -chdir=/home/merm/projects/back-office/terraform plan`
  - `terraform -chdir=/home/merm/projects/back-office/terraform apply -auto-approve`
- Added live per-project monthly AWS budgets for the remaining CloudFront-backed repos:
  - `thenewbeautifulme-monthly` at `USD 100`
  - `bible-app-monthly` at `USD 75`
  - `fuel-monthly` at `USD 50`
  - `certstudy-monthly` at `USD 50`
  - `etheos-app-monthly` at `USD 50`
  - `codyjo-com-monthly` at `USD 50`

## Pending

- Decide whether to commit and push the local safety default changes. At the moment they are implemented and tested locally but not yet committed.
- Decide whether to bring the code in line with the approval-first docs or soften the docs to match reality. The current gap is specifically around:
  - `Makefile` targets: `watch`, `scan-and-fix`, `full-scan`, and all `overnight*` targets
  - `backoffice/server.py` overnight start/stop/status endpoints
  - dashboard copy that says "Nothing runs unattended" while direct fix commands still exist
- If the approval-first story is the product direction, add an explicit server/dashboard/worker path for `ready -> in_progress -> ready_for_review` so the GitHub PR flow is truly end-to-end from the queue.
- Generated and scratch files are still present locally and should stay out of normal pushes unless there is an explicit archival reason:
  - `coverage.json`, `coverage.xml`, `lint-check.json`, `lint-output.json`, `pytest-output.txt`, `ruff-output.json`
  - `2026-03-23-compliance-audit-plan.md`
  - `AUDIT_PLAN-analogify.md`
  - `docs/superpowers/plans/2026-03-23-fuel-monetization-audit.md`
  - `docs/superpowers/plans/2026-03-24-monetization-audit-tnbm.md`
  - `generate-codyjo-monetization.js`
  - `docs/email/` if you do not want cross-repo implementation notes living in Back Office
- Decide whether to remove the remaining legacy automation codepaths entirely or keep them as internal-only compatibility surfaces. The primary dashboard UX and GitHub docs now center on approval-driven operation.
- Browser-verify the new approval queue interactions in `dashboard/index.html`. The Python test suite passed, but the new UI flow was not exercised in a live browser in this pass.
- If draft PR creation will be used heavily, add a targeted server test for the `gh pr create` success/failure path with subprocess mocking.
- Consider refreshing secondary docs and generated dashboard documentation surfaces if you want the same approval-first story everywhere, not just in the core GitHub docs.

## Key Decisions And Constraints

- The billing math matched exactly: CloudFront invalidation pricing is effectively `($0.005 * (paths - 1000 free))`; `203,470 - 1,000 = 202,470`, and `202,470 * 0.005 = USD 1,012.35`.
- The spike came from repeated dashboard syncs over a short window on March 24, 2026, not from normal traffic volume, Lambda usage, or origin transfer.
- Provider-level normalization is required in addition to engine-level shaping because Back Office has multiple sync invocation paths (`make dashboard`, `quick-sync`, `watch`, and CodeBuild CD).
- AWS Cost Anomaly Detection can use `IMMEDIATE` only when the subscriber is SNS. Direct email subscriptions require `DAILY` or `WEEKLY`.
- Do not assume the repo is clean; there were pre-existing modified and untracked files unrelated to this fix.
- The new approval workflow intentionally does not auto-run fixes when a finding is clicked. Clicking a finding now queues human-reviewable work; approval moves it to `ready`, and draft PR creation is a separate explicit action.
- `gh pr create` is executed from the task's `target_path` and intentionally refuses to open a PR from `main` or `master`.
- Product backlog isolation now comes from task queue summaries grouped by `product_key`; if future dashboards still show crossed counts, inspect product mapping in `dashboard/org-data.json` and `backoffice/tasks.py::infer_product_key`.

## Files To Read First

- `README.md`
- `docs/WORKFLOW-ARCHITECTURE.md`
- `docs/CICD-REFERENCE.md`
- `backoffice/tasks.py`
- `backoffice/server.py`
- `dashboard/index.html`
- `tests/test_tasks.py`
- `tests/test_servers.py`
- `backoffice/sync/engine.py`
- `backoffice/sync/providers/aws.py`
- `tests/test_sync_engine.py`
- `tests/test_sync_providers.py`
- `config/backoffice.yaml`
- `buildspec-cd.yml`
- `docs/COST_GUARDRAILS.md`
- `terraform/cost_guardrails.tf`
- `terraform/variables.tf`

## Integration Points

- Approval queue artifacts:
  - `config/task-queue.yaml`
  - `results/task-queue.json`
  - `dashboard/task-queue.json`
- Approval actions served by:
  - `backoffice/server.py`
  - `dashboard/index.html`
- Dashboard target definitions: `config/backoffice.yaml`
- Dashboard publish entrypoints: `scripts/sync-dashboard.sh`, `scripts/quick-sync.sh`
- Sync caller paths:
  - `Makefile`
  - `agents/watch.sh`
  - `buildspec-cd.yml`
- CloudFront targets:
  - `E30Z8D5XMDR1A9`
  - `E372ZR95FXKVT5`
  - `EF4U8A7W3OH5K` if public publish is ever enabled

## Recommended Next Steps

1. Browser-test the new finding queue, product suggestion, approval, and draft PR actions end-to-end from the dashboard.
2. Decide whether to fully remove or formally deprecate the remaining legacy automation codepaths so the product story stays consistent with the approval-centric docs and UI.
3. Confirm the email subscription on `back-office-billing-alerts` is accepted by the mailbox recipient.
4. Keep new deploy code aligned with the checklist in `docs/COST_GUARDRAILS.md`.

## Verification

- `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`
- `python3 -m pytest tests/test_sync_engine.py tests/test_sync_providers.py`
- `terraform -chdir=/home/merm/projects/back-office/terraform validate`
- `terraform -chdir=/home/merm/projects/back-office/terraform plan`
- `terraform -chdir=/home/merm/projects/back-office/terraform apply -auto-approve`

## 2026-03-25 Portfolio Standards Kickoff

- Added `scripts/sync_shared_packages.py` to copy source-of-truth shared packages into app-local vendor directories for repos that still require self-contained builds.
- Added `/home/merm/projects/shared/packages/app-shell` with first-pass shared shell helpers for skip-link/main-content consistency and versioned onboarding state.
- Added `docs/portfolio-engineering-standard.md` to define the portfolio baseline for shared packages, accessibility, testing, and shell conventions.
- Added `scripts/portfolio_drift_audit.py` as the first-pass automated drift check for the Next.js app portfolio.
- Added `/home/merm/projects/shared/packages/app-config` as the first new shared package for config-driven app metadata and shell extraction.
- Intended next step: create `@codyjo/app-shell`, then migrate Fuel and CertStudy first.
