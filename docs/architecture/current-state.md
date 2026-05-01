# Back Office — Current State

> Phase 0 reference document. Captures the system as it exists in the
> repository today. No code is changed alongside this document; later
> phases will reference these names, paths, and contracts.

This document is a working architecture map. It is intentionally concrete:
every claim is grounded in a file path or a CLI command that exists in the
repository at the time of writing.

---

## 1. What Back Office is today

Back Office is a **portfolio control plane** for AI-assisted engineering.
A single repository hosts:

- a Python package (`backoffice/`) — config, aggregation, queue, policy, server, sync;
- a set of shell agents (`agents/*.sh`) — department audits, fix agent, feature-dev agent, product-owner agent;
- a single-page operator dashboard (`dashboard/index.html` + `app.js`);
- an overnight orchestration script (`scripts/overnight.sh`);
- a corpus of JSON/YAML artifacts that flow between layers.

Operationally it answers four questions:

1. What is wrong across my portfolio? — audits + backlog
2. What should be fixed first? — score history + Product Owner + trust class
3. What is approved / queued / blocked / waiting for review? — task queue
4. What will reach GitHub, and what still needs human approval? — review/approve flow + draft PRs

The product line that everything else serves is on `README.md`. The
governing engineering rules live in `MASTER-PROMPT.md`. Both are
load-bearing — the rest of this document maps the running code to them.

---

## 2. System boundaries

```
┌───────────────────────────────────────────────────────────────────┐
│                       Operator (browser / CLI)                    │
└───────────────────┬─────────────────────────┬─────────────────────┘
                    │                         │
              dashboard/index.html      python -m backoffice ...
                    │                         │
        ┌───────────▼─────────────┐  ┌────────▼─────────────────┐
        │  backoffice.server      │  │  workflow / tasks /      │
        │  backoffice.api_server  │  │  sync / preview / review │
        │  HTTP + JSON            │  │  CLIs                    │
        └───────────┬─────────────┘  └──────────┬───────────────┘
                    │                            │
        ┌───────────▼────────────────────────────▼───────────────┐
        │      File-backed state                                 │
        │  config/   results/   dashboard/   tmp file artifacts  │
        └───────────┬───────────────────────────┬────────────────┘
                    │                            │
        ┌───────────▼─────────────┐  ┌──────────▼───────────────┐
        │  agents/*.sh             │  │  scripts/overnight.sh    │
        │  (subprocess workers)    │  │  (loop driver)           │
        └───────────┬─────────────┘  └──────────┬───────────────┘
                    │                            │
        ┌───────────▼────────────────────────────▼───────────────┐
        │   Backends (claude / codex CLIs)                       │
        │   via backoffice/backends/{claude,codex}.py            │
        └───────────┬───────────────────────────┬────────────────┘
                    │                            │
        ┌───────────▼────────────┐   ┌──────────▼───────────────┐
        │  Target repositories   │   │  GitHub (gh pr create)   │
        │  (in $HOME/projects/*) │   │  + Bunny CDN (sync)      │
        └────────────────────────┘   └──────────────────────────┘
```

Trust boundaries to remember:

- **Operator → Server**: API key (HMAC compare) + CORS allowlist + request-body cap.
  Implemented in `backoffice/server.py` and `backoffice/api_server.py`.
- **Server → Target repo**: target paths must resolve through
  `_validate_local_repo_path`/`resolve_target` to an approved root
  (`<repo_root>` or `~/projects`).
- **Server → Backend**: `subprocess.run`/`subprocess.Popen` with
  `cwd=<root>`. There is no agent identity passed through.
- **Server → GitHub**: only via `gh pr create --draft` from the request-pr
  endpoint — never auto-merge.

---

## 3. Module map

Top-level Python package — `backoffice/`:

