# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate 24 dashboard pages into a single HQ page with slide-over panels, consistent filtering, finding detail views, and a persistent backlog with content-hash deduplication.

**Architecture:** Single `index.html` serves as HQ with a product × department matrix. Department details open as 65%-width slide-over panels. Finding details open as nested 45%-width panels. A Python-side backlog system deduplicates findings across scans using content hashes and tracks recurrence. Score history snapshots power sparkline trends.

**Tech Stack:** Vanilla JS + inline CSS (existing pattern), Python aggregator, JSON data files, S3 + CloudFront deploy.

**Spec:** `docs/superpowers/specs/2026-03-22-dashboard-redesign-design.md`
**Mockup:** `.superpowers/brainstorm/1934860-1774220676/hq-mockup-v2.html`

---

## Chunk 1: Backlog System (Python)

### Task 1: Finding Hash Function

**Files:**
- Create: `backoffice/backlog.py`
- Create: `tests/test_backlog.py`

- [ ] **Step 1: Write failing tests for `finding_hash()`**

```python
# tests/test_backlog.py
import pytest
from backoffice.backlog import finding_hash


class TestFindingHash:
    def test_basic_hash(self):
        h = finding_hash("ada", "analogify", "Missing alt text", "src/Gallery.tsx")
        assert isinstance(h, str)
        assert len(h) == 16

    def test_deterministic(self):
        h1 = finding_hash("ada", "analogify", "Missing alt text", "src/Gallery.tsx")
        h2 = finding_hash("ada", "analogify", "Missing alt text", "src/Gallery.tsx")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = finding_hash("ADA", "Analogify", "Missing Alt Text", "src/Gallery.tsx")
        h2 = finding_hash("ada", "analogify", "missing alt text", "src/Gallery.tsx")
        assert h1 == h2

    def test_whitespace_trimmed(self):
        h1 = finding_hash("  ada  ", " analogify ", " title ", " file.tsx ")
        h2 = finding_hash("ada", "analogify", "title", "file.tsx")
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        h1 = finding_hash("ada", "analogify", "Title A", "file.tsx")
        h2 = finding_hash("ada", "analogify", "Title B", "file.tsx")
        assert h1 != h2

    def test_empty_file_path(self):
        h = finding_hash("monetization", "analogify", "Revenue opportunity", "")
        assert isinstance(h, str)
        assert len(h) == 16
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backlog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backoffice.backlog'`

- [ ] **Step 3: Implement `finding_hash()`**

```python
# backoffice/backlog.py
"""Finding backlog — persistent registry with content-hash deduplication."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def finding_hash(department: str, repo: str, title: str, file_path: str) -> str:
    """Compute a 16-char hex content hash for deduplication."""
    key = (
        f"{department.lower().strip()}:"
        f"{repo.lower().strip()}:"
        f"{title.lower().strip()}:"
        f"{file_path.lower().strip()}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backlog.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backoffice/backlog.py tests/test_backlog.py
git commit -m "feat(backlog): add finding_hash content deduplication function"
```

---

### Task 2: Normalize Finding Schema

**Files:**
- Modify: `backoffice/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write failing tests for `normalize_finding()`**

```python
# tests/test_backlog.py — add to existing file

from backoffice.backlog import normalize_finding


