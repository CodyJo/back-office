"""First-class agent registry.

Phase 4 introduces an :class:`AgentRegistry` so today's shell agents
(``agents/fix-bugs.sh``, ``agents/feature-dev.sh``, ``agents/product-owner.sh``,
the department scanners) can be named, paused, resumed, and budgeted as
identifiable participants — instead of being implicit subprocess calls.

Storage is JSON files under ``results/agents/<id>.json`` via the existing
:class:`backoffice.store.Store`. The registry is intentionally additive:
nothing in the codebase requires agents to be registered; this phase
makes registration possible without rewriting any existing flow.

See ``docs/architecture/target-state.md`` §3.1 and
``docs/architecture/phased-roadmap.md`` Phase 4.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import replace
from pathlib import Path

from backoffice.domain import Agent, AGENT_ROLES, AuditEvent, iso_now
from backoffice.store import FileStore, Store
from backoffice.store.atomic import atomic_write_json

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────


class AgentNotFound(LookupError):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        super().__init__(f"agent not found: {agent_id!r}")


class AgentRegistry:
    """CRUD wrapper over the file-backed agent records.

    Stored as ``results/agents/<id>.json``. Registry calls write the
    JSON atomically and emit ``agent.*`` audit events.
    """

    def __init__(self, store: Store | None = None):
        self.store: FileStore = store if isinstance(store, FileStore) else FileStore()  # type: ignore[assignment]

    # ----- paths ------------------------------------------------------

    def agents_dir(self) -> Path:
        return self.store.runs_dir().parent / "agents"

    def _agent_path(self, agent_id: str) -> Path:
        if not agent_id or "/" in agent_id or ".." in agent_id:
            raise ValueError(f"invalid agent id: {agent_id!r}")
        return self.agents_dir() / f"{agent_id}.json"

    # ----- CRUD -------------------------------------------------------

    def list(self) -> list[Agent]:
        d = self.agents_dir()
        if not d.exists():
            return []
        out: list[Agent] = []
        for path in sorted(d.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                out.append(Agent.from_dict(payload))
        return out

    def get(self, agent_id: str) -> Agent | None:
        path = self._agent_path(agent_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return Agent.from_dict(payload) if isinstance(payload, dict) else None

    def create(
        self,
        *,
        name: str,
        role: str = "custom",
        adapter_type: str = "process",
        adapter_config: dict | None = None,
        description: str = "",
        agent_id: str | None = None,
        actor: str = "operator",
    ) -> Agent:
        if role not in AGENT_ROLES:
            raise ValueError(f"unknown role: {role!r} (allowed: {AGENT_ROLES})")
        agent = Agent(
            id=agent_id or _gen_agent_id(name),
            name=name,
            role=role,
            description=description,
            adapter_type=adapter_type,
            adapter_config=dict(adapter_config or {}),
            status="active",
            created_at=iso_now(),
            updated_at=iso_now(),
        )
        if self.get(agent.id) is not None:
            raise ValueError(f"agent already exists: {agent.id!r}")
        atomic_write_json(self._agent_path(agent.id), agent.to_dict())
        self._audit("agent.created", agent.id, before=None, after=agent.to_dict(), actor=actor)
        return agent

    def update(self, agent: Agent, *, actor: str = "operator") -> Agent:
        before = self.get(agent.id)
        if before is None:
            raise AgentNotFound(agent.id)
        new = replace(agent, updated_at=iso_now())
        atomic_write_json(self._agent_path(new.id), new.to_dict())
        self._audit(
            "agent.updated",
            new.id,
            before=before.to_dict(),
            after=new.to_dict(),
            actor=actor,
        )
        return new

    def pause(self, agent_id: str, *, actor: str = "operator") -> Agent:
        agent = self._require(agent_id)
        if agent.status == "paused":
            return agent
        new = replace(agent, status="paused", paused_at=iso_now(), updated_at=iso_now())
        atomic_write_json(self._agent_path(new.id), new.to_dict())
        self._audit(
            "agent.paused",
            new.id,
            before={"status": agent.status},
            after={"status": "paused"},
            actor=actor,
        )
        return new

    def resume(self, agent_id: str, *, actor: str = "operator") -> Agent:
        agent = self._require(agent_id)
        if agent.status == "active":
            return agent
        new = replace(agent, status="active", paused_at="", updated_at=iso_now())
        atomic_write_json(self._agent_path(new.id), new.to_dict())
        self._audit(
            "agent.resumed",
            new.id,
            before={"status": agent.status},
            after={"status": "active"},
            actor=actor,
        )
        return new

    def retire(self, agent_id: str, *, actor: str = "operator") -> Agent:
        agent = self._require(agent_id)
        new = replace(agent, status="retired", updated_at=iso_now())
        atomic_write_json(self._agent_path(new.id), new.to_dict())
        self._audit(
            "agent.retired",
            new.id,
            before={"status": agent.status},
            after={"status": "retired"},
            actor=actor,
        )
        return new

    # ----- helpers ----------------------------------------------------

    def _require(self, agent_id: str) -> Agent:
        agent = self.get(agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        return agent

    def _audit(
        self,
        action: str,
        agent_id: str,
        *,
        before: dict | None,
        after: dict | None,
        actor: str,
    ) -> None:
        try:
            self.store.append_audit_event(
                AuditEvent(
                    at=iso_now(),
                    actor_id=actor,
                    action=action,
                    subject_kind="agent",
                    subject_id=agent_id,
                    before=before,
                    after=after,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to emit %s audit event", action)


def _gen_agent_id(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "-" for c in name.lower()).strip("-")
    return f"{safe or 'agent'}-{uuid.uuid4().hex[:8]}"


# ──────────────────────────────────────────────────────────────────────
# Config integration: parse ``agents:`` block from backoffice.yaml
# ──────────────────────────────────────────────────────────────────────


def sync_from_config(raw_agents: dict | list | None, registry: AgentRegistry | None = None) -> list[Agent]:
    """Reconcile the ``agents:`` config block with the registry.

    For each declared agent: create if missing, update adapter_config
    if changed. Never deletes — operators retire agents explicitly.
    Returns the resulting list of agents.
    """
    if registry is None:
        registry = AgentRegistry()

    declarations: list[dict] = []
    if isinstance(raw_agents, dict):
        for name, body in raw_agents.items():
            if isinstance(body, dict):
                declarations.append({"name": name, **body})
    elif isinstance(raw_agents, list):
        declarations = [d for d in raw_agents if isinstance(d, dict) and d.get("name")]

    out: list[Agent] = []
    for decl in declarations:
        name = str(decl.get("name", "")).strip()
        if not name:
            continue
        agent_id = str(decl.get("id") or "").strip() or _id_from_name(name)
        existing = registry.get(agent_id)
        if existing is None:
            try:
                out.append(
                    registry.create(
                        agent_id=agent_id,
                        name=name,
                        role=str(decl.get("role", "custom")),
                        adapter_type=str(decl.get("adapter_type", "process")),
                        adapter_config=dict(decl.get("adapter_config", {}) or {}),
                        description=str(decl.get("description", "")),
                        actor="config",
                    )
                )
            except ValueError:
                continue
        else:
            updated = replace(
                existing,
                name=name,
                role=str(decl.get("role", existing.role)),
                adapter_type=str(decl.get("adapter_type", existing.adapter_type)),
                adapter_config=dict(decl.get("adapter_config", {}) or {}) or existing.adapter_config,
                description=str(decl.get("description", existing.description)),
            )
            out.append(registry.update(updated, actor="config"))
    return out


def _id_from_name(name: str) -> str:
    """Stable id generator for config-declared agents (no random suffix)."""
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "-" for c in name.lower()).strip("-")
    return safe or "agent"


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backoffice agents", description="Agent registry")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List registered agents")

    show = sub.add_parser("show", help="Show one agent by id")
    show.add_argument("agent_id")

    create = sub.add_parser("create", help="Create a new agent")
    create.add_argument("--name", required=True)
    create.add_argument("--role", default="custom", choices=AGENT_ROLES)
    create.add_argument("--adapter-type", default="process")
    create.add_argument("--description", default="")
    create.add_argument("--id", dest="agent_id", default=None)
    create.add_argument("--by", default="operator")

    pause = sub.add_parser("pause", help="Pause an agent")
    pause.add_argument("agent_id")
    pause.add_argument("--by", default="operator")

    resume = sub.add_parser("resume", help="Resume a paused agent")
    resume.add_argument("agent_id")
    resume.add_argument("--by", default="operator")

    retire = sub.add_parser("retire", help="Retire an agent")
    retire.add_argument("agent_id")
    retire.add_argument("--by", default="operator")

    args = parser.parse_args(argv)
    registry = AgentRegistry()

    if args.cmd == "list":
        agents = registry.list()
        if not agents:
            print("(no agents registered)")
            return 0
        for a in agents:
            print(f"{a.id}\t{a.role}\t{a.status}\t{a.adapter_type}\t{a.name}")
        return 0

    if args.cmd == "show":
        agent = registry.get(args.agent_id)
        if agent is None:
            print(f"not found: {args.agent_id}", file=sys.stderr)
            return 2
        print(json.dumps(agent.to_dict(), indent=2))
        return 0

    if args.cmd == "create":
        agent = registry.create(
            name=args.name,
            role=args.role,
            adapter_type=args.adapter_type,
            description=args.description,
            agent_id=args.agent_id,
            actor=args.by,
        )
        print(agent.id)
        return 0

    if args.cmd == "pause":
        registry.pause(args.agent_id, actor=args.by)
        return 0

    if args.cmd == "resume":
        registry.resume(args.agent_id, actor=args.by)
        return 0

    if args.cmd == "retire":
        registry.retire(args.agent_id, actor=args.by)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
