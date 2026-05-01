# Task Lifecycle

The Back Office task queue is the operating record for AI-assisted
work in this portfolio. Every task moves through an explicit state
machine, every transition writes one structured audit event, and every
state-changing call validates against the same allow-list.

This document is the reference for that lifecycle.

---

## State diagram

```
                                ┌───────────────┐
                                │   proposed    │
                                └─┬───────┬─────┘
                                  │       │
                       approve gate│       │ start
                                  ▼       ▼
                       ┌──────────────────┐    ┌────────────┐
                       │ pending_approval │    │ in_progress│ ◀──┐
                       └────────┬─────────┘    └──┬─────┬───┘    │
                                │                  │     │        │
                          approve│                  │     │        │ resume
                                ▼                  │     │        │
                       ┌──────────────────┐        │     │   ┌───────────┐
                       │     ready        │ ─────► │     │   │  blocked  │
                       └────────┬─────────┘        │     ▼   └─────┬─────┘
                                │                  ▼ ┌──────────────┐│
                          claim │           ┌──────────────────┐│   ││
                                ▼           │ ready_for_review │┘   ││
                       ┌──────────────────┐ └─────────┬────────┘    ││
                       │     queued       │           │             ││
                       └────────┬─────────┘    open PR│             ││
                                │ checkout            ▼             ││
                                ▼               ┌──────────┐        ││
                       ┌──────────────────┐     │ pr_open  │        ││
                       │   checked_out    │     └──────────┘        ││
                       └──────────────────┘            │            ││
                                                merge  │            ││
                                                       ▼            ││
                                                ┌──────────┐        ││
                                                │   done   │        ││
                                                └──────────┘        ││
                                                                    ││
                                          (any state) ─cancel──► cancelled
                                          (running) ─error────► failed ──retry─► queued/ready
```

The authoritative table lives in `backoffice/domain/state_machines.py`
under `TASK_TRANSITIONS`. Adding or removing a transition there is the
only correct way to change behavior.

---

## State meanings

| State | Meaning |
|---|---|
| `proposed` | Default state after `tasks create` without `--status`. Author has not requested approval yet. |
| `pending_approval` | Author has explicitly queued the task for human approval. The dashboard "Approval Queue" surfaces these. |
| `approved` | Approver has granted approval but no agent has been chosen. Phase 4+ uses this when the registry knows about the agent ahead of time. |
| `ready` | Equivalent to `approved` for the legacy approval flow — `/api/tasks/approve` writes this directly so existing dashboards keep working. |
| `queued` | Approved and waiting for an agent to claim it. |
| `checked_out` | An agent atomically claimed the task (`Store.checkout_task`) and a `Run` exists. New in Phase 3. |
| `in_progress` | Active work. The legacy CLI `tasks start` writes this. |
| `blocked` | Active work paused on an external dependency. |
| `ready_for_review` | Implementation done; gates not yet satisfied. |
| `pr_open` | A draft GitHub PR has been opened (`/api/tasks/request-pr`). |
| `done` | Merged + verified. Terminal. |
| `failed` | Run failed; the task is recoverable via re-queue. |
| `cancelled` | Operator stopped the work. Terminal. |

---

## Transition rules

Three kinds of caller mutate task state today:

1. **CLI** — `python -m backoffice tasks {start, block, review, complete,
   cancel}` flow through `backoffice.tasks.update_status`. The legacy
   `proposed → in_progress` move is permitted (see
   `TASK_TRANSITIONS["proposed"]`).
2. **Operator HTTP** — `/api/tasks/approve`, `/api/tasks/cancel`,
   `/api/tasks/request-pr` validate via the same state machine and
   return **HTTP 409** with a `legal_targets` array when the move is
   refused.
3. **Agent HTTP** — `/api/tasks/<id>/checkout` and the run endpoints
   only mutate state via `Store.checkout_task` and
   `Store.transition_task`. Agents cannot bypass validation.

Illegal transitions:

* CLI: `update_status` returns rc=2; the queue is **not written**.
* HTTP: 409 response, queue is not written.

---

## Audit guarantees

Every state change emits one `task.transition` audit event to
`results/audit-events.jsonl`:

```jsonl
{"id":"evt-...","at":"2026-04-29T12:30:00Z","actor_id":"operator",
 "action":"task.transition","subject_kind":"task","subject_id":"back-office:fix-foo:...",
 "before":{"status":"pending_approval"},"after":{"status":"ready"},"reason":"lgtm","metadata":{}}
```

The legacy `task["history"]` list continues to be written for
backwards compatibility — the audit log is the new authoritative
cross-task feed.

`/api/tasks/{approve,cancel,request-pr}` emit specialized actions
(`task.approve`, `task.cancel`, `task.request_pr`) so dashboards can
distinguish operator decisions from generic transitions.

---

## Concurrency

`Store.transition_task` and `Store.checkout_task` both acquire a
fcntl-based lock on `results/.locks/task-queue.lock` for the entire
read-modify-write cycle. Concurrent writers serialize cleanly:

* Two parallel checkout attempts ⇒ exactly one wins; the other
  receives a structured `CheckoutConflict` with `reason=already_running`
  and `held_by_agent_id` populated.
* Two transitions on the same task ⇒ second waits for the first; both
  succeed if both moves remain legal.

Underneath, every queue write is atomic (`atomic_write_yaml` /
`atomic_write_json` use tempfile + `os.replace`). Readers always see a
consistent file.

---

## Recovery

The system is designed so a crash mid-write never leaves a task wedged:

* Run records are written **before** the queue update during checkout,
  so a crash leaves an orphan run file (easy to GC) rather than a task
  stuck in `checked_out` with no run.
* `current_run_id` pointing at a terminal or missing run is treated as
  stale — the next checkout proceeds with a fresh run.
* Failed transitions never write the queue.

Operators recover via the existing `tasks list` / `tasks show` / `tasks
cancel` commands, and via direct edits to `config/task-queue.yaml`
when truly necessary.
