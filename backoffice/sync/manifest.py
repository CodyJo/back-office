"""Canonical file manifest for dashboard sync.

Single source of truth for which files get uploaded and their
content types. Resolves discrepancies between the old
sync-dashboard.sh and quick-sync.sh file lists.
"""

DASHBOARD_FILES: list[str] = [
    "index.html",
    "migration.html",
    "faq-content.html",
    "docs-content.html",
    "site-branding.js", "department-context.js", "favicon.svg",
]

DEPT_DATA_MAP: dict[str, tuple[str, str]] = {
    "qa":           ("findings.json",             "qa-data.json"),
    "seo":          ("seo-findings.json",         "seo-data.json"),
    "ada":          ("ada-findings.json",         "ada-data.json"),
    "compliance":   ("compliance-findings.json",  "compliance-data.json"),
    "privacy":      ("privacy-findings.json",     "privacy-data.json"),
    "monetization": ("monetization-findings.json", "monetization-data.json"),
    "product":      ("product-findings.json",     "product-data.json"),
    "cloud-ops":    ("cloud-ops-findings.json",  "cloud-ops-data.json"),
    "self-audit":   ("findings.json",             "self-audit-data.json"),
}

AGG_DATA_MAP: dict[str, str] = {
    "data.json":              "qa-data.json",
    "seo-data.json":          "seo-data.json",
    "ada-data.json":          "ada-data.json",
    "compliance-data.json":   "compliance-data.json",
    "privacy-data.json":      "privacy-data.json",
    "monetization-data.json": "monetization-data.json",
    "product-data.json":      "product-data.json",
    "cloud-ops-data.json":    "cloud-ops-data.json",
}

SHARED_META_FILES: list[str] = [
    "automation-data.json",
    "org-data.json",
    "local-audit-log.json",
    "local-audit-log.md",
    "regression-data.json",
    "backlog.json",
    "score-history.json",
    "migration-plan.json",
    "cloud-cost-comparison.json",
    "remediation-plan.json",
    "task-queue.json",
]

JOB_STATUS_FILES: list[str] = [".jobs.json", ".jobs-history.json"]

_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".svg":  "image/svg+xml",
    ".md":   "text/markdown",
    ".css":  "text/css",
}


def content_type_for(filename: str) -> str:
    """Return the content type for a file based on extension."""
    for ext, ct in _CONTENT_TYPES.items():
        if filename.endswith(ext):
            return ct
    return "application/octet-stream"
