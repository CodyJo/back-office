"""Tests for the dual-backend orchestrator: registry, backends, and router."""
import pytest

from backoffice.backends import get_backend, get_all_backends
from backoffice.backends.base import HealthStatus, Capabilities, LimitState
from backoffice.backends.claude import ClaudeBackend
from backoffice.backends.codex import CodexBackend
from backoffice.router import Router, Assignment, TASK_TYPES


class TestClaudeBackend:
    def test_init(self):
        b = ClaudeBackend({"command": "claude", "model": "haiku"})
        assert b.name == "claude"
        assert b.model == "haiku"

    def test_capabilities(self):
        b = ClaudeBackend({})
        caps = b.capabilities()
        assert caps.long_context_reasoning is True
        assert caps.subagents is True
        assert caps.edit_files is True

    def test_check_limits(self):
        b = ClaudeBackend(
            {"local_budget": {"max_parallel_tasks": 3, "max_context_tokens": 100000}}
        )
        limits = b.check_limits()
        assert limits.recommended_parallelism == 3
        assert limits.context_window_tokens == 100000

    def test_build_command(self):
        b = ClaudeBackend({"command": "claude", "model": "haiku"})
        cmd = b.build_command("test prompt", ["Read", "Write"], "/tmp/repo")
        assert "--print" in cmd
        assert "--allowedTools" in cmd
        assert "--add-dir" in cmd
        assert "/tmp/repo" in cmd

    def test_build_command_no_tools(self):
        b = ClaudeBackend({"command": "claude", "model": "haiku"})
        cmd = b.build_command("test prompt", [], "/tmp/repo")
        assert "--print" in cmd
        assert "--allowedTools" not in cmd

    def test_build_command_model_already_in_command(self):
        b = ClaudeBackend({"command": "claude --model sonnet", "model": "haiku"})
        cmd = b.build_command("test", [], "/tmp/repo")
        # Should not add --model again since it's already in the command
        assert cmd.count("--model") == 1


class TestCodexBackend:
    def test_init(self):
        b = CodexBackend({"command": "codex"})
        assert b.name == "codex"

    def test_capabilities(self):
        b = CodexBackend({})
        caps = b.capabilities()
        assert caps.long_context_reasoning is False
        assert caps.subagents is False
        assert caps.edit_files is True

    def test_build_command(self):
        b = CodexBackend({"command": "codex"})
        cmd = b.build_command("test", ["Read"], "/tmp/repo")
        assert "codex" in cmd
        assert "-s" in cmd
        assert "workspace-write" in cmd

    def test_check_limits(self):
        b = CodexBackend(
            {"local_budget": {"max_parallel_tasks": 6, "max_context_tokens": 120000}}
        )
        limits = b.check_limits()
        assert limits.recommended_parallelism == 6
        assert limits.context_window_tokens == 120000


class TestRegistry:
    def test_get_backend_claude(self):
        b = get_backend("claude", {"command": "claude"})
        assert isinstance(b, ClaudeBackend)

    def test_get_backend_codex(self):
        b = get_backend("codex", {"command": "codex"})
        assert isinstance(b, CodexBackend)

    def test_get_backend_unknown(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("gpt4all", {})

    def test_get_all_backends(self):
        config = {
            "claude": {"enabled": True, "command": "claude"},
            "codex": {"enabled": False, "command": "codex"},
        }
        backends = get_all_backends(config)
        assert "claude" in backends
        assert "codex" not in backends  # disabled

    def test_get_all_backends_default_enabled(self):
        config = {
            "claude": {"command": "claude"},
            "codex": {"command": "codex"},
        }
        backends = get_all_backends(config)
        assert "claude" in backends
        assert "codex" in backends


class TestRouter:
    def _make_router(self, claude_healthy=True, codex_healthy=True):
        backends = {}
        if claude_healthy:
            backends["claude"] = ClaudeBackend({"command": "claude"})
        if codex_healthy:
            backends["codex"] = CodexBackend({"command": "codex"})
        policy = {
            "fallback_order": {
                "prioritize_backlog": ["claude", "codex"],
                "implement_feature": ["codex", "claude"],
                "fix_finding": ["codex", "claude"],
                "audit_repo": ["claude", "codex"],
            }
        }
        router = Router(backends, policy)
        # Mock the limit cache so we don't need real binaries
        for name in backends:
            router._limit_cache[name] = LimitState(
                backend=name,
                status="healthy",
                supports_structured_output=True,
                context_window_tokens=200000,
                rate_limit_state="ok",
                recommended_parallelism=2,
            )
        return router

    def test_routes_planning_to_claude(self):
        router = self._make_router()
        assignment = router.assign("prioritize_backlog")
        assert assignment.assigned_backend == "claude"

    def test_routes_fix_to_codex(self):
        router = self._make_router()
        assignment = router.assign("fix_finding")
        assert assignment.assigned_backend == "codex"

    def test_routes_feature_to_codex(self):
        router = self._make_router()
        assignment = router.assign("implement_feature")
        assert assignment.assigned_backend == "codex"

    def test_fallback_when_preferred_unavailable(self):
        router = self._make_router(codex_healthy=False)
        assignment = router.assign("fix_finding")
        assert assignment.assigned_backend == "claude"

    def test_no_backend_available(self):
        router = self._make_router(claude_healthy=False, codex_healthy=False)
        assignment = router.assign("audit_repo")
        assert assignment.assigned_backend == ""
        assert assignment.confidence == "low"

    def test_assignment_includes_reason(self):
        router = self._make_router()
        assignment = router.assign("audit_repo")
        assert "claude" in assignment.reason
        assert assignment.confidence in ("high", "medium")

    def test_claude_only_mode(self):
        router = self._make_router(codex_healthy=False)
        for task_type in TASK_TYPES:
            assignment = router.assign(task_type)
            assert assignment.assigned_backend == "claude"

    def test_codex_cannot_handle_planning(self):
        """Codex lacks long_context_reasoning, so it can't do prioritize_backlog."""
        router = self._make_router(claude_healthy=False)
        assignment = router.assign("prioritize_backlog")
        # Codex doesn't have long_context_reasoning, so no backend can handle it
        assert assignment.assigned_backend == ""

    def test_fallback_backend_set(self):
        router = self._make_router()
        assignment = router.assign("fix_finding")
        assert assignment.fallback_backend == "claude"

    def test_unknown_task_type_uses_any_available(self):
        router = self._make_router()
        assignment = router.assign("unknown_task")
        # Unknown task has no requirements, so first available backend wins
        assert assignment.assigned_backend != ""
