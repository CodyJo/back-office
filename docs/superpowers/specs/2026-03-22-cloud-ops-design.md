# Cloud Ops Department — Design Spec

**Date:** 2026-03-22
**Department:** Cloud Ops
**Status:** Draft

## Overview

Cloud Ops is a new Back Office department that performs an AWS Well-Architected Review scoped to infrastructure gaps not covered by existing departments. It audits Terraform files (static analysis, no AWS credentials required) across all 6 Well-Architected pillars, producing per-pillar scores and a weighted composite score.

## Motivation

Existing departments audit code (QA), content/markup (SEO, ADA), legal frameworks (Compliance), revenue opportunities (Monetization), and product direction (Product). None of them audit the AWS infrastructure layer — IAM policies, Lambda configuration, DynamoDB capacity modes, S3 lifecycle policies, CloudFront cache settings, or Terraform quality. Cloud Ops fills this gap.

## Scope

### What Cloud Ops audits (infrastructure layer):

| Pillar | Weight | Focus |
|---|---|---|
| Cost Optimization | 30% | Unused resources, over-provisioned capacity, missing lifecycle policies, architecture choices (arm64), tagging |
| Security | 25% | IAM overprivilege, missing encryption, public exposure, missing key rotation |
| Reliability | 20% | Missing DLQ/retry config, no PITR, missing versioning, no backup strategy, missing error responses |
| Performance Efficiency | 10% | Lambda memory tuning, CloudFront cache policies, missing indexes, compression, arm64 |
| Operational Excellence | 10% | Missing alarms, no log retention, Terraform module reuse, missing tags, state locking, CI/CD gaps |
| Sustainability | 5% | Right-sizing, provisioned→on-demand, x86→arm64, unused log groups |

### What Cloud Ops does NOT audit (covered by other departments):

- Code-level security (OWASP) → QA
- Frontend performance (Core Web Vitals) → SEO
- Accessibility → ADA
- Legal/regulatory compliance → Compliance
- Revenue opportunities → Monetization
- Feature gaps, tech debt in code → Product

## Architecture

### Approach: Single Agent, Phased Prompt (Approach C)

Follows the QA department pattern — one agent with an explicitly phased prompt. Each phase focuses on one pillar. The agent completes all phases in a single run, producing one findings file.

This maintains the "one department = one script = one prompt = one findings file" convention used by all existing departments.

## Components

### 1. Agent Prompt (`agents/prompts/cloud-ops-audit.md`)

**Role:** Cloud Infrastructure Analyst performing a Well-Architected Review.

**7 Phases (1 discovery + 6 pillar audits):**

1. **Discover** — Find all `.tf` files, identify AWS services in use. Read `CLAUDE.md` and `README.md` for project context.
2. **Cost Optimization** — Unused resources, over-provisioned capacity, missing lifecycle policies, price class choices, arm64 vs x86, missing cost allocation tags.
3. **Security** — IAM `*` actions/resources, missing encryption (S3 SSE, DynamoDB, Lambda env vars), public buckets, overpermissive security groups, missing KMS rotation, VPC considerations.
4. **Reliability** — Missing DLQ/failure destinations, no retry config, DynamoDB missing PITR, S3 missing versioning, no backup strategy, single-region considerations, missing CloudFront custom error responses.
5. **Performance Efficiency** — Default Lambda memory (128MB), missing CloudFront cache/TTL policies, DynamoDB missing GSIs, Lambda timeout tuning, missing compression, arm64/graviton.
6. **Operational Excellence** — Missing CloudWatch alarms, no log retention policies, Terraform not using modules, missing resource tags, no state locking, missing outputs, CI/CD gaps.
7. **Sustainability** — Right-sizing opportunities, provisioned→on-demand, x86→arm64, unused CloudWatch log groups.

**Rules:**
- Only audit Terraform files — no AWS CLI calls, no credential requirements
- Every finding must have evidence (the actual Terraform code) and a fix suggestion
- Mark `fixable_by_agent: true` for config changes (memory_size, tags, lifecycle rules)
- Mark `fixable_by_agent: false` for architectural changes (VPC placement, multi-region)
- Estimate effort honestly
- No false positives — if a configuration is intentional and documented, skip it

### 2. Agent Launcher (`agents/cloud-ops-audit.sh`)

Follows `qa-scan.sh` pattern:

1. Accept `TARGET` repo path and optional `--sync` flag
2. Validate git repo
3. Check for `terraform/` directory — if absent, write a full findings JSON to `results/<repo_name>/cloud-ops-findings.json` with all `pillar_scores` at 100, `cloud_ops_score` at 100, and a single info finding (`COPS-000: "No Terraform directory found"`), then exit cleanly
4. Read config from `targets.yaml` via `parse-config.py`
5. Concatenate prompt with target metadata
6. Launch agent runner with tools: `Read, Glob, Grep, Bash, Write, Agent`
7. Output to `results/<repo_name>/cloud-ops-findings.json`
8. Optionally sync via `quick-sync.sh`

