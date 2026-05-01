# Back Office — Phased Roadmap

> Phase 0 deliverable. Translates the high-level evolution plan into a
> Back Office-specific build sequence. Each phase is sized to a small
> number of reviewable PRs, includes tests, and preserves the
> guarantees in `target-state.md` §8.
>
> Companion to `current-state.md` and `target-state.md`. **Read those
> first.** The naming below assumes the modules and contracts they
> describe.

Phases are ordered for safety, not feature value. Phase 1 introduces
domain models without behavior changes; later phases progressively move
the system onto those models.

A phase is "done" when:

1. Its acceptance criteria are met,
2. Existing tests still pass,
3. New tests added in that phase pass,
4. Architecture/operator docs are updated,
5. The dashboard still renders against the new artifacts.

---

## Phase 0 — Architecture audit (this phase)

**Status:** in progress.

**Objective.** Establish a shared map of the current system and a target
shape so subsequent phases can reference concrete names.

**Deliverables.**

- `docs/architecture/current-state.md`
- `docs/architecture/target-state.md`
- `docs/architecture/phased-roadmap.md` (this file)

**Files / modules touched.** Documentation only.

**New models / APIs.** None.

**Tests.** Run existing suite to confirm no regression.

**Acceptance criteria.**

- Documents are accurate to the repo at this commit.
- No functional code changes.
- `pytest` passes.

**Risks.** Low. The only risk is documentation drift; mitigated by
referencing files/paths and re-validating each phase.

**Rollback strategy.** `git revert` the doc commits.

---

## Phase 1 — Domain models, no behavior change

**Objective.** Add first-class typed models for `Agent`, `Task`, `Run`,
`Approval`, `CostEvent`, `Workspace`, `AdapterConfig`, `Actor`,
`AuditEvent` — without rewiring any existing code paths.

**Files / modules.**

- New: `backoffice/domain/__init__.py` — re-exports.
- New: `backoffice/domain/models.py` — dataclasses (or Pydantic only if
  we accept that dependency; default: dataclasses, matching `config.py`).
- New: `backoffice/domain/state_machines.py` — explicit transition
  tables and a `transition(...)` helper.
- New: `backoffice/domain/compat.py` — converters between the new models
  and existing JSON/YAML payloads (legacy task-queue → `Task`,
  `task["approval"]` → `Approval`, etc.).
- Light edits: `backoffice/tasks.py` — internal use of the converter
  for new code paths only; existing CLI keeps writing legacy YAML.

**New APIs.**

- `Task.from_legacy(dict) -> Task`, `Task.to_legacy() -> dict`.
- `Approval.from_task_dict(task) -> Approval | None`.
- `transition(task: Task, to_state: str, *, actor, reason) -> Task` —
  raises on illegal transitions.
- `validate_run_state(from, to) -> bool`.

**Tests.**

- `tests/domain/test_models_serde.py` — round-trips for every model.
- `tests/domain/test_task_state_machine.py` — every legal/illegal edge.
- `tests/domain/test_run_state_machine.py`.
- `tests/domain/test_approval_compat.py` — load every existing
  task in `config/task-queue.yaml` (and `tests/data/...` fixtures) and
  assert no field is silently dropped.

**Acceptance criteria.**

- Existing tests still pass.
- New tests cover serde + state machines.
- A legacy task with `approval={approved_at, approved_by, note}`
  produces an `Approval(state=approved)` and round-trips back.
- Existing `dashboard/task-queue.json` shape is unchanged.

**Risks.**

- Subtle field drift if a converter forgets a key. Mitigated by a
  whole-fixture round-trip test that asserts dict equality on a real
  `task-queue.yaml`.

**Rollback strategy.**

- New modules are unimported by existing code paths until later phases.
  Reverting Phase 1 deletes the new modules; nothing else depends on
  them yet.

---

## Phase 2 — Storage abstraction

**Objective.** Centralize reads/writes behind a `Store` interface,
keeping file-backed storage as the default and the only implementation
in this phase. No new artifacts; only a refactor of access paths.

**Files / modules.**

