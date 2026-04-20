# Back Office — Agent Instructions

> **Governing prompt:** See `MASTER-PROMPT.md` for autonomy safety, engineering standards, and operating priorities that govern all Back Office development.

This is the Cody Jo Method Back Office: a multi-department operating system of AI agents that audit, scan, fix, and build across codebases. Each department has specialized agents, and the system operates autonomously through an overnight loop with AI Product Owner prioritization.

## Company Structure

### Audit Departments
- **QA Agent** — Scans repos for bugs, security issues, and performance problems
- **SEO Agent** — Audits technical SEO, AI search optimization, content SEO, and social meta
- **ADA Agent** — WCAG 2.1 AA/AAA accessibility (Perceivable, Operable, Understandable, Robust)
- **Compliance Agent** — GDPR, ISO 27001, and age verification law compliance
- **Monetization Agent** — Revenue opportunities: ads, affiliate, premium, digital products, services
- **Product Agent** — Feature gaps, UX improvements, technical debt, growth opportunities, roadmap

### Operations Agents
- **Fix Agent** — Auto-remediates findings using isolated git worktrees
- **Product Owner Agent** — Reviews backlog + scores, outputs prioritized work plan for overnight loop
- **Feature Dev Agent** — Implements small/medium features following TDD

## Project Structure

```
backoffice/       — Python package (CLI, aggregation, backlog, sync, config)
agents/           — Shell agent launchers + system prompts
  prompts/        — System prompts for each agent type
config/           — Target repo configuration (gitignored)
  backoffice.yaml             — SINGLE SOURCE OF TRUTH (runner, deploy, scan, fix, targets, autonomy)
  backoffice.bunny.example.yaml — Example config for Bunny Storage/Pull Zone deployment
  targets.yaml                — DEPRECATED (still read by shell; run `python -m backoffice check-drift`)
dashboard/        — Consolidated HQ dashboard with slide-over panels
  index.html      — Single HQ page (matrix view + all department panels)
  backlog.json    — Persistent finding registry (content-hash dedup)
  score-history.json — Score snapshots for sparklines
results/          — Agent findings output (gitignored, synced to Bunny Storage)
scripts/          — Shell scripts (overnight loop, setup, sync, agent runner)
ci/               — CI/CD webhook server for Bunny Magic Container
tests/            — Pytest suite
lib/              — Standards references and severity definitions
```

## Commands

### Auditing
- `make qa TARGET=/path` — Run QA scan
- `make seo TARGET=/path` — Run SEO audit
- `make ada TARGET=/path` — Run ADA compliance audit
- `make compliance TARGET=/path` — Run regulatory compliance audit
- `make monetization TARGET=/path` — Run monetization strategy audit
- `make product TARGET=/path` — Run product roadmap audit
- `make audit-all-parallel TARGET=/path` — All 6 departments (2 parallel waves)
- `make full-scan TARGET=/path` — All audits + auto-fix

### Fixing
- `make fix TARGET=/path` — Run fix agent on QA findings
- `make watch TARGET=/path` — Continuous watch + auto-fix mode

### Overnight Autonomous Loop
- `make overnight` — Start loop (audit, decide, fix, build, verify, deploy, repeat)
- `make overnight-dry` — Dry-run (audit + decide only, no changes)
- `make overnight-stop` — Graceful stop (finishes current phase)
- `make overnight-status` — Show latest plan and cycle history
- `make overnight-rollback` — Roll back all repos to last overnight snapshot

### Policy & Loop State
- `python -m backoffice policy <repo> <gate>` — Evaluate an autonomy gate (exit 0=allow, 1=block, 2=error; JSON stdout)
- `python -m backoffice check-drift` — Detect drift between `backoffice.yaml` and legacy `targets.yaml`
- `python -m backoffice targets-json` — Emit validated targets + autonomy blocks as JSON (for shell consumers)
- `python -m backoffice state ledger-append` — Append a decision record to `results/overnight-ledger.jsonl`
- `python -m backoffice state blocked-items` — Items that failed in the last N cycles (`FailureMemory`)
- `python -m backoffice state quarantined` — Repos under rollback-streak quarantine (cleared via `results/quarantine-clear.json`)

