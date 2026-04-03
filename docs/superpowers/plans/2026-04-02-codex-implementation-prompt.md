# Codex Implementation Prompt — Local Infrastructure Monitoring

Copy everything below the line into Codex.

---

## Task for Codex (OpenClaude)

**Objective:** Implement the local infrastructure monitoring stack for the borg workstation as specified in the implementation plan. This creates a Vector → Ingest → TimescaleDB → Grafana monitoring pipeline with 4 collector scripts, 4 Grafana dashboards, 11 alert rules, Makefile targets, remote access scripts, and Forgejo LAN exposure.

**Context:**
- Working directory: `/home/merm/projects/back-office`
- This is the BreakPoint Labs Back Office project — a multi-department AI agent audit system
- The `monitoring/` directory already exists with a basic Grafana-only docker-compose and provisioning files
- Forgejo git server is running at `ops/forgejo-local/` with Docker Compose
- The host machine (borg) has: Ryzen 7 8700G, 60GB RAM, RTX 3080 (10GB), Pop!_OS 24.04, Ollama running on port 11434
- Full spec: `docs/superpowers/specs/2026-04-02-local-infrastructure-monitoring-design.md`
- Full plan: `docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md`

**CRITICAL: Read the plan first.** Run:
```
cat docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md
```
The plan has 25 tasks across 10 chunks with complete code for every file. Follow it exactly. Do NOT deviate from the plan unless something doesn't work, in which case fix the issue and document what you changed.

**Execution order — follow the plan's dependency graph:**

1. **Chunk 1 (Tasks 1-6): Foundation** — .env, TimescaleDB init.sql, Python ingest service, docker-compose.yml, Grafana datasource, smoke test the foundation
2. **Chunk 2 (Tasks 7-10): Collectors** — gpu_metrics.sh, system_sensors.sh, ollama_metrics.sh, claude_sessions.sh. These are independent — do them in any order. Test each one locally after writing it.
3. **Chunk 3 (Tasks 11-12): Vector** — vector.yaml pipeline config, then start full stack and verify end-to-end data flow
4. **Chunk 4 (Tasks 13-16): Dashboards** — 4 Grafana dashboard JSON files. These are independent. The plan describes panels and SQL queries for each. Generate complete Grafana dashboard JSON (not stubs).
5. **Chunk 5 (Task 17): Dashboard provisioning** — Verify dashboards.yml picks up new files
6. **Chunk 6 (Task 18): Alerts** — alerts.yml with all 11 alert rules
7. **Chunk 7 (Task 19): Makefile** — Add monitoring-up/down/logs/status/restart/test targets
8. **Chunk 8 (Tasks 20-22): Remote access + Forgejo** — setup-remote-access.sh, undo-remote-access.sh, Forgejo .env update, Forgejo Makefile targets
9. **Chunk 9 (Tasks 23-24): Tests** — pytest collector tests, smoke test script + Makefile target
10. **Chunk 10 (Task 25): Verification** — Start full stack, verify dashboards load, verify alerts, verify data flow

**Constraints:**
- Commit after EACH task (not each chunk). Use conventional commit format: `feat(monitoring): ...` or `test(monitoring): ...`
- Do NOT modify files outside `monitoring/`, `Makefile`, `.gitignore`, `ops/forgejo-local/.env`, and `tests/monitoring/` unless the plan says to
- Do NOT run `setup-remote-access.sh` — that requires sudo and user interaction. Just create the file.
- Do NOT push to any remote
- The `.env` file with real passwords should be created but NOT committed (it's gitignored)
- Generate real passwords with `openssl rand -base64 16` for the .env file
- For Grafana dashboard JSON files (Tasks 13-16): generate COMPLETE, valid Grafana dashboard JSON with all panels, queries, and layout. The plan describes each panel's SQL query. Use the Grafana dashboard JSON model with proper panel types (timeseries, gauge, stat, table, bargauge). Set datasource UID to `timescaledb` and type to `postgres` on all panels.
- All collector scripts must be `chmod +x`
- The ingest service uses async psycopg (`psycopg_pool.AsyncConnectionPool`) — do NOT use sync psycopg
- The ingest service parses NDJSON (newline-delimited JSON), not JSON arrays — Vector's http sink sends NDJSON
- The Ollama collector is written entirely in Python (via bash heredoc) to avoid subshell variable scoping issues
- Vector's sinks are `type: http` pointing to `http://localhost:8087/ingest/metrics` and `http://localhost:8087/ingest/logs` — Vector has NO native PostgreSQL sink

**Key files to create/modify:**

```
CREATE:
  monitoring/.env.example
  monitoring/.env                          (gitignored, real passwords)
  monitoring/timescaledb/init.sql
  monitoring/ingest/requirements.txt
  monitoring/ingest/main.py
  monitoring/ingest/Dockerfile
  monitoring/vector/vector.yaml
  monitoring/vector/collectors/gpu_metrics.sh
  monitoring/vector/collectors/system_sensors.sh
  monitoring/vector/collectors/ollama_metrics.sh
  monitoring/vector/collectors/claude_sessions.sh
  monitoring/provisioning/datasources/timescaledb.yml
  monitoring/provisioning/dashboards/host-overview.json
  monitoring/provisioning/dashboards/gpu-monitoring.json
  monitoring/provisioning/dashboards/llm-inference.json
  monitoring/provisioning/dashboards/claude-sessions.json
  monitoring/provisioning/alerting/alerts.yml
  monitoring/scripts/setup-remote-access.sh
  monitoring/scripts/undo-remote-access.sh
  monitoring/scripts/smoke-test.sh
  tests/monitoring/__init__.py
  tests/monitoring/test_collectors.py

MODIFY:
  monitoring/docker-compose.yml            (replace contents)
  .gitignore                               (add monitoring/.env)
  Makefile                                 (add monitoring + forgejo targets)
  ops/forgejo-local/.env                   (change FORGEJO_DOMAIN to borg.local)
```

**Verification after each chunk:**

- **After Chunk 1:** `docker compose config --quiet` passes. `docker compose up -d timescaledb ingest grafana` starts. `curl localhost:8087/health` returns OK. `curl localhost:3333/api/health` returns OK. Test metric insert via curl to ingest endpoint works.
- **After Chunk 2:** Each collector script runs and outputs valid JSON: `./monitoring/vector/collectors/gpu_metrics.sh | python3 -m json.tool`
- **After Chunk 3:** `docker compose up -d` starts all 4 containers. After 30s, `docker exec breakpoint-timescaledb psql -U vector -d monitoring -c "SELECT source, count(*) FROM metrics GROUP BY source;"` shows data from multiple sources.
- **After Chunk 4:** Dashboards load at `http://localhost:3333` with real data in panels.
- **After Chunk 6:** Alerting → Alert Rules in Grafana shows 11 rules.
- **After Chunk 7:** `make monitoring-status` reports all services OK.
- **After Chunk 9:** `python3 -m pytest tests/monitoring/ -v` passes.

**Reporting:** After completing ALL tasks, report:
1. Files created/modified (count)
2. Commits made (count + messages)
3. Containers running and health status
4. Any deviations from the plan and why
5. Any issues or blockers encountered
