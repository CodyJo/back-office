"""Per-tool severity mapping tables and ordering helpers.

The five canonical severity levels — ``critical``, ``high``, ``medium``,
``low``, ``info`` — match what ``backoffice.aggregate.count_severities``
recognizes and what the QA scoring formula consumes. Anything that
flows into ``findings.json`` must use one of these strings.

Scanner-status findings (e.g. ``"semgrep not installed"``) intentionally
bypass the ``meets_min_severity`` filter so coverage gaps stay visible
in the dashboard regardless of the configured min severity.
"""
from __future__ import annotations

SEVERITY_ORDER: list[str] = ["critical", "high", "medium", "low", "info"]
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITY_ORDER)}


# ──────────────────────────────────────────────────────────────────────
# Per-tool severity tables
# ──────────────────────────────────────────────────────────────────────

SEMGREP_SEVERITY: dict[str, str] = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "_default": "low",
}

BANDIT_SEVERITY: dict[str, str] = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "_default": "low",
}

# pip-audit doesn't surface CVSS by default; CVE presence == high.
PIP_AUDIT_SEVERITY_DEFAULT: str = "high"

NPM_AUDIT_SEVERITY: dict[str, str] = {
    "critical": "critical",
    "high": "high",
    "moderate": "medium",
    "low": "low",
    "info": "info",
}

# Gitleaks has no severity field; committed secrets are always treated
# as critical (rotation required, possible historical exposure).
GITLEAKS_SEVERITY_DEFAULT: str = "critical"

# Ruff has no severity. Rule code prefix → canonical level.
# Tried 3-char prefix first, then 1-char, else _default.
RUFF_PREFIX_SEVERITY: dict[str, str] = {
    "S": "high",      # flake8-bandit (security)
    "F": "medium",    # pyflakes (undefined names, unused imports)
    "B": "medium",    # flake8-bugbear (likely bugs)
    "E9": "high",     # pycodestyle syntax errors
    "E": "low",       # pycodestyle style
    "W": "low",       # pycodestyle warnings
    "C": "low",       # mccabe complexity
    "ANN": "info",    # flake8-annotations
    "D": "info",      # pydocstyle
    "N": "info",      # pep8-naming
    "I": "info",      # isort
    "UP": "info",     # pyupgrade
    "_default": "info",
}

# Same prefix → canonical category (for the QA category enum).
RUFF_PREFIX_CATEGORY: dict[str, str] = {
    "S": "security",
    "E9": "lint-error",
    "E": "lint-error",
    "W": "lint-error",
    "F": "code-quality",
    "B": "code-quality",
    "_default": "code-quality",
}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def canonicalize_severity(raw: str, table: dict[str, str]) -> str:
    """Map a tool-native severity string to a canonical level via *table*.

    Tries the literal value, then the upper-cased value, then falls back
    to ``table["_default"]`` (or ``"info"`` if that key is absent).
    """
    if raw in table:
        return table[raw]
    upper = raw.upper() if isinstance(raw, str) else ""
    if upper in table:
        return table[upper]
    return table.get("_default", "info")


def ruff_severity(rule_id: str) -> str:
    """Return the canonical severity for a ruff rule code (e.g. ``"E501"``)."""
    return _ruff_lookup(rule_id, RUFF_PREFIX_SEVERITY)


def ruff_category(rule_id: str) -> str:
    """Return the canonical category for a ruff rule code."""
    return _ruff_lookup(rule_id, RUFF_PREFIX_CATEGORY)


def _ruff_lookup(rule_id: str, table: dict[str, str]) -> str:
    if not rule_id:
        return table["_default"]
    # Try longer prefixes first so 'E9' beats 'E'.
    for length in (3, 2, 1):
        prefix = rule_id[:length]
        if prefix in table:
            return table[prefix]
    return table["_default"]


def meets_min_severity(severity: str, min_severity: str) -> bool:
    """Return True when *severity* is at least as severe as *min_severity*."""
    return SEVERITY_RANK.get(severity, 99) <= SEVERITY_RANK.get(min_severity, 99)
