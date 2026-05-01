"""Cost & budget tracking.

Phase 7 introduces:

* Per-run cost recording via :func:`record_cost` (writes a
  :class:`backoffice.domain.CostEvent` to JSONL).
* Budget policies in ``config/backoffice.yaml`` under ``budgets:``.
* :func:`evaluate` — checks whether a new run is allowed under the
  current budget for a given scope. Returns a structured
  :class:`BudgetDecision`.

Cost is **estimated by default**. Adapters report verified costs when
the provider exposes them; otherwise downstream cost dashboards
display ``estimated`` clearly.

See ``docs/architecture/target-state.md`` §3.6, §3.7 and
``docs/architecture/phased-roadmap.md`` Phase 7.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from backoffice.domain import CostEvent, iso_now
from backoffice.store import FileStore
from backoffice.store.atomic import append_jsonl_line

logger = logging.getLogger(__name__)


COST_EVENTS_FILE = "cost-events.jsonl"


# ──────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────

VALID_SCOPES = ("global", "target", "department", "agent", "task", "run")
VALID_PERIODS = ("daily", "weekly", "monthly", "rolling_24h", "lifetime")


@dataclass(frozen=True)
class Budget:
    """One budget rule.

    ``scope_id`` is the discriminator for non-global scopes — e.g. the
    target name, the agent id, etc. For ``scope=global`` it is empty.
    """

    id: str
    scope: str  # one of VALID_SCOPES
    scope_id: str = ""
    period: str = "lifetime"  # one of VALID_PERIODS
    soft_limit_usd: float | None = None
    hard_limit_usd: float | None = None
    notes: str = ""

    def __post_init__(self):
        if self.scope not in VALID_SCOPES:
            raise ValueError(f"invalid scope {self.scope!r}; expected one of {VALID_SCOPES}")
        if self.period not in VALID_PERIODS:
            raise ValueError(f"invalid period {self.period!r}; expected one of {VALID_PERIODS}")
        if self.scope != "global" and not self.scope_id:
            raise ValueError(f"scope {self.scope!r} requires non-empty scope_id")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "period": self.period,
            "soft_limit_usd": self.soft_limit_usd,
            "hard_limit_usd": self.hard_limit_usd,
            "notes": self.notes,
        }


# Decision codes — stable strings.
ALLOW = "allow"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class BudgetDecision:
    state: str  # allow | warn | block
    spent_usd: float
    limit_usd: float | None
    budget_id: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.state in (ALLOW, WARN)


# ──────────────────────────────────────────────────────────────────────
# Cost recording
# ──────────────────────────────────────────────────────────────────────


def record_cost(
    store: FileStore,
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    verified: bool = False,
    source: str = "estimate",
    run_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    target: str | None = None,
) -> CostEvent:
    """Append one cost event to ``results/cost-events.jsonl``.

    The default ``source`` is ``"estimate"``; adapters set it to
    ``"adapter_reported"`` and provider integrations set
    ``"provider_api"``.
    """
    event = CostEvent(
        id=f"cost-{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        task_id=task_id,
        agent_id=agent_id,
        target=target,
        provider=provider,
        model=model,
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        total_tokens=int((input_tokens or 0) + (output_tokens or 0)),
        estimated_cost_usd=float(estimated_cost_usd or 0.0),
        verified=bool(verified),
        source=source,
        timestamp=iso_now(),
    )
    append_jsonl_line(_cost_path(store), event.to_dict())
    return event


def list_cost_events(store: FileStore) -> list[CostEvent]:
    path = _cost_path(store)
    if not path.exists():
        return []
    out: list[CostEvent] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json
                payload = json.loads(line)
            except (ValueError, OSError):
                continue
            if isinstance(payload, dict):
                out.append(CostEvent.from_dict(payload))
    except OSError as exc:
        logger.warning("could not read cost log %s: %s", path, exc)
        return []
    return out


def total_cost(events: Iterable[CostEvent]) -> float:
    return sum(float(e.estimated_cost_usd or 0.0) for e in events)


def cost_breakdown(events: Iterable[CostEvent]) -> dict[str, dict[str, float]]:
    """Group totals by agent_id, target, and provider."""
    out = {"by_agent": {}, "by_target": {}, "by_provider": {}}
    for e in events:
        if e.agent_id:
            out["by_agent"][e.agent_id] = out["by_agent"].get(e.agent_id, 0.0) + float(e.estimated_cost_usd or 0.0)
        if e.target:
            out["by_target"][e.target] = out["by_target"].get(e.target, 0.0) + float(e.estimated_cost_usd or 0.0)
        if e.provider:
            out["by_provider"][e.provider] = out["by_provider"].get(e.provider, 0.0) + float(e.estimated_cost_usd or 0.0)
    return out


# ──────────────────────────────────────────────────────────────────────
# Budget evaluation
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _Context:
    target: str = ""
    agent_id: str = ""
    task_id: str = ""
    run_id: str = ""
    department: str = ""


def _matches_scope(budget: Budget, ctx: _Context) -> bool:
    if budget.scope == "global":
        return True
    if budget.scope == "target":
        return budget.scope_id == ctx.target
    if budget.scope == "department":
        return budget.scope_id == ctx.department
    if budget.scope == "agent":
        return budget.scope_id == ctx.agent_id
    if budget.scope == "task":
        return budget.scope_id == ctx.task_id
    if budget.scope == "run":
        return budget.scope_id == ctx.run_id
    return False


def _filter_events(events: Iterable[CostEvent], ctx: _Context) -> list[CostEvent]:
    selected = []
    for e in events:
        if ctx.target and e.target and e.target != ctx.target:
            continue
        if ctx.agent_id and e.agent_id and e.agent_id != ctx.agent_id:
            continue
        if ctx.task_id and e.task_id and e.task_id != ctx.task_id:
            continue
        if ctx.run_id and e.run_id and e.run_id != ctx.run_id:
            continue
        selected.append(e)
    return selected


def _period_window_start(period: str, now: datetime) -> datetime | None:
    """Return the inclusive start of the period window for *now*.

    ``None`` means "no window" — sum the entire history (``lifetime``).
    All windows are computed in UTC.
    """
    now = now.astimezone(timezone.utc)
    if period == "lifetime":
        return None
    if period == "rolling_24h":
        return now - timedelta(hours=24)
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "weekly":
        # ISO week: Monday is the first day.
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=midnight.weekday())
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _parse_event_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Tolerate the trailing "Z" form and naive timestamps.
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _events_in_window(
    events: Iterable[CostEvent],
    *,
    period: str,
    now: datetime,
) -> list[CostEvent]:
    start = _period_window_start(period, now)
    if start is None:
        return list(events)
    selected: list[CostEvent] = []
    for e in events:
        ts = _parse_event_timestamp(e.timestamp)
        if ts is None:
            # Conservative: events with no parseable timestamp count
            # toward every window. Better to over-attribute than under.
            selected.append(e)
            continue
        if ts >= start:
            selected.append(e)
    return selected


def evaluate(
    budgets: list[Budget],
    events: Iterable[CostEvent],
    *,
    target: str = "",
    agent_id: str = "",
    task_id: str = "",
    run_id: str = "",
    department: str = "",
    now: datetime | None = None,
) -> BudgetDecision:
    """Decide whether a new run is allowed.

    Returns the **most restrictive** decision across all matching
    budgets:

    * Any matching budget over its hard limit ⇒ ``BLOCK``.
    * Else any matching budget over its soft limit ⇒ ``WARN``.
    * Else ⇒ ``ALLOW`` with cumulative spend.

    Each budget's ``period`` field defines the time window over which
    spend is summed: ``daily``, ``weekly``, ``monthly``, ``rolling_24h``,
    or ``lifetime``. ``now`` is injected for testability; defaults to
    ``datetime.now(timezone.utc)``.
    """
    ctx = _Context(target=target, agent_id=agent_id, task_id=task_id, run_id=run_id, department=department)
    matching = [b for b in budgets if _matches_scope(b, ctx)]
    if not matching:
        return BudgetDecision(state=ALLOW, spent_usd=0.0, limit_usd=None)

    when = now or datetime.now(timezone.utc)

    scoped_events = _filter_events(events, ctx)

    # Per-budget evaluation — each budget filters by its own period.
    blocking_decision: BudgetDecision | None = None
    warning_decision: BudgetDecision | None = None

    for b in matching:
        window_events = _events_in_window(scoped_events, period=b.period, now=when)
        spent = total_cost(window_events)

        if b.hard_limit_usd is not None and spent >= b.hard_limit_usd:
            decision = BudgetDecision(
                state=BLOCK,
                spent_usd=spent,
                limit_usd=b.hard_limit_usd,
                budget_id=b.id,
                reason=f"hard_limit:{b.scope}:{b.scope_id or 'global'}:{b.period}",
            )
            if blocking_decision is None:
                blocking_decision = decision
            continue

        if b.soft_limit_usd is not None and spent >= b.soft_limit_usd:
            decision = BudgetDecision(
                state=WARN,
                spent_usd=spent,
                limit_usd=b.soft_limit_usd,
                budget_id=b.id,
                reason=f"soft_limit:{b.scope}:{b.scope_id or 'global'}:{b.period}",
            )
            if warning_decision is None:
                warning_decision = decision

    if blocking_decision is not None:
        return blocking_decision
    if warning_decision is not None:
        return warning_decision

    # All clear. Report spend against the most-specific matching
    # budget so callers can show context. Lifetime spend is a
    # reasonable summary value when periods differ.
    most_specific = max(matching, key=lambda b: (0 if b.scope == "global" else 1, len(b.scope_id)))
    spent = total_cost(_events_in_window(scoped_events, period=most_specific.period, now=when))
    return BudgetDecision(
        state=ALLOW,
        spent_usd=spent,
        limit_usd=most_specific.hard_limit_usd,
        budget_id=most_specific.id,
    )


# ──────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────


def from_config(raw_budgets: dict | list | None) -> list[Budget]:
    """Build a list of Budgets from the ``budgets:`` block of
    ``config/backoffice.yaml``.

    Accepts list-of-dicts (preferred) or dict-of-dicts.
    """
    out: list[Budget] = []
    declarations: list[dict] = []
    if isinstance(raw_budgets, list):
        declarations = [d for d in raw_budgets if isinstance(d, dict)]
    elif isinstance(raw_budgets, dict):
        for bid, body in raw_budgets.items():
            if isinstance(body, dict):
                declarations.append({"id": bid, **body})

    for decl in declarations:
        try:
            out.append(
                Budget(
                    id=str(decl.get("id") or f"budget-{uuid.uuid4().hex[:8]}"),
                    scope=str(decl.get("scope", "global")),
                    scope_id=str(decl.get("scope_id", "")),
                    period=str(decl.get("period", "lifetime")),
                    soft_limit_usd=_optional_float(decl.get("soft_limit_usd")),
                    hard_limit_usd=_optional_float(decl.get("hard_limit_usd")),
                    notes=str(decl.get("notes", "")),
                )
            )
        except ValueError as exc:
            logger.warning("ignoring invalid budget %s: %s", decl, exc)
    return out


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────

def _cost_path(store: FileStore) -> Path:
    return store.audit_log_path().parent / COST_EVENTS_FILE
