# Deterministic Scanners

The Phase 1 cost-reduction layer. Free OSS tools (`semgrep`, `ruff`, `bandit`, `pip-audit`, `npm audit`, `gitleaks`, `lighthouse`, `axe-core`, `checkov`, `tfsec`, `license-checker`) produce findings in the canonical schema. The AI is reserved for what tools cannot catch.

Module: `backoffice/scanners/`. CLI: `python -m backoffice scan <target>`.

---

## What it does

```
backoffice/scanners/
├── severity.py          # per-tool → canonical severity tables + filters
├── discovery.py         # language + physical markers → tool list (handles polyglot)
├── tools.py             # 6 QA adapters (semgrep, ruff, bandit, pip-audit, npm-audit, gitleaks)
├── dept_tools.py        # 6 non-QA adapters (lighthouse, html-validate, axe-core, license-checker, checkov, tfsec)
├── scan_state.py        # per-(target, dept) git SHA tracking → skip when unchanged
├── triage.py            # OPTIONAL Haiku triage layer (off by default)
└── runner.py            # orchestrator + CLI handler
```

Output: `results/<repo>/<dept>-deterministic-findings.json`. The aggregate pipeline merges this file with the AI agent's `findings.json` (or whichever dept-specific file) using `finding_hash(dept, repo, title, file)` for dedup.

## CLI surface

| Flag | Purpose |
|---|---|
| `<target>` | Target name from `backoffice.yaml` (positional) |
| `--department / -d` | `qa` (default) \| `seo` \| `ada` \| `compliance` \| `cloud-ops` |
| `--tools` | Comma-separated tool override (e.g. `ruff,semgrep`) |
| `--min-severity` | Floor — `critical`, `high`, `medium`, `low`, `info` (default: from `config.scan.min_severity`) |
| `--max-findings` | Cap (default: from `config.scan.max_findings`) |
| `--out` | Override output path |
| `--dry-run` | Print which tools would run; do not execute |
| `--force` | Re-scan even when SHA hasn't changed since last successful scan |

## Tool selection

For each target, the runner picks tools from two layers:

1. **Declared language** — `target.language` in `backoffice.yaml` looks up `LANGUAGE_TOOLS`:

| Language | Base tools (QA) |
|---|---|
| `python` | semgrep, ruff, bandit, pip-audit |
| `typescript` / `javascript` / `astro` / `node` | semgrep, npm-audit |
| `terraform` / `hcl` | semgrep |
| `go` / `rust` / `ruby` / `java` / `kotlin` | semgrep |
| (default) | semgrep |

2. **Physical markers** — files at the repo root (or one level deep) trigger additions:

| Marker file | Adds tool |
|---|---|
| `pyproject.toml` / `setup.py` / `setup.cfg` | ruff, bandit |
| `requirements*.txt` / `Pipfile` / `pyproject.toml` / `setup.py` | pip-audit |
| `package.json` | npm-audit |
| `*.tf` | semgrep |

`gitleaks` always runs on every repo regardless of language.

Polyglot repos (e.g. `analogify` is python+terraform+astro) get the union of all matched tool sets.

## Severity mapping

Each tool has its own severity vocabulary. Adapters map to the canonical `critical | high | medium | low | info`:

* **ruff**: rule code prefix → severity (`S` = high security, `F` = medium pyflakes, `E9` = high syntax, `E`/`W` = low style)
* **bandit**: `HIGH/MEDIUM/LOW` direct + confidence boost (`LOW` + `HIGH` confidence → `medium`)
* **pip-audit**: any CVE = `high` by default (no CVSS surfaced)
* **npm audit**: `critical/high/moderate→medium/low/info` direct
* **semgrep**: `ERROR/WARNING/INFO` → `high/medium/low`
* **gitleaks**: always `critical` (committed secret = rotation required)
* **checkov / tfsec**: `CRITICAL/HIGH/MEDIUM/LOW` direct
* **axe-core**: `critical/serious→high/moderate→medium/minor→low`

## Scanner-status findings

When a tool binary is missing, the adapter emits one `info`-severity finding with `category="scanner-status"`:

```json
{"id": "DET-semgrep-status", "title": "semgrep not installed — skipped",
 "severity": "info", "category": "scanner-status", "source_tool": "semgrep"}
```

These bypass the `--min-severity` filter (so coverage gaps are always visible) but are excluded from severity totals (so they don't inflate the dashboard's count of real findings).

`bash scripts/check-scanner-tools.sh` produces a quick installed/missing report.

## Incremental scanning

`scan_state.py` records `(target, scope) → HEAD SHA` after every successful scan in `results/scan-state.json`. The next invocation:

1. Computes current `git rev-parse HEAD` for the target
2. If it matches the recorded SHA, returns the cached payload from `<dept>-deterministic-findings.json` and exits in milliseconds
3. Otherwise re-scans and updates state

`--force` bypasses the cache. `git rev-parse HEAD` failures (non-git dirs) always re-scan — safe default.

## Aggregate merge contract

`backoffice/aggregate.py:aggregate_qa()` and `aggregate_department()` both read the deterministic file alongside the AI-agent file:

1. Load `<dept>-findings.json` (AI) and `<dept>-deterministic-findings.json` (this module)
2. Build the AI findings' `finding_hash` set: `(dept, repo, title, file_or_location)`
3. Append deterministic findings whose hash is not already in the AI set
4. Recompute severity counts on the merged list (via `count_severities`)
5. Surface `scanner_status` from the deterministic file in the repo entry

Both files can be missing (skip the repo); either alone is sufficient.

## Concurrency

Per-(repo, dept) lock file at `results/<repo>/.det-scan-<dept>.lock`. Acquired non-blocking — a second concurrent scan on the same target/dept raises `RuntimeError`. Different departments and different repos can run in parallel without contention.

## Tests

`tests/test_scanners.py` (57 tests), `tests/test_scan_state.py` (10 tests). See `pytest -k scanners` to run just this surface.

## Pricing

$0. The whole point of this layer.

The optional `scan.haiku_triage: true` config flag adds a Haiku post-pass over the deterministic findings (~$0.001 per finding, capped at 50 findings per scan). See `docs/ai-cost-guide.md`.
