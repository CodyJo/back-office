#!/usr/bin/env python3
"""End-to-end smoke harness for the Phase 4–9 agent loop.

Runs against an isolated ``BACK_OFFICE_ROOT`` (a fresh tmpdir), so it
never touches a production deployment. Exercises:

  1. Register an agent (noop adapter).
  2. Issue a per-agent token via :func:`backoffice.auth.issue_token`.
  3. Authenticate the token.
  4. Seed a task into the queue.
  5. Atomically check it out via the agent API.
  6. Append a run log entry.
  7. Record a cost event.
  8. Move the run + task to ready_for_review.
  9. Request an approval.
 10. Operator decides the approval.
 11. Verify the audit log captured every mutation.

Exit code is 0 on success, non-zero with a clear diagnostic on
failure. Wire-through drift between any of the modules will surface
here before it surfaces in production.

Invoke via ``make smoke`` or directly:

    python3 scripts/smoke-agent-loop.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make sure we import from this checkout, not a globally-installed copy.
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
    workdir = Path(tempfile.mkdtemp(prefix="bo-smoke-"))
    print(f"Smoke harness working directory: {workdir}")

    # Provide a minimal config so load_config() works for any helper
    # the smoke path invokes.
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
        # Clean up unless the operator wanted to inspect the artifacts.
        if not os.environ.get("BACK_OFFICE_KEEP_SMOKE_DIR"):
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"\nKept smoke artifacts at {workdir}")


def _run(workdir: Path) -> int:
    import yaml

    from backoffice.agent_api import (
        handle_checkout,
        handle_decide_approval,
        handle_request_approval,
        handle_run_cost,
        handle_run_log,
        handle_run_ready_for_review,
    )
    from backoffice.agents import AgentRegistry
    from backoffice.auth import (
        AuthResult,
        DEFAULT_AGENT_SCOPES,
        authenticate_token,
        issue_token,
    )
    from backoffice.store import FileStore

    store = FileStore(root=workdir)

    # ── 1. Register agent ──────────────────────────────────────────
    _step("Register agent")
    registry = AgentRegistry(store=store)
    agent = registry.create(
        name="smoke-agent",
        agent_id="smoke-agent",
        role="fixer",
        adapter_type="noop",
    )
    _ok(f"agent {agent.id} created (status={agent.status})")

    # ── 2. Issue token ─────────────────────────────────────────────
    _step("Issue token")
    token = issue_token(store, agent_id="smoke-agent")
    if not token.startswith("bo-"):
        _fail(f"expected token to start with 'bo-', got {token!r}")
    _ok(f"plaintext returned (length={len(token)})")

    # ── 3. Authenticate token ──────────────────────────────────────
    _step("Authenticate token")
    auth = authenticate_token(store, token)
    if not auth.ok or auth.agent_id != "smoke-agent":
        _fail(f"authentication failed: {auth.reason!r}")
    _ok(f"agent_id={auth.agent_id} scopes={len(auth.scopes)}")

    # ── 4. Seed task ───────────────────────────────────────────────
    _step("Seed task")
    queue = {
        "version": 1,
        "tasks": [{
            "id": "smoke:t1",
            "repo": "back-office",
            "title": "smoke task",
            "status": "ready",
            "priority": "medium",
            "history": [],
        }],
    }
    store.task_queue_path().parent.mkdir(parents=True, exist_ok=True)
    store.task_queue_path().write_text(yaml.safe_dump(queue, sort_keys=False))
    _ok("smoke:t1 seeded as ready")

    # ── 5. Checkout ────────────────────────────────────────────────
    _step("Checkout")
    code, payload = handle_checkout(store, auth, task_id="smoke:t1", body={"adapter_type": "noop"})
    if code != 200:
        _fail(f"checkout failed: {code} {payload}")
    run_id = payload["run"]["id"]
    _ok(f"run {run_id} created, task moved to checked_out")

    # ── 6. Run log ─────────────────────────────────────────────────
    _step("Append run log")
    code, payload = handle_run_log(store, auth, run_id=run_id, body={"message": "starting"})
    if code != 200:
        _fail(f"run log failed: {code} {payload}")
    _ok("log line accepted")

    # ── 7. Cost event ──────────────────────────────────────────────
    _step("Record cost")
    code, payload = handle_run_cost(
        store, auth, run_id=run_id,
        body={
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "input_tokens": 1000,
            "output_tokens": 200,
            "estimated_cost_usd": 0.0225,
        },
    )
    if code != 200:
        _fail(f"cost record failed: {code} {payload}")
    _ok(f"cost ${payload['cost_event']['estimated_cost_usd']:.4f} recorded")

    # ── 8. Ready for review ────────────────────────────────────────
    _step("Mark ready for review")
    code, payload = handle_run_ready_for_review(store, auth, run_id=run_id, body={"note": "smoke OK"})
    if code != 200:
        _fail(f"ready-for-review failed: {code} {payload}")
    task = store.get_task("smoke:t1")
    if task is None or task.status != "ready_for_review":
        _fail(f"task did not transition: {task and task.status!r}")
    _ok(f"task in {task.status}")

    # ── 9. Request approval ────────────────────────────────────────
    _step("Request approval")
    code, payload = handle_request_approval(
        store, auth, body={"task_id": "smoke:t1", "scope": "merge", "note": "smoke"},
    )
    if code != 200:
        _fail(f"request approval failed: {code} {payload}")
    approval_id = payload["approval_id"]
    _ok(f"approval {approval_id} requested")

    # ── 10. Operator decides ───────────────────────────────────────
    _step("Operator decides approval")
    operator_auth = AuthResult(ok=True, agent_id="operator", scopes=DEFAULT_AGENT_SCOPES)
    code, payload = handle_decide_approval(
        store, operator_auth, approval_id=approval_id,
        body={"decision": "approved", "by": "smoke-operator"},
        operator_authenticated=True,
    )
    if code != 200 or payload["state"] != "approved":
        _fail(f"approval decide failed: {code} {payload}")
    _ok("approval decided=approved")

    # ── 11. Audit log captured everything ──────────────────────────
    _step("Audit log invariants")
    events = store.read_audit_events()
    actions = [e.action for e in events]
    required = {
        "agent.created",
        "token.issued",
        "run.created",
        "task.transition",
        "run.log",
        "approval.requested",
        "approval.approved",
    }
    missing = required - set(actions)
    if missing:
        _fail(f"missing audit actions: {sorted(missing)}")
    _ok(f"{len(events)} audit events covering {sorted(set(actions))}")

    # ── 12. Run record terminal ────────────────────────────────────
    _step("Run record state")
    final_run = store.get_run(run_id)
    if final_run is None or final_run.state != "succeeded":
        _fail(f"run not in succeeded: {final_run and final_run.state!r}")
    _ok(f"run {run_id} state={final_run.state}")

    # ── 13. Cost rollup ────────────────────────────────────────────
    _step("Cost rollup")
    from backoffice.budgets import cost_breakdown, list_cost_events, total_cost
    events = list_cost_events(store)
    if total_cost(events) <= 0:
        _fail("expected at least one positive cost event")
    rollup = cost_breakdown(events)
    if "smoke-agent" not in rollup["by_agent"]:
        _fail("agent rollup missing smoke-agent")
    _ok(f"total ${total_cost(events):.4f}; by_agent={rollup['by_agent']}")

    print("\nSmoke harness PASSED — Phase 4–9 wire-through is intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
