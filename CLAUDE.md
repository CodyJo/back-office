# Back Office — Claude Code Instructions

This is the **BreakPoint Labs Back Office** — a multi-department company of AI agents that audit, scan, and fix codebases. Each department has specialized agents and their own dashboard.

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

## Project Structure

```
agents/           — Shell scripts that launch Claude Code agents
agents/prompts/   — System prompts for each agent type
config/           — Target repo configuration (gitignored)
dashboard/        — Static HTML dashboards (one per department + HQ)
  index.html      — Company HQ landing page
  backoffice.html — QA Department dashboard
  seo.html        — SEO Department dashboard
  ada.html        — ADA Compliance dashboard
  compliance.html — Regulatory Compliance dashboard
results/          — Findings and fix status (gitignored, synced to S3)
scripts/          — Setup, deploy, and cron scripts
terraform/        — AWS infrastructure (S3 + CloudFront)
lib/              — Standards references and severity definitions
```

## Commands

### Individual Department Scans
- `make qa TARGET=/path/to/repo` — Run QA scan
- `make seo TARGET=/path/to/repo` — Run SEO audit
- `make ada TARGET=/path/to/repo` — Run ADA compliance audit
- `make compliance TARGET=/path/to/repo` — Run regulatory compliance audit

### Fixing
- `make fix TARGET=/path/to/repo` — Run fix agent on QA findings
- `make watch TARGET=/path/to/repo` — Continuous watch + auto-fix mode

### Company-Wide
- `make audit-all TARGET=/path/to/repo` — Run ALL department audits
- `make full-scan TARGET=/path/to/repo` — All audits + auto-fix

### Dashboard
- `make dashboard` — Deploy all dashboards to S3

## Data Flow

1. Agent scripts launch Claude Code sessions with department-specific prompts
2. Each agent writes findings to `results/<repo-name>/<department>-findings.json`
3. Dashboard HTML files read from `<department>-data.json` files
4. `scripts/sync-dashboard.sh` aggregates results and pushes to S3
5. CloudFront serves the dashboards

## Adding a New Department

1. Create agent prompt: `agents/prompts/<name>-audit.md`
2. Create agent script: `agents/<name>-audit.sh` (follow existing pattern)
3. Create dashboard: `dashboard/<name>.html`
4. Add reference docs: `lib/<name>-standards.md`
5. Add make target to `Makefile`
6. Update `dashboard/index.html` to include the new department card
