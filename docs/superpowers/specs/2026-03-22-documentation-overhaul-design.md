# Documentation Overhaul

**Date:** 2026-03-22
**Status:** Approved
**Scope:** Rewrite README.md from scratch, update CLAUDE.md and WORKFLOW-ARCHITECTURE.md, delete CLI-REFERENCE.md (absorbed into README)

## Problem

After the DX overhaul that consolidated scripts into a `backoffice/` package, four documentation files still reference the old `scripts/*.py` invocation pattern. The README doesn't explain the system well enough to show a colleague or remember how to use it after time away.

## Audience

- The repo owner (TAM) who wants to demo this to colleagues and remember how it works
- AI agents (Claude, Codex) operating on the codebase
- Any developer who clones the repo

## Changes

### 1. README.md — Full Rewrite

Clean slate. Structured for both demo walkthrough and daily reference. Generic URLs (no real domains).

#### Section 1: Hero
One paragraph pitch + one-liner showing the key value prop. Something like:

> AI agents that audit your entire portfolio for bugs, SEO, accessibility, compliance, monetization, and product gaps — then fix what they find. One command scans everything. Dashboards show results per site.

#### Section 2: How It Works
The department model explained simply. Mermaid diagram showing the flow:

```
Your Repos → Department Agents → Findings JSON → Dashboards
```

Brief description of each department (QA, SEO, ADA, Compliance, Monetization, Product) — one sentence each. Mention the Fix Agent that picks up findings and creates PRs.

#### Section 3: Quick Start

Five steps:
1. Clone and run `make setup`
2. Configure targets in `config/backoffice.yaml`
3. Run your first audit: `make qa TARGET=/path/to/repo`
4. See results: `make jobs` (opens dashboard at localhost:8070)
5. Deploy dashboards: `make dashboard`

#### Section 4: Command Reference

Full `python -m backoffice` CLI grouped by workflow. This replaces `docs/CLI-REFERENCE.md`.

**Auditing:**
```
python -m backoffice audit <target> [-d departments]
python -m backoffice audit-all [--targets name1,name2]
python -m backoffice list-targets
python -m backoffice refresh
```

**Dashboard & Sync:**
```
python -m backoffice sync                    # full dashboard deploy
python -m backoffice sync --dept qa          # quick-sync one department
python -m backoffice sync --dry-run          # preview without uploading
python -m backoffice serve --port 8070       # local dev server
```

**Task Queue:**
```
python -m backoffice tasks list [--repo name] [--status ready]
python -m backoffice tasks show --id <id>
python -m backoffice tasks create --repo <repo> --title "..."
python -m backoffice tasks start --id <id>
python -m backoffice tasks block --id <id> --note "reason"
python -m backoffice tasks review --id <id>
python -m backoffice tasks complete --id <id>
python -m backoffice tasks cancel --id <id> --note "reason"
python -m backoffice tasks sync
```

**Testing & Regression:**
```
python -m backoffice regression
python -m backoffice scaffold --target <name>
```

**Admin & Servers:**
```
python -m backoffice setup
python -m backoffice config show
python -m backoffice config shell-export
python -m backoffice serve --port 8070       # local dev dashboard server
python -m backoffice api-server --port 8070  # production API server
```

Also include the `make` targets as a convenience reference (they delegate to the CLI):

| Make Target | Equivalent |
|------------|------------|
| `make qa TARGET=...` | Runs QA agent on target |
| `make audit-all TARGET=...` | All departments sequentially |
| `make dashboard` | `python -m backoffice sync` |
| `make test` | `python -m pytest tests/` |
| etc. | |

#### Section 5: Dashboards

What the dashboards show. List each department dashboard with a one-sentence description. Mention the deployment pattern: `backoffice.yourdomain.com` per site, data filtered by `filter_repo` config.

#### Section 6: Configuration

Explain `config/backoffice.yaml` — the unified config file. Show the key sections:
- `runner:` — which AI agent to use (command + mode)
- `api:` — production API server settings (port, API key, CORS origins)
- `deploy:` — where dashboards are deployed (provider, S3 buckets, CloudFront, `filter_repo`)
- `targets:` — repos to audit with their commands and context
- `scan:` / `fix:` — audit behavior settings
- `notifications:` — sync-to-S3 toggle

Show a snippet from `config/backoffice.example.yaml` using the actual field names (`distribution_id`, `filter_repo`, etc.). Reference the example file as the starting point.

#### Section 7: Architecture

Package structure of `backoffice/`. Brief description of each module. Mermaid diagram showing how modules connect: CLI → workflow → aggregate/delivery/tasks → sync → providers → S3/CloudFront.

Data flow: Agent scripts → results JSON → aggregation → dashboard JSON → S3 → CloudFront → browser.

#### Section 8: Adding a New Site

Step-by-step:
1. Add target to `config/backoffice.yaml`
2. Run first audit
3. Add dashboard deployment target (S3 bucket + CloudFront)
4. Deploy

#### Section 9: Adding a New Department

Step-by-step:
1. Create agent prompt in `agents/prompts/`
2. Create agent script in `agents/`
3. Create dashboard HTML in `dashboard/`
4. Add to Makefile
5. Update aggregation
6. Update index.html

### 2. CLAUDE.md — Update

Update the project structure section to show `backoffice/` package instead of `scripts/` as the primary code location. Update the Commands section to reference both `make` targets and `python -m backoffice` CLI. Keep it concise — CLAUDE.md is instruction-focused, not a tutorial.

### 3. WORKFLOW-ARCHITECTURE.md — Update

Replace all `python3 scripts/backoffice-cli.py` references with `python -m backoffice`. Replace `scripts/local_audit_workflow.py` with `backoffice/workflow.py`. Update any diagrams that reference old script names. Remove the cross-reference to `docs/CLI-REFERENCE.md` (which is being deleted). Keep the document's structure and purpose (detailed topology for technical readers).

### 4. CLI-REFERENCE.md — Delete

Content is absorbed into README Section 4 (Command Reference). The separate file is redundant.

## What's Untouched

- `docs/CICD-REFERENCE.md` — already current
- `docs/HANDOFF.md` — already current
- `docs/LIVE-URLS.md` — already current (will be updated by subdomain rename task separately)
- `AGENTS.md` — already current
- All spec and plan documents in `docs/superpowers/`
