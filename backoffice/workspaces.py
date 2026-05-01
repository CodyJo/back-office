"""Workspace lifecycle helpers + PR provenance.

Phase 10 makes today's implicit ``back-office/preview/<job-id>``
branches into first-class :class:`backoffice.domain.Workspace`
records and tightens GitHub draft PR generation:

* Every PR body includes Back Office provenance (task / run / approval
  / workspace ids + evidence links).
* :func:`pr_body` refuses to mark a PR ready when test results show
  a non-zero exit code.

Storage: ``results/workspaces/<workspace-id>.json``.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from backoffice.domain import AuditEvent, Workspace
from backoffice.store import FileStore
from backoffice.store.atomic import atomic_write_json

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return "".join(c if c.isalnum() or c in {"-", "_"} else "-" for c in value).strip("-")


class WorkspaceRegistry:
    """File-backed registry of :class:`Workspace` records."""

    def __init__(self, store: FileStore | None = None):
        self.store = store or FileStore()

    # ----- paths ------------------------------------------------------

    def workspaces_dir(self) -> Path:
        return self.store.runs_dir().parent / "workspaces"

    def _path(self, workspace_id: str) -> Path:
        if not workspace_id or "/" in workspace_id or ".." in workspace_id:
            raise ValueError(f"invalid workspace id: {workspace_id!r}")
        return self.workspaces_dir() / f"{_safe_id(workspace_id)}.json"

    # ----- CRUD -------------------------------------------------------

    def list(self) -> list[Workspace]:
        d = self.workspaces_dir()
        if not d.exists():
            return []
        out: list[Workspace] = []
        for path in sorted(d.glob("*.json")):
            try:
                import json
                payload = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                out.append(Workspace.from_dict(payload))
        return out

    def get(self, workspace_id: str) -> Workspace | None:
        path = self._path(workspace_id)
        if not path.exists():
            return None
        try:
            import json
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return Workspace.from_dict(payload) if isinstance(payload, dict) else None

    def create(
        self,
        *,
        task_id: str,
        repo: str,
        branch: str,
        base_ref: str = "main",
        kind: str = "branch",
        worktree_path: str = "",
        workspace_id: str | None = None,
        actor: str = "system",
    ) -> Workspace:
        ws = Workspace(
            id=workspace_id or f"ws-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            repo=repo,
            kind=kind,
            branch=branch,
            base_ref=base_ref,
            worktree_path=worktree_path,
            created_at=_iso_now(),
            updated_at=_iso_now(),
        )
        atomic_write_json(self._path(ws.id), ws.to_dict())
        self._audit("workspace.created", ws.id, after=ws.to_dict(), actor=actor)
        return ws

    def update(self, ws: Workspace, *, actor: str = "system") -> Workspace:
        new = replace(ws, updated_at=_iso_now())
        atomic_write_json(self._path(new.id), new.to_dict())
        self._audit("workspace.updated", new.id, after=new.to_dict(), actor=actor)
        return new

    def attach_test_results(
        self,
        workspace_id: str,
        *,
        passed: bool,
        ref: str = "",
        actor: str = "system",
    ) -> Workspace:
        ws = self._require(workspace_id)
        meta = dict(ws.metadata)
        meta["test_results"] = {"passed": bool(passed), "ref": ref, "at": _iso_now()}
        new = replace(
            ws,
            test_results_ref=ref,
            metadata=meta,
            updated_at=_iso_now(),
        )
        atomic_write_json(self._path(new.id), new.to_dict())
        self._audit(
            "workspace.tests_attached",
            new.id,
            after={"passed": passed, "ref": ref},
            actor=actor,
        )
        return new

    def retire(self, workspace_id: str, *, actor: str = "system") -> Workspace:
        ws = self._require(workspace_id)
        new = replace(ws, retired_at=_iso_now(), updated_at=_iso_now())
        atomic_write_json(self._path(new.id), new.to_dict())
        self._audit("workspace.retired", new.id, after={"retired_at": new.retired_at}, actor=actor)
        return new

    # ----- helpers ----------------------------------------------------

    def _require(self, workspace_id: str) -> Workspace:
        ws = self.get(workspace_id)
        if ws is None:
            raise LookupError(f"workspace not found: {workspace_id!r}")
        return ws

    def _audit(
        self,
        action: str,
        workspace_id: str,
        *,
        after: dict | None,
        actor: str,
    ) -> None:
        try:
            self.store.append_audit_event(
                AuditEvent(
                    at=_iso_now(),
                    actor_id=actor,
                    action=action,
                    subject_kind="workspace",
                    subject_id=workspace_id,
                    after=after,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to emit %s audit event", action)


# ──────────────────────────────────────────────────────────────────────
# PR provenance
# ──────────────────────────────────────────────────────────────────────


class PRGuardError(RuntimeError):
    """Raised when PR creation is blocked (e.g. failing tests)."""


def pr_body(
    *,
    task_id: str,
    task_title: str = "",
    repo: str = "",
    run_id: str = "",
    approval_id: str = "",
    workspace_id: str = "",
    branch: str = "",
    test_results_passed: bool | None = None,
    evidence_links: list[str] | None = None,
    extra_sections: list[tuple[str, str]] | None = None,
) -> str:
    """Render a Back Office PR body with provenance.

    Refuses to render (raises :class:`PRGuardError`) when
    ``test_results_passed`` is explicitly ``False``. Callers must
    re-run tests and re-attach success before retrying.

    The body is intentionally Markdown so GitHub renders sensibly.
    """
    if test_results_passed is False:
        raise PRGuardError(
            "refusing to render PR body for a workspace whose tests did not pass"
        )

    lines: list[str] = []
    lines.append("## Back Office provenance")
    lines.append("")
    lines.append(f"- Task: `{task_id}`" + (f" — {task_title}" if task_title else ""))
    if repo:
        lines.append(f"- Repo: `{repo}`")
    if run_id:
        lines.append(f"- Run: `{run_id}`")
    if approval_id:
        lines.append(f"- Approval: `{approval_id}`")
    if workspace_id:
        lines.append(f"- Workspace: `{workspace_id}`")
    if branch:
        lines.append(f"- Branch: `{branch}`")
    if test_results_passed is True:
        lines.append("- Tests: passed ✓")
    elif test_results_passed is None:
        lines.append("- Tests: not attached (manual verification expected)")

    if evidence_links:
        lines.append("")
        lines.append("### Evidence")
        for link in evidence_links:
            lines.append(f"- {link}")

    if extra_sections:
        for heading, body in extra_sections:
            lines.append("")
            lines.append(f"### {heading}")
            lines.append(body)

    lines.append("")
    lines.append(
        "_This pull request was opened from Back Office's human approval "
        "workflow and requires GitHub review before merge._"
    )
    return "\n".join(lines)


def can_open_pr(workspace: Workspace) -> tuple[bool, str]:
    """Check whether a workspace is in a state that allows PR creation.

    Currently: refuses if attached test results explicitly failed.
    """
    test_meta = workspace.metadata.get("test_results") if isinstance(workspace.metadata, dict) else None
    if isinstance(test_meta, dict) and test_meta.get("passed") is False:
        return False, "tests_failed"
    if workspace.retired_at:
        return False, "workspace_retired"
    return True, "ok"