| Module | Responsibility | Lines |
|---|---|---|
| `__main__.py` | CLI dispatcher (`python -m backoffice <cmd>`) | ~470 |
| `config.py` | Frozen dataclass config loader for `config/backoffice.yaml`; defines `Target`, `Autonomy`, `BackendConfig`, `DashboardTarget`, `ApiConfig`, `RunnerConfig`, etc. | ~412 |
| `config_drift.py` | Reports drift between `backoffice.yaml` and legacy `config/targets.yaml` | ~111 |
| `workflow.py` | Audit orchestration; runs department shell scripts via subprocess; refreshes dashboard artifacts | ~548 |
| `aggregate.py` | Aggregates `results/<repo>/*-findings.json` into `dashboard/*-data.json`, `data.json`, `score-history.json` | ~755 |
| `backlog.py` | Canonical finding schema, `finding_hash`, `normalize_finding`, `merge_backlog`, `update_score_history`; trust-class stamping | ~289 |
| `tasks.py` | Task queue persisted to `config/task-queue.yaml`, mirrored to `results/task-queue.json` and `dashboard/task-queue.json`; defines 11 statuses; CLI commands | ~754 |
| `policy.py` | Per-target autonomy gate registry: `fix`, `feature_dev`, `auto_commit`, `auto_merge`, `deploy`. CLI exit codes 0/1/2 | ~192 |
| `overnight_state.py` | `ExecutionLedger` (JSONL audit trail), `FailureMemory` (skip recently-failed), `Quarantine` (consecutive-rollback guard) | ~206 |
| `server.py` | Dashboard-facing local HTTP server; broadest endpoint surface | ~1718 |
| `api_server.py` | Production-style API server (separate from `server.py`); previews/approve/discard flow | ~669 |
| `preview.py` | `build_preview()` produces `preview-<job-id>.json` for the dashboard Review panel | ~127 |
| `review.py` | `approve()` / `discard()` ff-only merges or branch deletion for preview branches | ~186 |
| `delivery.py` | Builds delivery automation payload | ~542 |
| `migration_plan.py` | Cloud migration plan reads/writes | ~667 |
| `remediation_plan.py` | Portfolio remediation plan reads/writes | ~828 |
| `deploy_control.py` | Aggregates live deploy inventory and CI status | ~574 |
| `github_actions_history.py` | Aggregates archived GH Actions metadata | ~144 |
| `mentor.py` | Ad-hoc mentor plan generation (fed into the queue) | ~126 |
| `regression.py` | Portfolio regression runner | ~522 |
| `setup.py` | First-run wizard | ~402 |
| `scaffolding.py` | Per-target `.github/workflows` scaffolds | ~185 |
| `cloud_migration_compare.py` | Cost/service comparison generator | ~453 |
| `router.py` | Capability-based backend router | ~127 |
| `log_config.py` | Structured logging setup | ~46 |
| `backends/base.py` | `Backend` ABC: `health_check`, `capabilities`, `check_limits`, `build_command`, `invoke` | small |
| `backends/{claude,codex}.py` | Concrete backends | – |
| `sync/engine.py` | Sync to Bunny Storage + Pull Zone purge | – |
| `sync/manifest.py` | What to upload | – |
| `sync/providers/*` | Storage / CDN providers | – |

Shell layer (`agents/*.sh` + `scripts/*`):

| Script | Purpose |
|---|---|
| `agents/qa-scan.sh`, `seo-audit.sh`, `ada-audit.sh`, `compliance-audit.sh`, `monetization-audit.sh`, `product-audit.sh`, `cloud-ops-audit.sh` | One per department; invokes the runner with the matching prompt under `agents/prompts/*.md`; writes `results/<repo>/<dept>-findings.json` |
| `agents/fix-bugs.sh` | Reads findings; runs the fix agent in isolated worktrees; supports `--preview` (lands on `back-office/preview/<job-id>` and emits a preview artifact instead of merging) |
| `agents/feature-dev.sh` | Runs the feature-dev agent on a queue item |
| `agents/product-owner.sh` | Generates a prioritized work plan |
| `agents/og-remediation.sh`, `agents/watch.sh` | Specialized helpers |
| `scripts/overnight.sh` | 9-phase loop: SNAPSHOT → AUDIT → DECIDE → FIX → BUILD → VERIFY → DEPLOY → REPORT → SLEEP |
| `scripts/run-agent.sh` | Common runner indirection (codex vs claude vs stdin-text) |
| `scripts/job-status.sh` | Maintains `results/.jobs.json` |
| `scripts/sync-dashboard.sh`, `scripts/quick-sync.sh` | Sync wrappers (mostly superseded by `backoffice.sync.engine`) |