No `WebSearch` or `WebFetch` — static analysis only.

**Note:** Existing launchers carry a dead `CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"` variable that is set but never used. The Cloud Ops launcher should reference `targets.yaml` only and not carry forward this dead variable.

### 3. Findings Schema

Standard Back Office findings with Cloud Ops-specific fields:

```json
{
  "scan_id": "uuid",
  "repo_name": "selah",
  "repo_path": "/home/merm/projects/selah",
  "scanned_at": "2026-03-22T10:00:00Z",
  "scan_duration_seconds": 90,
  "summary": {
    "total": 12,
    "critical": 1,
    "high": 3,
    "medium": 5,
    "low": 2,
    "info": 1
  },
  "pillar_scores": {
    "cost_optimization": 72,
    "security": 85,
    "reliability": 68,
    "performance_efficiency": 91,
    "operational_excellence": 80,
    "sustainability": 95
  },
  "pillar_weights": {
    "cost_optimization": 0.30,
    "security": 0.25,
    "reliability": 0.20,
    "performance_efficiency": 0.10,
    "operational_excellence": 0.10,
    "sustainability": 0.05
  },
  "cloud_ops_score": 79,
  "findings": [
    {
      "id": "COPS-001",
      "severity": "high",
      "pillar": "cost_optimization",
      "category": "over-provisioned",
      "title": "Lambda memory set to 1024MB but avg usage is under 128MB",
      "description": "Detailed explanation",
      "file": "terraform/lambda.tf",
      "line": 34,
      "evidence": "memory_size = 1024",
      "impact": "Paying ~8x more than needed for this function",
      "fix_suggestion": "Set memory_size = 128 and monitor with Lambda Power Tuning",
      "effort": "easy",
      "fixable_by_agent": true
    }
  ]
}
```

**Cloud Ops-specific fields:**
- `pillar` — WAR pillar name (cost_optimization, security, reliability, performance_efficiency, operational_excellence, sustainability)
- `pillar_scores` — per-pillar scores (0-100)
- `pillar_weights` — weight per pillar for composite calculation
- `cloud_ops_score` — weighted composite score
- Finding IDs prefixed `COPS-`

**Finding categories per pillar:**

| Pillar | Categories |
|---|---|
| cost_optimization | unused-resource, over-provisioned, missing-lifecycle-policy, reserved-vs-ondemand |
| security | iam-overprivilege, missing-encryption, public-exposure, missing-rotation |
| reliability | no-backup, single-az, missing-dlq, no-retry-config |
| performance_efficiency | lambda-memory-tuning, missing-cache-policy, missing-index, cold-start |
| operational_excellence | missing-monitoring, no-alarms, iac-drift, missing-tags |
| sustainability | right-sizing, unused-provisioned-capacity |

### 4. Scoring

**Per-pillar scoring:** Start at 100, deduct by severity:
- Critical: -15
- High: -8
- Medium: -3
- Low: -1
- Floor: 0

**Composite scoring:**
```
cloud_ops_score = round(
    cost_optimization * 0.30 +
    security * 0.25 +
    reliability * 0.20 +
    performance_efficiency * 0.10 +
    operational_excellence * 0.10 +
    sustainability * 0.05
)
```

### 5. Aggregation (`backoffice/aggregate.py`)

Uses existing `aggregate_department()` function:

```python
cloud_ops = aggregate_department(results_dir, "cloud-ops-findings.json", "cloud-ops", valid_repos)
write_json(dashboard_dir / "cloud-ops-data.json", cloud_ops)
```

Additions to existing code:

**`backoffice/backlog.py` — `normalize_finding()`:**
Add a `cloud-ops` block to preserve the `pillar` field (alongside existing department-specific blocks for `monetization`, `compliance`, `ada`):

```python
if department == "cloud-ops":
    if "pillar" in raw:
        canonical["pillar"] = raw["pillar"]
```

**`backoffice/aggregate.py` — `normalize_precalculated_summary()`:**
Add `cloud-ops` to the `score_map` dictionary:

```python
"cloud-ops": (
    "cloud_ops_score",
    [data.get("cloud_ops_score")],
),
```

Additionally, `pillar_scores` must be surfaced in the aggregated repo entry. In `aggregate_department()`, add handling to pass through `pillar_scores` from the raw findings data into the repo entry (similar to how `scores` dict is currently handled).

**`backoffice/aggregate.py` — `aggregate()` function:**
- Add cloud-ops to the grand total counter (hardcoded sum of department finding counts)
- Add `"cloud-ops": cloud_ops_data` to `dept_data_map` so cloud-ops findings flow into `merge_backlog()` and `update_score_history()`

**`backoffice/aggregate.py` — score history extraction:**
Add `summary.get("cloud_ops_score")` to the score extraction chain used for non-QA departments.

### 6. Dashboard (`dashboard/index.html`)

