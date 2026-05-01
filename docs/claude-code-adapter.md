# Claude Code Adapter

`backoffice.adapters.claude_code.ClaudeCodeAdapter` runs an approved
task through Claude Code in a controlled workspace.

---

## Safety rules

The adapter refuses to invoke when:

* The agent is not `active`.
* The `Run` has no `approval_id` — work was not approved.
* `adapter_config.command` is missing.
* The target repo path matches any entry in
  `adapter_config.refuse_against`.

These checks raise `InvocationDenied` before any subprocess starts.

---

## Configuration

```yaml
agents:
  claude-fixer:
    role: fixer
    adapter_type: claude_code
    adapter_config:
      # The actual binary. Use a fake command in tests; default is
      # disabled so an unconfigured deployment can't accidentally run.
      command: "claude --model claude-opus-4-7 --print"
      timeout_seconds: 1800
      run_log_dir: results/runs           # one .log per run id
      env_allowlist: [PATH, HOME]
      refuse_against:
        - /home/merm/projects/back-office  # never act on the control plane
      prompt_template_text: |              # optional override
        # Task
        {title}
        # Repo
        {repo}
        # Acceptance criteria
        {acceptance}
        # Allowed scope
        {allowed_scope}
        # Test command
        {test_command}
      allowed_files:
        - src/
        - tests/
      test_command: "make test"
```

If `prompt_template_text` is omitted the adapter uses
`DEFAULT_PROMPT_TEMPLATE` (see the module source). The prompt is
streamed via stdin so we never interpolate task content into shell
arguments.

---

## Workflow

1. Operator approves a task → `Run` is created with `approval_id`.
2. Adapter starts; writes `<run_log_dir>/<run_id>.log` with command
   bookends, stdout, and stderr.
3. Run completes; status reflects exit code (`succeeded` /
   `failed` / `timed_out`).
4. Agent calls `POST /api/runs/<id>/ready-for-review` when the
   adapter reports success and the agent is satisfied with the diff.
5. Operator clicks **Request PR** on the dashboard → draft PR opens
   with Back Office provenance in the body.

The adapter never auto-merges, never pushes, never commits.
Implementation lands on the working branch the agent created (the
existing `agents/fix-bugs.sh --preview` flow continues to work
unchanged for shell-based agents).

---

## Test mode

In tests we configure `command: "bash -c 'cat > /dev/null; echo done'"`
or similar. The adapter behaves identically; only the binary changes.
This is exercised by `tests/adapters/test_claude_code_adapter.py`.

---

## Production checklist

Before pointing a real agent at a target repo:

- [ ] Wire smoke passes: `make smoke-claude-code` (uses a fake
  command — no real model call).
- [ ] Wire smoke passes: `make smoke` (full agent loop end-to-end).
- [ ] Approval workflow tested end-to-end (`pending_approval → ready
  → checked_out → ready_for_review → pr_open`).
- [ ] `refuse_against` lists every repo the agent must not touch
  (including the back-office repo if relevant).
- [ ] Budget configured for the agent (`python -m backoffice budgets
  list` shows the cap).
- [ ] Token issued with **only** the scopes the agent needs (`bash
  python -m backoffice tokens issue --agent-id ... --scopes
  tasks:checkout runs:log runs:cost runs:ready_for_review`).
- [ ] `dry_run_default: true` for the first cycle in production.
- [ ] Operator monitors `results/audit-events.jsonl` and
  `results/runs/<run-id>.log` for the first run.

---

## Production runbook

The agent loop the adapter participates in:

```
operator approves task
       │
       ▼
  agent calls POST /api/tasks/<id>/checkout (Bearer agent-token)
       │ ↳ task: ready → checked_out, run created
       ▼
  ClaudeCodeAdapter.invoke() runs the fake or real Claude Code CLI
  with the rendered prompt streamed over stdin
       │ ↳ stdout/stderr + exit captured to results/runs/<run-id>.log
       ▼
  agent calls POST /api/runs/<id>/cost (estimated or verified)
       │ ↳ event appended to results/cost-events.jsonl
       ▼
  agent calls POST /api/runs/<id>/ready-for-review
       │ ↳ run: → succeeded, task: → ready_for_review
       ▼
  operator opens draft PR via dashboard / /api/tasks/request-pr
       │ ↳ pr_body() renders Back Office provenance, refuses on tests_failed
       ▼
  GitHub PR review and merge — outside Back Office's scope
```

If anything in that chain breaks, `make smoke` and
`make smoke-claude-code` will catch the regression locally before
operators see it in production.

---

## Live ops checks

After a real run completes:

```bash
# Did the run land in a terminal state?
python -m backoffice runs show <run-id>

# Did the cost event get recorded?
python -m backoffice budgets spend

# Are we under budget for this agent today?
python -m backoffice budgets evaluate --agent-id <agent-id>

# What did the audit log capture?
tail -n 20 results/audit-events.jsonl

# What did Claude actually emit?
cat results/runs/<run-id>.log
```

Each of these maps onto a piece of the lifecycle in the diagram.
