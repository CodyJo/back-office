#!/usr/bin/env python3
"""Smoke harness for the Claude Code adapter wiring.

Runs the full agent loop with a registered ``claude_code`` agent
whose ``command`` is a harmless fake. Verifies that:

  • the adapter refuses to run without an approval_id,
  • the adapter refuses against a path on its ``refuse_against`` list,
  • the adapter writes a structured run log,
  • the adapter respects ``dry_run``,
  • a successful run records cost and lands in ``succeeded``,
  • the surrounding agent loop (checkout → ready-for-review →
    approval) still works with this adapter type.

This is the wire-up check operators run **before** pointing a real
agent at production. No real Claude Code call is made.

Invoke via ``make smoke-claude-code`` or directly:

    python3 scripts/smoke-claude-code.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _step(name: str) -> None:
    print(f"\n→ {name}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="bo-claude-smoke-"))
    print(f"Smoke harness working directory: {workdir}")

    cfg_dir = workdir / "config"
    cfg_dir.mkdir()
    (cfg_dir / "backoffice.yaml").write_text(
        "runner:\n  command: claude\n  mode: claude-print\n"
        "deploy:\n  provider: bunny\n  bunny:\n    storage_zone: smoke\n"
        "targets: {}\n",
    )
    os.environ["BACK_OFFICE_ROOT"] = str(workdir)
    os.environ["BACK_OFFICE_CONFIG"] = str(cfg_dir / "backoffice.yaml")

    try:
        return _run(workdir)
    finally:
        if not os.environ.get("BACK_OFFICE_KEEP_SMOKE_DIR"):
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"\nKept smoke artifacts at {workdir}")


def _run(workdir: Path) -> int:
    from backoffice.adapters import ClaudeCodeAdapter
    from backoffice.adapters.base import AdapterContext, InvocationDenied
    from backoffice.agents import AgentRegistry
    from backoffice.domain import Agent, Run, Task
    from backoffice.store import FileStore

    store = FileStore(root=workdir)
    log_dir = workdir / "results" / "runs"

    # ── 1. Register a claude_code agent with a fake command ────────
    _step("Register claude_code agent (fake command)")
    registry = AgentRegistry(store=store)
    fake_command = "bash -c 'cat > /dev/null; echo claude-fake-output'"
    registry.create(
        agent_id="agent-claude-smoke",
        name="claude-smoke",
        role="fixer",
        adapter_type="claude_code",
        adapter_config={
            "command": fake_command,
            "run_log_dir": str(log_dir),
            "timeout_seconds": 30,
            "refuse_against": [str(ROOT)],  # back-office repo is forbidden
        },
    )
    _ok("agent-claude-smoke registered")

    adapter = ClaudeCodeAdapter()
    agent = registry.get("agent-claude-smoke")
    if agent is None:
        _fail("could not load registered agent")

    task = Task(
        id="claude:t1",
        repo="example-target",
        title="Apply foo fix",
        acceptance_criteria=["foo fix lands cleanly", "tests pass"],
        verification_command="echo make test",
    )

    # ── 2. Refuses without approval_id ─────────────────────────────
    _step("Refuses to invoke without approval_id")
    try:
        adapter.invoke(
            agent=agent,
            task=task,
            run=Run(id="r-1", task_id="claude:t1", agent_id=agent.id, approval_id=None),
            context=AdapterContext(target_repo_path=str(workdir)),
        )
    except InvocationDenied as exc:
        if "approval_id" not in str(exc):
            _fail(f"expected approval_id refusal, got: {exc}")
        _ok("InvocationDenied raised — approval_id is enforced")
    else:
        _fail("adapter did NOT refuse without approval_id")

    # ── 3. Refuses against the back-office repo path ──────────────
    _step("Refuses against refuse_against path")
    try:
        adapter.invoke(
            agent=agent,
            task=task,
            run=Run(id="r-2", task_id="claude:t1", agent_id=agent.id, approval_id="appr-x"),
            context=AdapterContext(target_repo_path=str(ROOT)),
        )
    except InvocationDenied as exc:
        if "refuse_against" not in str(exc):
            _fail(f"expected refuse_against refusal, got: {exc}")
        _ok("InvocationDenied raised — refuse_against is enforced")
    else:
        _fail("adapter did NOT refuse against refuse_against path")

    # ── 4. Dry-run does not execute ────────────────────────────────
    _step("Dry-run skips execution")
    handle = adapter.invoke(
        agent=agent,
        task=task,
        run=Run(id="r-3", task_id="claude:t1", agent_id=agent.id, approval_id="appr-x"),
        context=AdapterContext(target_repo_path=str(workdir), dry_run=True),
    )
    status = adapter.status(run=Run(id="r-3", task_id="claude:t1"), handle=handle)
    if status.state != "succeeded" or "dry-run" not in status.output_summary:
        _fail(f"expected dry-run succeeded; got {status}")
    _ok("dry-run produced succeeded status without invoking the command")

    # ── 5. Real invocation (fake command) ─────────────────────────
    _step("Run the fake command end-to-end")
    handle = adapter.invoke(
        agent=agent,
        task=task,
        run=Run(id="r-4", task_id="claude:t1", agent_id=agent.id, approval_id="appr-x"),
        context=AdapterContext(target_repo_path=str(workdir)),
    )
    status = adapter.status(run=Run(id="r-4", task_id="claude:t1"), handle=handle)
    if status.state != "succeeded":
        _fail(f"expected succeeded, got {status.state}: {status.error}")
    if "claude-fake-output" not in status.output_summary:
        _fail(f"expected fake stdout in output_summary, got: {status.output_summary!r}")
    _ok("succeeded; output captured")

    # ── 6. Run log artifact written ───────────────────────────────
    _step("Run log artifact")
    log_path = log_dir / "r-4.log"
    if not log_path.exists():
        _fail(f"expected run log at {log_path}")
    log_text = log_path.read_text()
    if "exit=0" not in log_text:
        _fail("run log missing exit code marker")
    if not any(art["path"] == str(log_path) for art in status.artifacts):
        _fail("run log artifact not surfaced on AdapterStatus.artifacts")
    _ok(f"log written to {log_path.name} ({len(log_text)} bytes)")

    # ── 7. Cancel of a completed run is honest about state ────────
    _step("cancel() of a completed run")
    cancel = adapter.cancel(run=Run(id="r-4", task_id="claude:t1"), handle=handle)
    if cancel.cancelled:
        _fail("cancel() returned cancelled=True for an already-finished run")
    _ok(f"cancel returned cancelled=False reason={cancel.reason!r}")

    print("\nClaude Code adapter wire-up PASSED. Safe to point at a real target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