Dashboard (`dashboard/`):

- One single-page operator UI (`index.html`) with slide-over panels per
  department.
- Static asset bundle (`app.js`, `theme*.{js,css}`, `department-context.js`,
  `site-branding.js`).
- Pre-rendered data files (`*-data.json`, `backlog.json`, `score-history.json`,
  `task-queue.json`, `local-audit-log.json`, etc.) consumed by the SPA on
  load.

---

## 4. Persistence model

State is **file-backed**. There is no database. Every concept either:

- lives as a YAML config file under `config/` (operator-authored),
- or as a JSON/JSONL artifact under `results/` and/or mirrored into
  `dashboard/` (machine-authored, dashboard-readable).

### 4.1 Configuration

| Path | Owner | Notes |
|---|---|---|
| `config/backoffice.yaml` | operator | Single source of truth: `runner`, `agent_backends`, `routing_policy`, `api`, `deploy.bunny`, `scan`, `fix`, `notifications`, `targets` (with `autonomy` blocks). Loaded by `backoffice.config.load_config`. |
| `config/targets.yaml` | operator | **Deprecated** but still read by `backoffice.workflow` and `scripts/overnight.sh` as a parallel target list. Drift surfaced via `python -m backoffice check-drift`. |
| `config/task-queue.yaml` | machine + operator | Authoritative queue state; loaded/written by `backoffice.tasks`. |
| `config/api-config.yaml`, `config/agent-runner.env` | legacy | Legacy config slices, still present but folded into `backoffice.yaml`. |
| `config/migration-plan.yaml`, `config/remediation-plan.yaml`, `config/cloud-cost-comparison.yaml` | machine + operator | Plan data consumed by `backoffice.{migration_plan,remediation_plan,cloud_migration_compare}` |

### 4.2 Findings, backlog, scores

| Path | Producer | Consumer | Contract |
|---|---|---|---|
| `results/<repo>/findings.json` | `agents/qa-scan.sh` | aggregate, backlog | `{summary, findings[]}` (fields per `backoffice.backlog.normalize_finding`) |
| `results/<repo>/<dept>-findings.json` | `agents/<dept>-audit.sh` | aggregate, backlog | same shape, dept-specific extra fields preserved |
| `dashboard/<dept>-data.json`, `dashboard/data.json` | `backoffice.aggregate` | dashboard SPA | per-department payload + portfolio summary |
| `dashboard/backlog.json` | `backoffice.backlog.merge_backlog` | dashboard SPA | `{version, updated_at, findings: { <hash>: {audit_count, first_seen, last_seen, current_finding, …} } }` |
| `dashboard/score-history.json` | `backoffice.backlog.update_score_history` | dashboard sparklines | last 10 timestamped score snapshots |

### 4.3 Queue, approval, audit log

| Path | Producer | Consumer | Contract |
|---|---|---|---|
| `config/task-queue.yaml` | `backoffice.tasks` | itself | `{version, tasks[]}` — full task records |
| `results/task-queue.json` | `backoffice.tasks.save_payload` | dashboard, server | dashboard-friendly payload with `{generated_at, summary, tasks}` |
| `dashboard/task-queue.json` | same | dashboard SPA | mirror of the above |
| `results/local-audit-log.json` + `.md` | `backoffice.workflow.write_audit_log` | dashboard, ops | per-target snapshot (latest scan + per-dept summary) |
| `results/overnight-ledger.jsonl` | `backoffice.overnight_state.ExecutionLedger` (via CLI from `overnight.sh`) | operators | append-only audit trail of every gate decision, skip, rollback, deploy |
| `results/overnight-history.json` | `overnight.sh` | `FailureMemory`, `Quarantine`, dashboard | last ~50 cycle summaries |
| `results/overnight-plan.json` | Product Owner step | `overnight.sh`, dashboard | next-cycle plan |
| `results/quarantine-clear.json` | operator | `Quarantine` | `{cleared:[repo,…]}` override file |
| `results/manual-items.json` | `_save_manual_items` | dashboard | operator-added backlog items |

