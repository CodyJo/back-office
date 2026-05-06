"""MCP server — read-only access to Back Office state.

Wraps the existing modules (``config``, ``agents``, ``backlog``,
``overnight_state``, ``store``) as MCP tools and resources so any
Claude Code session can query Back Office without shelling
``python -m backoffice ...``.

Read-only by design: every mutation surface stays on the Phase 9 HTTP
API (``backoffice.api_server``), which already enforces autonomy gates
and per-agent tokens. Promoting a write tool to MCP later means having
the same handler enforce the same gates — not duplicating policy here.

Run::

    python -m backoffice mcp        # stdio transport (for Claude Code)

Requires the ``mcp`` extra::

    pip install -e '.[mcp]'
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def build_server():
    """Construct the FastMCP server. The ``mcp`` import is local so the
    dependency is only required when the server actually runs."""
    from mcp.server.fastmcp import FastMCP

    from backoffice.agents import AgentRegistry
    from backoffice.config import load_config
    from backoffice.overnight_state import FailureMemory, Quarantine
    from backoffice.store import FileStore

    cfg = load_config()
    root = cfg.root
    dashboard_dir = root / "dashboard"
    results_dir = root / "results"

    mcp = FastMCP(
        "backoffice",
        instructions=(
            "Read-only access to Back Office state: configured targets, "
            "registered agents, backlog findings, score history, runs, "
            "items blocked by failure memory, and repos under quarantine. "
            "Mutations go through the Phase 9 HTTP API, not this server."
        ),
    )

    # ── Tools ─────────────────────────────────────────────────────────

    @mcp.tool()
    def list_targets() -> list[dict]:
        """List configured target repos with their autonomy posture."""
        out: list[dict] = []
        for name, t in cfg.targets.items():
            out.append({
                "name": name,
                "path": t.path,
                "language": t.language,
                "autonomy": {
                    "allow_fix": t.autonomy.allow_fix,
                    "allow_feature_dev": t.autonomy.allow_feature_dev,
                    "allow_auto_commit": t.autonomy.allow_auto_commit,
                    "allow_auto_merge": t.autonomy.allow_auto_merge,
                    "allow_auto_deploy": t.autonomy.allow_auto_deploy,
                },
            })
        return out

    @mcp.tool()
    def list_agents(status: str | None = None) -> list[dict]:
        """List registered agents.

        Args:
            status: filter by ``active``, ``paused``, or ``retired``.
        """
        agents = AgentRegistry().list()
        if status:
            agents = [a for a in agents if a.status == status]
        return [a.to_dict() for a in agents]

    @mcp.tool()
    def list_findings(
        repo: str | None = None,
        department: str | None = None,
        severity: str | None = None,
        status: str = "open",
        limit: int = 100,
    ) -> list[dict]:
        """Query the consolidated backlog. Filters are AND-combined.

        Severity values: ``critical``, ``high``, ``medium``, ``low``.
        Status defaults to ``open`` — pass an empty string to include all.
        """
        backlog = _load_json(dashboard_dir / "backlog.json") or {}
        findings = list((backlog.get("findings") or {}).values())
        out: list[dict] = []
        for f in findings:
            if repo and f.get("repo") != repo:
                continue
            if department and f.get("department") != department:
                continue
            if severity and f.get("severity") != severity:
                continue
            if status and f.get("status") != status:
                continue
            out.append(f)
            if len(out) >= limit:
                break
        return out

    @mcp.tool()
    def get_finding(finding_hash: str) -> dict | None:
        """Look up a single finding by its 16-char content hash."""
        backlog = _load_json(dashboard_dir / "backlog.json") or {}
        return (backlog.get("findings") or {}).get(finding_hash)

    @mcp.tool()
    def score_history(repo: str | None = None, limit: int = 10) -> list[dict]:
        """Recent department-score snapshots, optionally narrowed to one repo."""
        history = _load_json(dashboard_dir / "score-history.json") or {}
        snaps = (history.get("snapshots") or [])[-limit:]
        if repo:
            snaps = [
                {
                    "timestamp": s.get("timestamp"),
                    "scores": {repo: (s.get("scores") or {}).get(repo, {})},
                }
                for s in snaps
                if repo in (s.get("scores") or {})
            ]
        return snaps

    @mcp.tool()
    def blocked_items(window: int = 2) -> list[dict]:
        """Items the overnight loop will skip due to recent-cycle failures."""
        mem = FailureMemory(results_dir / "overnight-history.json", window=window)
        return [{"repo": r, "title": t} for r, t in sorted(mem.blocked_items())]

    @mcp.tool()
    def quarantined(threshold: int = 3) -> list[str]:
        """Repos under rollback-streak quarantine (cleared via results/quarantine-clear.json)."""
        q = Quarantine(
            results_dir / "overnight-history.json",
            threshold=threshold,
            overrides_path=results_dir / "quarantine-clear.json",
        )
        return sorted(q.flagged())

    @mcp.tool()
    def list_runs(state: str | None = None, limit: int = 25) -> list[dict]:
        """Recent run records (most recent first). Optional state filter."""
        runs = FileStore().list_runs()
        if state:
            runs = [r for r in runs if r.state == state]
        runs = sorted(runs, key=lambda r: r.started_at or "", reverse=True)[:limit]
        return [r.to_dict() for r in runs]

    # ── Resources ─────────────────────────────────────────────────────
    # Resources are for "give the model the whole document"; tools are
    # for filtered queries. We expose the JSON files clients most often
    # want to inline.

    @mcp.resource("backoffice://backlog")
    def backlog_resource() -> str:
        """Full backlog.json — every tracked finding across departments."""
        path = dashboard_dir / "backlog.json"
        return path.read_text() if path.exists() else "{}"

    @mcp.resource("backoffice://score-history")
    def score_history_resource() -> str:
        """All retained score snapshots."""
        path = dashboard_dir / "score-history.json"
        return path.read_text() if path.exists() else "{}"

    @mcp.resource("backoffice://agents")
    def agents_resource() -> str:
        """Snapshot of the agent registry."""
        return json.dumps(
            [a.to_dict() for a in AgentRegistry().list()], indent=2
        )

    return mcp


def run_stdio() -> int:
    try:
        mcp = build_server()
    except ImportError as exc:
        print(
            "MCP server requires the 'mcp' extra:\n"
            "    pip install -e '.[mcp]'\n"
            f"  ({exc})",
            file=sys.stderr,
        )
        return 2
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_stdio())
