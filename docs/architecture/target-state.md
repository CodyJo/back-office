# Back Office — Target State

> Phase 0 reference document. Defines where Back Office is going.
> Companion to `current-state.md` and `phased-roadmap.md`.
>
> Adopts well-understood agent-control-plane primitives — first-class
> agents, runs, atomic checkout, adapters, cost tracking — while
> staying focused on Back Office's mission: engineering portfolio
> governance, repo observability, finding-to-task workflow, and
> human-approved AI execution that ends in a draft GitHub PR.

---

## 1. Operating principles

These are non-negotiable. Every later phase is gated by whether it
preserves all of them.

1. **Back Office owns state, policy, audit, approval, queue, and
   evidence.** Agents are executors; they do not author truth.
2. **Every AI action is traceable.** Each mutation links to:
   `task_id` · `agent_id` · `run_id` · `target_repo` · `approval_id` · `audit_event_id`.
3. **Human approval is mandatory before any repo-changing work.**
   No bypass, no soft-default override.
4. **GitHub draft PR is the only path to `main`.** Back Office can
   prepare the branch and PR; merging is GitHub's domain.
5. **Existing artifacts continue to load.** No format breakage; new
   models must round-trip with the JSON/YAML the dashboard already reads.
6. **Explicit state machines beat booleans.** Tasks, runs, approvals
   each have a small finite state machine with validated transitions
   and an audit trail.
7. **Storage is abstracted.** File-backed remains default; SQLite or
   Postgres is plug-in-able later without changing call sites.
8. **Privacy first, self-hostable.** No telemetry, no third-party
   dependencies introduced casually, secrets never exported plaintext.
9. **Conservative-by-default autonomy.** Fix agents allowed; feature
   dev / auto-merge / deploy off unless explicitly enabled per target.
10. **Small reviewable changes.** New phases land as PR-sized increments
    with tests; broad rewrites are explicitly rejected.

---

## 2. Which control-plane primitives we adopt (and which we skip)

| Primitive | Adopted? | Where it lands in Back Office |
|---|---|---|
| First-class **agents** | ✅ | New `Agent` model. Existing shell agents (`fix-bugs.sh`, `feature-dev.sh`, `product-owner.sh`, …) become *registered* agents with adapter configs, identity, status, and budgets. Department audits remain task-producing scanners. |
| **Task / run lifecycle** | ✅ | New `Task` and `Run` models with explicit state machines. Task lifecycle stays close to today's `STATUS_ORDER` (renames + adds `checked_out`); Run lifecycle is new. |
| **Adapter abstraction** | ✅ | `AdapterContract` (`invoke`/`status`/`cancel`). `backoffice.backends.Backend` becomes one specific kind of adapter; new `noop`, `process`, and `claude_code` adapters land alongside. |
| **Claude Code adapter** | ✅ | Concrete adapter that executes approved tasks against an isolated workspace. Disabled by default in tests. |
| **Atomic task checkout** | ✅ | `Store.checkout_task(task_id, agent_id) → Run | Conflict`. Filesystem implementation uses fcntl-based locking; SQL backend later uses `SELECT … FOR UPDATE SKIP LOCKED`. |
| **Heartbeat / routine execution** | ✅ | `Routine`/`Trigger`/`Schedule` models. Local cron-like scheduler that respects budgets and pause state. `overnight.sh` becomes one routine among several. |
| **Cost / budget tracking** | ✅ | `CostEvent` model + `Budget` policies (global / target / department / agent / task / run). Estimated by default; adapters can report verified cost. |
| **Stronger audit trail** | ✅ | `AuditEvent` table-equivalent; existing `overnight-ledger.jsonl` is one consumer. Every mutating call writes an audit event. |
| **API surface for agents** | ✅ | Agents (local subprocess or remote process) interact with Back Office through a documented REST/CLI API: get tasks, checkout, log, mark ready-for-review, request approval. |
| **Plugin architecture** | ◯ later | Phase 12. Adapters / scanners / department checks / dashboard cards as registration-based plugins. Kept small, marked experimental. |

