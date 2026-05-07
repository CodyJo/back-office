# Safe-Apply Framework

Phase 2 of the cost-reduction redesign. Takes a finding from the canonical schema, resolves a fix strategy, applies it inside an isolated git worktree, verifies via the target's own `lint_command` + `test_command`, and either commits or rolls back. Honors per-target Autonomy policy.

Module: `backoffice/apply/`. CLI: `python -m backoffice apply <target>`.

---

## Default is dry-run

Mutations only happen when you pass `--apply` AND the target's Autonomy block allows `fix`. Without both, the framework creates a worktree, runs the strategy, captures the diff, and tears the worktree down without committing.

```bash
# Preview only (default)
python -m backoffice apply back-office --severity medium

# Actually mutate
python -m backoffice apply back-office --apply --max-changes 3
```

`--dry-run` wins over `--apply` if both are set.

---

## Lifecycle per finding

```
Finding (from scan or audit)
   │
   ▼
[1] Resolve strategy  ──→  ruff-fix | npm-audit-fix | semgrep-autofix | ai-delegate | manual
   │
   ▼  (skip if manual or ai-budget-blocked)
[2] Create git worktree on a fresh branch  back-office/apply/<target>-<finding-id>-<rand>
   │
   ▼
[3] Pre-verify  →  run target.lint_command + target.test_command in the worktree
   │
   ▼
[4] Apply strategy  →  ruff --fix --select <rule> <file>  (or equivalent)
   │
   ▼  (skip-with-error if no diff)
[5] Post-verify  →  run lint + test again
   │
   ▼  (rollback if anything passed pre but failed post)
[6] Commit (only if Autonomy.allow_auto_commit)  →  branch persists for human review
   │
   ▼
[7] Remove worktree (branch stays)  +  audit-events.jsonl entry
```

**Touchpoints we never cross**: pushing to a remote, opening PRs, merging, deploying. The branch sits in the target repo for human review.

---

## Fix strategies

| Strategy | Kind | When | Tool invocation |
|---|---|---|---|
| `ruff-fix` | deterministic | `source_tool == "ruff"` and `fixable_by_agent` | `ruff check --fix-only --select <rule_id> <file>` |
| `npm-audit-fix` | deterministic | `source_tool == "npm-audit"` and `fixable_by_agent` | `npm audit fix --no-fund --no-audit` |
| `semgrep-autofix` | deterministic | `source_tool == "semgrep"` and `fixable_by_agent` | `semgrep scan --config auto --autofix` |
| `ai-delegate` | ai | other `fixable_by_agent` cases | (Phase 2.5: invokes existing Fix Agent in worktree) |
| `manual` | manual | `fixable_by_agent: false` (e.g. gitleaks secrets, architectural changes) | no-op; recorded as `skipped: not-auto-fixable` |

The resolver in `backoffice/apply/strategies.py:resolve_strategy()` always returns a strategy — there's no "no strategy" sentinel. `manual` exists so callers can record "skipped" uniformly.

---

## Outcome states

Every finding produces an `ApplyOutcome` (recorded in `results/audit-events.jsonl` and the per-run summary at `results/<target>/apply-runs/<run-id>.json`):

| Status | Meaning |
|---|---|
| `dry-run` | Strategy would have applied; diff captured; worktree torn down |
| `applied` | Mutation committed to `back-office/apply/<target>-<id>-...` branch |
| `applied-uncommitted` | Mutation succeeded; `auto_commit` was disabled — worktree left for inspection |
| `rolled-back` | Either tests regressed or commit failed; branch + worktree deleted |
| `blocked` | Policy gate denied (`fix=false`, dirty worktree, etc.) |
| `skipped` | `manual` strategy, `ai-budget-blocked`, or `strategy-not-implemented` |
| `failed` | Strategy returned no change, or an exception during apply/worktree |

---

## CLI surface

| Flag | Purpose |
|---|---|
| `<target>` | Target name from `backoffice.yaml` |
| `--finding ID` | Apply one specific finding by id |
| `--source-tool TOOL` | Filter (e.g. `ruff`, `npm-audit`) |
| `--severity LEVEL` | Floor — default `medium` |
| `--max-changes N` | Cap per run — default `target.autonomy.max_changes_per_cycle`, else 3 |
| `--apply` | Actually mutate (default = dry-run) |
| `--dry-run` | Force dry-run; wins over `--apply` |

---

## Honors existing Autonomy / Policy

The runner calls `backoffice.policy.evaluate_gate(autonomy, "fix", ...)` and `evaluate_gate(autonomy, "auto_commit", ...)` before mutating. Conservative defaults from `backoffice.yaml`:

* `allow_fix: true` (default — required to apply at all)
* `require_clean_worktree: true` (default — refuses if the target repo has uncommitted changes)
* `allow_auto_commit: true` (default — commits to the new branch after verify)
* `max_changes_per_cycle: 3` (default — caps batch size)

Override per-target. Bumping `max_changes_per_cycle` to 10 lets a single invocation try 10 fixes; the cap protects against runaway batches.

---

## Budget interaction

`apply` calls `backoffice.budget_check.is_blocked(target, "qa")` once per invocation. If blocked:

* AI-delegate strategies are skipped with `reason="ai-budget-blocked"`
* Deterministic strategies (ruff, npm, semgrep autofix) **still run** — they cost nothing

So a budget-exhausted overnight loop can still apply free auto-fixes; only the AI escalations are paused.

---

## Verification

`backoffice/apply/verifier.py` runs `target.lint_command` and `target.test_command` (parsed via `shlex.split` — no shell injection). Each is allowed up to 600 seconds. The output tail (last 2 KB) is captured and stored on the outcome.

Regression detection: a check that **was passing pre-apply but is failing post-apply** triggers rollback. A check that was already failing before the change is tolerated — we don't punish a fix for not also fixing unrelated breakage.

---

## Audit log

Every outcome appends a line to `results/audit-events.jsonl`:

```json
{"at":"2026-...", "actor_id":"backoffice.apply", "action":"apply.applied",
 "subject_kind":"finding", "subject_id":"DET-ruff-F401-...",
 "after":{"status":"applied", "branch":"back-office/apply/...", "files_changed":["..."], ...}}
```

The log is rotated at 10 MiB by `backoffice.audit_rotation.maybe_rotate`.

A per-run summary sits at `results/<target>/apply-runs/apply-<timestamp>.json` for quick operator review.

---

## Tests

`tests/test_apply.py` — 21 tests covering strategy resolution, verifier, dry-run cleanup, real-apply commit-to-branch, regression rollback, blocked auto_commit, manual-skip, source-tool filter, severity floor, max-changes cap, scanner-status exclusion.

---

## Future Phase 2.5 work

* Wire `ai-delegate` strategy to invoke `agents/fix-bugs.sh` against the worktree (currently reports `strategy-not-implemented`)
* Push branches with `--push` flag (operator-consent touchpoint)
* Open draft PRs with `--pr` flag (uses existing `pr_body()` from `backoffice/workspaces.py`)
* Wire into `Quarantine` and `FailureMemory` so repeatedly-failing finding+target combos are auto-suppressed
