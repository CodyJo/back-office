"""Tests for ProcessAdapter using harmless local commands."""
from __future__ import annotations

from pathlib import Path

import pytest

from backoffice.adapters import ProcessAdapter
from backoffice.adapters.base import AdapterContext, InvocationDenied
from backoffice.domain import Agent, Run, Task


def _agent(command: str = "bash -c 'echo ok'", **extra) -> Agent:
    return Agent(
        id="a-process",
        name="proc-agent",
        role="custom",
        status="active",
        adapter_type="process",
        adapter_config={"command": command, **extra},
    )


def test_process_runs_simple_command():
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent("bash -c 'echo hello'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-1", task_id="t1"),
        context=AdapterContext(),
    )
    s = a.status(run=Run(id="r-pa-1", task_id="t1"), handle=handle)
    assert s.state == "succeeded"
    assert s.exit_code == 0
    assert "hello" in s.output_summary


def test_process_failure_recorded():
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent("bash -c 'exit 7'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-2", task_id="t1"),
        context=AdapterContext(),
    )
    s = a.status(run=Run(id="r-pa-2", task_id="t1"), handle=handle)
    assert s.state == "failed"
    assert s.exit_code == 7


def test_process_timeout_returns_timed_out():
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent("bash -c 'sleep 5'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-3", task_id="t1"),
        context=AdapterContext(timeout_seconds=1),
    )
    s = a.status(run=Run(id="r-pa-3", task_id="t1"), handle=handle)
    assert s.state == "timed_out"


def test_process_refuses_paused_agent():
    a = ProcessAdapter()
    paused = _agent()
    paused = Agent(**{**paused.__dict__, "status": "paused"})
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=paused,
            task=Task(id="t1", repo="r", title="x"),
            run=Run(id="r-pa-4", task_id="t1"),
            context=AdapterContext(),
        )


def test_process_requires_command_in_config():
    a = ProcessAdapter()
    bare = Agent(id="a", name="bare", role="custom", status="active",
                 adapter_type="process", adapter_config={})
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=bare,
            task=Task(id="t1", repo="r", title="x"),
            run=Run(id="r-pa-5", task_id="t1"),
            context=AdapterContext(),
        )


def test_process_dry_run_skips_execution(tmp_path: Path):
    """In dry-run mode the command must not actually run."""
    sentinel = tmp_path / "ran.txt"
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent(f"bash -c 'touch {sentinel}'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-6", task_id="t1"),
        context=AdapterContext(dry_run=True),
    )
    s = a.status(run=Run(id="r-pa-6", task_id="t1"), handle=handle)
    assert s.state == "succeeded"
    assert "dry-run" in s.output_summary
    assert not sentinel.exists()


def test_process_env_allowlist_drops_unlisted(monkeypatch: pytest.MonkeyPatch):
    """SECRET_TOKEN is in the parent env but not in the allowlist; child
    must not see it."""
    monkeypatch.setenv("SECRET_TOKEN", "topsecret")
    monkeypatch.setenv("SAFE_VAR", "ok")

    a = ProcessAdapter()
    # bash will print empty for unset vars, so we look for the token.
    handle = a.invoke(
        agent=_agent("bash -c 'echo \"saw=${SECRET_TOKEN:-unset}/safe=${SAFE_VAR:-unset}\"'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-7", task_id="t1"),
        context=AdapterContext(env_allowlist=["SAFE_VAR"]),
    )
    s = a.status(run=Run(id="r-pa-7", task_id="t1"), handle=handle)
    assert s.state == "succeeded"
    assert "saw=unset" in s.output_summary
    assert "safe=ok" in s.output_summary
    assert "topsecret" not in s.output_summary


def test_process_cancel_after_completion_is_safe():
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent("bash -c 'echo done'"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-8", task_id="t1"),
        context=AdapterContext(),
    )
    res = a.cancel(run=Run(id="r-pa-8", task_id="t1"), handle=handle)
    assert res.cancelled is False
    assert "succeeded" in res.reason or "already" in res.reason


def test_process_handles_missing_executable():
    a = ProcessAdapter()
    handle = a.invoke(
        agent=_agent("/nonexistent/binary"),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r-pa-9", task_id="t1"),
        context=AdapterContext(),
    )
    s = a.status(run=Run(id="r-pa-9", task_id="t1"), handle=handle)
    assert s.state == "failed"
    assert "failed to launch" in s.error or s.error