### 4.4 Preview artifacts (review/approve flow)

| Path | Producer | Consumer |
|---|---|---|
| `results/<repo>/preview-<job-id>.json` | `backoffice.preview.build_preview` (called by `agents/fix-bugs.sh --preview`) | dashboard Review panel + `backoffice.review` |
| Branch `back-office/preview/<job-id>` in target repo | fix agent | `backoffice.review.approve()` (ff-only merge to base) or `discard()` (delete branch) |

### 4.5 Atomicity

Most writers are not atomic — they `open(path, "w")` and write JSON.
A few exceptions:

- `backoffice.workflow.with_run_lock` uses `fcntl.flock(LOCK_EX|LOCK_NB)` on
  `results/.local-audit-run.lock` to prevent concurrent audit runs.
- `running_jobs`/`running_fix` dicts in the servers protect against
  same-process double-starts.
- `backlog.merge_backlog` overwrites in place; readers use lenient JSON
  parsing.

There is no journal, no two-phase write, and no checkpoint.
A killed writer can leave a half-written file — readers tolerate that
mostly by treating malformed JSON as "missing".

---

## 5. Task / queue / approval lifecycle (as implemented)

`backoffice.tasks.STATUS_ORDER`:

```
pending_approval → proposed → approved → ready → queued
                ↘                                   ↓
                  cancelled                       in_progress ↔ blocked
                                                    ↓
                                                ready_for_review
                                                    ↓
                                                  pr_open
                                                    ↓
                                                   done
```

State transitions today:

| From → To | Caller | Notes |
|---|---|---|
| (new) → `pending_approval` | `create_finding_task` (server `/api/tasks/queue-finding`), `create_product_suggestion_task`, `create_mentor_plan_task` | Dedup via `(repo, finding_hash)` |
| `pending_approval` → `ready` | `/api/tasks/approve` | Sets `task["approval"] = {approved_at, approved_by, note}` |
| `pending_approval` → `cancelled` | `/api/tasks/cancel` | Same path used to reject |
| `ready` → `in_progress` | `tasks start` CLI | Manual, single transition |
| `in_progress` ↔ `blocked` | `tasks block` / `tasks start` | |
| `in_progress` → `ready_for_review` | `tasks review` | |
| `ready_for_review` → `pr_open` | `/api/tasks/request-pr` | `gh pr create --draft`; refuses to PR from `main`/`master` |
| anything → `done` | `tasks complete` | Gate-checked via `summarize_gate_status()` against department findings + handoff path; can be overridden with `--allow-incomplete-gates` |
| anything → `cancelled` | `tasks cancel` | |

Each transition appends a record to `task["history"]`:

```json
{ "status": "<new>", "at": "<iso>", "by": "<actor>", "note": "<text>" }
```

Approval is a **field on the task record**, not a separate object:

```yaml
approval:
  approved_at: 2026-04-29T...
  approved_by: operator
  note: ...
```

Implications:

- One task = at most one approval today.
- "Rejected" is conflated with "cancelled" in the queue states.
- `pending_approval` and `proposed` exist side-by-side; `proposed` is the
  default for `tasks create` and is *not* the same as "needs approval".
- There is no notion of an approval that expires.

---

## 6. Audit / scan lifecycle

A typical local audit:

1. Operator (or `overnight.sh`) calls `python -m backoffice audit <target>` →
   `backoffice.workflow.handle_run_target`.
2. The run-lock is acquired (`with_run_lock`).
3. `run_job_status init` initializes `results/.jobs.json`.
4. For each department: `subprocess.run(["bash", agents/<dept>.sh, repo_path])`.
5. Each shell agent invokes the runner (`claude` or `codex` per
   `runner.command` in `backoffice.yaml`) with the matching prompt and
   writes `results/<repo>/<dept>-findings.json`.
6. `run_job_status finalize` and (always) `refresh_dashboard_artifacts`:
   - `aggregate.aggregate(results, dashboard/data.json)`
   - `delivery.main(config=…)`
   - `tasks.command_sync(...)` — re-emit queue payloads
   - `write_audit_log(...)` — refresh `results/local-audit-log.json`

