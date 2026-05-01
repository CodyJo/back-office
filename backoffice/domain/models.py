"""Typed domain models for Back Office.

Design notes
------------

* Models are non-frozen dataclasses so callers can pick between
  in-place mutation and ``dataclasses.replace``. State-machine helpers
  use ``replace`` for purity; storage helpers may mutate in place.
* State strings are kept loose (``str``) instead of ``Enum`` because
  the YAML I/O boundary already uses plain strings; switching to
  enums would break compatibility for no near-term gain.
* ``Task.approval``, ``Task.source_finding``, and ``Task.pr`` are
  preserved as raw ``dict`` values rather than canonical sub-dataclasses.
  Real ``config/task-queue.yaml`` entries put heterogeneous data there
  (mentor plans, suggested products, simple ``{}``), and forcing a
  canonical schema would lose information on round-trip. Typed views
  for these fields live in :mod:`backoffice.domain.compat`.
* Every model exposes ``from_dict`` / ``to_dict`` for round-trip use
  by storage and tests. Unknown keys are captured in ``extras`` so
  upstream additions never get silently dropped.

These models are intentionally unused by existing call sites in this
phase. See ``docs/architecture/phased-roadmap.md`` Phase 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ──────────────────────────────────────────────────────────────────────
# State string registries
# ──────────────────────────────────────────────────────────────────────

# Task states. ``checked_out`` and ``failed`` are net-new in the target
# model; the rest match ``backoffice.tasks.STATUS_ORDER`` plus
# ``proposed`` (the legacy default).
TASK_STATES: tuple[str, ...] = (
    "proposed",
    "pending_approval",
    "approved",
    "ready",
    "queued",
    "checked_out",
    "in_progress",
    "blocked",
    "ready_for_review",
    "pr_open",
    "done",
    "failed",
    "cancelled",
)

RUN_STATES: tuple[str, ...] = (
    "created",
    "queued",
    "starting",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)

APPROVAL_STATES: tuple[str, ...] = (
    "requested",
    "approved",
    "rejected",
    "expired",
    "superseded",
)

AGENT_ROLES: tuple[str, ...] = (
    "scanner",
    "fixer",
    "feature_dev",
    "product_owner",
    "mentor",
    "reviewer",
    "custom",
)

AGENT_STATUSES: tuple[str, ...] = (
    "active",
    "paused",
    "retired",
)

ACTOR_KINDS: tuple[str, ...] = (
    "operator",
    "agent",
    "routine",
    "system",
)


def iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _split_known(raw: dict, known: set[str]) -> tuple[dict, dict]:
    """Split a raw dict into (known, extras)."""
    known_part = {k: raw[k] for k in raw.keys() if k in known}
    extras_part = {k: raw[k] for k in raw.keys() if k not in known}
    return known_part, extras_part


# ──────────────────────────────────────────────────────────────────────
# HistoryEntry
# ──────────────────────────────────────────────────────────────────────


@dataclass
class HistoryEntry:
    """One row in ``Task.history``. Matches the legacy YAML shape."""

    status: str
    at: str
    by: str
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "HistoryEntry":
        if not isinstance(raw, dict):
            return cls(status="", at="", by="", note="")
        return cls(
            status=str(raw.get("status", "")),
            at=str(raw.get("at", "")),
            by=str(raw.get("by", "")),
            note=str(raw.get("note", "")),
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "at": self.at,
            "by": self.by,
            "note": self.note,
        }


# ──────────────────────────────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────────────────────────────


_TASK_CANONICAL_KEYS: set[str] = {
    "id",
    "repo",
    "title",
    "status",
    "priority",
    "category",
    "task_type",
    "owner",
    "created_by",
    "created_at",
    "updated_at",
    "notes",
    "product_key",
    "target_path",
    "handoff_required",
    "verification_command",
    "repo_handoff_path",
    "current_run_id",
    "acceptance_criteria",
    "audits_required",
    "history",
    "approval",
    "source_finding",
    "pr",
}


@dataclass
class Task:
    """A unit of work in the Back Office queue.

    Round-trips losslessly through ``from_dict`` / ``to_dict`` against
    the legacy ``config/task-queue.yaml`` shape produced by
    :func:`backoffice.tasks.ensure_task_defaults`.

    See ``docs/architecture/target-state.md`` §3.2.
    """

    id: str = ""
    repo: str = ""
    title: str = ""
    status: str = "proposed"
    priority: str = "medium"
    category: str = "feature"
    task_type: str = "implementation"
    owner: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""
    product_key: str = ""
    target_path: str = ""
    handoff_required: bool = True
    verification_command: str = ""
    repo_handoff_path: str = ""

    # The latest active Run id for this task, set by Store.checkout_task
    # and cleared when the run terminates. Empty when no run is in flight.
    current_run_id: str = ""

    acceptance_criteria: list[str] = field(default_factory=list)
    audits_required: list[str] = field(default_factory=list)
    history: list[HistoryEntry] = field(default_factory=list)

    # Heterogeneous nested payloads — preserved as raw dicts on purpose.
    # See module docstring.
    approval: dict = field(default_factory=dict)
    source_finding: dict = field(default_factory=dict)
    pr: dict = field(default_factory=dict)

    # Future-proofing: any keys not in the canonical set go here so
    # round-trip is exact even if upstream adds fields.
    extras: dict = field(default_factory=dict)

    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        if not isinstance(raw, dict):
            raise TypeError(f"Task.from_dict expected a mapping, got {type(raw).__name__}")
        history_raw = raw.get("history") or []
        if not isinstance(history_raw, list):
            history_raw = []
        return cls(
            id=str(raw.get("id", "")),
            repo=str(raw.get("repo", "")),
            title=str(raw.get("title", "")),
            status=str(raw.get("status", "proposed")),
            priority=str(raw.get("priority", "medium")),
            category=str(raw.get("category", "feature")),
            task_type=str(raw.get("task_type", "implementation")),
            owner=str(raw.get("owner", "")),
            created_by=str(raw.get("created_by", "")),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            notes=str(raw.get("notes", "")),
            product_key=str(raw.get("product_key", "")),
            target_path=str(raw.get("target_path", "")),
            handoff_required=bool(raw.get("handoff_required", True)),
            verification_command=str(raw.get("verification_command", "")),
            repo_handoff_path=str(raw.get("repo_handoff_path", "")),
            current_run_id=str(raw.get("current_run_id", "")),
            acceptance_criteria=list(raw.get("acceptance_criteria", []) or []),
            audits_required=list(raw.get("audits_required", []) or []),
            history=[HistoryEntry.from_dict(h) for h in history_raw if isinstance(h, dict)],
            approval=dict(raw.get("approval", {}) or {}),
            source_finding=dict(raw.get("source_finding", {}) or {}),
            pr=dict(raw.get("pr", {}) or {}),
            extras={k: v for k, v in raw.items() if k not in _TASK_CANONICAL_KEYS},
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "id": self.id,
            "repo": self.repo,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "category": self.category,
            "task_type": self.task_type,
            "owner": self.owner,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "product_key": self.product_key,
            "target_path": self.target_path,
            "handoff_required": self.handoff_required,
            "verification_command": self.verification_command,
            "repo_handoff_path": self.repo_handoff_path,
            "acceptance_criteria": list(self.acceptance_criteria),
            "audits_required": list(self.audits_required),
            "history": [h.to_dict() for h in self.history],
            "approval": dict(self.approval),
            "source_finding": dict(self.source_finding),
            "pr": dict(self.pr),
        }
        # ``current_run_id`` only emits when set so legacy task dicts
        # — which never had this field — round-trip byte-stable.
        if self.current_run_id:
            out["current_run_id"] = self.current_run_id
        # Extras land last so canonical keys win when there's a clash.
        for k, v in self.extras.items():
            if k not in out:
                out[k] = v
        return out


# ──────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────


_RUN_CANONICAL_KEYS: set[str] = {
    "id",
    "task_id",
    "agent_id",
    "adapter_type",
    "adapter_handle",
    "workspace_id",
    "approval_id",
    "state",
    "started_at",
    "ended_at",
    "exit_code",
    "duration_ms",
    "prompt_ref",
    "output_summary",
    "artifacts",
    "cost",
    "error",
    "metadata",
}


@dataclass
class Run:
    """A single attempt by an agent at a task.

    See ``docs/architecture/target-state.md`` §3.3.
    """

    id: str = ""
    task_id: str = ""
    agent_id: str = ""
    adapter_type: str = ""
    adapter_handle: str | None = None
    workspace_id: str | None = None
    approval_id: str | None = None
    state: str = "created"
    started_at: str = ""
    ended_at: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None
    prompt_ref: str | None = None
    output_summary: str = ""
    artifacts: list[dict] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    error: str = ""
    metadata: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "Run":
        if not isinstance(raw, dict):
            raise TypeError(f"Run.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            task_id=str(raw.get("task_id", "")),
            agent_id=str(raw.get("agent_id", "")),
            adapter_type=str(raw.get("adapter_type", "")),
            adapter_handle=raw.get("adapter_handle"),
            workspace_id=raw.get("workspace_id"),
            approval_id=raw.get("approval_id"),
            state=str(raw.get("state", "created")),
            started_at=str(raw.get("started_at", "")),
            ended_at=str(raw.get("ended_at", "")),
            exit_code=raw.get("exit_code"),
            duration_ms=raw.get("duration_ms"),
            prompt_ref=raw.get("prompt_ref"),
            output_summary=str(raw.get("output_summary", "")),
            artifacts=list(raw.get("artifacts", []) or []),
            cost=dict(raw.get("cost", {}) or {}),
            error=str(raw.get("error", "")),
            metadata=dict(raw.get("metadata", {}) or {}),
            extras={k: v for k, v in raw.items() if k not in _RUN_CANONICAL_KEYS},
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "adapter_type": self.adapter_type,
            "adapter_handle": self.adapter_handle,
            "workspace_id": self.workspace_id,
            "approval_id": self.approval_id,
            "state": self.state,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "prompt_ref": self.prompt_ref,
            "output_summary": self.output_summary,
            "artifacts": list(self.artifacts),
            "cost": dict(self.cost),
            "error": self.error,
            "metadata": dict(self.metadata),
        }
        for k, v in self.extras.items():
            if k not in out:
                out[k] = v
        return out


# ──────────────────────────────────────────────────────────────────────
# Approval
# ──────────────────────────────────────────────────────────────────────


_APPROVAL_CANONICAL_KEYS: set[str] = {
    "id",
    "task_id",
    "scope",
    "state",
    "requested_by",
    "requested_at",
    "decided_by",
    "decided_at",
    "reason",
    "expires_at",
    "policy_basis",
    "audit_event_id",
}


@dataclass
class Approval:
    """First-class approval record.

    Today this is synthesized at read-time from ``task["approval"]``;
    later phases will persist it directly. See ``compat.py``.
    """

    id: str = ""
    task_id: str = ""
    scope: str = "plan"  # plan | run | merge
    state: str = "requested"
    requested_by: str = ""
    requested_at: str = ""
    decided_by: str = ""
    decided_at: str = ""
    reason: str = ""
    expires_at: str = ""
    policy_basis: str = ""
    audit_event_id: str = ""
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "Approval":
        if not isinstance(raw, dict):
            raise TypeError(f"Approval.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            task_id=str(raw.get("task_id", "")),
            scope=str(raw.get("scope", "plan")),
            state=str(raw.get("state", "requested")),
            requested_by=str(raw.get("requested_by", "")),
            requested_at=str(raw.get("requested_at", "")),
            decided_by=str(raw.get("decided_by", "")),
            decided_at=str(raw.get("decided_at", "")),
            reason=str(raw.get("reason", "")),
            expires_at=str(raw.get("expires_at", "")),
            policy_basis=str(raw.get("policy_basis", "")),
            audit_event_id=str(raw.get("audit_event_id", "")),
            extras={k: v for k, v in raw.items() if k not in _APPROVAL_CANONICAL_KEYS},
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "id": self.id,
            "task_id": self.task_id,
            "scope": self.scope,
            "state": self.state,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "expires_at": self.expires_at,
            "policy_basis": self.policy_basis,
            "audit_event_id": self.audit_event_id,
        }
        for k, v in self.extras.items():
            if k not in out:
                out[k] = v
        return out


# ──────────────────────────────────────────────────────────────────────
# CostEvent
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CostEvent:
    """A single recorded cost data point.

    See ``docs/architecture/target-state.md`` §3.6.
    """

    id: str = ""
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    target: str | None = None
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    verified: bool = False
    source: str = "estimate"  # estimate | adapter_reported | provider_api
    timestamp: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "CostEvent":
        if not isinstance(raw, dict):
            raise TypeError(f"CostEvent.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            run_id=raw.get("run_id"),
            task_id=raw.get("task_id"),
            agent_id=raw.get("agent_id"),
            target=raw.get("target"),
            provider=str(raw.get("provider", "")),
            model=str(raw.get("model", "")),
            input_tokens=int(raw.get("input_tokens", 0) or 0),
            output_tokens=int(raw.get("output_tokens", 0) or 0),
            total_tokens=int(raw.get("total_tokens", 0) or 0),
            estimated_cost_usd=float(raw.get("estimated_cost_usd", 0.0) or 0.0),
            verified=bool(raw.get("verified", False)),
            source=str(raw.get("source", "estimate")),
            timestamp=str(raw.get("timestamp", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "target": self.target,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "verified": self.verified,
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ──────────────────────────────────────────────────────────────────────
# Workspace
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Workspace:
    """A tracked place where AI work happens (today: a preview branch).

    Round-trips with the existing ``preview-<job-id>.json`` artifacts
    via :mod:`backoffice.domain.compat`.

    See ``docs/architecture/target-state.md`` §3.5.
    """

    id: str = ""
    task_id: str = ""
    repo: str = ""
    kind: str = "branch"  # branch | worktree | patch
    branch: str = ""
    base_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    worktree_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    retired_at: str = ""
    test_results_ref: str = ""
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "Workspace":
        if not isinstance(raw, dict):
            raise TypeError(f"Workspace.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            task_id=str(raw.get("task_id", "")),
            repo=str(raw.get("repo", "")),
            kind=str(raw.get("kind", "branch")),
            branch=str(raw.get("branch", "")),
            base_ref=str(raw.get("base_ref", "")),
            base_sha=str(raw.get("base_sha", "")),
            head_sha=str(raw.get("head_sha", "")),
            worktree_path=str(raw.get("worktree_path", "")),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            retired_at=str(raw.get("retired_at", "")),
            test_results_ref=str(raw.get("test_results_ref", "")),
            metadata=dict(raw.get("metadata", {}) or {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "repo": self.repo,
            "kind": self.kind,
            "branch": self.branch,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "worktree_path": self.worktree_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retired_at": self.retired_at,
            "test_results_ref": self.test_results_ref,
            "metadata": dict(self.metadata),
        }


# ──────────────────────────────────────────────────────────────────────
# AdapterConfig
# ──────────────────────────────────────────────────────────────────────


@dataclass
class AdapterConfig:
    """Per-agent record of how the executor is invoked.

    See ``docs/architecture/target-state.md`` §3.10.
    """

    agent_id: str = ""
    adapter_type: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env_allowlist: list[str] = field(default_factory=list)
    cwd_strategy: str = "repo"  # repo | worktree | sandbox
    timeout_seconds: int = 0
    prompt_template: str = ""
    dry_run_default: bool = False
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "AdapterConfig":
        if not isinstance(raw, dict):
            raise TypeError(f"AdapterConfig.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            agent_id=str(raw.get("agent_id", "")),
            adapter_type=str(raw.get("adapter_type", "")),
            command=str(raw.get("command", "")),
            args=list(raw.get("args", []) or []),
            env_allowlist=list(raw.get("env_allowlist", []) or []),
            cwd_strategy=str(raw.get("cwd_strategy", "repo")),
            timeout_seconds=int(raw.get("timeout_seconds", 0) or 0),
            prompt_template=str(raw.get("prompt_template", "")),
            dry_run_default=bool(raw.get("dry_run_default", False)),
            metadata=dict(raw.get("metadata", {}) or {}),
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "adapter_type": self.adapter_type,
            "command": self.command,
            "args": list(self.args),
            "env_allowlist": list(self.env_allowlist),
            "cwd_strategy": self.cwd_strategy,
            "timeout_seconds": self.timeout_seconds,
            "prompt_template": self.prompt_template,
            "dry_run_default": self.dry_run_default,
            "metadata": dict(self.metadata),
        }


# ──────────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """A first-class identity for something that does work.

    See ``docs/architecture/target-state.md`` §3.1.
    """

    id: str = ""
    name: str = ""
    role: str = "custom"
    description: str = ""
    adapter_type: str = ""
    adapter_config: dict = field(default_factory=dict)
    status: str = "active"
    paused_at: str = ""
    budget_id: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Agent":
        if not isinstance(raw, dict):
            raise TypeError(f"Agent.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            role=str(raw.get("role", "custom")),
            description=str(raw.get("description", "")),
            adapter_type=str(raw.get("adapter_type", "")),
            adapter_config=dict(raw.get("adapter_config", {}) or {}),
            status=str(raw.get("status", "active")),
            paused_at=str(raw.get("paused_at", "")),
            budget_id=str(raw.get("budget_id", "")),
            metadata=dict(raw.get("metadata", {}) or {}),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "adapter_type": self.adapter_type,
            "adapter_config": dict(self.adapter_config),
            "status": self.status,
            "paused_at": self.paused_at,
            "budget_id": self.budget_id,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ──────────────────────────────────────────────────────────────────────
# Actor / AuditEvent
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Actor:
    """Who performed an action.

    See ``docs/architecture/target-state.md`` §3.9.
    """

    id: str = ""
    kind: str = "operator"  # operator | agent | routine | system
    display_name: str = ""
    agent_id: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Actor":
        if not isinstance(raw, dict):
            raise TypeError(f"Actor.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            kind=str(raw.get("kind", "operator")),
            display_name=str(raw.get("display_name", "")),
            agent_id=str(raw.get("agent_id", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "display_name": self.display_name,
            "agent_id": self.agent_id,
        }


@dataclass
class AuditEvent:
    """One mutation across the system.

    Existing ``results/overnight-ledger.jsonl`` becomes a filtered view
    of this stream; nothing about the ledger needs to change in this
    phase.
    """

    id: str = ""
    at: str = ""
    actor_id: str = ""
    action: str = ""
    subject_kind: str = ""  # task | run | approval | workspace | budget | routine
    subject_id: str = ""
    before: dict | None = None
    after: dict | None = None
    reason: str = ""
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "AuditEvent":
        if not isinstance(raw, dict):
            raise TypeError(f"AuditEvent.from_dict expected a mapping, got {type(raw).__name__}")
        return cls(
            id=str(raw.get("id", "")),
            at=str(raw.get("at", "")),
            actor_id=str(raw.get("actor_id", "")),
            action=str(raw.get("action", "")),
            subject_kind=str(raw.get("subject_kind", "")),
            subject_id=str(raw.get("subject_id", "")),
            before=raw.get("before"),
            after=raw.get("after"),
            reason=str(raw.get("reason", "")),
            metadata=dict(raw.get("metadata", {}) or {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "actor_id": self.actor_id,
            "action": self.action,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }
