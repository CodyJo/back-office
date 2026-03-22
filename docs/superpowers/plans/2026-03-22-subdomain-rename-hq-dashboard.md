# Subdomain Rename + HQ Dashboard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename all `admin.*` subdomains to `backoffice.*` and add a cross-site HQ dashboard at `hq.codyjo.com` with health scores, risk view, and coverage matrix.

**Architecture:** Two independent changes in one plan. The subdomain rename is a find-and-replace across config, branding JS, and docs. The HQ dashboard adds one new HTML file (`hq.html`), one new data generator (`aggregate_hq()` in `backoffice/aggregate.py`), and manifest updates. Both changes are deployed via the existing sync pipeline.

**Tech Stack:** Python 3.12, HTML/CSS/JS (inline, no build step), YAML config

**Spec:** `docs/superpowers/specs/2026-03-22-subdomain-rename-hq-dashboard-design.md`

---

## File Structure

### Files to Create
```
dashboard/hq.html                — Cross-site HQ dashboard with health/risk/coverage
tests/test_aggregate_hq.py       — Tests for aggregate_hq() function
```

### Files to Modify
```
config/backoffice.yaml            — subdomain: admin.* → backoffice.*, allowed_origins
config/backoffice.example.yaml    — same
dashboard/site-branding.js        — hostname regex admin → backoffice
backoffice/sync/manifest.py       — swap back-office-hq.html → hq.html, add hq-data.json
backoffice/aggregate.py           — add aggregate_hq() function + call from orchestrator
tests/test_sync_manifest.py       — update test for removed/added files
tests/test_aggregate.py           — add test for aggregate_hq in integration tests
dashboard/index.html              — update back-office-hq link → hq
dashboard/selah.html              — line 61: back-office-hq.html → hq.html
dashboard/analogify.html          — line 43: back-office-hq.html → hq.html
dashboard/chromahaus.html         — line 43: back-office-hq.html → hq.html
dashboard/tnbm-tarot.html         — line 43: back-office-hq.html → hq.html
docs/LIVE-URLS.md                 — admin.codyjo.com → backoffice.codyjo.com + hq URLs
docs/CICD-REFERENCE.md            — admin.* → backoffice.*
```

### Files to Delete
```
dashboard/back-office-hq.html     — replaced by hq.html
```

---

## Chunk 1: Subdomain Rename

### Task 1: Rename admin.* to backoffice.* in config and branding

**Files:**
- Modify: `config/backoffice.yaml`
- Modify: `config/backoffice.example.yaml`
- Modify: `dashboard/site-branding.js`

- [ ] **Step 1: Update config/backoffice.yaml**

Replace all `admin.` subdomain references with `backoffice.`:
- `api.allowed_origins`: `"https://admin.thenewbeautifulme.com"` → `"https://backoffice.thenewbeautifulme.com"`
- `deploy.aws.dashboard_targets[0].subdomain`: `"admin.thenewbeautifulme.com"` → `"backoffice.thenewbeautifulme.com"`
- `deploy.aws.dashboard_targets[1].subdomain`: `"admin.codyjo.com"` → `"backoffice.codyjo.com"`

Do NOT change S3 bucket names (`admin-thenewbeautifulme-site`, `admin-codyjo-site`).

- [ ] **Step 2: Update config/backoffice.example.yaml**

- `"https://admin.yoursite.com"` → `"https://backoffice.yoursite.com"`
- `subdomain: "admin.yoursite.com"` → `subdomain: "backoffice.yoursite.com"`

- [ ] **Step 3: Update dashboard/site-branding.js**

Line 74: Change hostname regex:
```javascript
// Before
var match = host.match(/^admin\.(.+)$/);
// After
var match = host.match(/^backoffice\.(.+)$/);
```

- [ ] **Step 4: Verify terraform/cd.tf needs no changes**

Run: `grep -n 'admin\.' terraform/cd.tf`

