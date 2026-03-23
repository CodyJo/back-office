# Dashboard Redesign — Design Spec

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Redesign the Back Office dashboard from 24 separate pages into a single HQ page with slide-over panels, consistent filtering, finding detail views, and a persistent backlog with deduplication.

---

## Problem

The current dashboard has 24 HTML files with inconsistent navigation, no shared product filtering, duplicate data views, and no finding persistence across scans. Users can't track whether a finding is new or has been flagged in previous audits.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| HQ layout | Hybrid matrix (C) | Products × departments grid lets users spot patterns in both dimensions |
| Department pages | Slide-over panels (C) | Never lose HQ context; quick drill-in/out; product filter inherited |
| Page count | 24 → 1 + panels | Eliminate redundant pages; everything accessible from HQ |
| Filters | Consistent across all panels | Severity, status, effort, AI fixable toggle, search — same everywhere |
| Finding detail | Nested slide-over panel | Click any finding to see full description, evidence, fix, AI fix command |
| Backlog | JSON file with content-hash deduplication | Track recurrence count across audits |

---

## 1. Architecture

### Page Structure

**Single page:** `index.html` (the HQ dashboard)

**Slide-over panels** (rendered inline, opened via JS):
- 6 department panels: QA, SEO, ADA, Compliance, Monetization, Product
- Privacy panel (filtered view of Compliance data)
- Jobs panel (audit progress tracker)
- FAQ panel (scoring documentation)
- Docs panel (combined CLI + CI/CD + GitHub docs, tabbed)

**Cut pages:**
- `selah.html`, `analogify.html`, `chromahaus.html`, `tnbm-tarot.html` — replaced by product selector
- `back-office-hq.html` — redundant HQ wrapper
- `self-audit.html` — replaced by QA panel filtered to "Back Office" product
- `backoffice.html` — legacy bug report form
- `admin.html` — folded into HQ
- `metrics.html`, `regression.html` — folded into HQ as summary cards with panel drill-through

### Data Files

No changes to existing department data JSON schemas. The aggregator gains two new post-processing steps (full-finding passthrough and backlog merge) but existing department data output structure is unchanged.

Existing files (unchanged schema):
- `qa-data.json`, `seo-data.json`, `ada-data.json`, `compliance-data.json`, `monetization-data.json`, `product-data.json`, `privacy-data.json`
- `org-data.json` (product-to-repo mappings)
- `.jobs.json`, `.jobs-history.json`

**Modified behavior:** The aggregator must pass through full finding objects (including `description`, `evidence`, `impact`, `fix_suggestion`) into the `-data.json` files rather than stripping them during aggregation. Currently, `aggregate_department()` only keeps `id, severity, category, title, file, line, effort, fixable, status`. The full finding is needed for the detail panel. See section 4a for the canonical finding schema.

**New files:**
- `backlog.json` — persistent finding registry (see section 5)
- `score-history.json` — per-department, per-repo score snapshots for sparklines (see section 5b)

### File Layout

```
dashboard/
  index.html              — Single HQ page (all panels rendered inline)
  site-branding.js        — Shared branding (unchanged)
  department-context.js   — Shared utilities (unchanged)
  favicon.svg             — Favicon (unchanged)
  faq-content.html        — FAQ content fragment (loaded into panel)
  docs-content.html       — Combined documentation content fragment
  *-data.json             — Department data (unchanged)
  backlog.json            — Persistent finding registry (new)
  score-history.json      — Per-department score snapshots for sparklines (new)
  org-data.json           — Product/repo mappings (unchanged)
```

---

## 2. HQ Page Layout

Three sections, top to bottom:

### 2a. Top Bar

Fixed bar across the top:
- **Left:** "Back Office" logo + product selector dropdown
- **Right:** Jobs button, Docs button, FAQ button, "Last scan: X min ago" timestamp

The product selector loads options from `org-data.json`. Selecting a product filters all data on the page (score cards, matrix, findings feed) to repos belonging to that product. The selection persists in the URL as `?product=key` and is inherited by any slide-over panel opened from HQ.

### 2b. Score Cards Row

Six cards in a single row, one per department: QA, SEO, ADA, Compliance, Monetization, Product.

Each card shows:
- Department name (uppercase label)
- Score (large number, color-coded: green ≥85, yellow/accent 65-84, orange 50-64, red <50)
- Sparkline (score trend over last 5 scans, from `score-history.json` — see section 5b)
- Trend delta ("±N from last scan")

Clicking a score card opens that department's slide-over panel, pre-filtered to the selected product.

### 2c. Product × Department Matrix

A table with products as rows and departments as columns. Each cell contains a color-coded score pill. Products are sourced from `org-data.json`; scores are read from each department's `-data.json` by matching repo names.

Color coding matches score cards: green ≥85, yellow 65-84, orange 50-64, red <50, gray for no data.

When a product maps to multiple repos, the cell shows the average score across those repos.

Clicking any cell opens the corresponding department slide-over panel filtered to that specific product/repo.

### 2d. Needs Attention Feed

A list of the top 10-15 findings across all departments, sorted by:
1. Severity (critical first)
2. Recurrence count (findings seen in more audits ranked higher)
3. Effort (easy fixes ranked higher within same severity)

Each row shows: department badge, severity pill, finding title, AI fixable badge (if applicable), repo name, effort level.

Clicking a finding row opens the finding detail panel directly.

---

## 3. Slide-Over Panels

### Behavior

- Opens from the right side, 65% viewport width
- HQ remains visible underneath (dimmed overlay)
- Escape key or overlay click closes the panel
- Product context is inherited from HQ's selector automatically
- URL updates to `?product=key&dept=qa` for deep linking

### Consistent Filter Bar

Every department panel has the same filter bar immediately below the header:

| Filter | Type | Options |
|--------|------|---------|
| Severity | Dropdown | All, Critical, High, Medium, Low, Info |
| Status | Dropdown | All, Open, Fixed, Presumed Fixed |
| Effort | Dropdown | All, Easy, Moderate, Hard |
| AI Fixable | Toggle button | On/off, purple accent when active |
| Search | Text input | Matches title, description, file path, ID |

Filters apply client-side to the findings list below. Filter state resets when the panel closes.

### Panel Content

Below the filter bar:

1. **Stats row** (4 cards): Score, Total Findings, AI Fixable count, Easy Wins count
2. **Findings list**: Rows showing severity pill, title (with AI fixable badge if applicable), effort level. Sorted by severity descending, then effort ascending.

### Department-Specific Notes

While filters are consistent, each department's stats row can show one department-relevant stat in the 4th slot:
- **QA**: "Tests Passing" count
- **SEO**: "Indexed Pages" or overall SEO score breakdown
- **ADA**: WCAG compliance level badge (AAA/AA/A)
- **Compliance**: Framework coverage (e.g., "GDPR: 80%")
- **Monetization**: Estimated revenue opportunity
- **Product**: Backlog item count

The **Privacy panel** is identical to the Compliance panel but loads `privacy-data.json` (already filtered by the aggregator using its canonical keyword list in `aggregate.py`). No client-side keyword filtering needed.

---

## 4a. Canonical Finding Schema

Raw finding schemas vary across departments. The aggregator normalizes all findings to this canonical schema before writing to `-data.json` files:

```json
{
  "id": "ADA-005",
  "department": "ada",
  "repo": "analogify",
  "severity": "high",
  "category": "understandable",
  "title": "Form inputs missing associated labels",
  "description": "6 form inputs use placeholder text only...",
  "evidence": "<input placeholder=\"Your email\"> without label",
  "impact": "Screen reader users cannot understand field purpose",
  "file": "src/components/ContactForm.tsx",
  "line": 18,
  "effort": "easy",
  "fix_suggestion": "Add <label> elements with for/id association",
  "fixable_by_agent": true,
  "status": "open"
}
```

**Field mapping from raw department schemas:**

| Canonical Field | QA/SEO/Product | ADA | Compliance | Monetization | Privacy |
|----------------|----------------|-----|------------|--------------|---------|
| `severity` | `severity` | `severity` | `severity` | `value` → map to severity | `severity` |
| `effort` | `effort` | `effort` or `"unknown"` | `effort` | `implementation_effort` | `effort` |
| `fixable_by_agent` | `fixable_by_agent` | `fixable_by_agent` or `false` | `fixable_by_agent` or `false` | `false` | `fixable` |
| `impact` | `impact` | `impact` | `legal_risk` | `description` (fallback) | `impact` or `legal_risk` |
| `fix_suggestion` | `fix_suggestion` | `fix_suggestion` or `fix` | `fix_suggestion` | `fix_suggestion` | `fix` or `fix_suggestion` |
| `description` | `description` | `description` or `details` | `description` | `description` | `description` |
| `file` | `file` | `file` | `file` or `""` | `file` or `""` | `file` or `""` |