- New: `backoffice/store/__init__.py` — `get_store()` factory.
- New: `backoffice/store/base.py` — `Store` Protocol.
- New: `backoffice/store/file_store.py` — implementation backed by the
  current files.
- New: `backoffice/store/atomic.py` — `atomic_write_json`,
  `atomic_write_yaml`, `LockFile` helpers (fcntl-based).
- Light edits: `backoffice/tasks.py`, `backoffice/server.py`,
  `backoffice/api_server.py` — selected writes routed through the new
  store. Existing public CLI behavior unchanged.

**New APIs.**

- `Store.load_task_queue() -> TaskQueueState`
- `Store.save_task_queue(state)`
- `Store.append_audit_event(event)`
- `Store.atomic_replace(path, payload)`
- `Store.lock(resource: str)` — context manager wrapping `fcntl.flock`.

**Tests.**

- `tests/store/test_atomic_write.py` — write-then-replace, partial
  write recovery, concurrent writers under flock.
- `tests/store/test_file_store.py` — every method round-trips against a
  temporary directory.
- `tests/store/test_compat_paths.py` — confirms exact paths
  (`config/task-queue.yaml`, `results/task-queue.json`,
  `dashboard/task-queue.json`, `results/overnight-ledger.jsonl`) match
  the existing layout.

**Acceptance criteria.**

- Existing flows (CLI, dashboard server, API server, sync) still work
  with no observable change.
- New store APIs have full unit coverage.
- File writes are atomic (tempfile + `os.replace`).
- Concurrent write of the queue file from two processes yields valid
  JSON in 100% of test runs.

**Risks.**

- Atomicity bugs (forgetting fsync, leaving stale tempfiles).
  Mitigated by helper functions and tests.

**Rollback strategy.**

- Store is opt-in per call site; old direct writes remain available
  during the migration. Reverting Phase 2 reverts each call-site
  migration independently.

---

## Phase 3 — Atomic checkout & explicit task state machine

**Objective.** Gate every task transition through a single function
and add `checkout_task` so duplicate work is impossible.

**Files / modules.**

- `backoffice/store/file_store.py` — implement `transition_task` and
  `checkout_task`.
- `backoffice/domain/state_machines.py` — codify allowed transitions.
- `backoffice/tasks.py` — CLI handlers (`start`, `block`, `review`,
  `complete`, `cancel`) call `Store.transition_task`.
- `backoffice/server.py`, `backoffice/api_server.py` — `/api/tasks/...`
  handlers call `Store.transition_task`.

**New APIs.**

- `Store.transition_task(task_id, to_state, *, actor, reason) -> Task`
- `Store.checkout_task(task_id, agent_id) -> Run | CheckoutConflict`
- `Run` rows now exist in storage.

**Tests.**

- `tests/store/test_checkout.py` — concurrent checkout attempts:
  exactly one wins, the other returns a structured conflict; resume by
  the same agent is permitted.
- `tests/store/test_transitions.py` — illegal transitions (`done →
  in_progress`, `cancelled → ready`, etc.) raise; legal transitions
  emit one audit event.
- `tests/server/test_tasks_endpoints.py` — endpoints emit audit events.

**Acceptance criteria.**

- Two parallel calls to `Store.checkout_task` resolve to one `Run`
  and one structured `CheckoutConflict`.
- Every CLI/HTTP transition produces an audit event.
- `task["history"]` continues to be written for compatibility.

**Risks.**

- Lock contention on the queue file. Mitigated by per-task locks (or a
  short critical section in the queue lock + per-run records elsewhere).

**Rollback strategy.**

- Wrappers fall back to the legacy direct-mutation path if a feature
  flag is set; default is on. Revert by toggling the flag and
  restoring the previous code.

---

## Phase 4 — Agent registry and adapter interface

**Objective.** First-class agents with a generic adapter contract.

**Files / modules.**

- New: `backoffice/agents.py` — `Agent` registry (CRUD over `Store`).
- New: `backoffice/adapters/base.py` — `Adapter` Protocol.
- New: `backoffice/adapters/noop.py` — deterministic test adapter.
- New: `backoffice/adapters/process.py` — wraps shell commands; today's
  `agents/*.sh` flows through here.
