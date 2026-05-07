# Back Office — User Guide

A 15-minute guide to running the Back Office on your own portfolio of repos.

This guide assumes you've cloned the Back Office repo and have Python 3.11+. For the architectural overview, see the top-level `README.md`.

---

## TL;DR — What's installed and what you can do today

You have three classes of capability, in order of cost:

1. **Free, fast, no AI** — `python -m backoffice scan <target>`. Runs OSS tools (ruff/semgrep/etc.) and produces structured findings in seconds. **$0 spend.** Always your first move.
2. **Cheap AI (when configured)** — `agents/qa-scan.sh <target>` in default hybrid mode. Runs deterministic scanners, then asks Claude only about changed files. **$0–$0.50 per scan.**
3. **Safe auto-fixes** — `python -m backoffice apply <target>`. Worktree-isolated, lint+test verified, rollback on regression, dry-run by default. **$0** for ruff/npm/semgrep autofix. Honors per-target Autonomy gates.

You can use #1 immediately. #2 and #3 work standalone; full AI pipelines need an `ANTHROPIC_API_KEY`.

---

## Step 1: Setup (5 minutes)

### 1a. Install Python deps

```bash
cd /path/to/back-office
pip install -e .              # installs backoffice + ruff + dev tooling
```

### 1b. Install free deterministic scanners (recommended)

The scanners gracefully skip when their tool isn't installed (and surface a coverage gap on the dashboard), but you'll get the most value with all of them:

```bash
# Python tooling
pip install bandit pip-audit checkov

# JS / general
brew install gitleaks semgrep            # macOS
# or: snap install gitleaks semgrep      # linux
# or follow the install docs for each tool

# Optional — for SEO / ADA / cloud-ops scanners
npm i -g @axe-core/cli html-validate license-checker
brew install lighthouse tfsec
```

Verify what landed:

```bash
bash scripts/check-scanner-tools.sh
```

You should see `OK` next to most rows. Anything missing shows as `MISS` and produces an `info`-severity scanner-status finding when you scan — operationally fine; the dashboard surfaces the gap.

### 1c. Initial config

```bash
make setup
```

This creates `config/backoffice.yaml` with sane defaults. It is the **single source of truth** for everything: targets, runner config, autonomy policy, budgets.

### 1d. (Optional) Anthropic API key for the AI side

Without an API key, you can still use the deterministic scanners and safe-apply with `ruff --fix`/`npm audit fix`/`semgrep --autofix`. With one, you unlock the hybrid AI scan mode and the optional Haiku triage layer.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add it to your shell rc (`.zshrc` / `.bashrc`) for persistence.

---

## Step 2: Add a target repo (2 minutes)

Edit `config/backoffice.yaml`. Find the `targets:` block and add an entry:

```yaml
targets:
  my-app:                              # the target name (used in CLI)
    path: /home/me/projects/my-app     # absolute path to the repo
    language: typescript               # python | typescript | javascript | astro | terraform | ...
    lint_command: npm run lint         # used by the safe-apply verifier
    test_command: npm test             # ditto
    default_departments: [qa, seo]     # which audits to run by default
    context: |
      Customer-facing dashboard. Stateless API. Don't touch /admin/* — owned by another team.
    autonomy:
      allow_fix: true                  # safe-apply can mutate
      require_clean_worktree: true     # refuse if uncommitted changes exist
      allow_auto_commit: true          # commit to a back-office/apply/... branch
      max_changes_per_cycle: 3         # batch cap
      # Defaults below are conservative; opt in explicitly when ready
      # allow_feature_dev: false
      # allow_auto_merge: false
      # allow_auto_deploy: false
```

Verify:

```bash
python3 -m backoffice list-targets
```

You should see `my-app: /home/me/projects/my-app`.

### Polyglot repos

`language` is a single string, but the scanner ALSO probes physical markers (`pyproject.toml`, `package.json`, `*.tf`) at the repo root and one level deep. So a Python repo with a `marketing/` Astro subdir gets ruff + bandit + npm-audit automatically. You don't need to declare polyglot.

---

## Step 3: Run your first scan (30 seconds)

```bash
python3 -m backoffice scan my-app
```

Output:

```
Scanned my-app: 12 findings (0C/3H/5M/4L/0I) + 2 scanner-status note(s) — 4 tools ok, 2 skipped.
```

Format: `<critical>C/<high>H/<medium>M/<low>L/<info>I`. Scanner-status notes (e.g. "semgrep not installed") don't count toward severity totals but appear in the findings list.

The full payload landed at `results/my-app/qa-deterministic-findings.json`.

### Try other departments

```bash
python3 -m backoffice scan my-app --department seo          # lighthouse + html-validate
python3 -m backoffice scan my-app --department ada          # axe-core
python3 -m backoffice scan my-app --department compliance   # license-checker + gitleaks
python3 -m backoffice scan my-app --department cloud-ops    # checkov + tfsec
```

