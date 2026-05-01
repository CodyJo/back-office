"""Tests for ClaudeCodeAdapter using a fake command (``echo``)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.adapters import ClaudeCodeAdapter
from backoffice.adapters.base import AdapterContext, InvocationDenied
from backoffice.domain import Agent, Run, Task


def _agent(adapter_config: dict | None = None, status: str = "active") -> Agent:
    return Agent(
        id="agent-claude",
        name="claude-code-agent",
        role="fixer",
        status=status,
        adapter_type="claude_code",
        adapter_config=adapter_config or {"command": "bash -c 'cat > /dev/null; echo done'"},
    )


def _task(**overrides) -> Task:
    base = dict(
        id="t1",
        repo="back-office",
        title="Fix foo",
        acceptance_criteria=["foo passes", "tests pass"],
        verification_command="make test",
    )
    base.update(overrides)
    return Task(**base)


def _run(approval_id: str = "appr-1") -> Run:
    return Run(id="r-claude-1", task_id="t1", agent_id="agent-claude", approval_id=approval_id)


def test_invoke_succeeds_with_fake_command(tmp_path: Path):
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({"command": "bash -c 'cat > /dev/null; echo done'", "run_log_dir": str(tmp_path)}),
        task=_task(),
        run=_run(),
        context=AdapterContext(),
    )
    s = a.status(run=_run(), handle=handle)
    assert s.state == "succeeded"
    assert s.exit_code == 0


def test_run_log_is_written(tmp_path: Path):
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({"command": "bash -c 'cat > /dev/null; echo hi'", "run_log_dir": str(tmp_path)}),
        task=_task(),
        run=_run(),
        context=AdapterContext(),
    )
    log_path = tmp_path / "r-claude-1.log"
    assert log_path.exists()
    assert "exit=0" in log_path.read_text()
    s = a.status(run=_run(), handle=handle)
    assert any(art["path"] == str(log_path) for art in s.artifacts)


def test_invoke_refuses_paused_agent(tmp_path: Path):
    a = ClaudeCodeAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent({"command": "echo x", "run_log_dir": str(tmp_path)}, status="paused"),
            task=_task(),
            run=_run(),
            context=AdapterContext(),
        )


def test_invoke_refuses_without_approval(tmp_path: Path):
    a = ClaudeCodeAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent({"command": "echo x", "run_log_dir": str(tmp_path)}),
            task=_task(),
            run=Run(id="r-claude-2", task_id="t1", agent_id="agent-claude", approval_id=None),
            context=AdapterContext(),
        )


def test_invoke_refuses_without_command(tmp_path: Path):
    a = ClaudeCodeAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent({"run_log_dir": str(tmp_path)}),
            task=_task(),
            run=_run(),
            context=AdapterContext(),
        )


def test_invoke_refuses_against_protected_path(tmp_path: Path):
    a = ClaudeCodeAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent({
                "command": "echo x",
                "run_log_dir": str(tmp_path),
                "refuse_against": ["/home/merm/projects/back-office"],
            }),
            task=_task(),
            run=_run(),
            context=AdapterContext(target_repo_path="/home/merm/projects/back-office"),
        )


def test_dry_run_does_not_execute(tmp_path: Path):
    sentinel = tmp_path / "ran.txt"
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({
            "command": f"bash -c 'touch {sentinel}; echo nope'",
            "run_log_dir": str(tmp_path),
        }),
        task=_task(),
        run=_run(),
        context=AdapterContext(dry_run=True),
    )
    s = a.status(run=_run(), handle=handle)
    assert s.state == "succeeded"
    assert "dry-run" in s.output_summary
    assert not sentinel.exists()


def test_timeout_recorded(tmp_path: Path):
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({
            "command": "bash -c 'cat > /dev/null; sleep 5'",
            "run_log_dir": str(tmp_path),
        }),
        task=_task(),
        run=_run(),
        context=AdapterContext(timeout_seconds=1),
    )
    s = a.status(run=_run(), handle=handle)
    assert s.state == "timed_out"


def test_failure_records_state(tmp_path: Path):
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({"command": "bash -c 'cat > /dev/null; exit 3'", "run_log_dir": str(tmp_path)}),
        task=_task(),
        run=_run(),
        context=AdapterContext(),
    )
    s = a.status(run=_run(), handle=handle)
    assert s.state == "failed"
    assert s.exit_code == 3


def test_default_prompt_template_renders():
    """The internal template must format with task fields and not crash."""
    a = ClaudeCodeAdapter()
    cfg = {}
    rendered = a._render_prompt(
        _task(),
        AdapterContext(),
        cfg,
    )
    assert "Fix foo" in rendered
    assert "back-office" in rendered
    assert "foo passes" in rendered
    assert "make test" in rendered


def test_explicit_prompt_text_overrides_template(tmp_path: Path):
    a = ClaudeCodeAdapter()
    handle = a.invoke(
        agent=_agent({"command": "bash -c 'cat'", "run_log_dir": str(tmp_path)}),
        task=_task(),
        run=_run(),
        context=AdapterContext(prompt="HELLO PROMPT"),
    )
    s = a.status(run=_run(), handle=handle)
    assert s.state == "succeeded"
    assert "HELLO PROMPT" in s.output_summary