What we deliberately leave out:

- Org-chart-first UX. Back Office's department × repo matrix is the
  product story; the new agents/runs views *augment* that surface, they
  don't replace it.
- A managed/multi-tenant control plane. Back Office stays single-tenant
  and self-hostable.
- A heavy SDK or in-product marketplace. The plugin system stays small
  and explicit.

---

## 3. Domain model (target shape)

All names are aspirational; concrete locations are in
`phased-roadmap.md`. The intent here is the **shape of the domain**,
not the file layout.

### 3.1 `Agent`

A first-class identity for something that does work.

```
Agent
  id                str   # ksuid-like, stable
  name              str   # "fix-agent", "product-owner", "selah-feature-dev"
  role              str   # fixer | feature_dev | scanner | product_owner | mentor | custom
  description       str
  adapter_type      str   # noop | process | claude_code | …
  adapter_config    dict  # adapter-specific (cmd, model, env allowlist, prompt template ref)
  status            str   # active | paused | retired
  paused_at         iso?
  budget_id         id?
  metadata          dict
  created_at        iso
  updated_at        iso
```

Existing shell agents become rows in this registry. Audit-time scanners
(qa, seo, ada, …) are also agents — but their adapter is "department
scanner" and their output flows into findings/backlog, not the queue.

### 3.2 `Task`

The unit of work. Replaces today's queue entry as the canonical record.
Backwards-compatible with the existing 11-status set; only `checked_out`
is added.

```
Task
  id                str
  title             str
  description       str
  repo              str
  product_key       str
  category          str    # bugfix | feature | review | product | …
  task_type         str    # finding_fix | feature | mentor_plan | product_suggestion | …
  trust_class       str    # objective | advisory  (carried from finding)
  priority          str    # high | medium | low
  state             str    # see lifecycle below
  source_finding    {hash, id, department, severity, file, line, fixable_by_agent}
  acceptance        list[str]
  audits_required   list[str]
  approvals         list[approval_id]   # references; not embedded
  current_run_id    str?                # latest checkout
  history           list[StateChange]   # state, at, by, note, audit_event_id
  workspace_id      str?
  pr                {url, branch, title, created_at}?
  created_at, updated_at, owner, created_by, notes
```

Lifecycle (target):

```
proposed ─approve─▶ pending_approval ─approve─▶ approved ─claim─▶ queued
                                       └─reject─▶ cancelled
queued ─checkout─▶ checked_out ─start─▶ running ─block─▶ blocked
                                                ─review─▶ ready_for_review
                                                ─fail──▶ failed
ready_for_review ─pr─▶ pr_open ─merge─▶ done
any                       ─cancel─▶ cancelled
```

Compatibility: the existing string statuses (`pending_approval`,
`proposed`, `approved`, `ready`, `queued`, `in_progress`, `blocked`,
`ready_for_review`, `pr_open`, `done`, `cancelled`) all remain valid;
the only new one is `checked_out`. `in_progress` maps to `running`
internally and is kept as a synonym at the storage boundary.

### 3.3 `Run`

A single attempt by an agent at a task. Multiple runs per task are
allowed — re-run, retry, parallel preview, etc.

```
Run
  id                str
  task_id           str
  agent_id          str
  adapter_type      str
  adapter_handle    str?  # opaque token returned by the adapter
  workspace_id      str?
  approval_id       str?  # the approval that authorized this run
  state             str   # see lifecycle below
  started_at, ended_at  iso
  exit_code         int?
  duration_ms       int?
  prompt_ref        str?  # path/hash to the prompt that was sent
  output_summary    str?
  artifacts         list[{kind, path, sha256}]
  cost              {provider, model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, verified}
  error             str?
  metadata          dict
```

Run lifecycle:

```
created → queued → starting → running ─▶ succeeded
                                   ├─▶ failed
                                   ├─▶ cancelled
                                   └─▶ timed_out
```

### 3.4 `Approval`

Approval becomes a first-class object, not a sub-dict on the task.

