# Adapters

Adapters are the bridge between Back Office's typed domain (tasks,
runs, approvals) and the actual thing that does the work — a shell
script, a Claude Code call, a third-party API.

The contract is intentionally tiny so writing a new adapter is a
small, well-defined exercise.

---

## Contract

```python
class Adapter(Protocol):
    name: str

    def invoke(self, *, agent: Agent, task: Task, run: Run,
               context: AdapterContext) -> AdapterHandle: ...

    def status(self, *, run: Run, handle: AdapterHandle) -> AdapterStatus: ...

    def cancel(self, *, run: Run, handle: AdapterHandle) -> AdapterCancelResult: ...
```

* `invoke` starts the work and returns an opaque `AdapterHandle`.
  Back Office stores it on the `Run` and replays it on subsequent
  `status` / `cancel` calls.
* `status` returns an `AdapterStatus` whose `state` aligns with
  `RUN_STATES` (`created`, `queued`, `starting`, `running`,
  `succeeded`, `failed`, `cancelled`, `timed_out`).
* `cancel` is idempotent.

Adapters do not write to the queue, never emit audit events, never
mutate task state. They report. The control plane records.

---

## Built-in adapters

| `adapter_type` | Module | Use case |
|---|---|---|
| `noop` | `backoffice.adapters.noop` | Deterministic test fake. |
| `process` | `backoffice.adapters.process` | Shell command with timeout + env allowlist. Wraps today's `agents/*.sh`. |
| `legacy_backend` | `backoffice.adapters.legacy_backend` | Wraps the existing `backoffice.backends.Backend` (claude/codex). |
| `claude_code` | `backoffice.adapters.claude_code` | Phase 5 — runs Claude Code in a controlled workspace. See `docs/claude-code-adapter.md`. |

---

## Safety guarantees

Every adapter must:

* **Refuse to invoke** when the agent is not `active`. Built-in
  adapters raise `InvocationDenied`.
* **Honor `context.dry_run`** — no side effects when set.
* **Honor `context.timeout_seconds`** — runs killed at the deadline
  surface as `state="timed_out"`.
* **Honor `context.env_allowlist`** when spawning subprocesses —
  parent env is dropped except for explicitly listed keys + `PATH`.
* **Never auto-merge, push, or commit** to the target's default
  branch.

Tests exercise each guarantee. New adapters should follow the same
pattern.

---

## Adapter config

Per-agent in `config/backoffice.yaml`:

```yaml
agents:
  fix-agent:
    role: fixer
    adapter_type: process
    adapter_config:
      command: "bash agents/fix-bugs.sh"
      args: ["--preview"]
      env_allowlist: [PATH, HOME, BUNNY_STORAGE_KEY]
      cwd_strategy: repo
      timeout_seconds: 1800
      dry_run_default: false
```

The `adapter_config` block is opaque to Back Office — its shape is
the adapter's contract with itself. Each adapter documents the keys
it consumes.

---

## Plugins

Phase 12 lets operators register adapter plugins via
`config/backoffice.yaml`:

```yaml
plugins:
  - name: my-adapter
    extension_point: adapter
    path: /opt/backoffice-plugins/my_adapter.py
    attribute: MyAdapter
```

The plugin loader registers the class under its `name` attribute;
agents can then declare `adapter_type: my_plugin_name`.

Plugin failures are isolated: a broken plugin emits a structured
error and never breaks the rest of the system.
