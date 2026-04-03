"""Archived GitHub Actions history for Back Office."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _archive_root(root: Path) -> Path:
    return root / "results" / "github-actions-history"


def _repo_dirs(root: Path) -> list[Path]:
    archive_root = _archive_root(root)
    if not archive_root.exists():
        return []
    return sorted(path for path in archive_root.iterdir() if path.is_dir())


def _format_repo_payload(repo_dir: Path) -> dict:
    repo_payload = _read_json(repo_dir / "repo.json")
    workflows_payload = _read_json(repo_dir / "workflows.json")
    runs_payload = _read_json(repo_dir / "runs.json")
    runners_payload = _read_json(repo_dir / "runners.json")

    repo_name = repo_payload.get("full_name") or repo_dir.name
    workflows = workflows_payload.get("workflows", [])
    runs = runs_payload.get("workflow_runs", [])
    runner_total = runners_payload.get("total_count")
    if runner_total is None and isinstance(runners_payload.get("runners"), list):
        runner_total = len(runners_payload["runners"])

    latest_run = runs[0] if runs else None
    providers = sorted({run.get("event") for run in runs if run.get("event")})
    repo_updated_at = repo_payload.get("updated_at")
    archive_updated_at = None
    try:
        archive_updated_at = datetime.fromtimestamp(
            (repo_dir / "runs.json").stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
    except OSError:
        archive_updated_at = None

    return {
        "repo": repo_name,
        "repo_dir": repo_dir.name,
        "html_url": repo_payload.get("html_url"),
        "private": repo_payload.get("private"),
        "default_branch": repo_payload.get("default_branch"),
        "language": repo_payload.get("language"),
        "updated_at": repo_updated_at,
        "archive_updated_at": archive_updated_at,
        "workflow_count": len(workflows),
        "workflows": workflows,
        "archived_runs": runs_payload.get("archived_count", len(runs)),
        "total_runs": runs_payload.get("total_count", len(runs)),
        "runner_count": runner_total,
        "recent_runs": runs[:8],
        "latest_run": latest_run,
        "events": providers,
        "has_runs": bool(runs),
        "has_workflows": bool(workflows),
        "archive_capped": runs_payload.get("total_count", len(runs)) > runs_payload.get("archived_count", len(runs)),
    }


def build_history_payload(root: Path) -> dict:
    repo_cards = [_format_repo_payload(repo_dir) for repo_dir in _repo_dirs(root)]
    repo_cards.sort(key=lambda item: (item["archived_runs"], item["workflow_count"], item["repo"]), reverse=True)

    total_runs = sum(int(item["archived_runs"]) for item in repo_cards)
    repos_with_runs = sum(1 for item in repo_cards if item["has_runs"])
    repos_with_workflows = sum(1 for item in repo_cards if item["has_workflows"])
    capped_repos = sum(1 for item in repo_cards if item["archive_capped"])

    archive_root = _archive_root(root)
    summary_path = archive_root / "summary.json"
    archive_generated_at = None
    try:
        archive_generated_at = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        archive_generated_at = None

    top_runs = []
    for repo in repo_cards:
        for run in repo["recent_runs"][:3]:
            top_runs.append({
                "repo": repo["repo"],
                "repo_dir": repo["repo_dir"],
                "html_url": repo["html_url"],
                "run": run,
            })
    top_runs.sort(key=lambda item: item["run"].get("created_at", ""), reverse=True)

    return {
        "generated_at": iso_now(),
        "archive_generated_at": archive_generated_at,
        "archive_root": str(archive_root),
        "summary": {
            "repos": len(repo_cards),
            "repos_with_runs": repos_with_runs,
            "repos_with_workflows": repos_with_workflows,
            "archived_runs": total_runs,
            "capped_repos": capped_repos,
        },
        "repos": repo_cards,
        "recent_runs": top_runs[:18],
    }


def archive_history(root: Path) -> dict:
    script = root / "scripts" / "archive-github-actions-history.sh"
    if not script.exists():
        raise FileNotFoundError(f"Missing archive script: {script}")

    result = subprocess.run(
        [str(script)],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }
