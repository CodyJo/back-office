"""Tool adapters for non-QA departments.

Each adapter follows the same shape as ``backoffice/scanners/tools.py``:
take a :class:`ScannerContext`, run a subprocess, parse output, return
a :class:`ScannerResult`. Severity / status / finding-id conventions
are identical, so the runner code is shared.

Departments and their tool coverage:

* ``seo``       — lighthouse (full audit), html-validate (markup)
* ``ada``       — axe-core CLI (accessibility violations)
* ``compliance``— license-check (npm/python license inventory + risk)
* ``cloud-ops`` — checkov (IaC + Dockerfile + workflow files), tfsec (Terraform)

``monetization`` and ``product`` are intentionally not represented —
their findings are judgment calls (revenue strategy, feature gaps,
roadmap prioritization) that no deterministic tool can produce. The
runner emits a single ``scanner-status`` finding for those depts noting
that AI scanning is the only useful mode.
"""
from __future__ import annotations

import json
import logging
import os

from backoffice.scanners.tools import (
    DEFAULT_TIMEOUT_SECONDS,
    ScannerResult,
    _failed_result,
    _make_finding,
    _missing_tool_result,
    _no_targets_result,
    _rel,
    _run,
    _which,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# SEO
# ──────────────────────────────────────────────────────────────────────


def run_lighthouse(ctx) -> ScannerResult:
    """Lighthouse score audit on the target's local dev URL.

    Targets must declare ``lint_command`` or expose a default URL —
    we conservatively skip when no URL is configured. (Real wiring
    requires standing up the dev server first; out of scope for
    Phase 3 scanning, which is read-only.)
    """
    binary = _which("lighthouse")
    if not binary:
        return _missing_tool_result("lighthouse", "lighthouse")
    # Phase 3 limitation: requires a running URL. Defer until URL
    # discovery is wired (per-target config field).
    return _no_targets_result(
        "lighthouse",
        "lighthouse needs a running dev server URL — not auto-discovered yet",
    )


def run_html_validate(ctx) -> ScannerResult:
    binary = _which("html-validate")
    if not binary:
        return _missing_tool_result("html-validate", "html-validate")
    # Look at common HTML output dirs
    candidates = ("dist", "build", "public", ".next", "out")
    target_dir = ""
    for c in candidates:
        full = os.path.join(ctx.repo_path, c)
        if os.path.isdir(full):
            target_dir = full
            break
    if not target_dir:
        return _no_targets_result(
            "html-validate",
            f"no built HTML directory found ({', '.join(candidates)})",
        )
    rc, stdout, stderr = _run(
        [binary, "--formatter=json", target_dir],
        cwd=ctx.repo_path,
    )
    if not stdout:
        return _failed_result("html-validate", stderr.strip()[:500] or f"exit {rc}")
    try:
        items = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("html-validate", f"invalid JSON: {exc}")
    findings = []
    for entry in items:
        path = entry.get("filePath", "")
        for msg in entry.get("messages", []):
            sev_num = msg.get("severity", 1)
            sev = "high" if sev_num >= 2 else "medium"
            rule = msg.get("ruleId", "html-validate")
            findings.append(_make_finding(
                tool="html-validate",
                rule_id=rule,
                title=f"{rule}: {msg.get('message', '')[:120]}",
                severity=sev,
                category="markup",
                file_path=_rel(path, ctx.repo_path),
                line=msg.get("line"),
                description=msg.get("message", ""),
                fix_suggestion="See html-validate docs for this rule.",
                fixable_by_agent=False,
                effort="easy",
            ))
    return ScannerResult(tool="html-validate", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# ADA
# ──────────────────────────────────────────────────────────────────────


def run_axe_core(ctx) -> ScannerResult:
    """axe-core CLI accessibility scan against built HTML files.

    Like lighthouse, axe needs a URL; this adapter scans static HTML
    files in common build dirs instead, which is safer for CI.
    """
    binary = _which("axe")
    if not binary:
        return _missing_tool_result("axe-core", "axe (npm i -g @axe-core/cli)")
    candidates = ("dist", "build", "public", ".next", "out")
    target_dir = ""
    for c in candidates:
        full = os.path.join(ctx.repo_path, c)
        if os.path.isdir(full):
            target_dir = full
            break
    if not target_dir:
        return _no_targets_result(
            "axe-core",
            f"no built HTML directory found ({', '.join(candidates)})",
        )
    rc, stdout, stderr = _run(
        [binary, target_dir, "--save", "/dev/stdout", "--silent"],
        cwd=ctx.repo_path,
        timeout=600,
    )
    if not stdout:
        return _failed_result("axe-core", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("axe-core", f"invalid JSON: {exc}")
    findings = []
    items = payload if isinstance(payload, list) else [payload]
    for page in items:
        page_url = page.get("url", "")
        for v in page.get("violations", []):
            rule_id = v.get("id", "axe.unknown")
            impact_map = {"critical": "critical", "serious": "high",
                          "moderate": "medium", "minor": "low"}
            sev = impact_map.get(v.get("impact", ""), "low")
            description = v.get("description") or v.get("help") or rule_id
            findings.append(_make_finding(
                tool="axe-core",
                rule_id=rule_id,
                title=f"{rule_id}: {description[:120]}",
                severity=sev,
                category="accessibility",
                file_path=page_url,
                line=None,
                description=description,
                fix_suggestion=v.get("helpUrl", ""),
                fixable_by_agent=False,
                effort="moderate",
            ))
    return ScannerResult(tool="axe-core", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Compliance
# ──────────────────────────────────────────────────────────────────────


def run_license_check(ctx) -> ScannerResult:
    """Inventory npm package licenses and flag GPL/AGPL/SSPL-family risk."""
    binary = _which("license-checker")
    if not binary:
        return _missing_tool_result("license-checker", "license-checker (npm i -g)")
    if not os.path.exists(os.path.join(ctx.repo_path, "package.json")):
        return _no_targets_result("license-checker", "no package.json in repo root")
    rc, stdout, _stderr = _run(
        [binary, "--json", "--production"],
        cwd=ctx.repo_path,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if not stdout:
        return _failed_result("license-checker", f"exit {rc}")
    try:
        packages = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("license-checker", f"invalid JSON: {exc}")
    risky = ("GPL", "AGPL", "SSPL", "CDDL", "EUPL")
    findings = []
    for pkg_name, info in packages.items():
        license_str = info.get("licenses", "") or ""
        if isinstance(license_str, list):
            license_str = ", ".join(license_str)
        upper = str(license_str).upper()
        if any(token in upper for token in risky):
            findings.append(_make_finding(
                tool="license-checker",
                rule_id=f"license.{license_str}",
                title=f"Restrictive license: {pkg_name} → {license_str}",
                severity="high",
                category="license",
                file_path="package.json",
                line=None,
                description=(
                    f"{pkg_name} is licensed under {license_str}, which carries "
                    "copyleft / share-alike obligations that may conflict with "
                    "commercial distribution."
                ),
                fix_suggestion=f"Consider replacing {pkg_name} or seeking license-compatible alternative.",
                fixable_by_agent=False,
                effort="hard",
            ))
    return ScannerResult(tool="license-checker", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Cloud-Ops
# ──────────────────────────────────────────────────────────────────────


def run_checkov(ctx) -> ScannerResult:
    """Checkov scans Terraform/Dockerfile/k8s/CI for misconfigurations."""
    binary = _which("checkov")
    if not binary:
        return _missing_tool_result("checkov", "checkov (pip install checkov)")
    rc, stdout, stderr = _run(
        [binary, "-d", ctx.repo_path, "-o", "json", "--quiet", "--compact"],
        cwd=ctx.repo_path,
        timeout=600,
    )
    if not stdout:
        return _failed_result("checkov", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("checkov", f"invalid JSON: {exc}")
    if isinstance(payload, list):
        # Multiple frameworks → list of result objects
        result_blobs = payload
    else:
        result_blobs = [payload]
    findings = []
    sev_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    for blob in result_blobs:
        results = (blob.get("results") or {}).get("failed_checks") or []
        for c in results:
            rule = c.get("check_id", "checkov.unknown")
            sev = sev_map.get(str(c.get("severity") or "").upper(), "medium")
            file_path = _rel(c.get("file_path", "") or c.get("repo_file_path", ""), ctx.repo_path)
            line_range = c.get("file_line_range") or [None]
            line = line_range[0] if line_range else None
            findings.append(_make_finding(
                tool="checkov",
                rule_id=rule,
                title=f"{rule}: {c.get('check_name', '')[:120]}",
                severity=sev,
                category="cloud-misconfig",
                file_path=file_path,
                line=line if isinstance(line, int) else None,
                description=c.get("check_name", ""),
                fix_suggestion=c.get("guideline") or "",
                fixable_by_agent=False,
                effort="moderate",
            ))
    return ScannerResult(tool="checkov", status="ok", findings=findings)


def run_tfsec(ctx) -> ScannerResult:
    binary = _which("tfsec")
    if not binary:
        return _missing_tool_result("tfsec", "tfsec")
    rc, stdout, _stderr = _run(
        [binary, ctx.repo_path, "--format", "json", "--soft-fail"],
        cwd=ctx.repo_path,
        timeout=300,
    )
    if not stdout:
        return _no_targets_result("tfsec", "no terraform files found")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("tfsec", f"invalid JSON: {exc}")
    sev_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    findings = []
    for r in payload.get("results") or []:
        rule = r.get("rule_id", "tfsec.unknown")
        sev = sev_map.get(str(r.get("severity") or "").upper(), "medium")
        loc = r.get("location") or {}
        findings.append(_make_finding(
            tool="tfsec",
            rule_id=rule,
            title=f"{rule}: {r.get('description', '')[:120]}",
            severity=sev,
            category="cloud-misconfig",
            file_path=_rel(loc.get("filename", ""), ctx.repo_path),
            line=loc.get("start_line") if isinstance(loc.get("start_line"), int) else None,
            description=r.get("description", ""),
            fix_suggestion=r.get("resolution", ""),
            fixable_by_agent=False,
            effort="moderate",
        ))
    return ScannerResult(tool="tfsec", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Department dispatch tables
# ──────────────────────────────────────────────────────────────────────


# Maps department → list of tool names whose adapters live above (or in tools.py).
DEPT_TOOLS: dict[str, list[str]] = {
    "seo":        ["lighthouse", "html-validate"],
    "ada":        ["axe-core"],
    "compliance": ["license-checker", "gitleaks"],  # gitleaks is reused from QA
    "cloud-ops":  ["checkov", "tfsec"],
    # monetization, product: AI-only — no deterministic adapters.
}

# Output filename per department, matching aggregate.py's expected filenames.
DEPT_OUTPUT_FILE: dict[str, str] = {
    "seo":        "seo-deterministic-findings.json",
    "ada":        "ada-deterministic-findings.json",
    "compliance": "compliance-deterministic-findings.json",
    "cloud-ops":  "cloud-ops-deterministic-findings.json",
}


# Department → adapter callable. Adapters from this module + reused
# ones from tools.py (gitleaks).
def _dept_dispatch() -> dict[str, callable]:
    from backoffice.scanners.tools import run_gitleaks
    return {
        "lighthouse":      run_lighthouse,
        "html-validate":   run_html_validate,
        "axe-core":        run_axe_core,
        "license-checker": run_license_check,
        "checkov":         run_checkov,
        "tfsec":           run_tfsec,
        "gitleaks":        run_gitleaks,
    }


DEPT_DISPATCH: dict[str, callable] = _dept_dispatch()