Expected: No matches. The file contains only S3 bucket ARNs with `admin-` (hyphen), not `admin.` (dot) subdomain strings. No changes needed — noting this explicitly since the spec lists the file.

- [ ] **Step 5: Verify no residual admin.* subdomain references in modified files**

Run: `grep -n 'admin\.' config/backoffice.yaml config/backoffice.example.yaml dashboard/site-branding.js | grep -v 'admin-'`

Expected: No matches (bucket names like `admin-codyjo-site` contain `admin-` with a hyphen, not `admin.` with a dot).

- [ ] **Step 6: Commit**

```bash
git add config/backoffice.yaml config/backoffice.example.yaml dashboard/site-branding.js
git commit -m "rename: admin.* subdomains to backoffice.* in config and branding"
```

---

### Task 2: Update documentation

**Files:**
- Modify: `docs/LIVE-URLS.md`
- Modify: `docs/CICD-REFERENCE.md`

- [ ] **Step 1: Update docs/LIVE-URLS.md**

Lines 30-38: Replace all `admin.codyjo.com` with `backoffice.codyjo.com`.

Add after the existing URLs:
```markdown
- `https://hq.codyjo.com/`
- `https://hq.codyjo.com/hq.html`
```

Do NOT change line 10 (`https://www.codyjo.com/back-office/admin/`) — that's a public site path, not a subdomain.

- [ ] **Step 2: Update docs/CICD-REFERENCE.md**

Line 124: `admin.*` → `backoffice.*`

- [ ] **Step 3: Commit**

```bash
git add docs/LIVE-URLS.md docs/CICD-REFERENCE.md
git commit -m "docs: update admin.* references to backoffice.*"
```

---

## Chunk 2: HQ Data Generation

### Task 3: Add aggregate_hq() function

**Files:**
- Modify: `backoffice/aggregate.py`
- Create: `tests/test_aggregate_hq.py`

- [ ] **Step 1: Write failing tests for aggregate_hq()**

