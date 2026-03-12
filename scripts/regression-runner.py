#!/usr/bin/env python3
"""
Portfolio regression runner for Back Office.

Runs each configured target's regression test command (from config/targets.yaml),
attempts to collect coverage, and writes:

- results/regression/<run_id>/regression.json (full machine-readable results)
- results/regression/<run_id>/<target>/stdout.log / stderr.log (raw logs)
- dashboard/regression-data.json (latest run summary for dashboards)

Design goals:
- No repo-specific coupling beyond targets.yaml
- Coverage is best-effort: if unavailable, we record why and still run tests
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import yaml


QA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS_PATH = os.path.join(QA_ROOT, "config", "targets.yaml")
RESULTS_ROOT = os.path.join(QA_ROOT, "results", "regression")
DASHBOARD_DIR = os.path.join(QA_ROOT, "dashboard")
DASHBOARD_OUT = os.path.join(DASHBOARD_DIR, "regression-data.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
        f.write("\n")


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class CmdResult:
    cmd: str
    cwd: str
    exit_code: int
    duration_ms: int
    stdout_path: str
    stderr_path: str


def run_cmd(cmd: str, cwd: str, out_dir: str, label: str, timeout_s: int) -> CmdResult:
    safe_mkdir(out_dir)
    stdout_path = os.path.join(out_dir, f"{label}.stdout.log")
    stderr_path = os.path.join(out_dir, f"{label}.stderr.log")

    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ},
    )
    dur_ms = int((time.time() - start) * 1000)

    write_text(stdout_path, proc.stdout or "")
    write_text(stderr_path, proc.stderr or "")

    return CmdResult(
        cmd=cmd,
        cwd=cwd,
        exit_code=int(proc.returncode),
        duration_ms=dur_ms,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def try_read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_pytest_cov_json(path: str) -> dict | None:
    data = try_read_json(path)
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return None
    pct = totals.get("percent_covered")
    if not isinstance(pct, (int, float)):
        return None
    return {
        "tool": "pytest-cov",
        "format": "coverage-json",
        "percent": float(pct),
    }


def parse_vitest_coverage_summary(path: str) -> dict | None:
    data = try_read_json(path)
    if not isinstance(data, dict):
        return None
    total = data.get("total")
    if not isinstance(total, dict):
        return None

    # v8 summary shape: { total: { lines: { pct }, statements: { pct }, functions: { pct }, branches: { pct } }, ... }
    lines = total.get("lines", {})
    pct = lines.get("pct") if isinstance(lines, dict) else None
    if not isinstance(pct, (int, float)):
        return None
    return {
        "tool": "vitest",
        "format": "coverage-summary-json",
        "percent": float(pct),
    }

def parse_lcov_percent(path: str) -> dict | None:
    """
    Parse LCOV and compute line coverage percent from LH/LF totals.
    """
    try:
        lf = 0
        lh = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("LF:"):
                    try:
                        lf += int(line.split(":", 1)[1])
                    except Exception:
                        continue
                elif line.startswith("LH:"):
                    try:
                        lh += int(line.split(":", 1)[1])
                    except Exception:
                        continue
        if lf <= 0:
            return None
        return {
            "tool": "vitest",
            "format": "lcov",
            "percent": (lh / lf) * 100.0,
        }
    except Exception:
        return None


def best_effort_coverage(target: dict, target_dir: str, run_dir: str, timeout_s: int) -> tuple[dict | None, list[CmdResult]]:
    """
    Attempt coverage run. Returns (coverage_summary, cmd_results).
    If coverage can't be collected, returns (None, cmd_results) and runner should run normal tests.
    """
    lang = str(target.get("language") or "")
    coverage_cmd = str(target.get("coverage_command") or "").strip()
    test_cmd = str(target.get("test_command") or "").strip()
    results: list[CmdResult] = []

    # Explicit coverage command wins and allows repos with non-default stacks
    # (for example Astro + Vitest) to participate in regression coverage.
    if coverage_cmd:
        try:
            r = run_cmd(coverage_cmd, cwd=target_dir, out_dir=run_dir, label="coverage", timeout_s=timeout_s)
            results.append(r)
            if r.exit_code == 0:
                summary_path = os.path.join(target_dir, "coverage", "coverage-summary.json")
                cov = parse_vitest_coverage_summary(summary_path)
                if cov:
                    return cov, results
                lcov_path = os.path.join(target_dir, "coverage", "lcov.info")
                cov = parse_lcov_percent(lcov_path)
                if cov:
                    return cov, results
                cov_json = os.path.join(target_dir, "coverage.json")
                cov = parse_pytest_cov_json(cov_json)
                if cov:
                    return cov, results
        except subprocess.TimeoutExpired:
            pass
        return None, results

    # Python: try pytest-cov JSON report.
    if lang == "python":
        cov_json = os.path.join(run_dir, "coverage.json")
        cov_cmd = f"python3 -m pytest --cov=. --cov-report=json:{cov_json} --cov-report=term"
        try:
            r = run_cmd(cov_cmd, cwd=target_dir, out_dir=run_dir, label="coverage", timeout_s=timeout_s)
            results.append(r)
            if r.exit_code == 0:
                cov = parse_pytest_cov_json(cov_json)
                if cov:
                    return cov, results
        except subprocess.TimeoutExpired:
            pass
        return None, results

    # TypeScript: try vitest coverage (expects a script in package.json).
    if lang == "typescript":
        # Prefer explicit project script so repos can control providers/reporters.
        cov_cmd = "npm run test:coverage"
        try:
            r = run_cmd(cov_cmd, cwd=target_dir, out_dir=run_dir, label="coverage", timeout_s=timeout_s)
            results.append(r)
            if r.exit_code == 0:
                summary_path = os.path.join(target_dir, "coverage", "coverage-summary.json")
                cov = parse_vitest_coverage_summary(summary_path)
                if cov:
                    return cov, results
                lcov_path = os.path.join(target_dir, "coverage", "lcov.info")
                cov2 = parse_lcov_percent(lcov_path)
                if cov2:
                    return cov2, results
        except subprocess.TimeoutExpired:
            pass
        return None, results

    # Unknown: no coverage
    _ = test_cmd
    return None, results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=TARGETS_PATH)
    ap.add_argument("--out", default=RESULTS_ROOT)
    ap.add_argument("--dashboard-out", default=DASHBOARD_OUT)
    ap.add_argument("--only", default="", help="comma-separated target names (optional)")
    ap.add_argument("--timeout-seconds", type=int, default=60 * 20, help="per-command timeout")
    args = ap.parse_args()

    cfg = load_yaml(args.targets)
    targets = cfg.get("targets", [])
    if not isinstance(targets, list) or not targets:
        print("No targets found in targets.yaml", file=sys.stderr)
        return 2

    only = [s.strip() for s in str(args.only).split(",") if s.strip()]
    if only:
        targets = [t for t in targets if t.get("name") in only]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = os.path.join(args.out, run_id)
    safe_mkdir(run_root)

    run_started = utc_now_iso()
    run_summary: dict[str, Any] = {
        "run_id": run_id,
        "started_at": run_started,
        "finished_at": None,
        "targets_total": len(targets),
        "targets_passed": 0,
        "targets_failed": 0,
        "targets": [],
    }

    for t in targets:
        name = str(t.get("name") or "").strip()
        repo_dir = str(t.get("path") or "").strip()
        test_cmd = str(t.get("test_command") or "").strip()
        if not name or not repo_dir or not test_cmd:
            continue

        target_run_dir = os.path.join(run_root, name)
        safe_mkdir(target_run_dir)

        target_record: dict[str, Any] = {
            "name": name,
            "path": repo_dir,
            "language": t.get("language"),
            "started_at": utc_now_iso(),
            "finished_at": None,
            "status": "unknown",
            "test": None,
            "coverage": None,
            "coverage_attempts": [],
        }

        # 1) Coverage attempt
        cov, cov_cmds = best_effort_coverage(t, repo_dir, target_run_dir, args.timeout_seconds)
        target_record["coverage_attempts"] = [c.__dict__ for c in cov_cmds]
        if cov:
            target_record["coverage"] = cov

        # 2) Always run configured regression command (source of truth)
        try:
            test_res = run_cmd(test_cmd, cwd=repo_dir, out_dir=target_run_dir, label="test", timeout_s=args.timeout_seconds)
            target_record["test"] = test_res.__dict__
            target_record["status"] = "passed" if test_res.exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            target_record["status"] = "failed"
            target_record["test"] = {
                "cmd": test_cmd,
                "cwd": repo_dir,
                "exit_code": 124,
                "duration_ms": args.timeout_seconds * 1000,
                "stdout_path": os.path.join(target_run_dir, "test.stdout.log"),
                "stderr_path": os.path.join(target_run_dir, "test.stderr.log"),
            }
            write_text(target_record["test"]["stdout_path"], "")
            write_text(target_record["test"]["stderr_path"], f"TIMEOUT after {args.timeout_seconds}s\n")

        target_record["finished_at"] = utc_now_iso()
        if target_record["status"] == "passed":
            run_summary["targets_passed"] += 1
        else:
            run_summary["targets_failed"] += 1

        run_summary["targets"].append(target_record)

    run_summary["finished_at"] = utc_now_iso()

    # Write run artifact
    write_json(os.path.join(run_root, "regression.json"), run_summary)

    # Write dashboard “latest” payload (summary only + pointers)
    dashboard_payload = {
        "generated_at": utc_now_iso(),
        "latest_run": run_summary,
        # Use a stable dashboard-relative path that works both in the local
        # HTTP server (rooted at QA_ROOT) and when deployed to dashboard S3 roots.
        "runs_dir": "results/regression",
    }
    safe_mkdir(os.path.dirname(args.dashboard_out))
    write_json(args.dashboard_out, dashboard_payload)

    print(f"Wrote regression run: {run_root}")
    print(f"Wrote dashboard payload: {args.dashboard_out}")
    return 0 if run_summary["targets_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