- New: `backoffice/adapters/legacy_backend.py` — wraps existing
  `backoffice.backends.Backend` so the router still routes.
- Light edits: `config/backoffice.yaml` schema gains an `agents:` block;
  `backoffice/config.py` parses it.
- New CLI: `python -m backoffice agents {list,create,pause,resume,retire}`.

**New APIs.**

- `Adapter.invoke(agent, task, run, context) -> AdapterHandle`
- `Adapter.status(agent, run, handle) -> AdapterStatus`
- `Adapter.cancel(agent, run, handle) -> AdapterCancelResult`
- `AgentRegistry.register(...)`, `pause(...)`, `resume(...)`.

**Tests.**

- `tests/adapters/test_noop_adapter.py` — deterministic round trip.
- `tests/adapters/test_process_adapter.py` — runs a harmless shell
  command (`bash -c 'echo ok'`); timeout enforcement; env allowlist.
- `tests/adapters/test_legacy_backend_adapter.py` — wraps the existing
  fake backend used in current tests.
- `tests/agents/test_registry.py` — pause/resume gates invocation.

**Acceptance criteria.**

- Operators can register/list/pause/resume agents from CLI.
- Process adapter passes a smoke test that does not require Claude/Codex.
- Adapter failures move the run to `failed` + emit an audit event;
  the task does not get stuck.
- No existing dashboard/CLI behavior breaks.

**Risks.**

- Process spawning races. Mitigated by reusing the existing
  `running_jobs`/`running_fix` discipline as a starting point and
  layering checkout-driven concurrency on top.

**Rollback strategy.**

- The agent registry is additive. The existing shell-script invocation
  path remains available until Phase 5 cuts over.

---

## Phase 5 — Claude Code adapter

**Objective.** Approved tasks can be executed via Claude Code in a
controlled isolated workspace, behind every existing guard.

**Files / modules.**

- New: `backoffice/adapters/claude_code.py` — implements the contract;
  spawns Claude Code (or a configurable command in tests) with prompt,
  cwd, environment allowlist, timeout, dry-run mode.
- New: `backoffice/prompts/templates/claude_code_task.md` — prompt
  template with placeholders for task id, repo, evidence, allowed
  files, acceptance criteria, test commands, PR expectations.
- New: workspace creation helper (Phase 10 hardens this).
- Edits: `agents/fix-bugs.sh` may stay as the fallback for now; new
  `claude_code` adapter is opt-in per agent.

**Safety requirements (must all hold).**

- Adapter never invokes against the working tree of `back-office`.
- Adapter never invokes without a referenced approval id.
- Disabled by default in tests; the binary path is configurable.
- Human approval remains required before `invoke()`.

**New APIs.**

- Adapter config keys: `command`, `model`, `prompt_template`,
  `timeout_seconds`, `env_allowlist`, `cwd_strategy`, `dry_run`.
- `claude_code.invoke()` returns a handle; structured run log is
  written to `results/runs/<run_id>.log` and the file path is recorded
  on the run.

**Tests.**

- `tests/adapters/test_claude_code_adapter.py` — uses a fake command
  (`echo`) configured via `command` to exercise success, failure,
  timeout, cancellation, and dry-run.
- `tests/integration/test_run_lifecycle.py` — end-to-end: queue →
  approve → checkout → invoke (fake) → succeeded → ready_for_review.

**Acceptance criteria.**

- Tests pass without Claude Code installed.
- Successful runs move the task to `ready_for_review`.
- Failed runs do not corrupt the queue.
- Run log artifact is recorded on the run record.

**Risks.**

- Prompt drift / hallucinated file edits. Mitigated by the existing
  preview/approve discipline (Phase 10 makes this explicit) and by
  the adapter not having merge permissions.
- Resource exhaustion on long runs. Mitigated by timeouts.

**Rollback strategy.**

- The Claude Code adapter is opt-in per agent. Disable the agent or
  remove its `adapter_type` to fall back to the existing process adapter.