```python
# tests/test_aggregate_hq.py
"""Tests for the HQ cross-site aggregation."""
import json
import os
from pathlib import Path

import pytest

from backoffice.aggregate import aggregate_hq


@pytest.fixture
def hq_results(tmp_path):
    """Create a results directory with two repos and department findings."""
    results = tmp_path / "results"

    # Repo 1: codyjo.com — has QA and SEO
    repo1 = results / "codyjo.com"
    repo1.mkdir(parents=True)
    (repo1 / "findings.json").write_text(json.dumps({
        "scanned_at": "2026-03-21T10:00:00Z",
        "summary": {"total": 5, "critical": 0, "high": 1, "medium": 2, "low": 2},
        "findings": [
            {"severity": "high", "title": "Issue 1"},
            {"severity": "medium", "title": "Issue 2"},
            {"severity": "medium", "title": "Issue 3"},
            {"severity": "low", "title": "Issue 4"},
            {"severity": "low", "title": "Issue 5"},
        ],
    }))
    (repo1 / "seo-findings.json").write_text(json.dumps({
        "scanned_at": "2026-03-20T14:00:00Z",
        "summary": {"seo_score": 88, "total": 3},
        "findings": [{"severity": "medium"}, {"severity": "low"}, {"severity": "info"}],
    }))

    # Repo 2: thenewbeautifulme — has QA only
    repo2 = results / "thenewbeautifulme"
    repo2.mkdir(parents=True)
    (repo2 / "findings.json").write_text(json.dumps({
        "scanned_at": "2026-03-19T08:00:00Z",
        "summary": {"total": 2, "critical": 1, "high": 0, "medium": 1, "low": 0},
        "findings": [
            {"severity": "critical", "title": "Critical bug"},
            {"severity": "medium", "title": "Medium issue"},
        ],
    }))

    return results


@pytest.fixture
def hq_dashboard(tmp_path):
    return tmp_path / "dashboard"


def test_aggregate_hq_produces_json(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    assert result is not None
    assert "sites" in result
    assert "totals" in result
    assert "generated_at" in result


def test_aggregate_hq_writes_file(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    aggregate_hq(str(hq_results), str(hq_dashboard))
    path = hq_dashboard / "hq-data.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert "sites" in data


def test_aggregate_hq_includes_all_repos(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    assert "codyjo.com" in result["sites"]
    assert "thenewbeautifulme" in result["sites"]


def test_aggregate_hq_health_score_excludes_missing_depts(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    # codyjo.com has QA and SEO scores — health should not be null
    site = result["sites"]["codyjo.com"]
    assert site["health_score"] is not None
    assert 0 <= site["health_score"] <= 100


def test_aggregate_hq_risk_counts(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    # thenewbeautifulme has 1 critical
    tnbm = result["sites"]["thenewbeautifulme"]
    assert tnbm["risk"]["critical"] == 1


def test_aggregate_hq_coverage_timestamps(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    site = result["sites"]["codyjo.com"]
    assert site["coverage"]["qa"]["last_audit"] == "2026-03-21T10:00:00Z"
    assert site["coverage"]["seo"]["last_audit"] == "2026-03-20T14:00:00Z"
    # Departments not audited should be null
    assert site["coverage"]["ada"] is None


def test_aggregate_hq_coverage_finding_count(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    site = result["sites"]["codyjo.com"]
    assert site["coverage"]["qa"]["finding_count"] == 5
    assert site["coverage"]["seo"]["finding_count"] == 3


def test_aggregate_hq_backoffice_url(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    # URL derived from repo name — for known domains, uses https://backoffice.{domain}
    site = result["sites"]["codyjo.com"]
    assert "backoffice" in site["backoffice_url"]


def test_aggregate_hq_totals(hq_results, hq_dashboard):
    hq_dashboard.mkdir(parents=True, exist_ok=True)
    result = aggregate_hq(str(hq_results), str(hq_dashboard))
    totals = result["totals"]
    assert totals["sites_audited"] == 2
    assert "sites_stale" in totals
    # Total risk across both sites
    assert totals["risk"]["critical"] == 1  # only thenewbeautifulme
    assert totals["risk"]["high"] == 1      # only codyjo.com


def test_aggregate_hq_empty_results(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    result = aggregate_hq(str(results), str(dashboard))
    assert result["sites"] == {}
    assert result["totals"]["health_score"] is None
    assert result["totals"]["sites_audited"] == 0


def test_aggregate_hq_malformed_json_skipped(tmp_path, caplog):
    import logging
    results = tmp_path / "results"
    repo = results / "bad-repo"
    repo.mkdir(parents=True)
    (repo / "findings.json").write_text("not valid json {{{")
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    with caplog.at_level(logging.WARNING, logger="backoffice"):
        result = aggregate_hq(str(results), str(dashboard))
    # Should still produce output, just skip the bad file
    assert "bad-repo" in result["sites"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_aggregate_hq.py -v`
