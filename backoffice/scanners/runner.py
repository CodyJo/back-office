"""Scan orchestration + CLI handler.

``run_scan`` discovers applicable tools, runs each, deduplicates the
combined finding set, applies severity filters and a max-finding cap,
then atomically writes ``results/<repo>/qa-deterministic-findings.json``.

A per-repo sidecar lock prevents two concurrent deterministic scans on
the same repo from racing on the output file. We deliberately do *not*
share ``workflow.RUN_LOCK_FILE`` so AI audits and deterministic scans
can run simultaneously.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
import uuid
from pathlib import Path

from backoffice.aggregate import count_severities
from backoffice.scanners import scan_state
from backoffice.scanners.discovery import (
    ScannerContext,
    discover_tools,
)
from backoffice.scanners.severity import (
    SEVERITY_ORDER,
    SEVERITY_RANK,
    meets_min_severity,
)
from backoffice.scanners.tools import (
    SCANNER_DISPATCH,
    ScannerResult,
)
from backoffice.store.atomic import LockFile, atomic_write_json
from backoffice.workflow import iso_now, read_json

logger = logging.getLogger(__name__)

OUTPUT_FILENAME = "qa-deterministic-findings.json"

# Department → output filename. QA stays under the legacy name.
DEPT_OUTPUT_FILES = {
    "qa": OUTPUT_FILENAME,
    "seo": "seo-deterministic-findings.json",
    "ada": "ada-deterministic-findings.json",
    "compliance": "compliance-deterministic-findings.json",
    "cloud-ops": "cloud-ops-deterministic-findings.json",
}


def run_scan(
    repo_name: str,
    repo_path: str,
    language: str,
    results_dir: str,
    *,
    exclude_patterns: list[str] | None = None,
    min_severity: str = "low",
    max_findings: int = 200,
    tools_override: list[str] | None = None,
    out_path: str | None = None,
    force: bool = False,
    department: str = "qa",
) -> dict:
    """Run all applicable deterministic tools and persist the merged result.

    When ``force=False`` (default) and the target's HEAD SHA matches the
    last successful scan, returns the prior payload from disk without
    re-running anything. ``force=True`` always re-scans.

    Returns the written (or cached) payload dict.
    """
    if not os.path.isdir(repo_path):
        raise ValueError(f"repo_path does not exist or is not a directory: {repo_path}")

    output_filename = DEPT_OUTPUT_FILES.get(department, OUTPUT_FILENAME)
    scope = f"{department}-deterministic"

    if not force:
        skip, reason = scan_state.should_skip(
            results_dir, target=repo_name, scope=scope, repo_path=repo_path,
        )
        if skip:
            cached_path = Path(out_path) if out_path else Path(results_dir) / repo_name / output_filename
            cached = read_json(str(cached_path)) if cached_path.exists() else None
            if cached:
                logger.info("Skipped %s/%s: %s (use force=True to re-scan)", repo_name, department, reason)
                return cached

    if department != "qa":
        # Use department-specific dispatch table.
        from backoffice.scanners.dept_tools import DEPT_DISPATCH, DEPT_TOOLS
        tools = list(tools_override) if tools_override else DEPT_TOOLS.get(department, [])
        runners_table = DEPT_DISPATCH
    else:
        tools = list(tools_override) if tools_override else discover_tools(repo_path, language)
        runners_table = SCANNER_DISPATCH
    ctx = ScannerContext(
        repo_name=repo_name,
        repo_path=repo_path,
        language=language,
        tools=tools,
        exclude_patterns=list(exclude_patterns or []),
        min_severity=min_severity,
        max_findings=max_findings,
    )

    repo_results_dir = Path(results_dir) / repo_name
    repo_results_dir.mkdir(parents=True, exist_ok=True)
    target_path = Path(out_path) if out_path else repo_results_dir / output_filename
    lock_path = repo_results_dir / f".det-scan-{department}.lock"

    started = time.monotonic()
    try:
        with LockFile(lock_path, blocking=False):
            results = _run_all_tools(tools, ctx, runners_table)
    except BlockingIOError as exc:
        raise RuntimeError(
            f"Another deterministic scan is already running for {repo_name}/{department} "
            f"(lock held: {lock_path})"
        ) from exc

    payload = _build_payload(
        repo_name=repo_name,
        repo_path=repo_path,
        results=results,
        min_severity=min_severity,
        max_findings=max_findings,
        duration_seconds=int(time.monotonic() - started),
    )
    # Optional Haiku triage (off by default; enabled via scan.haiku_triage in config)
    try:
        from backoffice.config import load_config
        from backoffice.scanners.triage import is_enabled as triage_enabled
        from backoffice.scanners.triage import triage_payload
        cfg = load_config()
        if triage_enabled(cfg.scan):
            payload = triage_payload(payload, target=repo_name)
    except Exception:
        logger.exception("Haiku triage failed (non-fatal)")

    atomic_write_json(target_path, payload)
    logger.info(
        "Wrote %s (%d findings across %d tools, %d skipped)",
        target_path,
        payload["summary"]["total"],
        payload["summary"]["tools_run"],
        payload["summary"]["tools_skipped"],
    )
    sha = scan_state.head_sha(repo_path)
    if sha:
        scan_state.update(
            results_dir,
            target=repo_name,
            scope=scope,
            sha=sha,
            finding_count=payload["summary"]["total"],
        )
    return payload


def _run_all_tools(
    tools: list[str],
    ctx: ScannerContext,
    runners_table: dict | None = None,
) -> list[ScannerResult]:
    """Run each tool sequentially. Unknown tool names are skipped with a log warning."""
    table = runners_table or SCANNER_DISPATCH
    results: list[ScannerResult] = []
    for name in tools:
        runner = table.get(name)
        if runner is None:
            logger.warning("scanner %r is not registered — skipping", name)
            continue
        try:
            results.append(runner(ctx))
        except Exception as exc:
            logger.exception("scanner %s raised", name)
            results.append(ScannerResult(
                tool=name,
                status="failed",
                findings=[],
                error=f"{type(exc).__name__}: {exc}",
            ))
    return results


def _build_payload(
    *,
    repo_name: str,
    repo_path: str,
    results: list[ScannerResult],
    min_severity: str,
    max_findings: int,
    duration_seconds: int,
) -> dict:
    """Merge, dedup, filter, cap, and return the payload to persist.

    Intra-scan dedup is by ``id``: each adapter builds an id encoding
    (tool, rule, file, line), so two hits of the same rule on the same
    file at different lines are kept distinct. The looser
    ``finding_hash`` dedup happens separately in ``aggregate_qa`` where
    we want fuzzy match against AI-produced findings.
    """
    merged: list[dict] = []
    seen_ids: set[str] = set()
    status_findings: list[dict] = []  # always-included scanner-status entries

    for result in results:
        for f in result.findings:
            if f.get("category") == "scanner-status":
                status_findings.append(f)
                continue
            if not meets_min_severity(f.get("severity", "info"), min_severity):
                continue
            fid = f.get("id", "")
            if fid and fid in seen_ids:
                continue
            if fid:
                seen_ids.add(fid)
            merged.append(f)

    # Sort by severity (critical first), then cap.
    merged.sort(key=lambda f: SEVERITY_RANK.get(f.get("severity", "info"), 99))
    if len(merged) > max_findings:
        logger.info(
            "Capping %s findings at max_findings=%d (dropping %d lowest-severity)",
            repo_name, max_findings, len(merged) - max_findings,
        )
        merged = merged[:max_findings]

    # Status findings always included, after capped real findings — they
    # are diagnostic metadata about coverage, not findings against the repo,
    # so they're excluded from severity totals.
    final_findings = merged + status_findings

    real_sev_counts = count_severities(merged)
    summary = {
        "total": len(merged),
        **{level: real_sev_counts[level] for level in SEVERITY_ORDER},
        "tools_run": sum(1 for r in results if r.status == "ok"),
        "tools_skipped": sum(1 for r in results if r.status != "ok"),
        "scanner_status_count": len(status_findings),
    }

    return {
        "scan_id": str(uuid.uuid4()),
        "repo_name": repo_name,
        "repo_path": repo_path,
        "scanned_at": iso_now(),
        "scan_duration_seconds": duration_seconds,
        "scanner": "deterministic",
        "tools_run": [r.tool for r in results if r.status == "ok"],
        "tools_unavailable": [r.tool for r in results if r.status == "skipped_missing_tool"],
        "scanner_status": [
            {
                "tool": r.tool,
                "status": r.status,
                "tool_version": r.tool_version,
                "finding_count": sum(1 for f in r.findings if f.get("category") != "scanner-status"),
                "error": r.error,
            }
            for r in results
        ],
        "summary": summary,
        "findings": final_findings,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI handler (registered in backoffice/__main__.py)
# ──────────────────────────────────────────────────────────────────────


def handle_scan_cli(args: argparse.Namespace) -> int:
    """``python -m backoffice scan <target>`` entry point."""
    from backoffice.config import load_config

    cfg = load_config()
    target = cfg.targets.get(args.target)
    if target is None:
        print(f"Unknown target: {args.target!r}. Run `python -m backoffice list-targets`.", flush=True)
        return 1
    if not target.path or not os.path.isdir(target.path):
        print(f"Target {args.target} path does not exist: {target.path!r}", flush=True)
        return 1

    results_dir = str(cfg.root / "results")
    tools_override: list[str] | None = None
    if getattr(args, "tools", None):
        tools_override = [t.strip() for t in args.tools.split(",") if t.strip()]

    if getattr(args, "dry_run", False):
        from backoffice.scanners.discovery import discover_tools as _disc
        tools = tools_override or _disc(target.path, target.language)
        print(f"Would run on {args.target} ({target.path}): {', '.join(tools)}")
        return 0

    min_sev = getattr(args, "min_severity", None) or cfg.scan.min_severity
    max_findings = getattr(args, "max_findings", None) or cfg.scan.max_findings

    try:
        payload = run_scan(
            repo_name=args.target,
            repo_path=target.path,
            language=target.language,
            results_dir=results_dir,
            exclude_patterns=list(cfg.scan.exclude_patterns),
            min_severity=min_sev,
            max_findings=max_findings,
            tools_override=tools_override,
            out_path=getattr(args, "out", None),
            force=getattr(args, "force", False),
            department=getattr(args, "department", "qa"),
        )
    except RuntimeError as exc:
        print(str(exc), flush=True)
        return 1

    summary = payload["summary"]
    status_note = (
        f" + {summary['scanner_status_count']} scanner-status note(s)"
        if summary.get("scanner_status_count")
        else ""
    )
    print(
        f"Scanned {args.target}: {summary['total']} findings "
        f"({summary['critical']}C/{summary['high']}H/{summary['medium']}M/"
        f"{summary['low']}L/{summary['info']}I){status_note} — "
        f"{summary['tools_run']} tools ok, {summary['tools_skipped']} skipped."
    )
    return 0