---

## Phase 6 — Dashboard additions for agents and runs

**Objective.** Make the new state visible without disrupting the
existing department surface.

**Files / modules.**

- `dashboard/index.html` — new cards: Agents, Active Runs, Run Detail
  drawer, Routines stub, Cost stub.
- `dashboard/app.js` — fetch & render new payloads; existing rendering
  unchanged.
- New: `dashboard/agents-data.json`, `dashboard/runs-data.json`
  (machine-generated by `backoffice.aggregate` or a new
  `backoffice.dashboard_data` module).
- Server endpoints: `GET /api/agents`, `GET /api/runs`,
  `GET /api/runs/<id>` with the new data.

**Tests.**

- `tests/dashboard/test_agents_payload.py` — schema and shape.
- `tests/dashboard/test_runs_payload.py` — same.
- `tests/server/test_new_endpoints.py` — auth + 404 + happy-path.
- Snapshot tests if appropriate.

**Acceptance criteria.**

- Dashboard still renders existing data when no agents or runs exist.
- New cards render gracefully empty.
- Department × repo matrix and Approval Queue panel are unchanged.

**Risks.**

- UI regression. Mitigated by snapshot tests on existing payloads and
  manual smoke checks documented in the PR description.

**Rollback strategy.**

- New cards live behind a feature flag in `dashboard/app.js`. Toggle
  off or revert the index changes.

---

## Phase 7 — Cost & budget tracking

**Objective.** Track AI execution cost (estimated by default) and gate
new runs against budget policies.

**Files / modules.**

- New: `backoffice/budgets.py` — `Budget`, `BudgetPolicy`, evaluation.
- New: `backoffice/cost.py` — `CostEvent` writes via the store.
- Edits: adapters report cost on completion (estimate by default);
  Claude Code adapter sets `source=adapter_reported` when it knows;
  process adapter records duration only.
- Edits: checkout path consults budget policy; hard-limit hit blocks
  the new run with a structured reason.

**New APIs.**

- `BudgetPolicy.check(scope) -> AllowDecision`
- `Store.record_cost(event)`
- `GET /api/budgets`, `GET /api/runs/<id>/cost`.

**Tests.**

- `tests/budgets/test_policy.py` — soft/hard limits, scope ordering.
- `tests/budgets/test_block_at_hard_limit.py` — checkout returns a
  structured conflict and emits an audit event.
- `tests/budgets/test_cost_aggregation.py` — sums costs per run/task/agent/target.

**Acceptance criteria.**

- Soft-limit hit emits a warn audit event and proceeds.
- Hard-limit hit blocks the new run and shows up on the dashboard.
- Without explicit cost reports, runs still complete (unverified cost).
- Sum of cost events on a target matches the dashboard's budget card.

**Risks.**

- Mis-estimating cost. Cost is labeled `estimated` until verified;
  this is documented in `docs/budgets.md`.

**Rollback strategy.**

- Budget enforcement is per-scope. Set hard/soft limits to `null` to
  disable enforcement without removing the model.

---

## Phase 8 — Heartbeats & routines

**Objective.** Schedule recurring work declaratively. `overnight.sh`
becomes one routine among several.

**Files / modules.**

- New: `backoffice/routines.py` — `Routine`, `Trigger`, `Schedule`.
- New: `backoffice/scheduler.py` — local scheduler that respects pause
  state and budgets; runs in `backoffice serve` or as a separate process.
- Edits: `config/backoffice.yaml` gains a `routines:` block.
- `scripts/overnight.sh` continues to work; a `routines:` entry models
  the same intent so the loop can be replaced incrementally.

**New APIs.**

- `python -m backoffice routines {list, run, pause, resume}`
- `POST /api/routines/<id>/run`
- `GET /api/routines`

**Tests.**

- `tests/routines/test_manual_trigger.py`
- `tests/routines/test_cron_schedule.py`
- `tests/routines/test_pause_and_budget_block.py`

**Acceptance criteria.**