Expected: FAIL (ImportError — aggregate_hq doesn't exist yet)

- [ ] **Step 3: Implement aggregate_hq()**

Add to `backoffice/aggregate.py`. The function should:

1. List all subdirectories in results/ (each is a repo)
2. For each repo, read all department findings files using the existing `FINDINGS_FILES` mapping
3. Extract scores per department:
   - QA: use `qa_score_from_summary()` pattern (already in workflow.py, reimplement inline or import)
   - SEO/ADA/Compliance/Product/Monetization: extract from `summary` dict using known field names
   - Privacy: use existing `privacy_score()` function from aggregate.py
4. Extract `scanned_at` timestamps for coverage (reuse `extract_scanned_at` pattern from workflow.py)
5. Count severities across all findings for risk view
6. Compute weighted health score per the spec formula
7. Compute totals (average health, total risk, site counts)
8. Write `dashboard/hq-data.json`

Key constants to define:
```python
HEALTH_WEIGHTS = {
    "qa": 0.25, "ada": 0.20, "seo": 0.15,
    "compliance": 0.15, "privacy": 0.10,
    "product": 0.10, "monetization": 0.05,
}

DEPT_FINDINGS_FILES = {
    "qa": "findings.json",
    "seo": "seo-findings.json",
    "ada": "ada-findings.json",
    "compliance": "compliance-findings.json",
    "privacy": "privacy-findings.json",
    "monetization": "monetization-findings.json",
    "product": "product-findings.json",
}

DEPT_SCORE_FIELDS = {
    "seo": "seo_score",
    "ada": "compliance_score",
    "compliance": "overall_score",
    "product": "product_readiness_score",
    "monetization": "monetization_readiness_score",
}
```

For QA score: `max(0, 100 - critical*15 - high*8 - medium*3 - low*1)` (same as workflow.py).

For privacy score: call existing `privacy_score()` with the compliance findings filtered through `is_privacy_finding()`.

**backoffice_url construction:** For each repo name, check if it looks like a domain (contains a dot). If so: `https://backoffice.{repo_name}`. Otherwise: `https://backoffice.codyjo.com` (fallback to main site). Can also check `org-data.json` for product metadata if available.

**sites_stale:** A site is "stale" if ALL its audited departments have `last_audit` > 30 days ago. `totals.sites_stale` counts these sites.

**finding_count:** Each coverage entry includes the total finding count for that department from the findings file.

**Privacy score dependency:** `aggregate_hq()` reads `privacy-findings.json` which is created by `aggregate_privacy()`. The call MUST be placed after `aggregate_privacy()` in the orchestrator. Add a comment noting this dependency.

Error handling:
- Empty results/ → empty sites, null totals
- Malformed JSON → log warning, skip file, continue
- All scores null for a site → health_score: null, exclude from totals average

- [ ] **Step 4: Wire aggregate_hq() into the aggregate() orchestrator**

Add call after the self-audit aggregation in the `aggregate()` function:
```python
# HQ dashboard (cross-site portfolio view)
# NOTE: Must run after aggregate_privacy() which creates privacy-findings.json files
aggregate_hq(results_dir, dashboard_dir)
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_aggregate_hq.py -v`
Expected: PASS (all 11 tests)

Run: `python3 -m pytest tests/ -v`
Expected: ALL tests pass

- [ ] **Step 6: Commit**

```bash
git add backoffice/aggregate.py tests/test_aggregate_hq.py
git commit -m "feat: add aggregate_hq() for cross-site HQ dashboard data"
```

---

### Task 4: Update sync manifest

**Files:**
- Modify: `backoffice/sync/manifest.py`
- Modify: `tests/test_sync_manifest.py`

- [ ] **Step 1: Update manifest.py**

In `DASHBOARD_FILES`: replace `"back-office-hq.html"` with `"hq.html"`.

In `SHARED_META_FILES`: add `"hq-data.json"`.

- [ ] **Step 2: Update test**

In `tests/test_sync_manifest.py`, add:
```python
def test_hq_html_in_dashboard_files():
    assert "hq.html" in DASHBOARD_FILES
    assert "back-office-hq.html" not in DASHBOARD_FILES

def test_hq_data_in_shared_meta():
    assert "hq-data.json" in SHARED_META_FILES
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_sync_manifest.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backoffice/sync/manifest.py tests/test_sync_manifest.py
git commit -m "feat: update sync manifest for hq.html and hq-data.json"
```

---

## Chunk 3: HQ Dashboard HTML + Cleanup

### Task 5: Create dashboard/hq.html

**Files:**
- Create: `dashboard/hq.html`

- [ ] **Step 1: Create hq.html**

Build a single-page dashboard following existing conventions (dark theme, inline CSS/JS, no build step). The page should:

1. **Header**: "Company HQ" title, site switcher dropdown, "All Sites" default
2. **Health Scores section**: Card grid. Each card shows site name, health score as large colored number (green 80+, yellow 50-79, red <50), department score breakdown as small horizontal bars, "Open in backoffice →" link
3. **Risk View section**: Table sorted worst-first. Columns: Site, Critical, High, Medium, Low, Link. Row highlighting for critical > 0
4. **Coverage Matrix section**: Grid table. Rows = sites, columns = departments. Cells show relative time with color background (green <7d, yellow 7-30d, red >30d, gray null)
5. **Interaction**: Dropdown sets `?site=name` param, filters all sections. Card click also filters. "All Sites" resets.

Reference existing dashboards (`qa.html`, `index.html`) for styling patterns: dark background (#0a0a0f), card styling, color palette, font (Inter + JetBrains Mono).

Fetch `hq-data.json` on load. Handle empty data gracefully (show "No data available" message).

- [ ] **Step 2: Verify it loads locally**

Run: `python3 -m http.server 8070 -d dashboard` and open `http://localhost:8070/hq.html`

Expected: Page renders with layout visible (will show "No data" if hq-data.json doesn't exist yet).

- [ ] **Step 3: Commit**

```bash
git add dashboard/hq.html
git commit -m "feat: add HQ cross-site dashboard with health/risk/coverage"
```

---

### Task 6: Update dashboard links and delete old HQ page

**Files:**
- Modify: `dashboard/index.html`
- Modify: `dashboard/selah.html`
- Modify: `dashboard/analogify.html`
- Modify: `dashboard/chromahaus.html`
- Modify: `dashboard/tnbm-tarot.html`
- Delete: `dashboard/back-office-hq.html`

- [ ] **Step 1: Find and replace back-office-hq.html references**

First, grep to find all references:
```bash
grep -rn 'back-office-hq' dashboard/
```

Replace `back-office-hq.html` with `hq.html` in each match. The known locations are `selah.html:61`, `analogify.html:43`, `chromahaus.html:43`, `tnbm-tarot.html:43`.

**Note on index.html:** `index.html` may not contain a direct `back-office-hq.html` reference (it IS the HQ landing page). If grep finds no match in `index.html`, no change is needed there — the spec's instruction was to ensure the HQ is linked, and `index.html` already serves as the main navigation.

- [ ] **Step 2: Delete old file**

```bash
git rm dashboard/back-office-hq.html
```

- [ ] **Step 3: Verify no remaining references**

```bash
grep -rn 'back-office-hq' dashboard/ backoffice/ config/ docs/
```

Expected: No matches.

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html dashboard/selah.html dashboard/analogify.html \
  dashboard/chromahaus.html dashboard/tnbm-tarot.html
git commit -m "refactor: replace back-office-hq.html with hq.html in all dashboards"
```

---

### Task 7: Add HQ target to config and final verification

**Files:**
- Modify: `config/backoffice.yaml`
- Modify: `config/backoffice.example.yaml`

- [ ] **Step 1: Add HQ dashboard target**

Add to `deploy.aws.dashboard_targets` in `config/backoffice.yaml`:
```yaml
  - bucket: "hq-codyjo-site"
    base_path: ""
    distribution_id: ""
    subdomain: "hq.codyjo.com"
    filter_repo: null
    allow_public_read: false
```

Add same to `config/backoffice.example.yaml` with placeholder values.

- [ ] **Step 2: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL tests pass.

- [ ] **Step 3: Verify grep for residual admin.* subdomain references**

```bash
grep -rn 'admin\.' config/ dashboard/ backoffice/ docs/ | grep -v 'admin-' | grep -v '.pyc' | grep -v __pycache__
```

Expected: No matches (bucket names with `admin-` are excluded).

- [ ] **Step 4: Commit**

```bash
git add config/backoffice.yaml config/backoffice.example.yaml
git commit -m "feat: add hq.codyjo.com dashboard target and final verification"
```