`monetization` and `product` are AI-only — no deterministic tools usefully evaluate revenue strategy or roadmap judgment. Use `make monetization TARGET=...` or `make product TARGET=...` (legacy AI-driven path) for those.

### See it in the dashboard

```bash
python3 -m backoffice refresh        # rebuild dashboard JSON
python3 -m backoffice serve --port 8070
open http://localhost:8070
```

The dashboard shows findings grouped by department, with severity breakdowns and scanner coverage. Deterministic findings sit alongside AI findings, deduped on `(department, repo, title, file)`.

### Re-run is free

```bash
python3 -m backoffice scan my-app
# → Skipped my-app/qa: unchanged-since-2026-05-06T18:35:41 (use force=True to re-scan)
```

The runner remembers your repo's HEAD SHA per (target, dept) in `results/scan-state.json`. Unchanged repos return their prior payload from disk in milliseconds. Pass `--force` to override.

---

## Step 4: Apply a fix safely (2 minutes)

```bash
# Preview only — default mode
python3 -m backoffice apply my-app --severity medium
```

You'll see something like:

```
DRY-RUN • my-app • 3 finding(s)
────────────────────────────────────────────────────────────
  [dry-run               ] DET-ruff-F401-app.ts-15           via ruff-fix          (dry-run-ok)  files: app.ts
  [dry-run               ] DET-npm-audit-lodash-1            via npm-audit-fix     (dry-run-ok)  files: package.json
  [skipped               ] DET-gitleaks-aws-key-secrets.env-3 via manual            (not-auto-fixable)  files: —
────────────────────────────────────────────────────────────
Summary: dry-run=2, skipped=1
Run record: results/my-app/apply-runs/apply-20260507T...json
(Re-run with --apply to actually commit changes.)
```

Each `dry-run` finding had its strategy applied in a temporary worktree, the diff captured, lint+test re-run, and the worktree torn down. Nothing changed in your real repo. The `manual` skip is correct: gitleaks secrets need rotation, not auto-fix.

When you're ready to actually mutate:

```bash
python3 -m backoffice apply my-app --apply --max-changes 3
```

Each finding lands as a separate commit on a new branch like `back-office/apply/my-app-DET-ruff-F401-app.ts-15-a1b2c3`. Your default branch (main / master) is never touched. Review the branches:

```bash
cd /home/me/projects/my-app
git branch | grep back-office/apply
```

Push or open a PR yourself when you're ready — the framework intentionally never pushes or opens PRs without you.

### Filter what gets attempted

```bash
# Only ruff fixes
python3 -m backoffice apply my-app --apply --source-tool ruff

# Only one specific finding
python3 -m backoffice apply my-app --apply --finding DET-ruff-F401-app.ts-15

# Only critical/high severity
python3 -m backoffice apply my-app --apply --severity high
```

### What if tests regress?

The verifier runs `lint_command` + `test_command` BEFORE applying (baseline) and AFTER (regression check). If something that was passing now fails, the worktree and branch are deleted; the audit log records `status: rolled-back, reason: verify-regressed`. Your repo is untouched.

---

## Step 5: Set up budget guardrails (3 minutes)

The AI side of the scan is the only place that costs money. Add a budget rule to `backoffice.yaml`:

```yaml
budgets:
  - id: monthly-cap
    scope: global
    period: monthly
    soft_limit_usd: 15.00
    hard_limit_usd: 20.00
    notes: "Match the org's $20 monthly extra-usage cap. Warn at 75%."
```

Now check the gate:

```bash
python3 -m backoffice budget-check my-app
# {"state": "allow", "spent_usd": 0.0, "limit_usd": 20.0, "budget_id": "monthly-cap", "reason": ""}
```

When the cap is hit, the gate returns `state: block` and the `qa-scan.sh` shell wrapper auto-falls-back to deterministic-only mode. The overnight loop keeps producing free findings instead of crashing on the cap.

See `docs/ai-cost-guide.md` for the full pricing breakdown, model-tier guidance, and prompt-caching specifics.

---

## Step 6: Wire it into your overnight loop

The hybrid mode already lives in `agents/qa-scan.sh`. To run it on all targets nightly:

```bash
make overnight
```

This runs the full audit + decide + fix + verify + deploy cycle from `config/backoffice.yaml`. Stop with `make overnight-stop`. Status: `make overnight-status`.

For a more focused weekly cron (deterministic-only across all targets, no AI spend at all):

```bash
# In your crontab (every weekday at 3am):
0 3 * * 1-5  cd /path/to/back-office && for t in $(python3 -m backoffice list-targets 2>&1 | awk -F: '/INFO/ {gsub(/.*workflow: /, ""); print $1}'); do python3 -m backoffice scan "$t" || true; done && python3 -m backoffice refresh
```

