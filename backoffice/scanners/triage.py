"""Optional Haiku-driven triage of deterministic-scanner findings.

Takes a raw deterministic scan payload and runs each finding through a
single Haiku call to:

* Confirm or downgrade severity (false-positive filter).
* Produce a one-paragraph fix suggestion when the deterministic adapter
  left it empty.
* Add ``ai_confidence`` ∈ {high, medium, low} so the dashboard can
  highlight findings that survived independent review.

This module is **disabled by default**. Enable per-target by adding
``scan.haiku_triage: true`` to ``backoffice.yaml``. Even when enabled,
the call respects the AI-spend budget gate — no key, no budget, no
triage.

Cost note: ~5K input tokens (system prompt cached) + ~500 input tokens
+ ~200 output tokens per finding = roughly $0.001/finding at Haiku
pricing. 200 findings ≈ $0.20.
"""
from __future__ import annotations

import json
import logging

from backoffice.budget_check import is_blocked as budget_blocked
from backoffice.llm.client import call_anthropic, has_api_key, has_sdk

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You triage findings from automated code scanners (ruff, semgrep, bandit,
npm audit, gitleaks, etc.) for the Back Office QA pipeline.

For each finding I send you, decide:

1. SEVERITY: confirm or downgrade. Output one of:
   critical, high, medium, low, info
   Downgrade if the rule fires on test code, fixtures, or dead branches.
   Never upgrade beyond what the source scanner reported.

2. CONFIDENCE: how sure are you the finding is real and worth fixing?
   Output one of: high, medium, low.

3. FIX_SUGGESTION: one or two sentences describing how to fix it.
   Concrete and code-aware. Empty string is fine if the original
   suggestion is already specific enough.

Respond with strict JSON (no prose, no markdown fence):

{"severity": "...", "confidence": "...", "fix_suggestion": "..."}

Be conservative — when in doubt about whether a finding is real, output
confidence=low. Operators trust your judgment more than your enthusiasm.
"""


def triage_finding(finding: dict, *, target: str) -> dict:
    """Return a dict with severity / confidence / fix_suggestion overrides.

    Empty dict means "no change" — caller treats the original finding
    as authoritative. The function is best-effort: any failure (no key,
    budget block, API error, malformed response) returns empty dict.
    """
    if not has_api_key() or not has_sdk():
        return {}
    if budget_blocked(target, "qa"):
        return {}

    user_prompt = json.dumps({
        "title": finding.get("title", ""),
        "severity": finding.get("severity", ""),
        "category": finding.get("category", ""),
        "file": finding.get("file", ""),
        "line": finding.get("line"),
        "description": finding.get("description", ""),
        "evidence": finding.get("evidence", "")[:1000],
        "source_tool": finding.get("source_tool", ""),
        "rule_id": finding.get("rule_id", ""),
    })

    result = call_anthropic(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model="haiku",
        max_tokens=400,
        cache_system=True,
        record_event=True,
        target=target,
        department="qa-triage",
    )
    if result.error or not result.text.strip():
        return {}

    try:
        payload = json.loads(result.text.strip())
    except json.JSONDecodeError:
        return {}

    out = {}
    sev = payload.get("severity", "").strip().lower()
    if sev in ("critical", "high", "medium", "low", "info"):
        out["severity"] = sev
    conf = payload.get("confidence", "").strip().lower()
    if conf in ("high", "medium", "low"):
        out["ai_confidence"] = conf
    fix = payload.get("fix_suggestion", "")
    if isinstance(fix, str) and fix.strip():
        out["fix_suggestion"] = fix.strip()
    return out


def triage_payload(payload: dict, *, target: str, max_findings: int = 50) -> dict:
    """Walk a deterministic-scan payload and apply Haiku triage to findings.

    Mutates and returns the payload. Status findings are skipped. The
    ``max_findings`` cap is a safety net: 50 findings × ~$0.001 ≈ $0.05
    per scan, so even an enabled triage layer stays well under any
    reasonable budget.
    """
    triaged = 0
    for f in payload.get("findings", []):
        if triaged >= max_findings:
            break
        if f.get("category") == "scanner-status":
            continue
        overrides = triage_finding(f, target=target)
        if not overrides:
            continue
        # Severity downgrade only — never overwrite to a higher level
        # than the source scanner produced (safety against AI inflation).
        if "severity" in overrides:
            from backoffice.scanners.severity import SEVERITY_RANK
            orig_rank = SEVERITY_RANK.get(f.get("severity", "info"), 4)
            new_rank = SEVERITY_RANK.get(overrides["severity"], 4)
            if new_rank >= orig_rank:
                f["severity"] = overrides["severity"]
        if "ai_confidence" in overrides:
            f["ai_confidence"] = overrides["ai_confidence"]
        if "fix_suggestion" in overrides and not f.get("fix_suggestion"):
            f["fix_suggestion"] = overrides["fix_suggestion"]
        triaged += 1

    payload.setdefault("summary", {})["haiku_triaged_count"] = triaged
    return payload


def is_enabled(scan_cfg) -> bool:
    """Return True iff config opted in via ``scan.haiku_triage: true``."""
    return bool(getattr(scan_cfg, "haiku_triage", False))
