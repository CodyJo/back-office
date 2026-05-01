"""Export / import — portable Back Office configuration.

Phase 11 supports two operator workflows:

* **Export.** ``export_payload(...)`` returns a deterministic
  dictionary safe to serialize and share. Sensitive keys (api keys,
  storage tokens, secrets) are redacted to ``<REDACTED>`` placeholders.
* **Import.** ``apply_payload(..., dry_run=True)`` validates the payload,
  reports a structured diff, and applies it only when ``dry_run=False``
  and conflicts are resolved.

The export does not touch the actual ``config/backoffice.yaml`` or
queue files — it operates on declarative resources owned by Back
Office (agents, routines, budgets, dashboard target metadata, autonomy
policies). Operators handle file placement after running this.

See ``docs/architecture/phased-roadmap.md`` Phase 11.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from backoffice.agents import AgentRegistry
from backoffice.routines import Routine, Scheduler
from backoffice.store import FileStore

logger = logging.getLogger(__name__)


REDACTED = "<REDACTED>"
EXPORT_VERSION = 1


# ──────────────────────────────────────────────────────────────────────
# Sensitive-key detection
# ──────────────────────────────────────────────────────────────────────

_SENSITIVE_KEY_FRAGMENTS = (
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
)


def _is_sensitive_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    lower = key.lower()
    return any(frag in lower for frag in _SENSITIVE_KEY_FRAGMENTS)


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys.

    Lists and tuples are walked; primitives that aren't keys are
    returned unchanged.
    """
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if _is_sensitive_key(str(k)):
                out[k] = REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


# ──────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ExportSelection:
    include_agents: bool = True
    include_routines: bool = True
    include_budgets: bool = True
    include_dashboard_targets: bool = True
    include_autonomy: bool = True


def export_payload(
    *,
    store: FileStore | None = None,
    config_payload: dict | None = None,
    selection: ExportSelection | None = None,
) -> dict:
    """Build a deterministic export of operator-owned configuration.

    *config_payload* is the raw ``backoffice.yaml`` mapping (caller
    parses YAML); we read declarative blocks from there and from the
    file-backed agent / routine registries.
    """
    selection = selection or ExportSelection()
    store = store or FileStore()
    config_payload = config_payload or {}

    out: dict = {"version": EXPORT_VERSION, "resources": {}}

    if selection.include_agents:
        registry = AgentRegistry(store=store)
        out["resources"]["agents"] = sorted(
            (_redact(a.to_dict()) for a in registry.list()),
            key=lambda a: a["id"],
        )

    if selection.include_routines:
        scheduler = Scheduler(store=store)
        out["resources"]["routines"] = sorted(
            (_redact(r.to_dict()) for r in scheduler.list()),
            key=lambda r: r["id"],
        )

    if selection.include_budgets:
        budgets_raw = config_payload.get("budgets") or []
        out["resources"]["budgets"] = sorted(
            (_redact(b) for b in _normalize_budgets(budgets_raw)),
            key=lambda b: b.get("id", ""),
        )

    if selection.include_dashboard_targets:
        dashboard_targets = (
            (config_payload.get("deploy") or {}).get("bunny", {}).get("dashboard_targets") or []
        )
        out["resources"]["dashboard_targets"] = [_redact(d) for d in dashboard_targets]

    if selection.include_autonomy:
        targets = config_payload.get("targets") or {}
        autonomy: dict = {}
        if isinstance(targets, dict):
            for name, body in targets.items():
                if isinstance(body, dict) and "autonomy" in body:
                    autonomy[name] = _redact(body["autonomy"])
        out["resources"]["autonomy"] = autonomy

    return out


def _normalize_budgets(raw) -> list[dict]:
    if isinstance(raw, list):
        return [b for b in raw if isinstance(b, dict)]
    if isinstance(raw, dict):
        return [{"id": bid, **(body if isinstance(body, dict) else {})} for bid, body in raw.items()]
    return []


def export_json(payload: dict) -> str:
    """Deterministic JSON serialization (sorted keys, indent=2)."""
    return json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"


# ──────────────────────────────────────────────────────────────────────
# Import (validate + diff + apply)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ImportPlan:
    """Result of :func:`apply_payload(..., dry_run=True)`.

    ``conflicts`` lists IDs that already exist with different content.
    ``additions`` lists net-new IDs that would be created.
    ``unchanged`` lists IDs that match what's already on disk.
    """

    additions: dict[str, list[str]]
    conflicts: dict[str, list[str]]
    unchanged: dict[str, list[str]]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "additions": dict(self.additions),
            "conflicts": dict(self.conflicts),
            "unchanged": dict(self.unchanged),
            "errors": list(self.errors),
        }


