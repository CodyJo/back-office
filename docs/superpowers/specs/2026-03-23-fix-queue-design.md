# Manual Fix Queue — Design Spec

**Date:** 2026-03-23
**Status:** Draft

## Overview

Add a manual fix queue to Back Office that lets the user cherry-pick which findings get fixed on the next fix run. Findings from any department with `fixable_by_agent: true` can be queued via the HQ dashboard or CLI. A dedicated `make fix-queued` command runs the fix agent against only queued items.

## Motivation

Currently, the fix agent either fixes everything by severity (manual `make fix`) or follows the Product Owner's prioritized plan (overnight loop). There's no way to say "fix these 3 specific findings and nothing else." The manual queue gives precise control over what gets fixed, when.

## Architecture

### Approach: Backlog-Native (Approach A)

Extend the existing `dashboard/backlog.json` with two new statuses (`"queued"`, `"fix_failed"`) and add a queue API endpoint to the existing server. No new files, no new data flows. The dashboard gets a "Queue for Fix" button, the CLI gets `queue` subcommands, and a new `make fix-queued` runs the fix agent against only queued findings.

## Components

### 1. Backlog Status Extension

Two new statuses added to the finding lifecycle:

```
open → queued → fixed       (happy path)
open → queued → fix_failed  (agent tried, failed)
fix_failed → queued         (re-queue for retry)
fix_failed → open           (give up, back to normal)
fix_failed → skipped        (won't fix)
queued → open               (dequeue, changed your mind)
```

No code changes to `backoffice/backlog.py` for status storage — the `status` field is already free-form. Consumers (dashboard, fix agent, CLI) need to recognize the new values.

**Sticky status protection in `merge_backlog()`:**

Scans produce findings with `status: "open"`, which would overwrite `"queued"` on the next aggregation run. Fix: add a `STICKY_STATUSES` set and preserve those during merge.

```python
STICKY_STATUSES = {"queued", "fix_failed"}
```

In `merge_backlog()`, replace the status update line:

```python
# Before:
entry["status"] = finding.get("status", entry.get("status", "open"))

# After:
incoming_status = finding.get("status", "open")
current_status = entry.get("status", "open")
if current_status not in STICKY_STATUSES:
    entry["status"] = incoming_status
```

### 2. API Endpoint

Add queue endpoints to the existing `backoffice/server.py` (runs on `make jobs` port 8070):

**`POST /api/queue/{hash}`** — Set finding status to `"queued"`
- Validates hash exists in backlog.json
- Validates `current_finding.fixable_by_agent` is true
- Returns 400 if not fixable, 404 if hash not found
- Returns `{status: "queued", hash: "...", title: "..."}`

**`DELETE /api/queue/{hash}`** — Dequeue finding (set status to `"open"`, or preserve `"fix_failed"` if that was the previous status before it was re-queued)
- Returns `{status: "open", hash: "...", title: "..."}`

**`GET /api/queue`** — List all queued findings
- Returns `{count: N, findings: [{hash, repo, department, title, severity, effort}]}`

### 3. CLI Commands

Add `queue` subcommand group to the `backoffice` CLI:

**`python -m backoffice queue add <hash>`** — Queue a finding by its 16-char backlog hash. Same validation as API.

**`python -m backoffice queue remove <hash>`** — Dequeue a finding.

**`python -m backoffice queue list`** — Show all queued findings as a terminal table:

```
Hash             Repo              Dept       Severity  Title
958937f641d1eac6 analogify         qa         high      Missing email allowlist validation
a3b2c1d4e5f67890 selah             cloud-ops  medium    Lambda memory at default 128MB
3 findings queued for fix
```

**`python -m backoffice queue clear`** — Dequeue all (reset all `"queued"` back to `"open"`).

All commands operate directly on `dashboard/backlog.json` via `backoffice.backlog`. No server required.

### 4. Dashboard UI

**Queue button in finding detail panel (`renderFindingDetail()`):**

Button states based on finding status and fixability:
- `fixable_by_agent: true` + status `"open"` → purple "Queue for Fix" button
- Status `"queued"` → outlined "Queued" button, click to dequeue
- Status `"fix_failed"` → orange "Re-queue for Fix" button
- Status `"fixed"`, `"skipped"`, or `fixable_by_agent: false` → no button

**API call:** `fetch('/api/queue/{hash}', {method: 'POST'})` or `DELETE`. On success, update the finding's status in local `backlogData` and re-render the detail panel + findings list.

**Finding list badges:** Queued findings get a purple "Queued" badge. Fix-failed findings get an orange "Fix Failed" badge. Both in the findings list rows alongside the existing "AI fixable" badge.

**Needs Attention feed:** Queued findings surface in the top-15 "Needs Attention" feed on the main dashboard, grouped with a "Fix Queue" label.

### 5. Fix Agent — Queue Mode

**New script:** `scripts/fix-queued.sh`

Flow:
1. Read `dashboard/backlog.json`, collect all `status: "queued"` findings
2. Group by repo
3. For each repo, check `allow_fix: true` in `config/targets.yaml` — skip if not allowed
4. Write temporary `results/{repo}/queued-findings.json` with just the queued findings
5. Call `agents/fix-bugs.sh {repo_path} --findings queued-findings.json`
6. On success: update backlog status to `"fixed"`
7. On failure: update backlog status to `"fix_failed"`
8. Run `backoffice refresh` to update dashboard data

**Change to `agents/fix-bugs.sh`:** Accept optional `--findings <filename>` flag to override the default `findings.json` input. When not provided, behavior is unchanged.

**No changes to the fix agent prompt** — it already works with any findings list.

### 6. Makefile Targets

**New targets:**
```makefile
fix-queued:  ## Fix all queued findings from the dashboard
	bash scripts/fix-queued.sh

queue-list:  ## Show queued findings
	python3 -m backoffice queue list

queue-clear: ## Clear the fix queue
	python3 -m backoffice queue clear
```

**No changes to existing targets.** `make fix`, `make overnight`, and `make full-scan` work exactly as today. The queue is a separate, manual-only path.

## Files to Create

| File | Purpose |
|---|---|
| `scripts/fix-queued.sh` | Queue-mode fix launcher |
| `backoffice/queue.py` | CLI queue commands + backlog queue helpers |

## Files to Modify

| File | Change |
|---|---|
| `backoffice/backlog.py` | Add `STICKY_STATUSES` set; update `merge_backlog()` status logic to preserve sticky statuses |
| `backoffice/server.py` | Add `POST /api/queue/{hash}`, `DELETE /api/queue/{hash}`, `GET /api/queue` endpoints |
| `backoffice/__main__.py` | Register `queue` subcommand group |
| `agents/fix-bugs.sh` | Accept optional `--findings <filename>` flag |
| `dashboard/index.html` | Add queue button to finding detail; add queued/fix_failed badges to finding list; add queue count to Needs Attention feed |
| `Makefile` | Add `fix-queued`, `queue-list`, `queue-clear` targets |
| `tests/test_backlog.py` | Add tests for sticky status preservation |
| `tests/test_aggregate.py` | Verify queued status survives aggregation |

## Out of Scope

- Remote queue actions from S3-hosted dashboard (local server only)
- Queue from overnight loop (Product Owner keeps its own decision flow)
- Queue priority ordering (fix agent processes queued items by severity, same as today)
- Queue expiry or auto-dequeue
- Notifications when queue items are fixed
