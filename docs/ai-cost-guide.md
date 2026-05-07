# AI Cost Guide

How to keep the Back Office's Anthropic spend bounded while still getting useful audits.

This doc tracks the cost surface introduced by the cost-reduction redesign (Phases 1–5). For the architecture, see `docs/architecture/phased-roadmap.md`.

---

## TL;DR — pick the right mode for the situation

| Situation | Mode | Cost / target / cycle |
|---|---|---|
| Overnight loop, all 12 targets, budget tight | `python -m backoffice scan <t>` (deterministic-only) | **$0** |
| Daily QA on changed branches | `agents/qa-scan.sh <t>` (hybrid mode, default) | ~$0.05–0.50 |
| Weekly deep review (architecture / novel issues) | `agents/qa-scan.sh <t> --ai-only` | ~$1.00–5.00 |
| Budget exhausted (org cap hit) | Any of the above + `budget-check` gate | falls back to deterministic-only |
| Per-finding fix attempt | `python -m backoffice apply <t>` (dry-run by default) | $0 for ruff/npm/semgrep autofix |

The new tooling defaults to the cheap path. Costs only land when you explicitly opt in to the AI side.

---

## Cost components per cycle

### Deterministic scanners — $0

`semgrep`, `ruff`, `bandit`, `pip-audit`, `npm audit`, `gitleaks`, `lighthouse`, `axe-core`, `checkov`, `tfsec`, `license-checker` all run locally. Wall time per repo: 5–60 seconds depending on tool installation and repo size.

The deterministic scanner is the new floor. If a department has no useful deterministic tools (Monetization, Product), the loop emits a `scanner-status` finding noting that AI scanning is the only mode for that department.

### Hybrid AI step — small per call

When `agents/qa-scan.sh` runs in default (hybrid) mode, Claude is invoked **only on changed files since `origin/main`**:

- Empty-changeset PRs: $0 (Claude skipped entirely)
- 1–10 changed files: typically a single Claude call with a focused prompt
- The deterministic findings are pre-seeded so Claude doesn't re-discover them

The system prompt for QA is identical across all 12 targets. With prompt caching enabled (next section), each target after the first costs ~10% of the first.

### AI-only step — full cost

`--ai-only` reverts to pre-redesign behavior: Claude scans the entire repo from scratch, no deterministic seeding, no file focus. Use for weekly deep reviews where architectural / judgment issues matter most.

---

## Prompt caching

Anthropic's `cache_control: ephemeral` cache has a 5-minute TTL. Anything in the system prompt that's reused across calls in that window costs ~10% of normal input pricing.

**The savings only land if you batch.** Calling Claude on one target, waiting 30 minutes, then calling on the next pays full price both times. Run all 12 targets in one batch and save ~70%.

The redesigned `backoffice.llm.client.call_anthropic()` enables `cache_control` automatically when the system prompt is over ~1KB. Audit-agent system prompts are typically 8–15 KB, so this is always on.

### Quantitative example

| Scenario | Approx cost (Sonnet 4.6) |
|---|---|
| 1 target, no cache | $0.15 |
| 1 target, cache enabled (cold start) | $0.18 (paid the cache write) |
| 12 targets, no cache | $1.80 |
| 12 targets, cache enabled (1 write + 11 reads) | $0.36 |

Cache writes cost slightly more than baseline input; cache reads cost ~10%. The crossover happens after the **second** call within the TTL window.

---

## Model tier guide

| Tier | When to use | Approx $/MTok input |
|---|---|---|
| **Haiku 4.5** | Triage, dedup, severity refinement, fix-suggestion enrichment, batch dispatch | $0.80 |
| **Sonnet 4.6** | Default for QA / SEO / ADA scanning, hybrid mode, judgment-driven analysis | $3.00 |
| **Opus 4.7** | Reserved for the deepest architectural reviews, complex multi-file refactor planning | $15.00 |

Haiku is good enough for ~70% of what the QA scanner currently uses Sonnet for, especially the structured outputs (severity tables, JSON findings). Reserve Sonnet for prose and Opus for genuinely hard reasoning.