**JavaScript registration:**
- Add `'cloud-ops'` to `DEPT_KEYS` array
- Add to `DEPT_SOURCES`: `'cloud-ops': {url: 'cloud-ops-data.json', scoreField: 'cloud_ops_score'}`

**Score card:** 7th card in score-row grid. Shows `cloud_ops_score` with sparkline. Label: "Cloud Ops".

**Grid layout adjustment:** Change `.score-row` from `repeat(6, 1fr)` to `repeat(auto-fill, minmax(160px, 1fr))` for responsive wrapping that handles 7 cards cleanly. The 1100px breakpoint can use `repeat(4, 1fr)` (4+3 layout) instead of `repeat(3, 1fr)` (which would leave an orphan). The 700px breakpoint at `repeat(2, 1fr)` works fine (4+3 → 2+2+2+1).

**Slide-over panel (65% width):**
- Pillar breakdown bar — 6 horizontal mini-bars with per-pillar scores, color-coded (green >80, yellow 50-80, red <50), showing weights
- Filter bar — severity, status, effort, fixable, pillar dropdown, search. The pillar dropdown is an additional `<select>` element that only renders when the active department is `cloud-ops`. It filters on `finding.pillar`. Extend `applyFilters()` to check for an active pillar filter and match against `finding.pillar` when present.
- Findings list — standard cards with pillar badge + severity badge
- Finding detail (45% width) — evidence, fix suggestion, backlog info

**Data source:** `cloud-ops-data.json`

### 7. Makefile

**New target:**
```makefile
cloud-ops: ## Run Cloud Ops audit on TARGET repo
	@test -n "$(TARGET)" || (echo "Usage: make cloud-ops TARGET=/path/to/repo" && exit 1)
	bash agents/cloud-ops-audit.sh "$(TARGET)"
```

**Audit waves (updated):**
- Wave 1 (parallel): QA + SEO + ADA + Cloud Ops (Cloud Ops is lightweight Terraform static analysis, adds minimal load to Wave 1)
- Wave 2 (parallel): Compliance + Monetization + Product

**Sequential audit-all:** append `cloud-ops` to the list.

**`audit-live` target:** Also add Cloud Ops to Wave 1, plus a `quick-sync.sh cloud-ops` call after completion.

**`job-status.sh init` strings:** Update the department list in both `audit-all` and `audit-all-parallel` targets from `"qa seo ada compliance monetization product"` to `"qa seo ada compliance monetization product cloud-ops"`.

**`clean` target:** Add `dashboard/cloud-ops-data.json` to the `rm -f` list.

### 8. Standards Reference (`lib/cloud-ops-standards.md`)

Focused checklist of serverless anti-patterns per pillar, scoped to: Lambda, DynamoDB, S3, CloudFront, IAM, Terraform, CodeBuild, Route53, ACM.

No enterprise patterns (Transit Gateway, multi-account, Control Tower, Organizations, Service Catalog).

### 9. Config (`config/targets.yaml`)

Add `cloud-ops` to `default_departments` for repos that have a `terraform/` directory.

## Files to Create

| File | Purpose |
|---|---|
| `agents/prompts/cloud-ops-audit.md` | System prompt (phased, 6 pillars) |
| `agents/cloud-ops-audit.sh` | Agent launcher |
| `lib/cloud-ops-standards.md` | Standards reference |

## Files to Modify

| File | Change |
|---|---|
| `Makefile` | Add `cloud-ops` target; update `audit-all`, `audit-all-parallel`, `audit-live` wave lists; update `job-status.sh init` strings; add `cloud-ops-data.json` to `clean` target |
| `backoffice/aggregate.py` | Add `aggregate_department()` call for cloud-ops; add `cloud-ops` to `score_map` in `normalize_precalculated_summary()`; add to `dept_data_map` for backlog/history; add to grand total counter; add `cloud_ops_score` to score history extraction chain; handle `pillar_scores` passthrough in repo entry |
| `backoffice/backlog.py` | Add `cloud-ops` block in `normalize_finding()` to preserve `pillar` field |
| `dashboard/index.html` | Add `cloud-ops` to `DEPT_KEYS` and `DEPT_SOURCES`; add 7th score card; change grid to `auto-fill, minmax(160px, 1fr)`; update 1100px breakpoint to `repeat(4, 1fr)`; add slide-over panel with pillar breakdown bars; add conditional pillar dropdown to filter bar; extend `applyFilters()` for pillar filtering |
| `config/targets.yaml` | Add `cloud-ops` to `default_departments` for repos with `terraform/` directories |
| `tests/` | Add test cases for cloud-ops aggregation, pillar normalization, and score history if `test_aggregate.py` or similar exists |

## Out of Scope

- Live AWS CLI queries (future enhancement)
- AWS Cost Explorer integration (future enhancement)
- Multi-account analysis
- Enterprise WAR patterns (Transit Gateway, Control Tower, etc.)
- Drift detection against live state
