"""Per-tool adapter functions.

Each adapter has the same shape: take a :class:`ScannerContext`, run a
subprocess, parse output into raw canonical-schema finding dicts, return
a :class:`ScannerResult`. Findings are pre-normalized (severity already
canonical, ``trust_class="objective"`` already set) so they can flow
straight through ``aggregate_qa``'s existing ``normalize_finding`` pass.

If a tool binary is missing, the adapter emits one ``info`` finding with
``category="scanner-status"`` so the dashboard surfaces the coverage
gap. ``run_scan`` deliberately bypasses ``meets_min_severity`` for
status findings to ensure they always appear.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from backoffice.scanners.severity import (
    BANDIT_SEVERITY,
    GITLEAKS_SEVERITY_DEFAULT,
    NPM_AUDIT_SEVERITY,
    PIP_AUDIT_SEVERITY_DEFAULT,
    SEMGREP_SEVERITY,
    canonicalize_severity,
    ruff_category,
    ruff_severity,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300


@dataclass
class ScannerResult:
    """Output of one tool adapter run."""
    tool: str
    status: str  # "ok" | "skipped_missing_tool" | "skipped_no_targets" | "failed"
    findings: list[dict] = field(default_factory=list)
    error: str = ""
    tool_version: str = ""


# ──────────────────────────────────────────────────────────────────────
# Subprocess helpers
# ──────────────────────────────────────────────────────────────────────


def _which(binary: str) -> str | None:
    """Return absolute path to *binary* or None."""
    return shutil.which(binary)


def _run(
    cmd: list[str],
    cwd: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """Run *cmd* in *cwd*. Returns ``(returncode, stdout, stderr)``.

    Never raises on non-zero exit. ``CalledProcessError`` would obscure
    parseable JSON that many of these tools emit even on findings (e.g.
    ruff, gitleaks both exit non-zero when findings exist).
    """
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _missing_tool_result(tool: str, binary: str) -> ScannerResult:
    return ScannerResult(
        tool=tool,
        status="skipped_missing_tool",
        findings=[_status_finding(tool, f"{binary} not installed — skipped")],
        error=f"{binary} not in PATH",
    )


def _failed_result(tool: str, message: str) -> ScannerResult:
    return ScannerResult(
        tool=tool,
        status="failed",
        findings=[_status_finding(tool, f"{tool} failed: {message}")],
        error=message,
    )


def _no_targets_result(tool: str, reason: str) -> ScannerResult:
    return ScannerResult(
        tool=tool,
        status="skipped_no_targets",
        findings=[],
        error=reason,
    )


def _status_finding(tool: str, message: str) -> dict:
    """Build an info-severity scanner-status finding."""
    return {
        "id": f"DET-{tool}-status",
        "title": message,
        "severity": "info",
        "category": "scanner-status",
        "file": "",
        "line": None,
        "description": message,
        "evidence": "",
        "fix_suggestion": f"Install {tool} on the scanner host to restore coverage.",
        "fixable_by_agent": False,
        "effort": "easy",
        "trust_class": "objective",
        "source_tool": tool,
        "rule_id": f"{tool}.unavailable",
    }


def _make_finding(
    *,
    tool: str,
    rule_id: str,
    title: str,
    severity: str,
    category: str,
    file_path: str,
    line: int | None,
    description: str,
    evidence: str = "",
    fix_suggestion: str = "",
    fixable_by_agent: bool = False,
    effort: str = "easy",
) -> dict:
    """Build a canonical-schema finding dict."""
    fid = f"DET-{tool}-{_slug(rule_id)}-{_slug(file_path)}-{line or 0}"
    return {
        "id": fid,
        "title": title,
        "severity": severity,
        "category": category,
        "file": file_path,
        "line": line,
        "description": description,
        "evidence": evidence,
        "fix_suggestion": fix_suggestion,
        "fixable_by_agent": bool(fixable_by_agent),
        "effort": effort,
        "trust_class": "objective",
        "source_tool": tool,
        "rule_id": rule_id,
    }


def _slug(value: str) -> str:
    """Tiny slugifier for finding IDs (keeps them URL-safe and short)."""
    out = []
    for ch in (value or "")[:40]:
        out.append(ch if ch.isalnum() or ch in "-_." else "-")
    return "".join(out).strip("-") or "x"


def _rel(path: str, repo_path: str) -> str:
    """Return *path* relative to *repo_path* if possible, else *path*."""
    if not path:
        return ""
    try:
        return os.path.relpath(path, repo_path)
    except ValueError:
        return path


# ──────────────────────────────────────────────────────────────────────
# Adapter: ruff (Python lint + flake8-bandit)
# ──────────────────────────────────────────────────────────────────────


def run_ruff(ctx) -> ScannerResult:
    binary = _which("ruff")
    if not binary:
        return _missing_tool_result("ruff", "ruff")
    rc, stdout, stderr = _run(
        [binary, "check", "--output-format=json", "--exit-zero", ctx.repo_path],
        cwd=ctx.repo_path,
    )
    if rc not in (0, 1) and not stdout:
        return _failed_result("ruff", stderr.strip()[:500] or f"exit {rc}")
    try:
        items = json.loads(stdout) if stdout else []
    except json.JSONDecodeError as exc:
        return _failed_result("ruff", f"invalid JSON: {exc}")

    findings: list[dict] = []
    for item in items:
        code = item.get("code") or "unknown"
        message = item.get("message", "")
        loc = item.get("location") or {}
        line = loc.get("row")
        file_path = _rel(item.get("filename", ""), ctx.repo_path)
        fix_obj = item.get("fix")
        fixable = bool(fix_obj)
        findings.append(_make_finding(
            tool="ruff",
            rule_id=code,
            title=f"{code} {message}".strip(),
            severity=ruff_severity(code),
            category=ruff_category(code),
            file_path=file_path,
            line=line if isinstance(line, int) else None,
            description=message,
            fix_suggestion="ruff --fix can apply this automatically." if fixable else "",
            fixable_by_agent=fixable,
            effort="easy",
        ))
    return ScannerResult(tool="ruff", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Adapter: bandit (Python security)
# ──────────────────────────────────────────────────────────────────────


def run_bandit(ctx) -> ScannerResult:
    binary = _which("bandit")
    if not binary:
        return _missing_tool_result("bandit", "bandit")
    rc, stdout, stderr = _run(
        [binary, "-r", ctx.repo_path, "-f", "json", "-q"],
        cwd=ctx.repo_path,
    )
    if rc not in (0, 1) and not stdout:
        return _failed_result("bandit", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        return _failed_result("bandit", f"invalid JSON: {exc}")

    findings: list[dict] = []
    for item in payload.get("results", []):
        sev_raw = item.get("issue_severity", "LOW")
        conf = item.get("issue_confidence", "LOW")
        canonical = canonicalize_severity(sev_raw, BANDIT_SEVERITY)
        # Boost LOW + HIGH-confidence to medium — bandit's confidence is
        # a useful tiebreaker.
        if canonical == "low" and str(conf).upper() == "HIGH":
            canonical = "medium"
        rule_id = item.get("test_id") or "B000"
        message = item.get("issue_text", "") or rule_id
        findings.append(_make_finding(
            tool="bandit",
            rule_id=rule_id,
            title=f"{rule_id}: {message}",
            severity=canonical,
            category="security",
            file_path=_rel(item.get("filename", ""), ctx.repo_path),
            line=item.get("line_number"),
            description=message,
            evidence=item.get("code", "") or "",
            fix_suggestion="",
            fixable_by_agent=False,
            effort="moderate",
        ))
    return ScannerResult(tool="bandit", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Adapter: pip-audit (Python dependency CVEs)
# ──────────────────────────────────────────────────────────────────────


def run_pip_audit(ctx) -> ScannerResult:
    binary = _which("pip-audit")
    if not binary:
        return _missing_tool_result("pip-audit", "pip-audit")

    has_target = (
        os.path.exists(os.path.join(ctx.repo_path, "pyproject.toml"))
        or os.path.exists(os.path.join(ctx.repo_path, "Pipfile"))
        or any(
            f.startswith("requirements") and f.endswith(".txt")
            for f in os.listdir(ctx.repo_path)
            if os.path.isfile(os.path.join(ctx.repo_path, f))
        )
    )
    if not has_target:
        return _no_targets_result(
            "pip-audit",
            "no pyproject.toml / requirements*.txt / Pipfile in repo root",
        )

    rc, stdout, stderr = _run(
        [binary, "--format", "json", "--progress-spinner", "off"],
        cwd=ctx.repo_path,
    )
    if rc not in (0, 1) and not stdout:
        return _failed_result("pip-audit", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        return _failed_result("pip-audit", f"invalid JSON: {exc}")

    findings: list[dict] = []
    deps = payload.get("dependencies") if isinstance(payload, dict) else payload
    for dep in deps or []:
        name = dep.get("name", "?")
        version = dep.get("version", "?")
        for vuln in dep.get("vulns", []) or []:
            vid = vuln.get("id", "PYSEC-?")
            fix_versions = vuln.get("fix_versions") or []
            description = vuln.get("description", "") or ""
            fix = (
                f"Upgrade {name} from {version} to {fix_versions[0]} (or later)."
                if fix_versions
                else f"No fixed version available for {name}=={version}."
            )
            findings.append(_make_finding(
                tool="pip-audit",
                rule_id=vid,
                title=f"{vid}: {name} {version} vulnerable",
                severity=PIP_AUDIT_SEVERITY_DEFAULT,
                category="security",
                file_path="pyproject.toml",
                line=None,
                description=description[:1000] or f"{name} {version} flagged by pip-audit.",
                fix_suggestion=fix,
                fixable_by_agent=bool(fix_versions),
                effort="easy" if fix_versions else "moderate",
            ))
    return ScannerResult(tool="pip-audit", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Adapter: npm audit (JS/TS dependency CVEs)
# ──────────────────────────────────────────────────────────────────────


def run_npm_audit(ctx) -> ScannerResult:
    binary = _which("npm")
    if not binary:
        return _missing_tool_result("npm-audit", "npm")
    if not os.path.exists(os.path.join(ctx.repo_path, "package.json")):
        return _no_targets_result("npm-audit", "no package.json in repo root")

    rc, stdout, stderr = _run(
        [binary, "audit", "--json"],
        cwd=ctx.repo_path,
    )
    if not stdout:
        return _failed_result("npm-audit", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("npm-audit", f"invalid JSON: {exc}")

    # npm v7+ shape only. v6's `advisories` shape has been EOL since 2022;
    # if a Phase-2 target turns out to need it, add a fallback then.
    findings: list[dict] = []
    vulns = payload.get("vulnerabilities") or {}
    for pkg_name, info in vulns.items():
        sev_raw = info.get("severity", "low")
        canonical = canonicalize_severity(sev_raw, NPM_AUDIT_SEVERITY)
        fix_avail = info.get("fixAvailable")
        fixable = bool(fix_avail) and fix_avail is not False
        via = info.get("via", [])
        via_titles = []
        for v in via if isinstance(via, list) else [via]:
            if isinstance(v, dict):
                title = v.get("title") or v.get("source") or v.get("name")
                if title:
                    via_titles.append(str(title))
        title_summary = "; ".join(via_titles[:3]) if via_titles else f"{pkg_name} vulnerable"
        findings.append(_make_finding(
            tool="npm-audit",
            rule_id=pkg_name,
            title=f"{pkg_name}: {title_summary}",
            severity=canonical,
            category="security",
            file_path="package.json",
            line=None,
            description=f"npm audit flagged {pkg_name} (severity={sev_raw}).",
            fix_suggestion="Run `npm audit fix`." if fixable else f"No automatic fix for {pkg_name}.",
            fixable_by_agent=fixable,
            effort="easy" if fixable else "moderate",
        ))
    return ScannerResult(tool="npm-audit", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Adapter: semgrep (multi-language security + code-quality)
# ──────────────────────────────────────────────────────────────────────


def run_semgrep(ctx) -> ScannerResult:
    binary = _which("semgrep")
    if not binary:
        return _missing_tool_result("semgrep", "semgrep")
    # No --error: that flag means "exit 1 if any findings", which inverts the
    # signal we use to distinguish a real subprocess failure from "found stuff".
    rc, stdout, stderr = _run(
        [binary, "scan", "--config", "auto", "--json", "--quiet", ctx.repo_path],
        cwd=ctx.repo_path,
    )
    if not stdout:
        return _failed_result("semgrep", stderr.strip()[:500] or f"exit {rc}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_result("semgrep", f"invalid JSON: {exc}")

    findings: list[dict] = []
    for item in payload.get("results", []):
        rule_id = item.get("check_id", "semgrep.unknown")
        extra = item.get("extra") or {}
        sev_raw = extra.get("severity", "INFO")
        canonical = canonicalize_severity(sev_raw, SEMGREP_SEVERITY)
        message = extra.get("message", "") or rule_id
        category = "security" if _looks_security(rule_id) else "code-quality"
        start = item.get("start") or {}
        findings.append(_make_finding(
            tool="semgrep",
            rule_id=rule_id,
            title=f"{rule_id}: {message[:120]}",
            severity=canonical,
            category=category,
            file_path=_rel(item.get("path", ""), ctx.repo_path),
            line=start.get("line"),
            description=message,
            evidence=(extra.get("lines") or "")[:500],
            fix_suggestion=extra.get("fix") or "",
            fixable_by_agent=bool(extra.get("fix")),
            effort="easy" if extra.get("fix") else "moderate",
        ))
    return ScannerResult(tool="semgrep", status="ok", findings=findings)


_SECURITY_TOKENS = (
    "security", "secret", "auth", "crypto", "injection", "xss", "sqli",
    "ssrf", "csrf", "deserializ", "path-traversal", "open-redirect",
    "command-injection", "hardcoded",
)


def _looks_security(rule_id: str) -> bool:
    rid = (rule_id or "").lower()
    return any(token in rid for token in _SECURITY_TOKENS)


# ──────────────────────────────────────────────────────────────────────
# Adapter: gitleaks (committed secrets)
# ──────────────────────────────────────────────────────────────────────


def run_gitleaks(ctx) -> ScannerResult:
    binary = _which("gitleaks")
    if not binary:
        return _missing_tool_result("gitleaks", "gitleaks")
    # No --report-path: gitleaks writes the JSON report to stdout when
    # --report-format=json and no path is set. Passing /dev/stdout breaks
    # silently on macOS where gitleaks opens it as a real file.
    rc, stdout, stderr = _run(
        [
            binary, "detect",
            "--source", ctx.repo_path,
            "--report-format", "json",
            "--no-banner", "--exit-code", "0",
        ],
        cwd=ctx.repo_path,
    )
    if rc not in (0, 1):
        return _failed_result("gitleaks", stderr.strip()[:500] or f"exit {rc}")
    try:
        items = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as exc:
        return _failed_result("gitleaks", f"invalid JSON: {exc}")

    findings: list[dict] = []
    for item in items:
        rule_id = item.get("RuleID", "gitleaks.secret")
        description = item.get("Description") or rule_id
        file_path = item.get("File", "")
        line = item.get("StartLine")
        commit = item.get("Commit", "")[:8]
        title = f"Secret detected: {description}"
        if commit:
            title += f" (commit {commit})"
        findings.append(_make_finding(
            tool="gitleaks",
            rule_id=rule_id,
            title=title,
            severity=GITLEAKS_SEVERITY_DEFAULT,
            category="security",
            file_path=file_path,
            line=line if isinstance(line, int) else None,
            description=description,
            evidence="(secret redacted)",
            fix_suggestion=(
                "Rotate the leaked credential immediately, then remove it from "
                "git history (git filter-repo / BFG) and add it to .gitignore."
            ),
            fixable_by_agent=False,
            effort="hard",
        ))
    return ScannerResult(tool="gitleaks", status="ok", findings=findings)


# ──────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────


Scanner = Callable[[object], ScannerResult]

SCANNER_DISPATCH: dict[str, Scanner] = {
    "ruff":      run_ruff,
    "bandit":    run_bandit,
    "pip-audit": run_pip_audit,
    "npm-audit": run_npm_audit,
    "semgrep":   run_semgrep,
    "gitleaks":  run_gitleaks,
}