```
Approval
  id                str
  task_id           str
  scope             str   # plan | run | merge   (what is being approved)
  state             str   # requested | approved | rejected | expired | superseded
  requested_by      str
  requested_at      iso
  decided_by        str?
  decided_at        iso?
  reason            str
  expires_at        iso?
  policy_basis      str   # which gate(s) required this approval
  audit_event_id    str
```

This unlocks: multiple approvals per task; distinct approve/reject;
expiration; "approved by Alice but rejected by Bob"; required-second-approver
policies.

### 3.5 `Workspace`

A tracked artifact for the place AI work happens.

```
Workspace
  id                str
  task_id           str
  repo              str
  kind              str   # branch | worktree | patch
  branch            str?
  base_ref          str?
  base_sha          str?
  head_sha          str?
  worktree_path     str?
  created_at, updated_at, retired_at
  test_results_ref  str?  # link to artifact
  metadata          dict
```

Today's preview branches (`back-office/preview/<job-id>`) become
`Workspace(kind=branch)` rows.

### 3.6 `CostEvent`

```
CostEvent
  id                str
  run_id            str?  # most cost is per-run
  task_id           str?
  agent_id          str?
  target            str?
  provider          str
  model             str
  input_tokens, output_tokens, total_tokens   int
  estimated_cost_usd  float
  verified          bool
  source            str   # estimate | adapter_reported | provider_api
  timestamp         iso
```

### 3.7 `Budget`

```
Budget
  id, scope (global|target|department|agent|task|run), scope_id
  period            str    # daily | weekly | monthly | rolling_24h
  soft_limit_usd    float?
  hard_limit_usd    float?
  reset_at          iso?
```

`BudgetPolicy` evaluates whether a new run is allowed:

- soft limit exceeded → warn, audit event, allow
- hard limit exceeded → block, audit event, route to approval

### 3.8 `Routine` / `Trigger` / `Schedule`

```
Routine
  id, name, description
  trigger           {type: cron|manual|webhook|on_task_created|on_approval_granted, payload}
  action            {kind: enqueue_audit | enqueue_task | run_agent | sync_dashboard, payload}
  paused            bool
  budget_id         id?
  last_run_at       iso?
  metadata          dict
```

`overnight.sh` becomes the prototype routine ("cron: every 45m → enqueue
audit-all + product-owner + fix"); operators can add others (e.g.
"daily 08:00 → run scanner X on repo Y") via config or CLI.

### 3.9 `Actor` and `AuditEvent`

```
Actor
  id, kind (operator|agent|routine|system), display_name, agent_id?

AuditEvent
  id
  at                iso
  actor_id          str
  action            str    # task.transition | approval.requested | run.started | …
  subject_kind      str    # task | run | approval | workspace | budget | routine
  subject_id        str
  before, after     dict?
  reason            str
  metadata          dict
```

Existing append-only `overnight-ledger.jsonl` continues to be written;
the new audit log is the union of every mutating operation across the
system, of which the ledger is one consumer view.

### 3.10 `AdapterConfig`

Per-agent record of how the executor is invoked.

```
AdapterConfig
  agent_id
  adapter_type      str
  command           str?     # for process / claude_code
  args              list[str]
  env_allowlist     list[str]
  cwd_strategy      str      # repo | worktree | sandbox
  timeout_seconds   int
  prompt_template   str?     # path/ref
  dry_run_default   bool
  metadata          dict
```

---

## 4. Adapter contract

```python
class Adapter(Protocol):
    name: str

    def invoke(self, *, agent: Agent, task: Task, run: Run,
               context: AdapterContext) -> AdapterHandle: ...

    def status(self, *, run: Run, handle: AdapterHandle) -> AdapterStatus: ...

    def cancel(self, *, run: Run, handle: AdapterHandle) -> AdapterCancelResult: ...
```

Adapter types in scope:

- `noop` — deterministic, used in tests; emits a synthetic "succeeded" run.
- `process` — runs an arbitrary, allowlisted command (`bash agents/X.sh ...`)
  with timeout and structured logs. Today's shell agents are wrapped here.
