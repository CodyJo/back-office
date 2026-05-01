# Budgets

Back Office tracks AI execution cost via :mod:`backoffice.budgets`.
Cost is **estimated by default**; adapters can mark events
`verified` when the provider returns ground truth.

---

## Configuration

`config/backoffice.yaml`:

```yaml
budgets:
  - id: global-monthly
    scope: global
    period: monthly
    soft_limit_usd: 50
    hard_limit_usd: 100

  - id: codyjo-com-monthly
    scope: target
    scope_id: codyjo.com
    period: monthly
    hard_limit_usd: 25

  - id: fix-agent-day
    scope: agent
    scope_id: agent-fix
    period: daily
    soft_limit_usd: 5
    hard_limit_usd: 10
```

Scopes: `global`, `target`, `department`, `agent`, `task`, `run`.
Periods: `daily`, `weekly`, `monthly`, `rolling_24h`, `lifetime`.
At the time of writing, period filtering is informational; the
evaluator sums lifetime spend in the matching scope. Time-window
filtering is a roadmap item.

---

## Evaluation

Programmatic:

```python
from backoffice.budgets import evaluate, list_cost_events, from_config
from backoffice.config import load_config
from backoffice.store import FileStore

config = load_config()
budgets = from_config(config.budgets)
events = list_cost_events(FileStore())

decision = evaluate(budgets, events, agent_id="agent-fix")
if not decision.ok:
    raise RuntimeError(f"budget block: {decision.reason}")
```

CLI:

```bash
python -m backoffice budgets list
python -m backoffice budgets spend
python -m backoffice budgets evaluate --agent-id agent-fix
```

`evaluate` returns the **most restrictive** decision across all
matching budgets:

* Hard limit hit → `block`. The agent API returns HTTP 402 with
  `{"error": "budget_blocked", ...}`.
* Soft limit hit → `warn`. Logged + audit event; checkout proceeds.
* Otherwise → `allow`.

---

## Recording cost

The agent reports cost via the API:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"provider":"anthropic","model":"claude-opus-4-7","input_tokens":1500,"output_tokens":300,"estimated_cost_usd":0.0225}' \
     https://admin.codyjo.com/api/runs/run-abc/cost
```

Or programmatically:

```python
from backoffice.budgets import record_cost
record_cost(store, provider="anthropic", model="claude-opus-4-7",
            input_tokens=1500, output_tokens=300,
            estimated_cost_usd=0.0225, run_id="run-abc",
            agent_id="agent-fix", target="codyjo.com")
```

Persisted to `results/cost-events.jsonl`. Each event carries
`source ∈ {estimate, adapter_reported, provider_api}` so dashboards
can label uncertainty.

---

## Where cost guards run today

* **Routine fires** — `Scheduler.run_now` honors the routine's
  optional `budget_id`; a `block` decision is recorded as
  `routine.blocked`.
* **Agent checkout** — `handle_checkout(... , budgets=)` returns 402
  when over a hard limit. Server wiring is opt-in.
* **Manual evaluation** — operators run `python -m backoffice
  budgets evaluate` to predict.

Future phases will tighten checkout to always consult the configured
budgets list.