For the content hash (section 5), findings without a meaningful `file` (e.g., monetization opportunities) use an empty string, which means they deduplicate on `department + repo + title` alone.

**Effort value normalization:** `easy` → "Easy", `medium`/`moderate` → "Moderate", `hard`/`complex` → "Hard", anything else → "Unknown".

---

## 4. Finding Detail Panel

### Behavior

- Opens as a nested slide-over (right side, 45% viewport width) on top of the department panel
- The department panel remains visible underneath (shifted left)
- Escape closes the detail panel first, then the department panel
- Can also be opened directly from the HQ "Needs Attention" feed

### Content Sections

Top to bottom:

1. **Header**: Finding ID (mono font), title, metadata tags (severity pill, department-specific category tag, effort tag, AI fixable tag)

2. **AI Fix Banner** (only if `fixable_by_agent` is true): Purple-accented banner showing "AI can fix this" with a copyable `make fix` command

3. **Description**: Full text description of the finding

4. **Evidence**: Code block showing the specific code or configuration that triggered the finding

5. **Impact**: Description of user/business impact

6. **File**: File path with line number, styled as a clickable reference

7. **Recommended Fix**: Green-accented box with the suggested remediation

8. **Backlog Info** (new): "First seen: 2026-03-15 · Seen in 4 audits · Last seen: 2026-03-22". Shows recurrence data from the backlog.

---

## 5. Finding Backlog

### Purpose

Track every finding across audits so users can see: is this new or has it been flagged before? How many times? When was it first seen?

### Storage

`dashboard/backlog.json` — a JSON file written by the aggregator during `backoffice refresh`.

### Schema

```json
{
  "version": 1,
  "updated_at": "2026-03-22T22:16:02Z",
  "findings": {
    "<content_hash>": {
      "hash": "<content_hash>",
      "department": "ada",
      "repo": "analogify",
      "title": "Form inputs missing associated labels",
      "severity": "high",
      "file": "src/components/ContactForm.tsx",
      "first_seen": "2026-03-15T10:30:00Z",
      "last_seen": "2026-03-22T22:16:02Z",
      "audit_count": 4,
      "status": "open",
      "fixable_by_agent": true,
      "current_finding": { /* full finding object from latest scan */ }
    }
  }
}
```

### Content Hash

The deduplication key is a SHA-256 hash of: `department + repo + title + file_path` (normalized to lowercase, whitespace-trimmed).

```python
import hashlib

def finding_hash(department: str, repo: str, title: str, file_path: str) -> str:
    key = f"{department.lower().strip()}:{repo.lower().strip()}:{title.lower().strip()}:{file_path.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```

Using a 16-character hex prefix (64 bits) gives negligible collision probability for the expected finding count (<10,000).

### Merge Algorithm

Run during `backoffice refresh`, after aggregation:

```
for each finding in all department data files:
    hash = finding_hash(department, repo, title, file)
    if hash in backlog:
        backlog[hash].last_seen = now
        backlog[hash].audit_count += 1
        backlog[hash].severity = finding.severity  # update to latest
        backlog[hash].status = finding.status
        backlog[hash].current_finding = finding
    else:
        backlog[hash] = new entry with audit_count=1, first_seen=now
```

### Stale Finding Handling

Findings that appear in the backlog but NOT in the current scan keep their existing data unchanged. Their `last_seen` stays as-is, signaling they may have been fixed. After 30 days without reappearing, they can be auto-marked as `presumed_fixed`.

---

## 5b. Score History

### Purpose

Provide sparkline data showing score trends over the last N scans per department per repo.

### Storage

`dashboard/score-history.json` — appended to on each `backoffice refresh`.

### Schema

```json
{
  "snapshots": [
    {
      "timestamp": "2026-03-22T22:16:02Z",
      "scores": {
        "analogify": { "qa": 76, "seo": 87, "ada": 77, "compliance": 72, "monetization": 48, "product": 67 },
        "codyjo.com": { "qa": 88, "seo": 90, "ada": 79, "compliance": 70, "monetization": 62, "product": 74 }
      }
    }
  ]
}
```

### Behavior