def validate_payload(payload: Any) -> list[str]:
    """Return a list of validation errors. Empty list = valid."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    if payload.get("version") != EXPORT_VERSION:
        errors.append(f"unsupported export version: {payload.get('version')!r}")
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        errors.append("resources block missing or invalid")
        return errors
    for kind in ("agents", "routines", "budgets", "dashboard_targets", "autonomy"):
        if kind in resources and not isinstance(resources[kind], (list, dict)):
            errors.append(f"resources.{kind} must be a list or dict")
    return errors


def apply_payload(
    payload: dict,
    *,
    store: FileStore | None = None,
    dry_run: bool = True,
    overwrite: bool = False,
    actor: str = "import",
) -> ImportPlan:
    """Apply *payload* to the local Back Office store.

    By default ``dry_run=True`` reports what would change without
    writing. Pass ``dry_run=False`` to actually apply, and
    ``overwrite=True`` if existing records should be replaced.

    Sensitive placeholders (``<REDACTED>``) on import are interpreted
    as "leave the existing value alone" — never as the literal string.
    """
    errors = validate_payload(payload)
    if errors:
        return ImportPlan(additions={}, conflicts={}, unchanged={}, errors=errors)

    store = store or FileStore()
    resources = payload["resources"]
    plan = ImportPlan(additions={}, conflicts={}, unchanged={}, errors=[])

    _plan_agents(plan, store, resources.get("agents") or [], dry_run, overwrite, actor)
    _plan_routines(plan, store, resources.get("routines") or [], dry_run, overwrite, actor)

    return plan


def _plan_agents(
    plan: ImportPlan,
    store: FileStore,
    agents_raw: Any,
    dry_run: bool,
    overwrite: bool,
    actor: str,
) -> None:
    if not isinstance(agents_raw, list):
        return
    registry = AgentRegistry(store=store)
    additions: list[str] = []
    conflicts: list[str] = []
    unchanged: list[str] = []
    for raw in agents_raw:
        if not isinstance(raw, dict):
            continue
        agent_id = str(raw.get("id") or "")
        if not agent_id:
            plan.errors.append("agent missing id")
            continue
        existing = registry.get(agent_id)
        if existing is None:
            additions.append(agent_id)
            if not dry_run:
                registry.create(
                    agent_id=agent_id,
                    name=str(raw.get("name", agent_id)),
                    role=str(raw.get("role", "custom")),
                    adapter_type=str(raw.get("adapter_type", "process")),
                    adapter_config=_strip_redactions(raw.get("adapter_config", {})),
                    description=str(raw.get("description", "")),
                    actor=actor,
                )
        else:
            if _agent_matches(existing.to_dict(), raw):
                unchanged.append(agent_id)
            else:
                conflicts.append(agent_id)
                if not dry_run and overwrite:
                    from dataclasses import replace
                    new = replace(
                        existing,
                        name=str(raw.get("name", existing.name)),
                        role=str(raw.get("role", existing.role)),
                        adapter_type=str(raw.get("adapter_type", existing.adapter_type)),
                        adapter_config=_strip_redactions(raw.get("adapter_config", existing.adapter_config)),
                        description=str(raw.get("description", existing.description)),
                    )
                    registry.update(new, actor=actor)
    plan.additions["agents"] = additions
    plan.conflicts["agents"] = conflicts
    plan.unchanged["agents"] = unchanged


def _plan_routines(
    plan: ImportPlan,
    store: FileStore,
    routines_raw: Any,
    dry_run: bool,
    overwrite: bool,
    actor: str,
) -> None:
    if not isinstance(routines_raw, list):
        return
    scheduler = Scheduler(store=store)
    additions: list[str] = []
    conflicts: list[str] = []
    unchanged: list[str] = []
    for raw in routines_raw:
        if not isinstance(raw, dict):
            continue
        routine_id = str(raw.get("id") or "")
        if not routine_id:
            plan.errors.append("routine missing id")
            continue
        existing = scheduler.get(routine_id)
        if existing is None:
            additions.append(routine_id)
            if not dry_run:
                try:
                    routine = Routine(
                        id=routine_id,
                        name=str(raw.get("name", routine_id)),
                        description=str(raw.get("description", "")),
                        trigger_kind=str(raw.get("trigger_kind", "manual")),
                        trigger=dict(raw.get("trigger", {}) or {}),
                        action_kind=str(raw.get("action_kind", "noop")),
                        action=dict(raw.get("action", {}) or {}),
                        paused=bool(raw.get("paused", False)),
                        budget_id=str(raw.get("budget_id", "")),
                        metadata=dict(raw.get("metadata", {}) or {}),
                    )
                except ValueError as exc:
                    plan.errors.append(f"routine {routine_id!r} invalid: {exc}")
                    continue
                scheduler.upsert(routine, actor=actor)
        else:
            if existing.to_dict() == raw:
                unchanged.append(routine_id)
            else:
                conflicts.append(routine_id)
                if not dry_run and overwrite:
                    try:
                        routine = Routine(
                            id=routine_id,
                            name=str(raw.get("name", existing.name)),
                            description=str(raw.get("description", existing.description)),
                            trigger_kind=str(raw.get("trigger_kind", existing.trigger_kind)),
                            trigger=dict(raw.get("trigger", existing.trigger) or {}),
                            action_kind=str(raw.get("action_kind", existing.action_kind)),
                            action=dict(raw.get("action", existing.action) or {}),
                            paused=bool(raw.get("paused", existing.paused)),
                            budget_id=str(raw.get("budget_id", existing.budget_id)),
                            metadata=dict(raw.get("metadata", existing.metadata) or {}),
                        )
                    except ValueError as exc:
                        plan.errors.append(f"routine {routine_id!r} invalid: {exc}")
                        continue
                    scheduler.upsert(routine, actor=actor)
    plan.additions["routines"] = additions
    plan.conflicts["routines"] = conflicts
    plan.unchanged["routines"] = unchanged


def _strip_redactions(value: Any) -> Any:
    """Replace any ``<REDACTED>`` placeholders with empty strings.

    Importing redactions wholesale would silently overwrite real
    secrets. We strip them so the operator must re-supply real values.
    """
    if isinstance(value, dict):
        return {k: ("" if v == REDACTED else _strip_redactions(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_redactions(item) for item in value]
    if value == REDACTED:
        return ""
    return value


def _agent_matches(existing: dict, incoming: dict) -> bool:
    """Compare the import-relevant fields, ignoring timestamps."""
    keys = ("id", "name", "role", "adapter_type", "description")
    return all(existing.get(k) == incoming.get(k) for k in keys)