- `claude_code` — runs Claude Code in an isolated workspace under
  controlled prompts; never against the working tree.
- `legacy_backend` (transitional) — wraps existing `backoffice.backends.{claude,codex}`
  via their `invoke()` so the router keeps working until callers move
  onto adapters directly.

Adapter contract guarantees:

- Adapters do not mutate state directly; they emit events Back Office
  records.
- Adapter failures yield `Run(state=failed)` and an `AuditEvent` —
  never a partial task transition.
- Adapter timeouts are enforced by Back Office, not the adapter.
- `cancel()` is idempotent.

---

## 5. Storage abstraction

```python
class Store(Protocol):
    def get_agent(...): ...
    def list_agents(...): ...
    def upsert_agent(...): ...

    def get_task(...): ...
    def list_tasks(filter, page): ...
    def transition_task(task_id, to_state, actor, reason) -> Task: ...
    def checkout_task(task_id, agent_id) -> Run | Conflict: ...

    def create_run(...): ...
    def update_run_state(run_id, to_state, ...): ...
    def append_artifact(run_id, artifact): ...

    def request_approval(...): ...
    def decide_approval(...): ...

    def record_cost(...): ...

    def append_audit_event(...): ...

    # Compatibility helpers — unchanged file paths
    def load_legacy_task_queue() -> dict: ...
    def save_legacy_task_queue(payload): ...
```

Initial implementation: `FileStore` over the existing
`config/task-queue.yaml`, `results/...`, `dashboard/...` layout.

Future: `SqliteStore`, `PostgresStore`. Phases beyond Phase 2 do not
require a DB.

Atomic write strategy for the file store:

- write to `<path>.tmp`, `fsync`, then `os.replace(<path>.tmp, <path>)`;
- per-resource lockfiles via `fcntl.flock` for any "read-modify-write"
  cycle (queue mutations, audit append, run state update);
- audit events appended via O_APPEND for crash safety.

---

## 6. Lifecycle surfaces (target)

### 6.1 Approval

```
requested ─approve─▶ approved
          ─reject─▶ rejected
          ─expire─▶ expired
approved ─supersede─▶ superseded   (a newer approval replaces this one)
```

Today's state-on-task remains writable for compatibility; the source of
truth becomes the `Approval` record. Conversion is read-side: when
loading a legacy task with an `approval` dict, the store synthesizes an
`Approval(state=approved, decided_at, decided_by, reason)`.

### 6.2 Run

```
created → queued → starting → running ─▶ succeeded
                                   ├─▶ failed
                                   ├─▶ cancelled
                                   └─▶ timed_out
```

Heartbeat: while `running`, the adapter (or Back Office on the adapter's
behalf) writes a status update at most every N seconds. Stale runs are
eligible for cancellation by an operator or by a watchdog routine.

### 6.3 Task

(See §3.2 for the diagram.) Implementation requires:

- `transition_task()` validates the source state against an allow-list;
- every transition writes one `AuditEvent` *and* one history entry;
- `checkout_task()` atomically moves `approved → checked_out` and
  creates a `Run(state=created)` linked to the task; conflict on
  re-checkout returns the existing run;
- `tasks complete` keeps the gate-check it has today (`audits_required`
  + handoff path) but resolves it through `Run` artifacts rather than
  the legacy `findings.json` lookup.

---

## 7. Dashboard / API targets

### 7.1 Dashboard

The single-page operator dashboard remains the product surface.
New cards/panels are *additive*:

- existing department score cards, matrix, Needs Attention, Approval
  Queue — unchanged;
- new **Agents** card (registered agents, status, current run, recent runs);
- new **Active Runs** strip (top of operations panel);
- new **Run Detail** drawer (state, prompt ref, artifacts, cost, logs);
- new **Cost** card (estimated portfolio spend, by target / agent / day);
- new **Routines** card (scheduled work, last/next run, paused state);
- existing finding/queue links extended to deep-link into runs.

### 7.2 API