- On each refresh, a new snapshot is appended with the current scores from all department data files
- Only the last 10 snapshots are kept (older ones are pruned)
- The dashboard reads the last 5 snapshots for sparklines and computes trend deltas from the most recent two
- When a product maps to multiple repos, the sparkline shows the average score across those repos

### Integration Points

- **Aggregator** (`backoffice/aggregate.py`): After aggregating department data, run the backlog merge and write `backlog.json`
- **Dashboard** (`index.html`): Load `backlog.json` alongside department data. Enrich each displayed finding with `first_seen`, `audit_count`, `last_seen` from the backlog
- **Finding detail panel**: Show "Backlog Info" section with recurrence data
- **Needs Attention feed**: Use `audit_count` as a secondary sort key (chronic issues rank higher)

---

## 6. Page Consolidation Plan

### Files to Create

| File | Purpose |
|------|---------|
| `dashboard/index.html` | Complete rewrite — single HQ page with all panels inline |
| `dashboard/backlog.json` | New — persistent finding registry |

### Files to Modify

| File | Change |
|------|--------|
| `backoffice/aggregate.py` | Pass through full finding objects (add description, evidence, impact, fix_suggestion); add schema normalization; add backlog merge step; add score history snapshot |
| `backoffice/workflow.py` | Call backlog merge and score history during `refresh_dashboard_artifacts` |
| `backoffice/sync/manifest.py` | Add `backlog.json`, `score-history.json` to `SHARED_META_FILES` |

### Files to Delete (after new index.html is stable)

| File | Reason |
|------|--------|
| `qa.html` | Replaced by QA slide-over panel |
| `seo.html` | Replaced by SEO slide-over panel |
| `ada.html` | Replaced by ADA slide-over panel |
| `compliance.html` | Replaced by Compliance slide-over panel |
| `monetization.html` | Replaced by Monetization slide-over panel |
| `product.html` | Replaced by Product slide-over panel |
| `privacy.html` | Replaced by Privacy slide-over panel |
| `self-audit.html` | Replaced by QA panel filtered to "Back Office" |
| `admin.html` | Folded into HQ |
| `selah.html` | Replaced by product selector |
| `analogify.html` | Replaced by product selector |
| `chromahaus.html` | Replaced by product selector |
| `tnbm-tarot.html` | Replaced by product selector |
| `back-office-hq.html` | Redundant HQ wrapper |
| `backoffice.html` | Legacy bug report form |
| `metrics.html` | Folded into HQ |
| `regression.html` | Folded into HQ |
| `documentation.html` | Folded into Docs panel |
| `documentation-cli.html` | Folded into Docs panel |
| `documentation-cicd.html` | Folded into Docs panel |
| `documentation-github.html` | Folded into Docs panel |

| `jobs.html` | Content extracted into Jobs panel fragment |
| `faq.html` | Content extracted into FAQ panel fragment |

Content fragments (`faq-content.html`, `docs-content.html`) are loaded via `fetch()` + `innerHTML` into their respective panel containers. They contain only the inner content (no `<html>`, `<head>`, or `<body>` tags).

---

## 7. Implementation Sequence

1. **Backlog system** — Add `finding_hash()`, backlog merge to aggregator, write `backlog.json`
2. **New index.html** — Build the HQ page with matrix view, score cards, needs attention feed
3. **Slide-over panel framework** — Reusable panel open/close/stack behavior, filter bar component
4. **Department panels** — Port each department's rendering logic into panel templates
5. **Finding detail panel** — Nested panel with full finding info + backlog data
6. **Product filtering** — Wire product selector to filter all data views
7. **Support panels** — Jobs, FAQ, Docs panels
8. **Cleanup** — Delete old pages, update sync manifest, verify deploy

---

## 8. Error & Loading States

- **Page load**: Show a skeleton layout (gray placeholder cards/rows) while JSON files are fetching
- **Fetch failure**: Show inline error message "Failed to load [department] data" in the affected score card or panel. Other departments continue to work.
- **No data**: Matrix cells show gray "—" for unscanned product/department combinations. Score cards show "—" instead of a number.
- **Empty findings list**: Panel shows "No findings for this product" with a suggestion to run a scan
- **Stale data**: If `generated_at` in any data file is older than 24 hours, show a subtle "Data may be stale" indicator next to the timestamp

---

## 9. Mockups

Interactive mockups are available in `.superpowers/brainstorm/1934860-1774220676/`:
- `hq-mockup-v2.html` — Full HQ with matrix, slide-over panels, finding detail, AI fixable toggle