---

## Common operations

| I want to… | Command |
|---|---|
| List configured targets | `python3 -m backoffice list-targets` |
| Run free QA scan on one target | `python3 -m backoffice scan my-app` |
| Force re-scan (bypass SHA cache) | `python3 -m backoffice scan my-app --force` |
| Run only ruff | `python3 -m backoffice scan my-app --tools ruff` |
| Show what tools would run | `python3 -m backoffice scan my-app --dry-run` |
| Preview safe-apply outcomes | `python3 -m backoffice apply my-app` |
| Actually apply ruff fixes | `python3 -m backoffice apply my-app --apply --source-tool ruff` |
| Apply one specific finding | `python3 -m backoffice apply my-app --apply --finding F001` |
| Check AI budget gate | `python3 -m backoffice budget-check my-app` |
| Refresh dashboard | `python3 -m backoffice refresh` |
| Open dashboard | `python3 -m backoffice serve --port 8070` |
| Check installed scanner tools | `bash scripts/check-scanner-tools.sh` |
| Run all tests | `make test` |

Make targets (convenience wrappers):

| Make | Equivalent CLI |
|---|---|
| `make scan TARGET_NAME=my-app` | `python3 -m backoffice scan my-app` |
| `make scan TARGET_NAME=my-app DEPT=seo` | `python3 -m backoffice scan my-app --department seo` |
| `make scan-all` | scan every configured target |
| `make scan-tools-check` | inspect installed scanners |
| `make apply-dry TARGET_NAME=my-app` | preview safe-apply |
| `make apply TARGET_NAME=my-app` | actually apply |
| `make budget-check TARGET_NAME=my-app` | budget gate |

---

## Troubleshooting

### "Unknown target" error

Run `python3 -m backoffice list-targets` to confirm the target name. The CLI takes the **target name from `backoffice.yaml`**, not a filesystem path. If you see your target listed but the CLI doesn't recognize it, check `python3 -m backoffice check-drift` for a `targets.yaml` ↔ `backoffice.yaml` drift report.

### Scanner says "not in PATH" for tools you installed

Check `bash scripts/check-scanner-tools.sh`. The scanners use `shutil.which` to locate binaries. If the binary is in `~/.local/bin` or a virtualenv, make sure that directory is on your `PATH` when running `python -m backoffice scan`.

### Apply says "strategy-not-implemented"

That finding's source tool isn't covered by a deterministic auto-fix yet (e.g. semgrep findings without `--autofix` patches, or AI-delegate cases). Fix it manually for now. Phase 2.5 wires the AI-delegate path to the existing Fix Agent.

### Apply says "blocked: worktree_dirty"

Your target repo has uncommitted changes. Either commit/stash them first, or set `autonomy.require_clean_worktree: false` for that target if you accept the risk of mixing your changes with auto-fixes (not recommended).

### Apply rolls back with "verify-regressed"

The fix passed lint or test pre-apply but broke something post-apply. The framework correctly refused to commit. Read the per-run summary at `results/<target>/apply-runs/apply-<ts>.json` — the `post_verify.output` field has the failure tail. Decide whether to file a bug against the tool's autofix or apply manually with adjustment.

### "Budget BLOCK" on a `qa-scan.sh` run

You hit a `hard_limit_usd` in your `budgets:` config. The shell wrapper auto-fell-back to deterministic-only and exited 0. To raise the cap, edit `backoffice.yaml`. To force AI mode anyway, pass `--ai-only` to `qa-scan.sh` (will fail with `usage limit` from Anthropic if you're also over the org cap).

### My deterministic findings aren't showing up in the dashboard

Run `python3 -m backoffice refresh` after scanning. The dashboard reads `dashboard/qa-data.json` (etc.) which `refresh` regenerates from `results/<repo>/<dept>-deterministic-findings.json` + `results/<repo>/findings.json`. If you see the per-repo file but it doesn't appear after refresh, check that the target name matches `config/backoffice.yaml` exactly (no typos, no path-vs-name confusion).

---

## Where to read next

- `docs/deterministic-scanners.md` — full scanner reference, tool selection rules, severity tables
- `docs/safe-apply.md` — strategy registry, lifecycle, outcome states, audit log format
- `docs/ai-cost-guide.md` — model tiers, prompt caching, batch API, budget recipes
- `docs/budgets.md` — the underlying `Budget` data model and `evaluate()` semantics
- `docs/security.md` — privacy/compliance/security control list
- `docs/architecture/phased-roadmap.md` — full rollout plan (you're at Phase 5 of the cost-reduction redesign)
- `MASTER-PROMPT.md` — the governing engineering prompt (autonomy safety, operating priorities)