Key fragility: each department's findings file lives under a dept-specific
filename (`findings.json`, `seo-findings.json`, `ada-findings.json`, …)
and the mapping is duplicated in `workflow.FINDINGS_FILES`,
`tasks.FINDINGS_FILE_BY_DEPARTMENT`, and `aggregate` constants.

---

## 7. Overnight loop (autonomy)

`scripts/overnight.sh` runs as long-lived process and steps through
nine phases (see header comment):

`SNAPSHOT → AUDIT → DECIDE → FIX → BUILD → VERIFY → DEPLOY → REPORT → SLEEP`

Per-target gating uses `python -m backoffice policy <repo> <gate>` —
exit code 0 (allow), 1 (block), 2 (error). Gates: `fix`, `feature_dev`,
`auto_commit`, `auto_merge`, `deploy`.

Loop state lives in three Python helpers (CLI-exposed):

| Helper | Purpose |
|---|---|
| `ExecutionLedger` | Append-only JSONL of every decision (`results/overnight-ledger.jsonl`) |
| `FailureMemory` | Items that failed in the last N cycles are blocked from the next plan |
| `Quarantine` | Repos with N consecutive rollback cycles are skipped until cleared |

Overnight produces `results/overnight-{plan,history,summary}.json` — read
by the dashboard Operations panel.

---

## 8. Dashboard / API surface

Two HTTP servers exist side by side:

### 8.1 `backoffice.server` — local dashboard server

