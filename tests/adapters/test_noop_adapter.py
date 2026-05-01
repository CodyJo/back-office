"""Tests for NoopAdapter and the adapter registry."""
from __future__ import annotations

import pytest

from backoffice.adapters import NoopAdapter, get, registry
from backoffice.adapters.base import AdapterContext, InvocationDenied
from backoffice.domain import Agent, Run, Task


def _agent(status: str = "active") -> Agent:
    return Agent(id="a1", name="noop-agent", role="custom", status=status, adapter_type="noop")


def test_noop_invoke_returns_handle():
    a = NoopAdapter()
    handle = a.invoke(
        agent=_agent(),
        task=Task(id="t1", repo="r", title="x"),
        run=Run(id="r1", task_id="t1"),
        context=AdapterContext(),
    )
    assert handle.adapter_type == "noop"
    assert "r1" in handle.handle


def test_noop_status_succeeded_by_default():
    a = NoopAdapter()
    handle = a.invoke(
        agent=_agent(), task=Task(id="t", repo="r", title="x"),
        run=Run(id="r1", task_id="t"), context=AdapterContext(),
    )
    s = a.status(run=Run(id="r1", task_id="t"), handle=handle)
    assert s.state == "succeeded"
    assert s.exit_code == 0


def test_noop_default_status_can_be_overridden():
    a = NoopAdapter(default_status="failed")
    handle = a.invoke(
        agent=_agent(), task=Task(id="t", repo="r", title="x"),
        run=Run(id="r1", task_id="t"), context=AdapterContext(),
    )
    s = a.status(run=Run(id="r1", task_id="t"), handle=handle)
    assert s.state == "failed"
    assert s.exit_code == 1


def test_noop_refuses_paused_agent():
    a = NoopAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent(status="paused"),
            task=Task(id="t", repo="r", title="x"),
            run=Run(id="r1", task_id="t"),
            context=AdapterContext(),
        )


def test_noop_refuses_retired_agent():
    a = NoopAdapter()
    with pytest.raises(InvocationDenied):
        a.invoke(
            agent=_agent(status="retired"),
            task=Task(id="t", repo="r", title="x"),
            run=Run(id="r1", task_id="t"),
            context=AdapterContext(),
        )


def test_noop_cancel_returns_true():
    a = NoopAdapter()
    handle = a.invoke(
        agent=_agent(), task=Task(id="t", repo="r", title="x"),
        run=Run(id="r1", task_id="t"), context=AdapterContext(),
    )
    res = a.cancel(run=Run(id="r1", task_id="t"), handle=handle)
    assert res.cancelled is True


def test_registry_has_builtins():
    reg = registry()
    assert "noop" in reg
    assert "process" in reg
    assert "legacy_backend" in reg


def test_get_returns_class():
    cls = get("noop")
    assert cls is NoopAdapter
    assert get("does-not-exist") is None