class TestNormalizeFinding:
    def test_qa_finding(self):
        raw = {
            "id": "QA-001", "severity": "high", "category": "security",
            "title": "SQL injection", "description": "Unsanitized input",
            "evidence": "db.query(f'...')", "impact": "Data breach",
            "file": "src/api.ts", "line": 45, "effort": "low",
            "fixable_by_agent": True, "fix_suggestion": "Use parameterized queries",
        }
        result = normalize_finding(raw, "qa", "analogify")
        assert result["severity"] == "high"
        assert result["effort"] == "easy"
        assert result["fixable_by_agent"] is True
        assert result["fix_suggestion"] == "Use parameterized queries"
        assert result["department"] == "qa"
        assert result["repo"] == "analogify"

    def test_monetization_finding_maps_value_to_severity(self):
        raw = {
            "id": "MON-001", "value": "high", "category": "premium",
            "title": "Add subscription tier", "description": "Revenue opportunity",
            "implementation_effort": "hard", "revenue_estimate": "$500/mo",
            "phase": "phase-2",
        }
        result = normalize_finding(raw, "monetization", "analogify")
        assert result["severity"] == "high"
        assert result["effort"] == "hard"
        assert result["fixable_by_agent"] is False

    def test_compliance_finding_maps_legal_risk_to_impact(self):
        raw = {
            "id": "COMP-001", "severity": "critical", "category": "gdpr",
            "title": "No consent mechanism", "description": "Missing consent",
            "legal_risk": "GDPR violation risk", "file": "src/app.tsx",
            "effort": "moderate", "fix_suggestion": "Add consent banner",
        }
        result = normalize_finding(raw, "compliance", "analogify")
        assert result["impact"] == "GDPR violation risk"
        assert result["effort"] == "moderate"

    def test_effort_normalization(self):
        for raw_val, expected in [("low", "easy"), ("easy", "easy"),
                                   ("tiny", "easy"), ("small", "easy"),
                                   ("medium", "moderate"), ("moderate", "moderate"),
                                   ("hard", "hard"), ("complex", "hard"),
                                   ("large", "hard"),
                                   ("unknown", "unknown"), (None, "unknown")]:
            raw = {"id": "X", "title": "T", "effort": raw_val}
            result = normalize_finding(raw, "qa", "repo")
            assert result["effort"] == expected, f"{raw_val} should map to {expected}"

    def test_missing_fields_get_defaults(self):
        raw = {"id": "X", "title": "Minimal finding"}
        result = normalize_finding(raw, "qa", "repo")
        assert result["description"] == ""
        assert result["evidence"] == ""
        assert result["impact"] == ""
        assert result["file"] == ""
        assert result["fix_suggestion"] == ""
        assert result["fixable_by_agent"] is False
        assert result["status"] == "open"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backlog.py::TestNormalizeFinding -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_finding'`

- [ ] **Step 3: Implement `normalize_finding()`**

Add to `backoffice/backlog.py`:

```python
EFFORT_MAP = {
    "low": "easy", "easy": "easy", "trivial": "easy",
    "tiny": "easy", "small": "easy",
    "medium": "moderate", "moderate": "moderate",
    "hard": "hard", "complex": "hard", "high": "hard",
    "large": "hard",
}


def normalize_finding(raw: dict, department: str, repo: str) -> dict:
    """Normalize a raw finding from any department to the canonical schema."""
    severity = raw.get("severity") or raw.get("value", "medium")
    effort_raw = raw.get("effort") or raw.get("implementation_effort")
    effort = EFFORT_MAP.get(str(effort_raw).lower(), "unknown") if effort_raw else "unknown"

    return {
        "id": raw.get("id", ""),
        "department": department,
        "repo": repo,
        "severity": severity,
        "category": raw.get("category", ""),
        "title": raw.get("title", raw.get("description", "Untitled")),
        "description": raw.get("description", raw.get("details", "")),
        "evidence": raw.get("evidence", ""),
        "impact": raw.get("impact", raw.get("legal_risk", "")),
        "file": raw.get("file") or raw.get("location", ""),
        "line": raw.get("line"),
        "effort": effort,
        "fix_suggestion": raw.get("fix_suggestion") or raw.get("fix", ""),
        "fixable_by_agent": bool(raw.get("fixable_by_agent", raw.get("fixable", False))),
        "status": raw.get("status", "open"),
        # Preserve department-specific fields
        **({"revenue_estimate": raw["revenue_estimate"], "phase": raw["phase"]}
           if "revenue_estimate" in raw else {}),
        **({"regulation": raw["regulation"]} if "regulation" in raw else {}),
        **({"wcag_criterion": raw.get("wcag_criterion", raw.get("criterion", "")),
            "wcag_level": raw.get("wcag_level", raw.get("level", ""))}
           if department == "ada" else {}),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backlog.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backoffice/backlog.py tests/test_backlog.py
git commit -m "feat(backlog): add normalize_finding schema normalization"
```

---