### Dashboard
- `python3 -m backoffice serve --port 8070` — Local dashboard server
- `python3 -m backoffice refresh` — Regenerate dashboard data from results
- `python3 -m backoffice sync` — Deploy dashboards to Bunny Storage/Pull Zone

### Testing
- `make test` — Run pytest suite
- `make test-coverage` — Run with coverage
- `make regression` — Portfolio regression tests

## Data Flow

1. Agent scripts launch AI agents with department-specific prompts
2. Agents write findings to `results/<repo>/<department>-findings.json`
3. `backoffice.aggregate` normalizes findings, merges into backlog, updates score history
4. Dashboard loads `*-data.json`, `backlog.json`, `score-history.json`
5. `backoffice.sync` uploads to Bunny Storage + purges Pull Zone

## CI/CD — Bunny Magic Container

- **CI** (pull requests): Shell syntax, Python linting (ruff), pytest regression.
  - Config: `ci/` directory
- **CD** (push to main): Validates, tests, deploys dashboards.
  - Config: `ci/` directory
- **Auth**: Bunny API key authentication for storage and pull zone access
- **Logs**: Magic Container webhook server logs

## Key Architecture Decisions

- **Single dashboard page**: All department views are slide-over panels in `index.html`, not separate pages
- **Content-hash dedup**: Findings tracked across scans via SHA-256 hash of department+repo+title+file
- **Canonical finding schema**: All departments normalized to same format in `backoffice/backlog.py`
- **Trust class on every finding**: `trust_class ∈ {objective, advisory}` is a schema field stamped by `normalize_finding` from `DEPARTMENT_TRUST_CLASS`; agents may override per-finding via `raw['trust_class']`. Flows through `backlog.json`, `aggregate`, and Product Owner prioritisation.
- **Per-target autonomy policy**: `autonomy` block in `config/backoffice.yaml` (source of truth). `backoffice.policy` turns it into allow/block decisions for the overnight loop via a gate registry (`fix`, `feature_dev`, `auto_commit`, `auto_merge`, `deploy`).
- **Loop resilience** (`backoffice/overnight_state.py`):
  - **ExecutionLedger** — append-only JSONL at `results/overnight-ledger.jsonl`; every gate decision, skip, rollback, and deploy writes a record. This is the operator audit trail.
  - **FailureMemory** — items that failed in the last N cycles are suppressed from the next plan (`python -m backoffice state blocked-items`).
  - **Quarantine** — repos with N consecutive rollback cycles are skipped until an operator drops `{"cleared": [...]}` into `results/quarantine-clear.json`.
- **Conservative defaults**: Fixes allowed, feature dev/merge/deploy disabled unless explicitly enabled.

## Adding a New Department

1. Create agent prompt: `agents/prompts/<name>-audit.md`
2. Create agent script: `agents/<name>-audit.sh` (follow existing pattern)
3. Add make target to `Makefile`
4. Register in `audit-all` / `audit-all-parallel` sequences
5. Add to `backoffice/aggregate.py` department list
6. Add panel template to `dashboard/index.html`
7. Add standards reference: `lib/<name>-standards.md`

## Adding a New Target

1. Add entry to `config/backoffice.yaml` under `targets:` with path, language, lint/test/deploy commands
2. Optionally add `autonomy:` block (conservative defaults apply otherwise — see `backoffice/config.py`)
3. Mirror the entry in `config/targets.yaml` until that file is retired; verify with `python -m backoffice check-drift`
4. Verify: `python3 -m backoffice list-targets`
5. Test: `python3 -m backoffice audit <name> --departments qa`
6. Full audit: `python3 -m backoffice audit <name>`
7. Refresh: `python3 -m backoffice refresh && python3 -m backoffice sync`
