# Security

Back Office is privacy-first and self-hostable. This document
describes the trust model, authentication, secret handling, and
known limitations.

---

## Trust model

Three actors:

1. **Operators** — humans running the dashboard or CLI. Authenticate
   via the operator API key (`config.api.api_key`). Same key
   everywhere; rotate by editing the config.
2. **Agents** — registered programs that do work via the agent API.
   Authenticate via per-agent bearer tokens issued through
   `python -m backoffice tokens issue`. Each token is scoped to its
   agent; cross-agent mutations are denied at the auth layer.
3. **Plugins** — code loaded at startup from explicit operator
   declarations. They run with the same trust as Back Office itself
   (this is documented as experimental — see `docs/agents.md`).

Read paths (e.g. `/api/health`, `/api/agents`, dashboard static
assets) require no auth. Mutating paths require operator key or
agent token.

---

## Authentication

### Operator key

```yaml
api:
  port: 8071
  api_key: "<random hex>"
  allowed_origins:
    - https://admin.codyjo.com
    - http://localhost:8070
```

Generated via `openssl rand -hex 24`. Stored in
`config/backoffice.yaml` (gitignored). Sent as
`Authorization: Bearer <key>` or `?api_key=<key>`. Comparisons use
`hmac.compare_digest`.

### Agent tokens

Issued, stored, and verified in `backoffice/auth.py`:

```bash
python -m backoffice tokens issue --agent-id agent-fix
# bo-XXXXXXXXXXXXXXXXXXXXXXXXX
```

The plaintext is **printed once**. Only the SHA-256 hash is persisted
to `results/agent-tokens.json`. The plaintext cannot be recovered.

Tokens carry **scopes** that gate specific endpoints:

| Scope | Endpoint |
|---|---|
| `tasks:read` | `GET /api/tasks` (when agent-only auth is in use) |
| `tasks:checkout` | `POST /api/tasks/<id>/checkout` |
| `runs:log` | `POST /api/runs/<id>/log` |
| `runs:artifact` | `POST /api/runs/<id>/artifact` (Phase 6+) |
| `runs:cost` | `POST /api/runs/<id>/cost` |
| `runs:ready_for_review` | `POST /api/runs/<id>/ready-for-review` |
| `approvals:request` | `POST /api/approvals/request` |

Approval **decisions** are operator-only.

Revoke a token:

```bash
python -m backoffice tokens revoke --token bo-...
python -m backoffice tokens revoke-all --agent-id agent-fix
```

---

## Cross-agent isolation

Every agent-mutating endpoint resolves the run's `agent_id` from the
store and compares to the authenticated agent. `agent-a` calling
`/api/runs/<run-of-agent-b>/log` receives `403 cross_agent_denied`
without leaking whether the run exists.

---

## Secret handling

* **Operator API key** — `config/backoffice.yaml` is gitignored.
* **Storage / CDN keys** — read from environment variables
  (`BUNNY_STORAGE_KEY`, etc.) by `backoffice.sync.providers`.
* **Agent tokens** — SHA-256 hashed at rest.
* **Export** — `python -m backoffice export` redacts every key whose
  name contains `key`, `secret`, `token`, `password`, `credential`
  (case-insensitive, recursive). On import the redaction marker is
  treated as "leave the existing value alone" — it never becomes a
  literal string.

Audit logs and run logs **never** contain plaintext secrets — agents
that accidentally include them are still risky, but Back Office does
not stash them in artifacts under its control.

---

## File system trust

The HTTP server validates target repo paths through
`_validate_local_repo_path` against an allowlist (`<repo_root>` and
`~/projects`). Paths outside the allowlist are rejected. The
`request-pr` handler refuses to operate on the default branch
(`main`/`master`).

The `claude_code` adapter accepts a `refuse_against` list in its
config so operators can hard-block invocation against specific paths
(e.g. the back-office repo itself).

---

## Audit trail

Every mutating call writes one structured event to
`results/audit-events.jsonl`. The file rotates at 10 MiB by default
(see `backoffice.audit_rotation`). Rotated logs are kept indefinitely
on disk; export to long-term storage is the operator's responsibility.

The legacy `results/overnight-ledger.jsonl` continues to record
overnight-loop decisions. The two files complement each other; the
audit log is the union of all mutations across the system.

---

## Known limitations

* The HTTP server uses Python's stdlib `http.server`. It is
  appropriate for trusted internal use behind a reverse proxy. Do
  not expose it to the internet without TLS termination + a real
  HTTP server in front.
* `LockFile` uses POSIX advisory locks. Cooperative only. Processes
  outside Back Office that don't acquire the lock can corrupt state.
* Plugins run with the same privileges as Back Office. Treat plugin
  declarations the way you'd treat shell scripts in `agents/`.
* Audit-log rotation is single-process; concurrent processes may
  rotate in different windows. Consider serialising the rotation
  call if multiple workers share the same `results/` directory.