### Task 3: Backlog Merge

**Files:**
- Modify: `backoffice/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write failing tests for `merge_backlog()`**

```python
# tests/test_backlog.py — add to existing file
import json
from pathlib import Path
from backoffice.backlog import merge_backlog, finding_hash


class TestMergeBacklog:
    def test_new_finding_added(self, tmp_path):
        backlog_path = tmp_path / "backlog.json"
        findings = [{"department": "qa", "repo": "analogify", "title": "Bug",
                      "file": "src/app.ts", "severity": "high", "fixable_by_agent": False,
                      "status": "open"}]
        merge_backlog(findings, backlog_path)
        data = json.loads(backlog_path.read_text())
        assert len(data["findings"]) == 1
        entry = list(data["findings"].values())[0]
        assert entry["audit_count"] == 1
        assert entry["title"] == "Bug"

    def test_existing_finding_increments(self, tmp_path):
        backlog_path = tmp_path / "backlog.json"
        findings = [{"department": "qa", "repo": "analogify", "title": "Bug",
                      "file": "src/app.ts", "severity": "high", "fixable_by_agent": False,
                      "status": "open"}]
        merge_backlog(findings, backlog_path)
        merge_backlog(findings, backlog_path)
        data = json.loads(backlog_path.read_text())
        entry = list(data["findings"].values())[0]
        assert entry["audit_count"] == 2

    def test_stale_finding_not_updated(self, tmp_path):
        backlog_path = tmp_path / "backlog.json"
        h = finding_hash("qa", "analogify", "Old Bug", "src/old.ts")
        initial = {"version": 1, "updated_at": "2026-03-20T00:00:00Z",
                    "findings": {h: {"hash": h, "department": "qa", "repo": "analogify",
                                      "title": "Old Bug", "file": "src/old.ts",
                                      "severity": "low", "first_seen": "2026-03-01T00:00:00Z",
                                      "last_seen": "2026-03-20T00:00:00Z", "audit_count": 3,
                                      "status": "open", "fixable_by_agent": False,
                                      "current_finding": {}}}}
        backlog_path.write_text(json.dumps(initial))
        # Merge with NO findings matching the old one
        merge_backlog([], backlog_path)
        data = json.loads(backlog_path.read_text())
        assert data["findings"][h]["audit_count"] == 3  # unchanged
        assert data["findings"][h]["last_seen"] == "2026-03-20T00:00:00Z"

    def test_empty_backlog_created(self, tmp_path):
        backlog_path = tmp_path / "backlog.json"
        merge_backlog([], backlog_path)
        data = json.loads(backlog_path.read_text())
        assert data["version"] == 1
        assert data["findings"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backlog.py::TestMergeBacklog -v`
Expected: FAIL — `ImportError: cannot import name 'merge_backlog'`

- [ ] **Step 3: Implement `merge_backlog()`**

Add to `backoffice/backlog.py`:

```python
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def merge_backlog(findings: list[dict], backlog_path: Path) -> dict:
    """Merge current findings into the persistent backlog."""
    backlog_path = Path(backlog_path)

    # Load existing backlog
    if backlog_path.exists():
        try:
            backlog = json.loads(backlog_path.read_text())
        except (json.JSONDecodeError, OSError):
            backlog = {"version": 1, "findings": {}}
    else:
        backlog = {"version": 1, "findings": {}}

    now = _iso_now()
    seen_hashes = set()

    for f in findings:
        h = finding_hash(
            f.get("department", ""),
            f.get("repo", ""),
            f.get("title", ""),
            f.get("file", ""),
        )
        seen_hashes.add(h)

        if h in backlog["findings"]:
            entry = backlog["findings"][h]
            entry["last_seen"] = now
            entry["audit_count"] += 1
            entry["severity"] = f.get("severity", entry["severity"])
            entry["status"] = f.get("status", entry["status"])
            entry["fixable_by_agent"] = f.get("fixable_by_agent", entry.get("fixable_by_agent", False))
            entry["current_finding"] = f
        else:
            backlog["findings"][h] = {
                "hash": h,
                "department": f.get("department", ""),
                "repo": f.get("repo", ""),
                "title": f.get("title", ""),
                "severity": f.get("severity", "medium"),
                "file": f.get("file", ""),
                "first_seen": now,
                "last_seen": now,
                "audit_count": 1,
                "status": f.get("status", "open"),
                "fixable_by_agent": f.get("fixable_by_agent", False),
                "current_finding": f,
            }

    new_count = len(seen_hashes) - len(seen_hashes & (set(backlog["findings"].keys()) - seen_hashes))
    # Simpler: count entries where first_seen == now
    new_count = sum(1 for h in seen_hashes
                    if backlog["findings"].get(h, {}).get("first_seen") == now)

    backlog["updated_at"] = now
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(json.dumps(backlog, indent=2, default=str) + "\n")
    logger.info("Backlog updated: %d total entries, %d new this scan",
                len(backlog["findings"]), new_count)
    return backlog
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backlog.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backoffice/backlog.py tests/test_backlog.py
git commit -m "feat(backlog): add merge_backlog persistent finding registry"
```

> **Deferred:** Auto-marking findings as `presumed_fixed` after 30 days without reappearing (spec section 5). This can be added later as a simple date check in the merge loop.

---

### Task 4: Score History

**Files:**
- Modify: `backoffice/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write failing tests for `update_score_history()`**

```python
# tests/test_backlog.py — add to existing file
from backoffice.backlog import update_score_history


class TestScoreHistory:
    def test_creates_new_file(self, tmp_path):
        history_path = tmp_path / "score-history.json"
        scores = {"analogify": {"qa": 76, "seo": 87}}
        update_score_history(scores, history_path)
        data = json.loads(history_path.read_text())
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["scores"]["analogify"]["qa"] == 76

    def test_appends_snapshot(self, tmp_path):
        history_path = tmp_path / "score-history.json"
        scores = {"analogify": {"qa": 76}}
        update_score_history(scores, history_path)
        update_score_history({"analogify": {"qa": 80}}, history_path)
        data = json.loads(history_path.read_text())
        assert len(data["snapshots"]) == 2
        assert data["snapshots"][1]["scores"]["analogify"]["qa"] == 80

    def test_prunes_to_10_snapshots(self, tmp_path):
        history_path = tmp_path / "score-history.json"
        for i in range(12):
            update_score_history({"repo": {"qa": i}}, history_path)
        data = json.loads(history_path.read_text())
        assert len(data["snapshots"]) == 10
        assert data["snapshots"][-1]["scores"]["repo"]["qa"] == 11
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backlog.py::TestScoreHistory -v`
Expected: FAIL — `ImportError: cannot import name 'update_score_history'`

- [ ] **Step 3: Implement `update_score_history()`**

Add to `backoffice/backlog.py`:

```python
MAX_SNAPSHOTS = 10


def update_score_history(
    scores: dict[str, dict[str, int | float | None]],
    history_path: Path,
) -> dict:
    """Append a score snapshot and prune to last MAX_SNAPSHOTS."""
    history_path = Path(history_path)

    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except (json.JSONDecodeError, OSError):
            history = {"snapshots": []}
    else:
        history = {"snapshots": []}

    history["snapshots"].append({
        "timestamp": _iso_now(),
        "scores": scores,
    })

    # Prune old snapshots
    if len(history["snapshots"]) > MAX_SNAPSHOTS:
        history["snapshots"] = history["snapshots"][-MAX_SNAPSHOTS:]

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, default=str) + "\n")
    logger.info("Score history updated: %d snapshots", len(history["snapshots"]))
    return history
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backlog.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backoffice/backlog.py tests/test_backlog.py
git commit -m "feat(backlog): add score history snapshots for sparklines"
```

---

### Task 5: Integrate Backlog into Aggregator

**Files:**
- Modify: `backoffice/aggregate.py` — update `aggregate_department()` to pass through full findings, update `aggregate()` to call backlog merge
- Modify: `backoffice/workflow.py` — no changes needed (already calls `aggregate()` via `run_aggregate()`)
- Modify: `backoffice/sync/manifest.py` — add `backlog.json` and `score-history.json`
- Modify: `tests/test_aggregate.py` — update tests for new finding fields

- [ ] **Step 1: Update `aggregate_department()` to pass through full finding objects**

In `backoffice/aggregate.py`, replace the findings list comprehension (lines 321-340) to include all fields by using `normalize_finding()`:

```python
# At top of aggregate.py, add import:
from backoffice.backlog import normalize_finding

# In aggregate_department(), replace the findings comprehension with:
                "findings": [
                    normalize_finding(f, department_name, repo_name)
                    for f in findings
                ],
```

- [ ] **Step 2: Update `aggregate_qa()` similarly**

In `aggregate_qa()`, update the enriched finding dict (lines 221-233) to include full fields:

```python
# Replace the enriched.append block:
                normalized = normalize_finding(f, "qa", repo_name)
                normalized["status"] = fix_info.get("status", "open")
                normalized["commit"] = fix_info.get("commit_hash", "")
                normalized["fixed_at"] = fix_info.get("fixed_at", "")
                enriched.append(normalized)
```

- [ ] **Step 3: Add backlog merge and score history to `aggregate()`**

At the end of `aggregate()`, after all department aggregations, add:

```python
    # -- Backlog merge --
    from backoffice.backlog import merge_backlog, update_score_history

    all_findings = []
    score_snapshot = {}
    for dept_file in ["qa-data.json", "seo-data.json", "ada-data.json",
                       "compliance-data.json", "monetization-data.json",
                       "product-data.json"]:
        dept_path = dashboard_dir / dept_file
        if dept_path.exists():
            try:
                dept_data = json.loads(dept_path.read_text())
                for repo in dept_data.get("repos", []):
                    repo_name = repo.get("name", "")
                    for f in repo.get("findings", []):
                        all_findings.append(f)
                    # Collect scores for history
                    summary = repo.get("summary", {})
                    dept_key = dept_file.replace("-data.json", "")
                    score = None
                    if dept_key == "qa":
                        # QA has no pre-computed score; derive from severity counts
                        c = int(summary.get("critical", 0))
                        h = int(summary.get("high", 0))
                        m = int(summary.get("medium", 0))
                        lo = int(summary.get("low", 0))
                        total = c + h + m + lo + int(summary.get("info", 0))
                        score = max(0, 100 - c * 15 - h * 8 - m * 3 - lo) if total else None
                    else:
                        for field in ["seo_score", "compliance_score",
                                       "monetization_readiness_score",
                                       "product_readiness_score", "score"]:
                            score = summary.get(field)
                            if score is not None:
                                break
                    if score is not None:
                        score_snapshot.setdefault(repo_name, {})[dept_key] = score
            except (json.JSONDecodeError, OSError):
                pass

    backlog_path = Path(dashboard_dir) / "backlog.json"
    merge_backlog(all_findings, backlog_path)

    history_path = Path(dashboard_dir) / "score-history.json"
    update_score_history(score_snapshot, history_path)
```

- [ ] **Step 4: Update sync manifest**

In `backoffice/sync/manifest.py`, add to `SHARED_META_FILES`:

```python
SHARED_META_FILES: list[str] = [
    "automation-data.json",
    "org-data.json",
    "local-audit-log.json",
    "local-audit-log.md",
    "regression-data.json",
    "backlog.json",
    "score-history.json",
]
```

- [ ] **Step 5: Run existing tests**

Run: `python3 -m pytest tests/test_aggregate.py -v`
Expected: All existing tests PASS (they use `valid_repos=None` and won't trigger backlog)

- [ ] **Step 6: Run full refresh to test integration**

Run: `python3 -m backoffice refresh`
Expected: Backlog and score history files created in `dashboard/`

- [ ] **Step 7: Verify output files**

```bash
python3 -c "import json; d=json.load(open('dashboard/backlog.json')); print(f'Backlog: {len(d[\"findings\"])} entries')"
python3 -c "import json; d=json.load(open('dashboard/score-history.json')); print(f'Score history: {len(d[\"snapshots\"])} snapshots')"
```

- [ ] **Step 8: Commit**

```bash
git add backoffice/aggregate.py backoffice/backlog.py backoffice/sync/manifest.py tests/test_backlog.py
git commit -m "feat(backlog): integrate backlog merge and score history into aggregator"
```

---

## Chunk 2: New HQ Dashboard (index.html)

### Task 6: HQ Page — Top Bar + Score Cards + Matrix

**Files:**
- Create: `dashboard/index-new.html` (work in separate file, rename at end)

Build the new HQ page following the mockup at `.superpowers/brainstorm/1934860-1774220676/hq-mockup-v2.html`. This is the largest single task.

- [ ] **Step 1: Create `index-new.html` with top bar, score cards, and matrix**

Structure:
1. All CSS in a single `<style>` block (follow existing dark theme: `--bg: #0a0a0f`, `--accent: #c4944a`)
2. Top bar: logo, product selector, Jobs/Docs/FAQ buttons, last scan timestamp
3. Score cards row: 6 cards with sparklines from `score-history.json`
4. Product × Department matrix: color-coded cells from all `-data.json` files
5. Needs Attention feed: top 15 findings sorted by severity → audit_count → effort

Data loading:
```javascript
const DATA_SOURCES = {
    qa: 'qa-data.json', seo: 'seo-data.json', ada: 'ada-data.json',
    compliance: 'compliance-data.json', monetization: 'monetization-data.json',
    product: 'product-data.json', privacy: 'privacy-data.json',
};
const SUPPORT_DATA = ['org-data.json', 'backlog.json', 'score-history.json'];
```

Product filtering: read `org-data.json` products, filter repos by `product.repos.includes(repoName)`.

Score card color coding: green ≥85, yellow 65-84, orange 50-64, red <50.

Sparklines: read last 5 snapshots from `score-history.json`, render as tiny bar charts.

Needs Attention: collect all findings across departments, sort by severity (critical=0, high=1, medium=2, low=3, info=4), then by `backlog.audit_count` descending, then effort (easy=0, moderate=1, hard=2). Show top 15.

- [ ] **Step 2: Add error and loading states**

Implement the 5 states from spec section 8:
1. **Loading skeleton**: Gray placeholder cards/rows rendered on page load, replaced when data arrives
2. **Fetch failure**: If a department JSON fails to load, show "Failed to load [dept] data" in its score card; other departments continue working
3. **No data**: Matrix cells show gray "—" for unscanned product/department combinations
4. **Empty findings**: Panel body shows "No findings for this product" with a muted suggestion
5. **Stale data**: If any `generated_at` timestamp is older than 24 hours, show "Data may be stale" next to the last scan timestamp

- [ ] **Step 3: Add URL deep linking**

On page load, read `?product=` and `?dept=` from the URL. If present, set the product selector and open the corresponding department panel. On product change or panel open/close, update the URL via `history.replaceState()`.

- [ ] **Step 4: Test locally**

Run: `python3 -m backoffice serve --port 8070`
Open: `http://localhost:8070/index-new.html`
Verify: Score cards show real scores, matrix is populated, findings appear.
Test: `http://localhost:8070/index-new.html?product=selah&dept=qa` opens with Selah selected and QA panel open.
Test: Kill the server and reload — verify loading skeleton appears, then error states show.

- [ ] **Step 5: Commit**

```bash
git add dashboard/index-new.html
git commit -m "feat(dashboard): new HQ page with score cards, matrix, error states, deep linking"
```

---

### Task 7: Slide-Over Panel Framework

**Files:**
- Modify: `dashboard/index-new.html`

Add the slide-over panel system:

- [ ] **Step 1: Add slide-over HTML structure and CSS**

At the bottom of `<body>`, add:
- Overlay div (`class="overlay"`)
- Slide-over container (`class="slideover"`) with header, filter bar, body
- Detail panel container (`class="detail-panel"`) nested for finding detail

CSS for panels:
- `.slideover`: fixed right, 65% width, slides in from right
- `.detail-panel`: fixed right, 45% width, slides over the slideover
- Escape key handling: close detail first, then slideover

- [ ] **Step 2: Add panel open/close JavaScript**

```javascript
function openDeptPanel(department, repo) { /* populate panel header + content */ }
function closeDeptPanel() { /* close slideover + overlay */ }
function openFindingDetail(finding) { /* populate detail panel */ }
function closeFindingDetail() { /* close just the detail panel */ }
```

Wire click handlers: score cards → `openDeptPanel(dept, null)`, matrix cells → `openDeptPanel(dept, repo)`, finding rows → `openFindingDetail(finding)`.

- [ ] **Step 3: Add consistent filter bar**

Inside the slideover, add the filter bar with: Severity dropdown, Status dropdown, Effort dropdown, AI Fixable toggle, Search input. All filters apply client-side to the findings list.

- [ ] **Step 4: Test locally**

Open: `http://localhost:8070/index-new.html`
Click: Score card → verify slideover opens with department findings
Click: Matrix cell → verify slideover opens filtered to that repo
Click: Escape → verify panels close in order

- [ ] **Step 5: Commit**

```bash
git add dashboard/index-new.html
git commit -m "feat(dashboard): add slide-over panel framework with filters"
```

---

### Task 8: Department Panel Content

**Files:**
- Modify: `dashboard/index-new.html`

- [ ] **Step 1: Build department panel rendering function**

```javascript
function renderDeptPanel(department, repoFilter) {
    // 1. Load department data from deptData[department]
    // 2. Filter repos by repoFilter (if set) or product selector
    // 3. Render stats row: Score, Findings, AI Fixable, Easy Wins
    // 4. Render findings list with severity pills + AI badges
    // 5. Apply current filter bar state
}
```

Each department uses the same rendering pattern. Department-specific 4th stat:
- QA: "Tests Passing" (from summary)
- SEO: "SEO Score" (overall)
- ADA: WCAG level badge
- Compliance: "Frameworks" count
- Monetization: "Revenue Est."
- Product: "Backlog Items"

- [ ] **Step 2: Add Privacy panel as filtered Compliance view**

Load `privacy-data.json` and render with the same panel template. No special keyword filtering needed — the aggregator already produces privacy-filtered data.

- [ ] **Step 3: Test all 7 department panels**

Open each department via score card and matrix cell clicks. Verify:
- Findings load correctly
- Filters work (severity, status, effort, AI fixable, search)
- Product context is maintained

- [ ] **Step 4: Commit**

```bash
git add dashboard/index-new.html
git commit -m "feat(dashboard): render all department panels with findings"
```

---

### Task 9: Finding Detail Panel

**Files:**
- Modify: `dashboard/index-new.html`

- [ ] **Step 1: Build finding detail rendering function**

```javascript
function renderFindingDetail(finding) {
    // 1. Header: ID, title, severity/category/effort/AI tags
    // 2. AI Fix Banner (if fixable_by_agent): "make fix TARGET=<repo>"
    // 3. Description section
    // 4. Evidence code block
    // 5. Impact section
    // 6. File path with line number
    // 7. Recommended Fix (green box)
    // 8. Backlog Info: first_seen, audit_count, last_seen from backlog.json
}
```

Backlog enrichment: look up the finding's content hash in `backlogData.findings[hash]` to get recurrence info.

- [ ] **Step 2: Wire finding row clicks to detail panel**

Both in the Needs Attention feed and in department panels, clicking a finding row calls `openFindingDetail(finding)`.

- [ ] **Step 3: Test finding detail**

Click a finding → verify all sections populate. Verify backlog info shows "First seen" / "Seen in N audits". Verify AI fix banner only appears for fixable findings.

- [ ] **Step 4: Commit**

```bash
git add dashboard/index-new.html
git commit -m "feat(dashboard): add finding detail panel with backlog info"
```

---

### Task 10: Support Panels (Jobs, FAQ, Docs)

**Files:**
- Modify: `dashboard/index-new.html`
- Create: `dashboard/faq-content.html` (extracted from `faq.html`)
- Create: `dashboard/docs-content.html` (combined from `documentation*.html`)

- [ ] **Step 1: Extract FAQ content into fragment**

Copy the `<main>` content from `faq.html` into `faq-content.html` (no `<html>`, `<head>`, `<body>` tags). Just the FAQ sections.

- [ ] **Step 2: Extract and combine docs content**

Merge content from `documentation.html`, `documentation-cli.html`, `documentation-cicd.html`, `documentation-github.html` into a single tabbed `docs-content.html` fragment.

- [ ] **Step 3: Add Jobs panel**

Load `.jobs.json` and `.jobs-history.json`. Render as a simple list of running/completed jobs with timestamps.

- [ ] **Step 4: Add FAQ and Docs panels**

Load fragments via `fetch('faq-content.html')` and `fetch('docs-content.html')`, inject into panel body via `innerHTML`.

- [ ] **Step 5: Wire top bar buttons**

Jobs, Docs, FAQ buttons in the top bar open their respective panels.

- [ ] **Step 6: Test all support panels**

Click each button, verify content loads.

- [ ] **Step 7: Commit**

```bash
git add dashboard/index-new.html dashboard/faq-content.html dashboard/docs-content.html
git commit -m "feat(dashboard): add Jobs, FAQ, and Docs support panels"
```

---

## Chunk 3: Cleanup and Deploy

### Task 11: Swap and Cleanup

**Files:**
- Rename: `dashboard/index.html` → `dashboard/index-old.html` (backup)
- Rename: `dashboard/index-new.html` → `dashboard/index.html`
- Modify: `backoffice/sync/manifest.py` — update `DASHBOARD_FILES`

- [ ] **Step 1: Swap index files**

```bash
mv dashboard/index.html dashboard/index-old.html
mv dashboard/index-new.html dashboard/index.html
```

- [ ] **Step 2: Update DASHBOARD_FILES in manifest**

Replace the current list with:

```python
DASHBOARD_FILES: list[str] = [
    "index.html",
    "faq-content.html",
    "docs-content.html",
    "site-branding.js", "department-context.js", "favicon.svg",
]
```

- [ ] **Step 3: Test full refresh + local serve**

```bash
python3 -m backoffice refresh
python3 -m backoffice serve --port 8070
```

Open `http://localhost:8070/` and verify the new dashboard works end-to-end.

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html dashboard/index-old.html dashboard/faq-content.html dashboard/docs-content.html backoffice/sync/manifest.py
git commit -m "feat(dashboard): swap to new consolidated HQ dashboard"
```

---

### Task 12: Delete Old Pages

**Files:**
- Delete: 20 HTML files (see spec section 6 for full list)

- [ ] **Step 1: Delete redundant files**

```bash
git rm dashboard/qa.html dashboard/seo.html dashboard/ada.html \
       dashboard/compliance.html dashboard/monetization.html dashboard/product.html \
       dashboard/privacy.html dashboard/self-audit.html dashboard/admin.html \
       dashboard/selah.html dashboard/analogify.html dashboard/chromahaus.html \
       dashboard/tnbm-tarot.html dashboard/back-office-hq.html dashboard/backoffice.html \
       dashboard/metrics.html dashboard/regression.html \
       dashboard/documentation.html dashboard/documentation-cli.html \
       dashboard/documentation-cicd.html dashboard/documentation-github.html \
       dashboard/jobs.html dashboard/faq.html
```

- [ ] **Step 2: Verify nothing breaks**

```bash
python3 -m backoffice refresh
python3 -m backoffice serve --port 8070
```

Open `http://localhost:8070/` and test all panels.

- [ ] **Step 3: Delete backup**

```bash
git rm dashboard/index-old.html
```

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(dashboard): remove 23 old dashboard pages, consolidated into single HQ"
```

---

### Task 13: Deploy Verification

- [ ] **Step 1: Run sync dry-run**

```bash
python3 -m backoffice sync --dry-run
```

Verify only the new files are in the upload list.

- [ ] **Step 2: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 3: Deploy**

```bash
python3 -m backoffice sync
```

- [ ] **Step 4: Verify live dashboards**

Check `admin.codyjo.com` loads the new HQ dashboard with matrix view and slide-over panels.

- [ ] **Step 5: Final commit**

```bash
git commit -m "chore(dashboard): verify deploy of consolidated dashboard"
```
