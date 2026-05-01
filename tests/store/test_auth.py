"""Tests for Phase 9 per-agent token auth + scope checks."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.auth import (
    DEFAULT_AGENT_SCOPES,
    SCOPE_CHECKOUT,
    SCOPE_RUN_LOG,
    authenticate_token,
    authorize,
    issue_token,
    list_tokens,
    revoke_all_for_agent,
    revoke_token,
)
from backoffice.store import FileStore


@pytest.fixture
def store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path)


# ──────────────────────────────────────────────────────────────────────
# Token issuance
# ──────────────────────────────────────────────────────────────────────


def test_issue_token_returns_plaintext(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    assert token.startswith("bo-")
    assert len(token) > 20


def test_issue_token_persists_only_hash(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    tokens_file = store.audit_log_path().parent / "agent-tokens.json"
    raw = tokens_file.read_text()
    assert token not in raw  # plaintext must never appear on disk


def test_issue_token_default_scopes(store: FileStore):
    issue_token(store, agent_id="agent-fix")
    tokens = list_tokens(store)
    assert len(tokens) == 1
    assert set(tokens[0].scopes) == set(DEFAULT_AGENT_SCOPES)


def test_issue_token_custom_scopes(store: FileStore):
    issue_token(store, agent_id="agent-fix", scopes=[SCOPE_RUN_LOG])
    tokens = list_tokens(store)
    assert tokens[0].scopes == (SCOPE_RUN_LOG,)


def test_issue_requires_agent_id(store: FileStore):
    with pytest.raises(ValueError):
        issue_token(store, agent_id="")


def test_issue_emits_audit_event(store: FileStore):
    issue_token(store, agent_id="agent-fix")
    events = store.read_audit_events()
    assert any(e.action == "token.issued" for e in events)


# ──────────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────────


def test_authenticate_known_token_succeeds(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    auth = authenticate_token(store, token)
    assert auth.ok
    assert auth.agent_id == "agent-fix"
    assert SCOPE_CHECKOUT in auth.scopes


def test_authenticate_unknown_token_fails(store: FileStore):
    issue_token(store, agent_id="agent-fix")
    auth = authenticate_token(store, "bo-not-a-real-token")
    assert not auth.ok
    assert auth.reason == "unknown_token"


def test_authenticate_missing_token(store: FileStore):
    auth = authenticate_token(store, "")
    assert not auth.ok
    assert auth.reason == "missing_token"


def test_authenticate_updates_last_used_at(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    auth1 = authenticate_token(store, token)
    assert auth1.ok
    rec = list_tokens(store)[0]
    assert rec.last_used_at  # populated


# ──────────────────────────────────────────────────────────────────────
# Revocation
# ──────────────────────────────────────────────────────────────────────


def test_revoke_token_blocks_future_auth(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    assert revoke_token(store, token=token)
    auth = authenticate_token(store, token)
    assert not auth.ok


def test_revoke_emits_audit_event(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    revoke_token(store, token=token)
    events = store.read_audit_events()
    assert any(e.action == "token.revoked" for e in events)


def test_revoke_all_for_agent(store: FileStore):
    issue_token(store, agent_id="a1")
    issue_token(store, agent_id="a1")
    issue_token(store, agent_id="a2")
    n = revoke_all_for_agent(store, "a1")
    assert n == 2
    remaining = list_tokens(store)
    assert len(remaining) == 1
    assert remaining[0].agent_id == "a2"


def test_revoke_unknown_returns_false(store: FileStore):
    assert revoke_token(store, token="bo-unknown") is False


# ──────────────────────────────────────────────────────────────────────
# Authorization
# ──────────────────────────────────────────────────────────────────────


def test_authorize_allows_with_scope(store: FileStore):
    token = issue_token(store, agent_id="agent-fix")
    auth = authenticate_token(store, token)
    allowed, _ = authorize(auth, required_scope=SCOPE_CHECKOUT)
    assert allowed


def test_authorize_denies_missing_scope(store: FileStore):
    token = issue_token(store, agent_id="agent-fix", scopes=[SCOPE_RUN_LOG])
    auth = authenticate_token(store, token)
    allowed, reason = authorize(auth, required_scope=SCOPE_CHECKOUT)
    assert not allowed
    assert "missing_scope" in reason


def test_authorize_denies_cross_agent(store: FileStore):
    """An agent cannot mutate another agent's resources."""
    token_a = issue_token(store, agent_id="agent-a")
    auth = authenticate_token(store, token_a)
    allowed, reason = authorize(
        auth,
        required_scope=SCOPE_RUN_LOG,
        target_agent_id="agent-b",
    )
    assert not allowed
    assert reason == "cross_agent_denied"


def test_authorize_allows_same_agent_target(store: FileStore):
    token = issue_token(store, agent_id="agent-a")
    auth = authenticate_token(store, token)
    allowed, _ = authorize(
        auth,
        required_scope=SCOPE_RUN_LOG,
        target_agent_id="agent-a",
    )
    assert allowed


def test_authorize_denies_when_not_authenticated():
    from backoffice.auth import AuthResult
    auth = AuthResult(ok=False, reason="missing_token")
    allowed, reason = authorize(auth, required_scope=SCOPE_CHECKOUT)
    assert not allowed
    assert reason == "missing_token"