Today's endpoints continue to function. The agent-facing API is
documented and grows:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/agents` | Registry |
| GET | `/api/agents/<id>/tasks` | Tasks assigned to the agent |
| POST | `/api/tasks/<id>/checkout` | Atomic checkout → `Run` |
| POST | `/api/runs/<id>/log` | Append run log line |
| POST | `/api/runs/<id>/artifact` | Upload run artifact |
| POST | `/api/runs/<id>/cost` | Report cost event |
| POST | `/api/runs/<id>/ready-for-review` | Move task to ready-for-review |
| POST | `/api/runs/<id>/cancel` | Cancel run |
| POST | `/api/approvals/request` | Request approval |
| POST | `/api/approvals/<id>/decide` | Approve / reject |
| GET | `/api/audit-events` | Filterable audit log |
| GET | `/api/budgets`, `POST /api/budgets/<id>/refresh` | Budget visibility |
| GET | `/api/routines`, `POST /api/routines/<id>/run` | Heartbeats |

Authentication:

- operator API key (existing) for human-driven calls;
- per-agent API keys (new) — scoped to that agent's tasks/runs/approvals;
- local trusted mode for development (no key, loopback only).

Mutating calls always write an `AuditEvent`.

---

## 8. Safety guarantees

These properties must be true at every phase boundary:

- Existing JSON/YAML artifacts continue to load.
- Existing CLI commands and Make targets continue to work.
- The current dashboard renders even when no agents/runs exist yet.
- Tests remain green; new code arrives with new tests.
- No auto-merge to default branches, ever.
- No agent run without an approval (except read-only scanners that
  never mutate the target repo).
- All mutating operations produce an `AuditEvent`.
- Failed runs never leave a task in an indeterminate state — runs fail
  cleanly into `Run(state=failed)` and the task either reverts to
  `approved` or moves to `failed` by policy.

---

## 9. Observability targets

- One `AuditEvent` stream sufficient to reconstruct any task's history.
- Per-run logs as plain text with a stable schema for the structured
  bookends (start/end markers).
- Cost reported as **estimated** until the provider confirms.
- A "what's running" view is computable in O(active_runs).
- Heartbeats expose stale runs (no status update for N minutes).

---

## 10. What this is *not*

- Not a multi-tenant SaaS.
- Not an "AI does the work and emails you" system. AI proposes; humans
  approve.
- Not a replacement for git. Workspaces are tracked; merges still go
  through git.
- Not a feature flag system, not a deployment platform, not a CI runner.
  Back Office *gates* and *records* these things; it does not own them.
- Not a place to put product analytics or user PII. Privacy-first
  remains a hard constraint.

---

## 11. Migration anchors

Several pieces of today's code map cleanly to the new model. These
anchors guide the phased work:

| Today | Maps to |
|---|---|
| `backoffice.tasks.STATUS_ORDER` | `Task` state machine (with `checked_out` added) |
| `task["approval"] = {...}` | `Approval` record referenced by `task.approvals[]` |
| `task["history"]` entries | `AuditEvent` rows (history is a derived view) |
| `agents/<dept>-audit.sh` | `Agent(role=scanner, adapter_type=process)` |
| `agents/fix-bugs.sh`, `feature-dev.sh`, `product-owner.sh` | `Agent(role=…, adapter_type=process | claude_code)` |
| `backoffice.backends.Backend` | One `Adapter` implementation; new adapters live alongside |
| `backoffice.router.Router` | Continues; reads agent registry instead of bare backends |
| `results/<repo>/preview-<job-id>.json` + branch | `Workspace(kind=branch)` + `Run(artifacts=[…])` |
| `results/overnight-ledger.jsonl` | Filtered view onto `AuditEvent` |
| `scripts/overnight.sh` | A `Routine` (and: many other routines become possible) |
| `config/backoffice.yaml` | Continues to be authoritative; gains `agents:`, `routines:`, `budgets:` sections |

The intent is that an operator running today's commands tomorrow sees
**the same dashboard, the same files, the same approvals** — and gains
the ability to register agents, see runs, watch costs, and schedule
routines without changing any existing workflow.
