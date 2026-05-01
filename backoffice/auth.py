"""Per-agent API tokens and scope checks.

Phase 9 introduces agent identity for API calls. The dashboard's
operator API key (existing) authenticates humans; per-agent tokens
authenticate registered agents. Tokens are stored hashed (SHA-256
hex) so the on-disk file never carries plaintext secrets.

Storage: ``results/agent-tokens.json`` — a small JSON map of
``{token_hash: {agent_id, scopes, created_at, last_used_at}}``.

The file lives under ``results/`` (gitignored), never under ``config/``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backoffice.store import FileStore
from backoffice.store.atomic import atomic_write_json

logger = logging.getLogger(__name__)


TOKENS_FILE = "agent-tokens.json"


# ──────────────────────────────────────────────────────────────────────
# Scopes
# ──────────────────────────────────────────────────────────────────────

# Agent scopes — keep small and obvious.
SCOPE_READ_TASKS = "tasks:read"
SCOPE_CHECKOUT = "tasks:checkout"
SCOPE_RUN_LOG = "runs:log"
SCOPE_RUN_ARTIFACT = "runs:artifact"
SCOPE_RUN_COST = "runs:cost"
SCOPE_RUN_READY = "runs:ready_for_review"
SCOPE_REQUEST_APPROVAL = "approvals:request"

DEFAULT_AGENT_SCOPES = (
    SCOPE_READ_TASKS,
    SCOPE_CHECKOUT,
    SCOPE_RUN_LOG,
    SCOPE_RUN_ARTIFACT,
    SCOPE_RUN_COST,
    SCOPE_RUN_READY,
    SCOPE_REQUEST_APPROVAL,
)


# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenRecord:
    token_hash: str
    agent_id: str
    scopes: tuple[str, ...]
    created_at: str
    last_used_at: str = ""

    def to_dict(self) -> dict:
        return {
            "token_hash": self.token_hash,
            "agent_id": self.agent_id,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


@dataclass(frozen=True)
class AuthResult:
    """Outcome of :func:`authenticate_token`."""

    ok: bool
    agent_id: str = ""
    scopes: tuple[str, ...] = ()
    reason: str = ""

    def has_scope(self, scope: str) -> bool:
        return self.ok and scope in self.scopes


# ──────────────────────────────────────────────────────────────────────


def _tokens_path(store: FileStore) -> Path:
    return store.audit_log_path().parent / TOKENS_FILE


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(store: FileStore) -> dict[str, dict]:
    path = _tokens_path(store)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _save(store: FileStore, data: dict[str, dict]) -> None:
    atomic_write_json(_tokens_path(store), data)


# ──────────────────────────────────────────────────────────────────────
# Token CRUD
# ──────────────────────────────────────────────────────────────────────


def issue_token(
    store: FileStore,
    *,
    agent_id: str,
    scopes: tuple[str, ...] | list[str] | None = None,
    actor: str = "operator",
) -> str:
    """Issue a new token for *agent_id* and return the **plaintext**.

    The plaintext is returned **once**. Only the SHA-256 hash is
    persisted; it is impossible to recover the plaintext later. Make
    sure the operator captures it.
    """
    if not agent_id:
        raise ValueError("agent_id is required")
    token = f"bo-{secrets.token_urlsafe(32)}"
    record = TokenRecord(
        token_hash=_hash(token),
        agent_id=agent_id,
        scopes=tuple(scopes) if scopes is not None else DEFAULT_AGENT_SCOPES,
        created_at=_iso_now(),
    )
    data = _load(store)
    data[record.token_hash] = record.to_dict()
    _save(store, data)
    _audit(store, "token.issued", agent_id, {"agent_id": agent_id, "scopes": list(record.scopes)}, actor)
    return token


def revoke_token(store: FileStore, *, token: str = "", token_hash: str = "", actor: str = "operator") -> bool:
    """Revoke a single token. At least one of *token* and *token_hash*
    must be provided. Returns True if a record was removed."""
    h = token_hash or (_hash(token) if token else "")
    if not h:
        return False
    data = _load(store)
    record = data.pop(h, None)
    if record is None:
        return False
    _save(store, data)
    _audit(store, "token.revoked", record.get("agent_id", ""), {"token_hash": h[:16]}, actor)
    return True


def revoke_all_for_agent(store: FileStore, agent_id: str, *, actor: str = "operator") -> int:
    data = _load(store)
    drop = [h for h, rec in data.items() if rec.get("agent_id") == agent_id]
    for h in drop:
        data.pop(h, None)
    if drop:
        _save(store, data)
        _audit(store, "token.revoked_all", agent_id, {"count": len(drop)}, actor)
    return len(drop)


def list_tokens(store: FileStore) -> list[TokenRecord]:
    data = _load(store)
    return [
        TokenRecord(
            token_hash=h,
            agent_id=rec.get("agent_id", ""),
            scopes=tuple(rec.get("scopes") or DEFAULT_AGENT_SCOPES),
            created_at=rec.get("created_at", ""),
            last_used_at=rec.get("last_used_at", ""),
        )
        for h, rec in data.items()
    ]


# ──────────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────────


def authenticate_token(store: FileStore, token: str) -> AuthResult:
    """Validate *token* against the store. Records last_used_at on success.

    Comparison uses :func:`hmac.compare_digest` to avoid timing attacks
    on the hash lookup.
    """
    if not token:
        return AuthResult(ok=False, reason="missing_token")
    candidate = _hash(token)
    data = _load(store)
    for h, rec in data.items():
        if hmac.compare_digest(h, candidate):
            rec["last_used_at"] = _iso_now()
            _save(store, data)
            return AuthResult(
                ok=True,
                agent_id=str(rec.get("agent_id", "")),
                scopes=tuple(rec.get("scopes") or ()),
            )
    return AuthResult(ok=False, reason="unknown_token")


def authorize(
    auth: AuthResult,
    *,
    required_scope: str,
    target_agent_id: str = "",
) -> tuple[bool, str]:
    """Combine authentication + scope + cross-agent isolation.

    Returns ``(allowed, reason)``. ``target_agent_id`` is the agent
    the request *targets* (for example, the agent that owns the run
    the caller is trying to log against). When set, only the
    matching agent may proceed — preventing cross-agent mutations.
    """
    if not auth.ok:
        return False, auth.reason or "unauthenticated"
    if required_scope and not auth.has_scope(required_scope):
        return False, f"missing_scope:{required_scope}"
    if target_agent_id and target_agent_id != auth.agent_id:
        return False, "cross_agent_denied"
    return True, "ok"


# ──────────────────────────────────────────────────────────────────────


def _audit(store: FileStore, action: str, subject_id: str, after: dict, actor: str) -> None:
    try:
        from backoffice.domain import AuditEvent  # local
        store.append_audit_event(
            AuditEvent(
                id=f"evt-{uuid.uuid4().hex[:12]}",
                at=_iso_now(),
                actor_id=actor,
                action=action,
                subject_kind="agent_token",
                subject_id=subject_id,
                after=after,
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to emit %s audit event", action)