The `backoffice.llm.client.get_model_for_tier()` helper resolves `"haiku"` / `"sonnet"` / `"opus"` to the latest pinned model id — version-bump in one place.

---

## Batch API

For non-urgent work (overnight loops, periodic recompute, retroactive audits), use Anthropic's Message Batches API: 50% off list pricing in exchange for 24-hour turnaround.

Wiring is not yet integrated into the Back Office (Phase 6+ work), but it's the natural next step for departments where overnight latency is fine.

---

## Budget enforcement

The redesign introduces:

* `python -m backoffice budget-check <target> --department qa` — exit 0 (allow / warn) or 1 (block). Used by `agents/qa-scan.sh` to fall back to deterministic-only when the AI budget is exhausted.
* `Budget` declarations in `backoffice.yaml` under `budgets:`. Scope can be `global`, `target`, `department`, `agent`, `task`, `run`. Periods: `daily`, `weekly`, `monthly`, `rolling_24h`, `lifetime`.
* `BudgetDecision.state` ∈ `{allow, warn, block}`. The most restrictive matching budget wins.

Recommended baseline (add to `backoffice.yaml`):

```yaml
budgets:
  - id: monthly-cap
    scope: global
    period: monthly
    soft_limit_usd: 15.00
    hard_limit_usd: 20.00
    notes: "Match the org's $20 monthly extra-usage cap; warn at 75%."

  - id: per-target-daily
    scope: target
    scope_id: codyjo.com
    period: daily
    hard_limit_usd: 1.00
    notes: "No single target should burn more than $1/day."
```

When `block` fires, the `qa-scan.sh` shell wrapper logs `Budget BLOCK — falling back to deterministic-only` and exits 0 — the loop keeps producing value instead of crashing on the cap.

---

## Haiku triage (off by default)

`scan.haiku_triage: true` in config enables a Haiku pass over the deterministic-scanner output: confirms severity, adds `ai_confidence` ∈ `{high, medium, low}`, and fills in missing `fix_suggestion` text.

Cost: ~$0.001 per finding (Haiku, system prompt cached). 200 findings ≈ $0.20. Capped per-scan at 50 findings (configurable in `triage.py`).

It's off by default because it costs money and the deterministic findings are already structured. Turn it on when you start doing PR reviews based on the dashboard and want false-positive filtering.

---

## Cost projection helper

```python
from backoffice.llm.cost_estimator import project_dept_scan_cost

print(project_dept_scan_cost(
    model="sonnet",
    system_prompt_tokens=10_000,
    user_prompt_tokens=2_000,
    output_tokens=3_000,
    targets=12,
))
```

Returns a dict with `first_call_usd`, `per_subsequent_usd`, `total_usd`, and the model's pricing breakdown. Useful before turning on a new department or loop.

---

## Cost recording

Every API call routed through `backoffice.llm.client.call_anthropic()` writes to `results/cost-events.jsonl`:

```json
{"id":"cost-...", "timestamp":"...", "provider":"anthropic", "model":"claude-haiku-4-5-20251001",
 "input_tokens": 1200, "output_tokens": 200, "estimated_cost_usd": 0.0018,
 "source": "provider_api", "target": "codyjo.com", "agent_id": "backoffice.llm.qa-triage"}
```

`python -m backoffice budgets list` shows current budgets; `python -m backoffice budgets spend` shows accumulated spend by scope.

The dashboard does not yet surface cost panels — Phase 6 work.

---

## Operational rules of thumb

1. **Default to deterministic.** If you can't articulate why an AI step is necessary for this scan, don't enable it.
2. **Cache or batch.** If you must call the AI, run all targets in the same window so the system prompt cache pays off.
3. **Pick Haiku unless prose matters.** The structured output for severity tables and finding JSON works fine on Haiku.
4. **Set hard budget caps.** Anthropic's spend cap and your `backoffice.yaml` budgets should be the same number — if you blow through the local one, you'll trip the org one too.
5. **Trust deterministic dedup.** Don't re-run the AI to confirm what semgrep already found — that's what `aggregate_qa`'s merge does for free.
6. **Skip-when-unchanged.** Phase 2a's git SHA tracking means re-running the same loop on the same commits costs zero. Don't manually invalidate state.
