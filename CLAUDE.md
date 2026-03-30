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
  backoffice.yaml             — Unified config (runner, deploy, scan, fix, targets)
  backoffice.bunny.example.yaml — Example config for Bunny Storage/Pull Zone deployment
  targets.yaml                — Target repos with autonomy policy
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

### Dashboard
- `python -m backoffice serve --port 8070` — Local dashboard server
- `python -m backoffice refresh` — Regenerate dashboard data from results
- `python -m backoffice sync` — Deploy dashboards to Bunny Storage/Pull Zone

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
- **Per-target autonomy policy**: `autonomy` block in targets.yaml controls what the overnight loop can do
- **Conservative defaults**: Fixes allowed, feature dev/merge/deploy disabled unless explicitly enabled

## Adding a New Department

1. Create agent prompt: `agents/prompts/<name>-audit.md`
2. Create agent script: `agents/<name>-audit.sh` (follow existing pattern)
3. Add make target to `Makefile`
4. Register in `audit-all` / `audit-all-parallel` sequences
5. Add to `backoffice/aggregate.py` department list
6. Add panel template to `dashboard/index.html`
7. Add standards reference: `lib/<name>-standards.md`

## Adding a New Target

1. Add entry to `config/targets.yaml` with path, language, lint/test/deploy commands
2. Verify: `python -m backoffice list-targets`
3. Test: `python -m backoffice audit <name> --departments qa`
4. Full audit: `python -m backoffice audit <name>`
5. Refresh: `python -m backoffice refresh && python -m backoffice sync`
6. Optional: Add `autonomy:` block for overnight loop control