- A scheduled routine can enqueue an audit and a Product Owner pass.
- Paused agents are not invoked; budget-blocked agents are not invoked.
- Heartbeat events are audited.

**Risks.**

- Scheduler complexity. Mitigated by keeping it local, single-process,
  in-memory wake-ups; no distributed lock manager.

**Rollback strategy.**

- Routines are additive. Disable a routine via `paused: true`. Revert
  the scheduler module to fall back to operator-triggered work only.

---

## Phase 9 — Agent-facing API hardening

**Objective.** Allow agents (local subprocesses or future remote
processes) to interact with Back Office through a documented API with
scoped permissions.

**Files / modules.**

- New: `backoffice/auth.py` — per-agent API keys, scopes.
- Edits: `backoffice/server.py`, `backoffice/api_server.py` — endpoints
  authenticate either an operator or a scoped agent token; mutating
  endpoints write audit events with `actor.kind=agent`.
- New endpoints listed in `target-state.md` §7.2.

**Tests.**

- `tests/server/test_agent_auth.py` — scope checks; cross-agent
  mutations are denied.
- `tests/server/test_audit_actor.py` — every mutation records the
  correct actor.
- `tests/integration/test_agent_loop.py` — an agent can complete the
  full loop using only the API.

**Acceptance criteria.**

- An agent can checkout a task, log progress, report cost, mark ready
  for review, and request approval, all via API/CLI only.
- Unauthorized agents cannot mutate other agents' tasks.
- API responses are documented in `docs/agents.md` and `docs/adapters.md`.

**Risks.**

- API surface explosion. Mitigated by keeping the agent API small and
  loop-shaped (checkout → log → report → ready).

**Rollback strategy.**

- New endpoints are additive. Disable agent tokens to revert to
  operator-only access.

---

## Phase 10 — Workspace isolation & GitHub draft PR hardening

**Objective.** Make AI-generated repo changes safer and more reviewable
end-to-end.

**Files / modules.**

- New: `backoffice/workspaces.py` — `Workspace` lifecycle helpers
  (create, mark stale, retire). Replaces the implicit
  `back-office/preview/<job-id>` convention with a tracked record.
- Edits: `backoffice.preview`, `backoffice.review` — operate over
  `Workspace` rows instead of inferring branch names from artifacts.
- Edits: PR generation in `backoffice.server._handle_task_request_pr`
  includes provenance: task id, run id, approval id, evidence link,
  test result link.
- New: stale workspace cleanup routine (Phase 8).

**Rules (preserved & strengthened).**

- No direct commits to `main` / `master`.
- No auto-merge.
- Every PR includes provenance back to task/run/approval.
- Failed-test runs cannot generate a "ready to merge" PR.

**Tests.**

- `tests/workspaces/test_lifecycle.py`
- `tests/workspaces/test_pr_metadata.py` — PR body contains
  task/run/approval ids and evidence links.
- `tests/workspaces/test_cleanup.py`

**Acceptance criteria.**

- AI run produces a tracked workspace + branch + (optionally) draft PR.
- Draft PR body includes Back Office provenance and is gated on test
  results.
- Dashboard links a task to its PR and to the underlying workspace.

**Risks.**

- Stale branches in target repos. Mitigated by the cleanup routine
  and by retiring workspaces only after explicit `discard`/`approve`.

**Rollback strategy.**

- Workspace records are additive. Existing preview branches keep working
  during the transition.

---

## Phase 11 — Export / import & templates

**Objective.** Portable Back Office configuration without leaking
secrets.

**Files / modules.**

- New: `backoffice/portable.py` — export/import.
- CLI: `python -m backoffice export`, `python -m backoffice import
  [--dry-run]`.

**Scope.**

- Export: departments, policies, agent definitions (with secrets
  redacted to placeholders), budget policies, routine definitions,
  dashboard config.
- Import: validate schema; dry-run; conflict handling
  (skip / overwrite); placeholder substitution.

**Tests.**

- `tests/portable/test_round_trip.py`
- `tests/portable/test_secret_redaction.py`
- `tests/portable/test_dry_run.py`

**Acceptance criteria.**

