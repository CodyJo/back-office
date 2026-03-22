# Back Office — Agent Instructions

This is the Cody Jo Method Back Office: a multi-department operating system of AI agents that audit, scan, and fix codebases. Each department has specialized agents and its own dashboard surface.

## Company Structure

### QA Department
- **QA Agent** — Scans repos for bugs, security issues, and performance problems
- **Fix Agent** — Picks up findings, fixes them in isolated git worktrees

### SEO Department
- **SEO Agent** — Audits sites for technical SEO, AI search optimization, content SEO, and social meta

### ADA Compliance Department
- **ADA Agent** — Audits sites for WCAG 2.1 AA/AAA accessibility compliance (Perceivable, Operable, Understandable, Robust)

### Regulatory Compliance Department
- **Compliance Agent** — Audits for GDPR, ISO 27001, and age verification law compliance (US state laws + UK Online Safety Act)

### Monetization Strategy Department
- **Monetization Agent** — Audits sites for revenue opportunities: display ads, affiliate marketing, premium features, print fulfillment, digital products, client services, and sponsorships

### Product Roadmap Department
- **Product Agent** — Analyzes codebases for feature gaps, UX improvements, technical debt, growth opportunities, and produces a prioritized product roadmap and backlog

## Project Structure

```
backoffice/       — Primary Python package (CLI, API, workflow, sync, config)
agents/           — Shell scripts that launch department agents
agents/prompts/   — System prompts for each agent type
config/           — Target repo configuration (gitignored)
dashboard/        — Static HTML dashboards (one per department + HQ)
  index.html      — Company HQ landing page
  qa.html         — QA Department dashboard
  backoffice.html — Public bug report form (legacy)
  seo.html        — SEO Department dashboard
  ada.html        — ADA Compliance dashboard
  compliance.html — Regulatory Compliance dashboard
  monetization.html — Monetization Strategy dashboard
  product.html    — Product Roadmap dashboard
  jobs.html       — Real-time job progress dashboard
results/          — Findings and fix status (gitignored, synced to S3)
scripts/          — Shell scripts (setup, deploy, cron) and parse-config.py wrapper
terraform/        — AWS infrastructure (S3 + CloudFront)
lib/              — Standards references and severity definitions
```

## Commands

### CLI
The `backoffice` package is the primary interface:
- `python -m backoffice list-targets` — List configured audit targets
- `python -m backoffice audit <target>` — Run all department audits for a target
- `python -m backoffice sync` — Aggregate results and push dashboards to S3
- `python -m backoffice config show` — Print resolved configuration

### Individual Department Scans
- `make qa TARGET=/path/to/repo` — Run QA scan
- `make seo TARGET=/path/to/repo` — Run SEO audit
- `make ada TARGET=/path/to/repo` — Run ADA compliance audit
- `make compliance TARGET=/path/to/repo` — Run regulatory compliance audit
- `make monetization TARGET=/path/to/repo` — Run monetization strategy audit
- `make product TARGET=/path/to/repo` — Run product roadmap audit

### Fixing
- `make fix TARGET=/path/to/repo` — Run fix agent on QA findings
- `make watch TARGET=/path/to/repo` — Continuous watch + auto-fix mode

### Company-Wide
- `make audit-all TARGET=/path/to/repo` — Run ALL department audits (sequential)
- `make audit-all-parallel TARGET=/path/to/repo` — Run ALL audits in parallel (2 waves of 3)
- `make full-scan TARGET=/path/to/repo` — All audits + auto-fix

### Dashboard
- `make dashboard` — Deploy all dashboards to S3
- `make jobs` — Open job progress dashboard (local server on port 8070)

## Data Flow

1. Agent scripts launch the configured coding agent with department-specific prompts
2. Each agent writes findings to `results/<repo-name>/<department>-findings.json`
3. Dashboard HTML files read from `<department>-data.json` files
4. `backoffice.aggregate` aggregates results; `backoffice.sync` pushes to S3
5. CloudFront serves the dashboards

## Adding a New Department

1. Create agent prompt: `agents/prompts/<name>-audit.md`
2. Create agent script: `agents/<name>-audit.sh` (follow existing pattern)
3. Create dashboard: `dashboard/<name>.html`
4. Add reference docs: `lib/<name>-standards.md`
5. Add make target to `Makefile`
6. Update `dashboard/index.html` to include the new department card
