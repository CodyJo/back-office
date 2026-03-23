"""Backlog tracking for recurring findings across audit scans.

Provides:
- finding_hash: stable identity key for a finding
- normalize_finding: canonical schema for any department's raw finding
- merge_backlog: upsert findings into a persistent backlog.json
- update_score_history: append + prune timestamped score snapshots
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_SNAPSHOTS = 10

# Maps raw effort labels -> canonical effort levels
EFFORT_MAP = {
    "low": "easy",
    "easy": "easy",
    "trivial": "easy",
    "tiny": "easy",
    "small": "easy",
    "medium": "moderate",
    "moderate": "moderate",
    "hard": "hard",
    "complex": "hard",
    "high": "hard",
    "large": "hard",
}


def finding_hash(department, repo, title, file_path):
    """Return a 16-char hex SHA-256 prefix for a finding's identity.

    The hash is computed from the lowercased, whitespace-trimmed
    concatenation ``department:repo:title:file_path``.
    """
    key = ":".join(
        part.strip().lower()
        for part in (department, repo, title, file_path)
    )
    digest = hashlib.sha256(key.encode()).hexdigest()
    return digest[:16]


def normalize_finding(raw, department, repo):
    """Normalize a raw department finding to the canonical backlog schema.

    Field aliases resolved (first match wins):
      severity        <- raw["severity"] or raw["value"]
      effort          <- raw["effort"] or raw["implementation_effort"], then EFFORT_MAP
      impact          <- raw["impact"] or raw["legal_risk"] (compliance alias);
                        monetization falls back to raw["description"]
      fixable_by_agent <- raw["fixable_by_agent"] or raw["fixable"]
      fix_suggestion  <- raw["fix_suggestion"] or raw["fix"]
      description     <- raw["description"] or raw["details"]
      file            <- raw["file"] or raw["location"]
      evidence        <- raw["evidence"] (passed through as-is)
      line            <- raw["line"] (passed through as-is)

    Department-specific fields preserved when present:
      monetization:  revenue_estimate, phase
      compliance:    regulation
      ada:           wcag_criterion, wcag_level
    """
    def _get(*keys, default=""):
        for k in keys:
            if k in raw:
                return raw[k]
        return default

    severity = _get("severity", "value", "legal_risk", default="")
    raw_effort = _get("effort", "implementation_effort", default="")
    effort = EFFORT_MAP.get(str(raw_effort).lower(), raw_effort) if raw_effort else raw_effort

    fixable = _get("fixable_by_agent", "fixable", default=False)
    fix_suggestion = _get("fix_suggestion", "fix", default="")
    description = _get("description", "details", default="")
    file_path = _get("file", "location", default="")

    # impact: raw["impact"] first, then raw["legal_risk"], then empty string.
    # For monetization, fall back to description if neither exists.
    impact = raw.get("impact") or raw.get("legal_risk") or ""
    if not impact and department == "monetization":
        impact = description

    canonical = {
        "id": raw.get("id", ""),
        "department": department,
        "repo": repo,
        "severity": severity,
        "category": raw.get("category", ""),
        "title": raw.get("title", ""),
        "file": file_path,
        "description": description,
        "effort": effort,
        "fix_suggestion": fix_suggestion,
        "fixable_by_agent": bool(fixable),
        "status": raw.get("status", "open"),
        "evidence": raw.get("evidence", ""),
        "line": raw.get("line"),
    }

    # impact is always included when non-empty
    if impact:
        canonical["impact"] = impact

    # Department-specific preserved fields
    if department == "monetization":
        if "revenue_estimate" in raw:
            canonical["revenue_estimate"] = raw["revenue_estimate"]
        if "phase" in raw:
            canonical["phase"] = raw["phase"]

    if department == "compliance":
        if "regulation" in raw:
            canonical["regulation"] = raw["regulation"]

    if department == "ada":
        if "wcag_criterion" in raw:
            canonical["wcag_criterion"] = raw["wcag_criterion"]
        if "wcag_level" in raw:
            canonical["wcag_level"] = raw["wcag_level"]

    return canonical


def _load_backlog(backlog_path):
    """Load backlog.json from disk, returning a fresh structure if absent."""
    if os.path.exists(backlog_path):
        try:
            with open(backlog_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read backlog %s: %s", backlog_path, exc)
    return {"version": 1, "updated_at": "", "findings": {}}


def merge_backlog(findings, backlog_path):
    """Upsert *findings* into the persistent backlog at *backlog_path*.

    For each finding:
    - Compute its hash from (department, repo, title, file).
    - If the hash already exists: increment audit_count, update last_seen,
      severity, status, and current_finding payload.
    - If the hash is new: create an entry with audit_count=1.

    Stale findings (in the backlog but absent from the current scan) are
    left untouched.

    Writes the updated backlog to disk and returns the backlog dict.
    """
    backlog = _load_backlog(backlog_path)
    now = datetime.now(timezone.utc).isoformat()

    existing = backlog.get("findings", {})

    for finding in findings:
        dept = finding.get("department", "")
        repo = finding.get("repo", "")
        title = finding.get("title", "")
        file_path = finding.get("file", "")

        h = finding_hash(dept, repo, title, file_path)

        if h in existing:
            entry = existing[h]
            entry["audit_count"] = entry.get("audit_count", 1) + 1
            entry["last_seen"] = now
            entry["hash"] = h
            entry["department"] = dept
            entry["repo"] = repo
            entry["title"] = title
            entry["file"] = file_path
            entry["severity"] = finding.get("severity", entry.get("severity", ""))
            entry["status"] = finding.get("status", entry.get("status", "open"))
            entry["current_finding"] = finding
        else:
            existing[h] = {
                "hash": h,
                "department": dept,
                "repo": repo,
                "title": title,
                "file": file_path,
                "audit_count": 1,
                "first_seen": now,
                "last_seen": now,
                "severity": finding.get("severity", ""),
                "status": finding.get("status", "open"),
                "current_finding": finding,
            }

    backlog["findings"] = existing
    backlog["version"] = backlog.get("version", 1)
    backlog["updated_at"] = now

    os.makedirs(os.path.dirname(backlog_path) or ".", exist_ok=True)
    with open(backlog_path, "w") as f:
        json.dump(backlog, f, indent=2)

    return backlog


def update_score_history(scores, history_path):
    """Append a timestamped score snapshot and prune to MAX_SNAPSHOTS.

    Args:
        scores: dict of repo -> dict of dept -> score value.
        history_path: path to the score_history.json file.

    Returns:
        The updated history dict (also written to disk).
    """
    # Load existing history
    history = {"snapshots": []}
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read score history %s: %s", history_path, exc)
            history = {"snapshots": []}

    snapshots = history.get("snapshots", [])
    snapshots.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": scores,
    })

    # Prune to last MAX_SNAPSHOTS
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]

    history["snapshots"] = snapshots

    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    return history
