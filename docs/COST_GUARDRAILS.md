# Cost Guardrails

Last updated: March 24, 2026

## Why This Exists

The March 2026 AWS bill spike was caused by CloudFront invalidation paths, not runtime traffic.

- CloudFront charged about `USD 1,012.35`
- Usage type was `Invalidations`
- Volume was `203,470` invalidation paths
- Back Office dashboard syncs were invalidating `22-23` file paths per publish across two admin distributions

CloudFront pricing is path-based. Batching many paths into one API request does not make it cheap. One request with 23 paths is billed as 23 paths.

## Non-Negotiable Rules

1. Never let deploy code submit an unbounded list of CloudFront invalidation paths.
2. Prefer one wildcard invalidation per namespace: `/*` or `/<prefix>/*`.
3. If versioned assets are available, invalidate only entrypoint documents or avoid invalidations entirely.
4. Any workflow that can run repeatedly (`watch`, `quick-sync`, scheduled jobs, overnight loops, CI/CD) must use the same bounded invalidation helper.
5. Cost-sensitive AWS APIs must fail closed when usage is unexpectedly broad.

## Prevention Checklist

Use this checklist before merging or deploying any AWS-facing change.

### CloudFront

- Invalidation code is routed through a single helper, not assembled ad hoc in scripts.
- Helper enforces a hard maximum path count.
- Multi-path invalidations are collapsed to one wildcard or rejected.
- Static assets use fingerprinted filenames and long cache TTLs.
- HTML and JSON entrypoints use short cache TTLs or are the only invalidated paths.
- CI/CD smoke tests verify deployment, but do not trigger extra invalidations outside the deploy itself.

### Automation

- Repeated execution paths are identified: CI/CD, cron, overnight loops, watch mode, admin scripts.
- Expensive AWS actions are idempotent or explicitly rate-limited.
- One deploy path is preferred over multiple partially-overlapping scripts.
- Manual operator scripts use the same safety checks as CI/CD.

### AWS Billing Controls

- AWS Budget exists for monthly account spend.
- AWS Budget exists for CloudFront spend, or at minimum the main production account.
- Cost Anomaly Detection is enabled for CloudFront.
- Alerts go to a human-owned email or SNS topic that is actually monitored.
- Cost Explorer grouping by `Service`, `Region`, and `Usage Type` is part of incident response.

### IAM

- Deploy roles can only affect the exact buckets and distributions they need.
- No broad `cloudfront:*` or cross-project S3 write permissions.
- Deploy roles for one project do not have permissions for another project unless intentionally shared.

## Portfolio Audit

### High Risk

- `back-office`
  - Former issue: programmatic per-file invalidation in Python sync engine.
  - Repeated entrypoints exist: `scripts/sync-dashboard.sh`, `scripts/quick-sync.sh`, `agents/watch.sh`, `scripts/overnight.sh`, `buildspec-cd.yml`.
  - Current state: fixed in code. Engine and provider now collapse invalidations to one wildcard.

### Medium Risk

- `thenewbeautifulme`
  - Current deploy invalidates `/*` for both public and useradmin distributions in [buildspec-cd.yml](/home/merm/projects/thenewbeautifulme/buildspec-cd.yml#L64).
  - Safe from per-file path explosion, but repeated deploy frequency can still create cost.
- `selah`
  - Current deploy invalidates `/*` in [buildspec-cd.yml](/home/merm/projects/selah/buildspec-cd.yml#L38).
  - Safe from path explosion; still should have CloudFront budget and anomaly alerts.
- `fuel`
  - Current deploy invalidates `/*` in [buildspec-cd.yml](/home/merm/projects/fuel/buildspec-cd.yml#L36).
  - Same recommendation: budget, anomaly detection, versioned assets.
- `certstudy`
  - Current deploy invalidates `/*` in [buildspec-cd.yml](/home/merm/projects/certstudy/buildspec-cd.yml#L35).
  - Safer than Back Office, but still deploy-frequency sensitive.
- `cordivent`
  - Current deploy invalidates `/*` in [buildspec-cd.yml](/home/merm/projects/cordivent/buildspec-cd.yml#L28).
  - Same risk pattern as other static sites.
- `codyjo.com`
  - Current deploy invalidates `/*` in [buildspec-cd.yml](/home/merm/projects/codyjo.com/buildspec-cd.yml#L35).
  - Low path-count risk, but still should be covered by billing alerts.

### Lower Risk

- `analogify`
  - Current deploy invalidates a small fixed list of 6 paths in [buildspec-cd.yml](/home/merm/projects/analogify/buildspec-cd.yml#L58).
  - This is not unbounded, though it still costs more than a single wildcard.
  - Already has an AWS budget in [cost_allocation.tf](/home/merm/projects/analogify/terraform/cost_allocation.tf#L72).

## Recommended Follow-Through

1. Add account-level AWS Budget and Cost Anomaly Detection for CloudFront in the main AWS account.
2. Add per-project monthly budgets for any repo with recurring AWS spend, using `analogify` as the baseline pattern.
3. Standardize a deploy review question: "Is this AWS API billed per request, per path, per GB, per minute, or per resource?"
4. Keep CloudFront invalidation logic centralized and bounded anywhere Back Office touches publishing.
5. Prefer asset fingerprinting over invalidation for frontend repos as they evolve.
