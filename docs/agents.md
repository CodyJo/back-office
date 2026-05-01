# Agents

Back Office tracks every actor that does work in the system as a
**registered agent**. Agents have identity, status, an adapter (the
thing that actually runs them), and an optional budget.

This page is the operator manual for agent registration and the agent
HTTP API.

---

## CLI

```bash
# Register a new agent
python -m backoffice agents create \
  --id agent-fix \
  --name fix-agent \
  --role fixer \
  --adapter-type process

# List agents
python -m backoffice agents list

# Show one
python -m backoffice agents show agent-fix

# Pause / resume / retire
python -m backoffice agents pause  agent-fix
python -m backoffice agents resume agent-fix
python -m backoffice agents retire agent-fix
```

`pause` is reversible; `retire` is permanent for the registry's
purposes (the JSON record stays for audit, but the agent no longer
appears as `active`).

---

## Roles

| Role | Description |
|---|---|
| `fixer` | Auto-remediates QA findings (e.g. `agents/fix-bugs.sh`). |
| `feature_dev` | Implements small/medium features under approval. |
| `scanner` | Department audit (qa, seo, ada, compliance, monetization, product, cloud-ops). |
| `product_owner` | Generates prioritised work plans. |
| `mentor` | Educational planning. |
| `reviewer` | Reviews proposed work or PRs. |
| `custom` | Anything else; the operator names the role. |

---

## Adapters

Adapters are the bridge between the registry and execution. See
`docs/adapters.md` for the full contract. Each agent declares one:

```yaml
agents:
  fix-agent:
    role: fixer
    adapter_type: process
    adapter_config:
      command: "bash agents/fix-bugs.sh"
      env_allowlist: [PATH, HOME]
```

Built-in adapter types: `noop`, `process`, `legacy_backend`,
`claude_code`. Plugins can add more (`docs/security.md`).

---

## Authentication

Agents authenticate to the HTTP API with **per-agent tokens**.
Operators issue them:

```bash
python -m backoffice tokens issue --agent-id agent-fix
# Prints a `bo-...` plaintext token — captured ONCE; only the
# SHA-256 hash is persisted to disk.
```

Revoke:

```bash
python -m backoffice tokens revoke --token bo-...
python -m backoffice tokens revoke-all --agent-id agent-fix
```

The plaintext is never logged, never echoed in `tokens list`, and
never returned by any endpoint. Operators must capture it at issue
time.

---

## Agent HTTP API

All endpoints take `Authorization: Bearer <token>`. Cross-agent
mutations are denied — an agent can only mutate runs it owns.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/tasks/<id>/checkout` | Atomic claim. Body `{adapter_type?, approval_id?}`. |
| `POST` | `/api/runs/<id>/log` | Append a log entry. Body `{message, level?}`. |
| `POST` | `/api/runs/<id>/cost` | Report cost. Body `{provider, model, input_tokens, output_tokens, estimated_cost_usd, verified?, source?, target?}`. |
| `POST` | `/api/runs/<id>/ready-for-review` | Mark run + task done. |
| `POST` | `/api/runs/<id>/cancel` | Cancel the run. |
| `POST` | `/api/approvals/request` | Body `{task_id, scope?, note?}`. Returns an approval id. |
| `POST` | `/api/approvals/<id>/decide` | **Operator-only**. Body `{decision: approved|rejected, by, note?}`. |

Response shape:

* `2xx` — `{"ok": true, ...}`
* `4xx` — `{"error": "<code>", ...}` with stable error codes
  (`already_running`, `task_not_found`, `cross_agent_denied`,
  `illegal_task_transition`, `budget_blocked`, `tests_failed`, …)
* `5xx` — `{"error": "<short>"}` — never includes a stack trace.

---

## Lifecycle

A typical agent loop:

1. **Get assigned tasks** — `GET /api/agents/<id>/tasks` (operator
   surfaces or by polling the dashboard's `/api/tasks` payload).
2. **Checkout** — `POST /api/tasks/<id>/checkout` with the agent's
   token. On success Back Office moves the task to `checked_out`,
   creates a `Run`, and returns the run id.
3. **Work** — adapter executes; agent appends `/api/runs/<id>/log`
   entries and reports cost via `/api/runs/<id>/cost` as available.
4. **Ready for review** — `POST /api/runs/<id>/ready-for-review`.
   Back Office moves the task to `ready_for_review`.
5. **Operator decides** — operator opens a draft PR via the dashboard
   (which calls `/api/tasks/request-pr`). PR body carries Back Office
   provenance (task / run / approval / branch ids).

Failures at any step land cleanly: the run moves to `failed` (or the
agent calls `/api/runs/<id>/cancel`), the task can be re-queued, and
no state gets stuck.
