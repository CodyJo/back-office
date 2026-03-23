"""Portfolio regression runner for Back Office.

Runs each configured target's regression test command (from Config.targets),
attempts to collect coverage, and writes:

- results/regression/<run_id>/regression.json  (full machine-readable results)
- results/regression/<run_id>/<target>/stdout.log / stderr.log  (raw logs)
- dashboard/regression-data.json  (latest run summary for dashboards)

Design goals:
- No repo-specific coupling beyond Config.targets
- Coverage is best-effort: if unavailable, we record why and still run tests
- Use Config.targets dict instead of loading targets.yaml directly
- Accepts explicit path overrides for backward-compat with CLI callers
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path defaults — resolved relative to the package root
# ---------------------------------------------------------------------------

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_RESULTS_ROOT = _PACKAGE_ROOT / "results" / "regression"
_DEFAULT_DASHBOARD_DIR = _PACKAGE_ROOT / "dashboard"
_DEFAULT_DASHBOARD_OUT = _DEFAULT_DASHBOARD_DIR / "regression-data.json"


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_mkdir(path: str | Path) -> None:
    os.makedirs(path, exist_ok=True)


def write_text(path: str | Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json(path: str | Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


@dataclass
class CmdResult:
    cmd: str
    cwd: str
    exit_code: int
    duration_ms: int
    stdout_path: str
    stderr_path: str


def run_cmd(cmd: str, cwd: str, out_dir: str, label: str, timeout_s: int) -> CmdResult:
    """Run *cmd* in *cwd*, write stdout/stderr to *out_dir*, return CmdResult.

    Raises subprocess.TimeoutExpired if the command exceeds *timeout_s*.
    """
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


# ---------------------------------------------------------------------------
# Coverage parsers
# ---------------------------------------------------------------------------


def try_read_json(path: str | Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def parse_pytest_cov_json(path: str | Path) -> dict | None:
    """Parse a coverage.json produced by pytest-cov --cov-report=json.

    Returns ``{"tool": "pytest-cov", "format": "coverage-json", "percent": float}``
    or *None* if the file is absent or structurally wrong.
    """
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


def parse_vitest_coverage_summary(path: str | Path) -> dict | None:
    """Parse a vitest/c8 coverage-summary.json.

    Shape: ``{ total: { lines: { pct }, statements: { pct }, ... }, ... }``

    Returns ``{"tool": "vitest", "format": "coverage-summary-json", "percent": float}``
    or *None*.
    """
    data = try_read_json(path)
    if not isinstance(data, dict):
        return None
    total = data.get("total")
    if not isinstance(total, dict):
        return None
    lines = total.get("lines", {})
    pct = lines.get("pct") if isinstance(lines, dict) else None
    if not isinstance(pct, (int, float)):
        return None
    return {
        "tool": "vitest",
        "format": "coverage-summary-json",
        "percent": float(pct),
    }


def parse_lcov_percent(path: str | Path) -> dict | None:
    """Parse an LCOV file and compute line-coverage percent from LH/LF totals.

    Returns ``{"tool": "vitest", "format": "lcov", "percent": float}`` or *None*.
    """
    try:
        lf = 0
        lh = 0
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
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


# ---------------------------------------------------------------------------
# best_effort_coverage
# ---------------------------------------------------------------------------


def best_effort_coverage(
    target: dict,
    target_dir: str,
    run_dir: str,
    timeout_s: int,
) -> tuple[dict | None, list[CmdResult]]:
    """Attempt coverage collection for *target*.

    Returns ``(coverage_summary, cmd_results)``.  If coverage cannot be
    collected, returns ``(None, cmd_results)``; the caller should still run
    the configured test command.
    """
    lang = str(target.get("language") or "")
    coverage_cmd = str(target.get("coverage_command") or "").strip()
    test_cmd = str(target.get("test_command") or "").strip()
    results: list[CmdResult] = []

    # Explicit coverage_command wins — allows non-default stacks (e.g. Astro+Vitest).
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

    # TypeScript: try vitest coverage via npm script.
    if lang == "typescript":
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

    # Unknown language: skip coverage silently.
    _ = test_cmd
    return None, results


# ---------------------------------------------------------------------------
# Core run logic
# ---------------------------------------------------------------------------


def run_regression(
    targets: list[dict],
    results_root: str | Path,
    dashboard_out: str | Path,
    timeout_s: int = 60 * 20,
) -> dict[str, Any]:
    """Run regression for *targets* and write all artifacts.

    Parameters
    ----------
    targets:
        List of target dicts with at minimum ``name``, ``path``, and
        ``test_command`` keys.
    results_root:
        Directory under which per-run subdirectories are created.
    dashboard_out:
        Path where ``regression-data.json`` is written for the dashboard.
    timeout_s:
        Per-command timeout in seconds.

    Returns
    -------
    The full run-summary dict (same data written to ``regression.json``).
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = os.path.join(str(results_root), run_id)
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
            logger.warning("Skipping incomplete target entry: %r", t)
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

        # 1) Best-effort coverage
        cov, cov_cmds = best_effort_coverage(t, repo_dir, target_run_dir, timeout_s)
        target_record["coverage_attempts"] = [c.__dict__ for c in cov_cmds]
        if cov:
            target_record["coverage"] = cov

        # 2) Always run configured regression command (source of truth)
        try:
            test_res = run_cmd(test_cmd, cwd=repo_dir, out_dir=target_run_dir, label="test", timeout_s=timeout_s)
            target_record["test"] = test_res.__dict__
            target_record["status"] = "passed" if test_res.exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            target_record["status"] = "failed"
            target_record["test"] = {
                "cmd": test_cmd,
                "cwd": repo_dir,
                "exit_code": 124,
                "duration_ms": timeout_s * 1000,
                "stdout_path": os.path.join(target_run_dir, "test.stdout.log"),
                "stderr_path": os.path.join(target_run_dir, "test.stderr.log"),
            }
            write_text(target_record["test"]["stdout_path"], "")
            write_text(target_record["test"]["stderr_path"], f"TIMEOUT after {timeout_s}s\n")
            logger.warning("Target '%s' timed out after %ds", name, timeout_s)

        target_record["finished_at"] = utc_now_iso()
        if target_record["status"] == "passed":
            run_summary["targets_passed"] += 1
        else:
            run_summary["targets_failed"] += 1

        run_summary["targets"].append(target_record)
        logger.info(
            "target=%s status=%s",
            name,
            target_record["status"],
        )

    run_summary["finished_at"] = utc_now_iso()

    # Write run artifact
    regression_json_path = os.path.join(run_root, "regression.json")
    write_json(regression_json_path, run_summary)
    logger.info("Wrote regression run: %s", run_root)

    # Write dashboard "latest" payload
    dashboard_payload = {
        "generated_at": utc_now_iso(),
        "latest_run": run_summary,
        "runs_dir": "results/regression",
    }
    safe_mkdir(os.path.dirname(str(dashboard_out)))
    write_json(dashboard_out, dashboard_payload)
    logger.info("Wrote dashboard payload: %s", dashboard_out)

    return run_summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    config=None,
) -> int:
    """CLI entry point.

    Parameters
    ----------
    argv:
        Argument list (defaults to sys.argv[1:]).
    config:
        Optional ``backoffice.config.Config`` instance.  When provided,
        ``config.targets`` is used instead of loading ``targets.yaml``.
    """
    ap = argparse.ArgumentParser(
        description="Portfolio regression runner",
    )
    ap.add_argument(
        "--targets",
        default=None,
        help="Path to targets.yaml (ignored when a Config object is supplied)",
    )
    ap.add_argument(
        "--out",
        default=str(_DEFAULT_RESULTS_ROOT),
        help="Directory for run artifacts",
    )
    ap.add_argument(
        "--dashboard-out",
        default=str(_DEFAULT_DASHBOARD_OUT),
        help="Path for regression-data.json dashboard payload",
    )
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated target names to run (optional)",
    )
    ap.add_argument(
        "--timeout-seconds",
        type=int,
        default=60 * 20,
        help="Per-command timeout in seconds",
    )
    args = ap.parse_args(argv)

    # Build targets list --------------------------------------------------
    if config is not None:
        # Config.targets is dict[str, Target]; adapt to the dict shape expected
        # by run_regression / best_effort_coverage.
        targets: list[dict] = [
            {
                "name": name,
                "path": t.path,
                "language": t.language,
                "test_command": t.test_command,
                "coverage_command": t.coverage_command,
            }
            for name, t in config.targets.items()
        ]
    else:
        # Fall back to targets.yaml (backward-compat)
        import yaml  # local import to keep top-level import list minimal

        targets_path = args.targets
        if targets_path is None:
            # Default location
            targets_path = str(_PACKAGE_ROOT / "config" / "targets.yaml")

        try:
            with open(targets_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            logger.error("targets.yaml not found at %s", targets_path)
            return 2

        raw_targets = cfg.get("targets", [])
        if not isinstance(raw_targets, list) or not raw_targets:
            logger.error("No targets found in %s", targets_path)
            return 2
        targets = raw_targets

    # Apply --only filter
    only = [s.strip() for s in str(args.only).split(",") if s.strip()]
    if only:
        targets = [t for t in targets if t.get("name") in only]

    if not targets:
        logger.error("No targets to run after filtering")
        return 2

    run_summary = run_regression(
        targets=targets,
        results_root=args.out,
        dashboard_out=args.dashboard_out,
        timeout_s=args.timeout_seconds,
    )

    return 0 if run_summary["targets_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
