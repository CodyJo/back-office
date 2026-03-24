# Back Office Handoff

Last updated: March 24, 2026

## Current Direction

Back Office is the portfolio control plane for local repo audits, dashboard aggregation, delegated task tracking, and dashboard publishing. The immediate priority is cost-safe dashboard publishing: the March 2026 AWS bill spike was traced to CloudFront invalidation charges from Back Office sync behavior, and the sync path now has both engine-level and provider-level safeguards to keep invalidation cost bounded.

## Completed

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

- Review the existing dirty worktree files before bundling Back Office changes into any future commit. This repo already contains pre-existing modified and untracked files outside this change.

## Key Decisions And Constraints

- The billing math matched exactly: CloudFront invalidation pricing is effectively `($0.005 * (paths - 1000 free))`; `203,470 - 1,000 = 202,470`, and `202,470 * 0.005 = USD 1,012.35`.
- The spike came from repeated dashboard syncs over a short window on March 24, 2026, not from normal traffic volume, Lambda usage, or origin transfer.
- Provider-level normalization is required in addition to engine-level shaping because Back Office has multiple sync invocation paths (`make dashboard`, `quick-sync`, `watch`, `overnight`, CodeBuild CD).
- AWS Cost Anomaly Detection can use `IMMEDIATE` only when the subscriber is SNS. Direct email subscriptions require `DAILY` or `WEEKLY`.
- Do not assume the repo is clean; there were pre-existing modified and untracked files unrelated to this fix.

## Files To Read First

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

- Dashboard target definitions: `config/backoffice.yaml`
- Dashboard publish entrypoints: `scripts/sync-dashboard.sh`, `scripts/quick-sync.sh`
- Sync caller paths:
  - `Makefile`
  - `agents/watch.sh`
  - `scripts/overnight.sh`
  - `buildspec-cd.yml`
- CloudFront targets:
  - `E30Z8D5XMDR1A9`
  - `E372ZR95FXKVT5`
  - `EF4U8A7W3OH5K` if public publish is ever enabled

## Recommended Next Steps

1. Confirm the email subscription on `back-office-billing-alerts` is accepted by the mailbox recipient.
2. Keep new deploy code aligned with the checklist in `docs/COST_GUARDRAILS.md`.

## Verification

- `python3 -m pytest tests/test_sync_engine.py tests/test_sync_providers.py`
- `terraform -chdir=/home/merm/projects/back-office/terraform validate`
- `terraform -chdir=/home/merm/projects/back-office/terraform plan`
- `terraform -chdir=/home/merm/projects/back-office/terraform apply -auto-approve`