- Export produces deterministic JSON/YAML.
- Import dry-run reports diffs without applying.
- Secrets are never exported in plaintext (test asserts).

**Risks.**

- Schema drift between releases. Mitigated by an explicit `version`
  field on the export and a compatibility shim.

**Rollback strategy.**

- Export/import is read-only on the export side; on the import side a
  dry-run is mandatory before apply. Safe to revert.

---

## Phase 12 — Plugin architecture (experimental)

**Objective.** Allow a small, explicit set of extension points without
turning Back Office into a marketplace.

**Files / modules.**

- New: `backoffice/plugins.py` — entry-point or config-based loader.
- Documented extension points: adapters, scanners, department checks,
  dashboard cards, budget reporters, notification sinks.

**Tests.**

- `tests/plugins/test_loader.py`
- `tests/plugins/test_isolation.py` — plugin failure does not break
  core workflows.

**Acceptance criteria.**

- An example plugin is provided in-tree (e.g. a "slack notification
  sink" stub).
- Plugin loading failures emit an audit event and continue.
- Plugin operations that mutate state are audited like any other.
- Stability level is documented as experimental in `docs/security.md`.

**Risks.**

- Plugin execution as a vector for code execution. Mitigated by
  explicit registration in config (no autoloading) and by documenting
  that plugins run with the same trust as Back Office itself.

**Rollback strategy.**

- Plugins are off by default. Remove the `plugins:` config block to
  disable.

---

## Cross-phase notes

### Test discipline

- Each phase ends with `make test` clean.
- New tests live next to existing modules (`tests/<area>/test_*.py`)
  using `pytest`; no new test framework is introduced.
- Tests must not require Claude Code, Codex, GitHub credentials, or
  network access. All adapters expose a fake/test mode.

### Documentation deliverables

Created or updated by the corresponding phase (see
`target-state.md` §7 for the dashboard surface):

| Phase | Doc |
|---|---|
| 0 | `docs/architecture/{current-state,target-state,phased-roadmap}.md` |
| 1 | `docs/task-lifecycle.md` |
| 2 | `docs/storage.md` (new), update `current-state.md` |
| 3 | update `docs/task-lifecycle.md` with checkout |
| 4 | `docs/agents.md`, `docs/adapters.md` |
| 5 | `docs/claude-code-adapter.md` |
| 6 | dashboard section of `docs/agents.md` |
| 7 | `docs/budgets.md` |
| 8 | `docs/routines.md` |
| 9 | `docs/security.md` (auth + scopes section) |
| 10 | update `docs/workflow-architecture.md` (new GitHub flow) |
| 11 | `docs/portable.md` |
| 12 | extend `docs/security.md` with the experimental plugin stance |

### Compatibility checkpoints

At the end of every phase, confirm:

- `python -m backoffice list-targets` works.
- `python -m backoffice tasks list` works.
- `python -m backoffice serve` renders the dashboard with no JS console errors.
- `dashboard/task-queue.json` has the same top-level shape as before.
- `results/overnight-ledger.jsonl` continues to receive entries when
  `overnight.sh` runs.

### Out of scope (explicitly)

These belong to a future, separate plan:

- Multi-tenant deployments.
- Hosted SaaS.
- A Back Office mobile app.
- Auto-merge of any kind.
- Any analytics that capture target-repo source code or user PII.

---

## Phase 1 plan (next action)

Phase 0 stops here. The next session should:

1. Open a worktree (`docs/architecture/...` lives on `main`).
2. Create the `backoffice/domain/` package and the converter module.
3. Add fixtures + tests in `tests/domain/`.
4. Implement just enough to round-trip an existing `task-queue.yaml`
   into typed `Task`/`Approval` objects and back.
5. Confirm `make test` is green.
6. Update `docs/task-lifecycle.md` with the explicit state machines.
7. Open a small PR titled `phase-1: domain models, no behavior change`.

Phase 1 should not modify any caller behavior. The point is to land
the model layer cleanly so Phase 2 can re-target storage, and Phases 3+
can adopt the state machines incrementally.
