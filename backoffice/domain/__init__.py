"""Back Office domain models.

Phase 1 of the control-plane evolution: typed representations of
the queue / run / approval / agent concepts that today live as YAML/JSON
dicts. Adding these models does NOT change behavior — they are
consumed only by new code paths and round-trip tests.

See ``docs/architecture/target-state.md`` for the model definitions
and ``docs/architecture/phased-roadmap.md`` for the migration plan.
"""
from backoffice.domain.models import (
    ACTOR_KINDS,
    AGENT_ROLES,
    AGENT_STATUSES,
    APPROVAL_STATES,
    RUN_STATES,
    TASK_STATES,
    Actor,
    AdapterConfig,
    Agent,
    Approval,
    AuditEvent,
    CostEvent,
    HistoryEntry,
    Run,
    Task,
    Workspace,
    iso_now,
)
from backoffice.domain.state_machines import (
    APPROVAL_TRANSITIONS,
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    IllegalTransition,
    is_legal_approval_transition,
    is_legal_run_transition,
    is_legal_task_transition,
    transition_approval,
    transition_run,
    transition_task,
)

__all__ = [
    "ACTOR_KINDS",
    "AGENT_ROLES",
    "AGENT_STATUSES",
    "APPROVAL_STATES",
    "APPROVAL_TRANSITIONS",
    "Actor",
    "AdapterConfig",
    "Agent",
    "Approval",
    "AuditEvent",
    "CostEvent",
    "HistoryEntry",
    "IllegalTransition",
    "RUN_STATES",
    "RUN_TRANSITIONS",
    "Run",
    "TASK_STATES",
    "TASK_TRANSITIONS",
    "Task",
    "Workspace",
    "is_legal_approval_transition",
    "is_legal_run_transition",
    "is_legal_task_transition",
    "iso_now",
    "transition_approval",
    "transition_run",
    "transition_task",
]