Started via `python -m backoffice serve [--port 8070]` or `make jobs`.
Serves the `dashboard/` directory plus this API surface
(see `do_GET` / `do_POST` in `backoffice/server.py`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ops/status` | Jobs, queue, overnight, backends, forgejo, targets |
| GET | `/api/ops/backends` | Backend health + routing |
| GET | `/api/tasks` | Queue payload |
| GET | `/api/migration-plan` (+ `/comparison`) | Cloud migration plan |
| GET | `/api/remediation-plan` | Remediation plan |
| GET | `/api/deploy/control` | Deploy inventory |
| GET | `/api/github-actions/history` | Archived GH Actions runs |
| POST | `/api/run-scan` | Run one department on the configured TARGET |
| POST | `/api/run-all` | Run all departments (parallel/sequential) |
| POST | `/api/run-regression` | Portfolio regression |
| POST | `/api/manual-item` | Append manual backlog item |
| POST | `/api/ops/audit` | `make audit-all-parallel|audit-all|full-scan` |
| POST | `/api/ops/overnight/{start,stop}` | Start/stop overnight loop |
| POST | `/api/ops/product/{add,suggest,approve}` | Add/suggest/approve a product target |
| POST | `/api/ops/mentor/plan` | Generate mentor plan task |
| POST | `/api/tasks/queue-finding` | Queue a finding for approval |
| POST | `/api/tasks/approve` | Approve a queue item |
| POST | `/api/tasks/cancel` | Cancel a queue item |
| POST | `/api/tasks/request-pr` | `gh pr create --draft` |
| POST | `/api/remediation-plan/...`, `/api/migration-plan/...` | Update plans |
| POST | `/api/deploy/dispatch`, `/api/github-actions/archive` | Delivery actions |

Auth: optional bearer / `X-API-Key` / `?api_key=` (HMAC compare). CORS
allowlist comes from `config.api.allowed_origins`. Body capped at 1 MiB.

### 8.2 `backoffice.api_server` — production worker API

Started via `python -m backoffice api-server`. Narrower scope, intended
as a long-running service:

- `GET /api/status`, `/api/jobs`
- `POST /api/run-scan`, `/api/run-all`, `/api/run-fix` (with `preview`)
- `GET /api/previews` — list `preview-*.json` artifacts
- `POST /api/approve` / `/api/discard` — call into `backoffice.review`
- `POST /api/stop`

Refuses to bind a non-loopback address without an API key.

These two servers overlap. The split is partial — `server.py` is the
"do everything" local surface, `api_server.py` is the "execute jobs +
review previews" surface. Endpoint contracts are similar but not
identical, and there is no shared HTTP handler.

---

## 9. GitHub PR generation

Two paths terminate at GitHub today:

### 9.1 Approval-driven draft PR (`/api/tasks/request-pr`)

`backoffice.server._handle_task_request_pr`:

1. Validate task and resolve `task["target_path"]` through the
   approved-roots check.
2. Read current branch from `git rev-parse --abbrev-ref HEAD`.
3. Refuse if the branch is `main`/`master`.
4. Build PR title (`Review: <task title>`) and body (Approval Request,
   task id, repo, status).
5. `gh pr create --draft --title ... --body ...` with `cwd=<repo_path>`.
6. On success, mark the task `pr_open`, store
   `task["pr"] = {url, title, branch, created_at}`, append history.

### 9.2 Preview branch + Review panel (`agents/fix-bugs.sh --preview`)

1. Fix agent commits to `back-office/preview/<job-id>` in the target repo
   (no PR yet).
2. `python -m backoffice preview ...` writes
   `results/<repo>/preview-<job-id>.json`.
3. Dashboard Review panel calls `backoffice.api_server`
   `GET /api/previews` and shows `{commits, diffstat, checklist, compare_url}`.
4. Operator approves → `backoffice.review.approve()` does an `ff-only`
   merge into `base_ref` and deletes the artifact. Or discards → branch
   deleted, artifact removed. Both refuse to run on a dirty worktree.

Neither path can auto-merge to `main`. Path 9.1 publishes a draft PR for
GitHub review. Path 9.2 advances a *local* branch only — there is no
integration with GitHub remotes in `review.py` itself.

---

## 10. Backends and routing

`backoffice.backends.base.Backend` is an ABC with five methods:

```python
health_check() -> HealthStatus
capabilities() -> Capabilities
check_limits()  -> LimitState
build_command(prompt, tools, repo_dir) -> list[str]
invoke(prompt, tools, repo_dir) -> InvocationResult
```

Concrete implementations: `claude.py`, `codex.py`. `Capabilities` is a
boolean grid (`read_files`, `edit_files`, `commit_changes`, `subagents`,
`structured_output`, `long_context_reasoning`, …).

`backoffice.router.Router` maps known **task types** (`prioritize_backlog`,
`audit_repo`, `fix_finding`, `implement_feature`, `verify_changes`,
`summarize_cycle`) to backends using capability requirements + a
fallback policy from `config.routing_policy`.

Important: today **only the agent shell scripts actually invoke
backends**. The router is wired but not called from the queue lifecycle.
Tasks have no "current run" pointer and no backend assignment record;
the router exists to support future routing decisions.

---

## 11. Trust class

Every finding carries a `trust_class ∈ {objective, advisory}` field
(`backoffice.backlog.DEPARTMENT_TRUST_CLASS`):

- objective: qa, ada, compliance, privacy, cloud-ops
- advisory: seo, monetization, product (with per-finding override
  via `raw["trust_class"]`)

It threads through:

- raw → `normalize_finding` → `backlog.json`
- aggregate → `dashboard/*-data.json` (`trust_class_counts`, `trust_class_totals`)
- `preview.build_preview` → preview checklist (different verification
  blurb per class)
- Product Owner prioritisation logic (advisory items are framed as
  product decisions, not remediations).

---

## 12. Strengths

These are the parts of the current system that are doing real work and
should be preserved:

- **Department × repo matrix is legible.** Operators can see what is
  wrong, where, and how often, without hunting.
- **Trust-class field is on every finding.** Hard distinction between
  remediable facts and judgment calls — already wired into prioritisation.
- **Approval is mandatory before repo-changing work.** All paths to PR
  creation pass through `pending_approval → ready` and a draft PR for
  GitHub review.
- **Preview branches + ff-only merges.** Fix agents never touch the
  default branch; operators review the diff before integration.
- **Per-target autonomy policy is data, not code.** `policy.py` evaluates
  named gates from a small registry, callable from shell.
- **Loop resilience primitives.** `ExecutionLedger`, `FailureMemory`,
  `Quarantine` — all with tests.
- **Backend abstraction.** Capabilities and limit reporting are already
  modeled, even if not yet used at the queue level.
- **Cost-conscious sync.** Sync gating + bounded CDN purge in
  `backoffice.sync.engine`.
- **Comprehensive test suite.** ~30 test modules covering aggregate,
  backlog, tasks, autonomy, policy, ledger/memory/quarantine, preview,
  review, sync, etc.

---

## 13. Fragile areas

These are the parts most likely to bite during the planned evolution:

1. **Two configuration sources still live.** `backoffice.yaml` is
   authoritative, but `workflow.py`, `tasks.py`, and `overnight.sh` still
   read `config/targets.yaml`. Drift detection works (`check-drift`),
   but the migration is incomplete.
2. **Two HTTP servers.** `server.py` (1718 lines) and `api_server.py`
   (669 lines) overlap in surface area, duplicate auth/CORS logic, and
   share module-level state. There is no shared HTTP layer.
3. **Module-level state.** `_root`, `_target_repo`, `running_jobs`, and
   the running-fix dict are module globals. It works but hurts testing,
   resets, and concurrency.
4. **Task state machine is implicit.** Status is a string; transitions
   are scattered across CLI handlers and HTTP handlers. There is no
   single `transition(task, to_state)` function and no validation that
   `pr_open → in_progress` (for example) is illegal.
5. **No first-class run records.** When the fix or feature-dev agent
   runs, there is a job-status entry and a `.jobs.json` snapshot, but
   the **task has no link to a run id, no log, no cost, no exit code,
   no duration**. If a run fails mid-flight, the queue item often stays
   in `in_progress` forever.
6. **No atomic task checkout.** Two operators (or two automated
   processes) could call `tasks start` on the same task; the only
   protection is the queue file being rewritten last-writer-wins.
7. **No agent identity.** Backends are typed; agents are not. The
   "Product Owner agent", "fix agent", and "feature-dev agent" are shell
   scripts. There is no record of *which* agent did what against a task.
8. **No workspace records.** Preview branches exist as git refs; nothing
   in storage connects a task to a workspace, a branch name, a base
   commit, or a test-result artifact. `review.py` re-derives the branch
   name from the preview artifact.
9. **Approval is a dictionary on the task.** No history of multiple
   approvals, no expiration, no clear distinction between "rejected"
   and "cancelled", and no way to require a second approver for a
   higher-risk change.
10. **No cost tracking.** `Capabilities.long_context_reasoning` exists,
    but there is no `CostEvent` model, no per-target budget, no spend
    visualization.
11. **Heartbeat = `overnight.sh`.** The only recurring driver is one
    long-lived shell loop. There is no way to schedule "audit X every
    hour" without writing more shell.
12. **Implicit shell parsing.** `overnight.sh` consumes JSON from
    `python -m backoffice` subcommands; when JSON evolves, shell-side
    consumers must keep up. The `state ledger-append` / `blocked-items`
    / `quarantined` CLIs are the explicit contract here.
13. **Last-writer-wins everywhere.** Concurrent writes to
    `task-queue.yaml`, `manual-items.json`, plan files can clobber.
    Most flows are operator-initiated and serial, so this rarely fires —
    but the risk is real once heartbeats and agents share the queue.

---

## 14. What should remain unchanged

Even as Back Office evolves, these properties are **product**, not
implementation detail, and must be preserved:

- The dashboard remains the primary operator surface (one page, slide-over
  panels, department × repo matrix, Needs Attention, Approval Queue).
- Findings keep their canonical schema and trust class.
- Approval remains mandatory before any AI-driven repo change.
- Draft PR remains the only way changes reach `main`.
- `config/backoffice.yaml` remains the single config source of truth.
- Existing JSON/YAML artifacts continue to load — `backlog.json`,
  `score-history.json`, `task-queue.json`, `local-audit-log.json`,
  `overnight-{plan,history,ledger}.{json,jsonl}`, `preview-<job-id>.json`.
- Existing CLI (`python -m backoffice <cmd>`) and Make targets keep
  working.
- Tests keep passing.

The phased roadmap that follows is additive on top of these guarantees.
