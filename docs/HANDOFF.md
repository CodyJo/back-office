# Back Office Handoff

Last updated: April 2, 2026

## 2026-04-02 Local Infrastructure Monitoring Chunks 6-8 Tasks 19-22

- Current direction:
  - local infrastructure monitoring plan implementation advanced through Chunk 6 Task 19, Chunk 7 Task 20, and Chunk 8 Tasks 21-22 from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - the next pending work remains the later testing and verification tasks from the plan
- Completed work:
  - updated [Makefile](/home/merm/projects/back-office/Makefile) with the monitoring stack targets exactly from the plan: `monitoring-up`, `monitoring-down`, `monitoring-logs`, `monitoring-status`, `monitoring-restart`
  - updated [Makefile](/home/merm/projects/back-office/Makefile) so `grafana` and `grafana-stop` are aliases for `monitoring-up` and `monitoring-down`
  - added the Forgejo targets exactly from the plan in [Makefile](/home/merm/projects/back-office/Makefile): `forgejo-up`, `forgejo-down`, `forgejo-mirror`
  - created executable remote access scripts from the plan:
    - [monitoring/scripts/setup-remote-access.sh](/home/merm/projects/back-office/monitoring/scripts/setup-remote-access.sh)
    - [monitoring/scripts/undo-remote-access.sh](/home/merm/projects/back-office/monitoring/scripts/undo-remote-access.sh)
  - updated the local Forgejo runtime config in [ops/forgejo-local/.env](/home/merm/projects/back-office/ops/forgejo-local/.env) from `FORGEJO_DOMAIN=localhost` to `FORGEJO_DOMAIN=borg.local`
  - created the requested commits:
    - `f192a32` `feat(monitoring): add Makefile targets for monitoring stack`
    - `126387c` `feat(monitoring): add remote access setup/undo scripts (SSH, Samba, RDP)`
- Pending work:
  - do not rerun or modify the remote access scripts unless the operator is ready to execute privileged setup on the host
  - restart Forgejo manually later if the new `FORGEJO_DOMAIN=borg.local` setting needs to take effect at runtime
  - continue with later monitoring-plan tasks, especially tests and any runtime verification that intentionally starts containers
- Constraints:
  - followed the plan snippets exactly for the `Makefile` additions and both remote access scripts
  - did not run `monitoring/scripts/setup-remote-access.sh`
  - did not run any `sudo` commands
  - did not start Docker containers or restart Forgejo
  - `ops/forgejo-local/.env` is runtime-local and was intentionally left uncommitted
- Key files:
  - [Makefile](/home/merm/projects/back-office/Makefile)
  - [monitoring/scripts/setup-remote-access.sh](/home/merm/projects/back-office/monitoring/scripts/setup-remote-access.sh)
  - [monitoring/scripts/undo-remote-access.sh](/home/merm/projects/back-office/monitoring/scripts/undo-remote-access.sh)
  - [ops/forgejo-local/.env](/home/merm/projects/back-office/ops/forgejo-local/.env)
  - [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
- Integrations and assumptions:
  - `monitoring-status` expects local services at `localhost:5433`, `localhost:8087`, `localhost:8686`, and `localhost:3333`
  - `forgejo-mirror` reads target repo paths from `config/targets.yaml` and pushes to `http://borg.local:3300/merm/<repo>.git`
  - the remote access scripts assume host user `merm`, LAN subnet `10.0.0.0/24`, Samba path `/media/merm`, and GNOME remote desktop on the machine named `borg`
- Verification state:
  - `make monitoring-status` ran successfully and reported all services `DOWN`, which is expected because the stack was not started in this task
  - both remote access scripts were marked executable
  - the Forgejo `.env` value was updated in-place only; no runtime verification was performed because restart was explicitly skipped

## 2026-04-02 Local Infrastructure Monitoring Chunk 4 Tasks 13-18

- Current direction:
  - Chunk 4 dashboard provisioning and Chunk 5 alert provisioning are now implemented from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - `dashboards.yml` was reviewed and already auto-discovers all JSON dashboards from `/etc/grafana/provisioning/dashboards`, so no provisioning change was needed for Task 17
- Completed work:
  - created [monitoring/provisioning/dashboards/host-overview.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/host-overview.json) with 11 host panels covering CPU per-core, load, RAM, swap, disk, network, temperature, OOM kills, and page faults
  - created [monitoring/provisioning/dashboards/gpu-monitoring.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/gpu-monitoring.json) with the required GPU hero gauge, thermal history, VRAM panels, power, clocks, fan, throttle stats, and PCIe link status
  - created [monitoring/provisioning/dashboards/llm-inference.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/llm-inference.json) with repeating per-model VRAM ratio gauges plus model status, inference performance, service status, headroom, and correlation panels
  - created [monitoring/provisioning/dashboards/claude-sessions.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/claude-sessions.json) with session/worktree stats, session history, uptime detail, and system-impact panels
  - created [monitoring/provisioning/alerting/alerts.yml](/home/merm/projects/back-office/monitoring/provisioning/alerting/alerts.yml) with 11 Grafana alert rules for disk, GPU thermal/throttling, RAM, swap, GPU offload, inference degradation, VRAM exhaustion, Ollama availability, and OOM kills
- Pending work:
  - runtime-import verification in Grafana remains pending because Docker/Grafana were not started in this task
  - if a later pass brings the stack up, verify dashboard rendering, repeated-model behavior on the LLM dashboard, and alert rule import in the Grafana UI/API
- Constraints:
  - did not start Docker containers
  - the repo has substantial unrelated modified and untracked files; they were left untouched
  - the GPU dashboard has 14 panels because the task required distinct VRAM, PCIe, and four separate throttle stat panels
- Key files:
  - [monitoring/provisioning/dashboards/dashboards.yml](/home/merm/projects/back-office/monitoring/provisioning/dashboards/dashboards.yml)
  - [monitoring/provisioning/dashboards/host-overview.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/host-overview.json)
  - [monitoring/provisioning/dashboards/gpu-monitoring.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/gpu-monitoring.json)
  - [monitoring/provisioning/dashboards/llm-inference.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/llm-inference.json)
  - [monitoring/provisioning/dashboards/claude-sessions.json](/home/merm/projects/back-office/monitoring/provisioning/dashboards/claude-sessions.json)
  - [monitoring/provisioning/alerting/alerts.yml](/home/merm/projects/back-office/monitoring/provisioning/alerting/alerts.yml)
- Integrations and assumptions:
  - every dashboard panel uses the provisioned Postgres datasource `timescaledb`
  - all SQL targets read from the `metrics_5m` continuous aggregate and assume the collectors/vector pipeline from earlier chunks are active
  - the LLM dashboard depends on `ollama_*` metrics from both the Ollama collector and the journal-derived inference parser
- Verification state:
  - `python3 -c "import json; json.load(open('monitoring/provisioning/dashboards/host-overview.json')); print('OK')"` passed
  - `python3 -c "import json; json.load(open('monitoring/provisioning/dashboards/gpu-monitoring.json')); print('OK')"` passed
  - `python3 -c "import json; json.load(open('monitoring/provisioning/dashboards/llm-inference.json')); print('OK')"` passed
  - `python3 -c "import json; json.load(open('monitoring/provisioning/dashboards/claude-sessions.json')); print('OK')"` passed
  - `monitoring/provisioning/dashboards/dashboards.yml` already points Grafana at `/etc/grafana/provisioning/dashboards` with `foldersFromFilesStructure: false`
  - Grafana UI import/render validation and alert execution validation were not run
- Recommended next steps:
  - bring Grafana up in a later task and verify all four dashboards import cleanly
  - confirm the exact alert provisioning schema against the running Grafana version if import warnings appear
  - add the follow-on Makefile targets from Chunk 6 after dashboard/alert provisioning is accepted

## 2026-04-02 Local Infrastructure Monitoring Chunk 3 Task 11

- Current direction:
  - local infrastructure monitoring plan implementation continues from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - Chunk 3 Task 11 is now complete; Task 12 and later plan tasks remain pending
- Completed work:
  - created [monitoring/vector/vector.yaml](/home/merm/projects/back-office/monitoring/vector/vector.yaml) with the full Vector pipeline exactly from the plan
  - included API config on `0.0.0.0:8686`
  - included all required sources: `host_metrics`, `gpu_metrics`, `system_sensors`, `ollama_metrics`, `claude_metrics`, `ollama_journal`, `system_journal`, `docker_logs`
  - included all required transforms: `host_normalize`, `gpu_passthrough`, `sensors_passthrough`, `ollama_passthrough`, `claude_passthrough`, `ollama_inference_parse`, `ollama_logs`, `system_logs`, `system_event_metrics`, `docker_normalize`
  - included both required HTTP sinks: `ingest_metrics` and `ingest_logs`
  - preserved the exact `ingest_metrics` inputs from the plan, including `ollama_inference_parse` and `system_event_metrics`
- Pending work:
  - do not modify Task 11 further unless the plan changes
  - perform Chunk 3 Task 12 separately: start the stack and verify end-to-end flow
  - run Vector-native validation later if Docker access is used for the planned `vector validate` step
- Constraints:
  - followed the plan YAML exactly, including the VRL regex-based `ollama_inference_parse` transform that emits 7 inference metrics
  - did not start Docker containers
  - the repo still contains substantial unrelated modified and untracked files that were left untouched
- Key files:
  - [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - [monitoring/vector/vector.yaml](/home/merm/projects/back-office/monitoring/vector/vector.yaml)
  - [monitoring/vector/collectors/gpu_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh)
  - [monitoring/vector/collectors/system_sensors.sh](/home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh)
  - [monitoring/vector/collectors/ollama_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh)
  - [monitoring/vector/collectors/claude_sessions.sh](/home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh)
- Integrations and assumptions:
  - the Vector config expects collector scripts at `/etc/vector/collectors/*.sh`
  - the HTTP sinks target the local ingest service on `http://localhost:8087`
  - journald and docker sources will only function correctly when Vector has the expected runtime mounts/permissions from the later stack setup
- Verification state:
  - `python3 -c "import yaml; yaml.safe_load(open('monitoring/vector/vector.yaml')); print('YAML OK')"` passed
  - the Docker-based `vector validate` step from the plan was not run in this task
- Recommended next steps:
  - execute Task 12 without changing the checked-in YAML unless validation reveals a plan mismatch
  - when the stack is started, confirm that the ingest service receives both metrics and log batches
  - if Vector reports source-specific warnings, distinguish expected mount/runtime issues from actual config errors before editing the pipeline

## 2026-04-02 Local Infrastructure Monitoring Chunk 2

- Current direction:
  - local infrastructure monitoring plan implementation is in progress from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - Chunk 2 Tasks 7-10 are complete; Chunk 3 and later plan tasks are still pending
- Completed work:
  - created [monitoring/vector/collectors/gpu_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh)
  - created [monitoring/vector/collectors/system_sensors.sh](/home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh)
  - created [monitoring/vector/collectors/ollama_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh)
  - created [monitoring/vector/collectors/claude_sessions.sh](/home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh)
  - marked all four scripts executable
  - committed each script separately:
    - `ea82e58` `feat(monitoring): add GPU metrics collector (nvidia-smi)`
    - `76d9c45` `feat(monitoring): add system sensors collector (temp, freq, vmstat)`
    - `9964fca` `feat(monitoring): add Ollama metrics collector (model status, VRAM ratio)`
    - `6a00baf` `feat(monitoring): add Claude Code sessions collector`
- Pending work:
  - implement Chunk 3 Vector pipeline configuration and later monitoring stack tasks
  - validate the collectors again inside the eventual containerized `/host` mount layout
- Constraints:
  - followed the plan code exactly for the four collector scripts
  - did not start any Docker containers
  - the repository has substantial unrelated pre-existing modified and untracked files; they were left untouched
- Key files:
  - [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md)
  - [monitoring/vector/collectors/gpu_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh)
  - [monitoring/vector/collectors/system_sensors.sh](/home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh)
  - [monitoring/vector/collectors/ollama_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh)
  - [monitoring/vector/collectors/claude_sessions.sh](/home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh)
- Integrations and assumptions:
  - `gpu_metrics.sh` uses `NVIDIA_SMI` for testability and returns `[]` if `nvidia-smi` is unavailable
  - `system_sensors.sh` expects container mount paths under `/host/sys` and `/host/proc`
  - `ollama_metrics.sh` polls `OLLAMA_HOST` or `http://localhost:11434`
  - `claude_sessions.sh` inspects `ps` output for `claude` and counts extra git worktrees under `/home/merm/projects` unless `PROJECTS_DIR` overrides it
- Verification state:
  - `./monitoring/vector/collectors/gpu_metrics.sh | python3 -m json.tool` passed and returned `[]` because `nvidia-smi` was not available in this environment
  - `HOST_SYS=/sys HOST_PROC=/proc sed 's|/host/sys|/sys|g; s|/host/proc|/proc|g' ./monitoring/vector/collectors/system_sensors.sh | bash | python3 -m json.tool` passed with valid JSON including `cpu_temp_celsius`, `cpu_freq_mhz`, `memory_page_faults_major`, `oom_kills_total`, `swap_io_in_pages`, and `swap_io_out_pages`
  - `./monitoring/vector/collectors/ollama_metrics.sh | python3 -m json.tool` passed with valid JSON and `ollama_running: 0`
  - `./monitoring/vector/collectors/claude_sessions.sh | python3 -m json.tool` passed with valid JSON; this environment reported `claude_active_sessions: 682` and `claude_worktrees_active: 33`
- Recommended next steps:
  - wire these collectors into the upcoming Vector `exec` sources exactly as specified in Chunk 3
  - verify whether the very high Claude process count is expected before treating it as a stable operational signal
  - when Docker mounts exist, re-run the collectors in-container to confirm `/host` path behavior

## 2026-04-02 Product Roadmap Audit Of Back Office

- Completed a repo-level product audit focused on actual operator flows, roadmap gaps, UX friction, and technical debt in Back Office itself.
- Wrote the refreshed artifacts to:
  - [results/back-office/product-findings.json](/home/merm/projects/back-office/results/back-office/product-findings.json)
  - [results/back-office/product-roadmap.md](/home/merm/projects/back-office/results/back-office/product-roadmap.md)
- Audit scope:
  - context reviewed: [CLAUDE.md](/home/merm/projects/back-office/CLAUDE.md), [MASTER-PROMPT.md](/home/merm/projects/back-office/MASTER-PROMPT.md), [README.md](/home/merm/projects/back-office/README.md), [package.json](/home/merm/projects/back-office/package.json), [pyproject.toml](/home/merm/projects/back-office/pyproject.toml), [AGENTS.md](/home/merm/projects/back-office/AGENTS.md)
  - product/runtime files reviewed: [backoffice/__main__.py](/home/merm/projects/back-office/backoffice/__main__.py), [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py), [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py), [backoffice/workflow.py](/home/merm/projects/back-office/backoffice/workflow.py), [backoffice/tasks.py](/home/merm/projects/back-office/backoffice/tasks.py), [backoffice/config.py](/home/merm/projects/back-office/backoffice/config.py), [backoffice/backlog.py](/home/merm/projects/back-office/backoffice/backlog.py), [backoffice/deploy_control.py](/home/merm/projects/back-office/backoffice/deploy_control.py), [backoffice/github_actions_history.py](/home/merm/projects/back-office/backoffice/github_actions_history.py)
  - dashboard/config files reviewed: [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html), [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html), [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html), [dashboard/actions-history.html](/home/merm/projects/back-office/dashboard/actions-history.html), [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml), [config/targets.yaml](/home/merm/projects/back-office/config/targets.yaml), [Makefile](/home/merm/projects/back-office/Makefile)
- Result summary:
  - product readiness score: `74`
  - findings: `9 total`
  - severity split: `1 critical`, `4 high`, `2 medium`, `1 low`, `1 info`
- Highest-signal findings:
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) posts repo paths from the ops audit launcher while [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) resolves audits by target name, so the HQ audit launcher can fail on valid selections
  - [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) validates selected audit departments but then ignores them and always runs `audit-all*`
  - [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml) and [config/targets.yaml](/home/merm/projects/back-office/config/targets.yaml) still drift and both point at removed legacy scripts
  - [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) saves new products with blank lint/test/coverage/deploy commands, so onboarding is incomplete
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) eagerly loads the full [dashboard/backlog.json](/home/merm/projects/back-office/dashboard/backlog.json), which is currently about `38.7 MB`
- Current direction:
  - fix the broken HQ audit-launch path first, because that is a core control-plane promise and the only critical roadmap blocker in this pass
  - then make selective scans real and collapse target configuration toward one source of truth
  - defer growth work like notifications/webhooks until the core operator flows are reliable
- Constraints:
  - this was a static source audit plus file-size/config inspection; no browser automation or live API interaction was performed in the sandbox
  - `scan_duration_seconds` remains `0` in the JSON output because this pass was not instrumented as a timed pipeline run
- Verification:
  - validated file existence and structure for the output artifacts
  - used direct code evidence and current checked-in file sizes for each roadmap item
  - did not run the full test suite during this pass
- Recommended next steps:
  - fix the `ops audit` target payload mismatch between [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) and [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py)
  - thread selected departments through the actual audit command path
  - choose one canonical target config and remove the stale command references
  - make new-product onboarding require or scaffold real repo commands before saving
  - paginate or lazy-load backlog data so the dashboard no longer downloads the full backlog up front

## 2026-04-02 Monetization Audit Of Back Office

- Completed a repo and live-surface monetization audit focused on Back Office itself as a B2B control-plane product.
- Wrote the refreshed artifacts to:
  - [results/back-office/monetization-findings.json](/home/merm/projects/back-office/results/back-office/monetization-findings.json)
  - [results/back-office/monetization-strategy.md](/home/merm/projects/back-office/results/back-office/monetization-strategy.md)
- Audit scope:
  - repo context reviewed: [CLAUDE.md](/home/merm/projects/back-office/CLAUDE.md), [MASTER-PROMPT.md](/home/merm/projects/back-office/MASTER-PROMPT.md), [README.md](/home/merm/projects/back-office/README.md), [package.json](/home/merm/projects/back-office/package.json), [pyproject.toml](/home/merm/projects/back-office/pyproject.toml), [config/targets.yaml](/home/merm/projects/back-office/config/targets.yaml), [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml)
  - product surfaces reviewed: [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html), [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html), [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html), [dashboard/actions-history.html](/home/merm/projects/back-office/dashboard/actions-history.html), [dashboard/docs-content.html](/home/merm/projects/back-office/dashboard/docs-content.html), [dashboard/faq-content.html](/home/merm/projects/back-office/dashboard/faq-content.html), [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py), [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py), [backoffice/tasks.py](/home/merm/projects/back-office/backoffice/tasks.py), [backoffice/aggregate.py](/home/merm/projects/back-office/backoffice/aggregate.py)
  - latest gating audits incorporated: [results/back-office/findings.json](/home/merm/projects/back-office/results/back-office/findings.json), [results/back-office/ada-findings.json](/home/merm/projects/back-office/results/back-office/ada-findings.json), [results/back-office/compliance-findings.json](/home/merm/projects/back-office/results/back-office/compliance-findings.json)
- Result summary:
  - monetization readiness score: `49`
  - total opportunities: `11`
  - value split: `4 high`, `5 medium`, `2 low`
  - quick wins: `4`
  - realistic revenue range: `$2.5k-$12k/month` if phased correctly
- Current direction:
  - treat Back Office as a high-trust B2B control-plane product, not an ad-supported property
  - prioritize paid services and managed private deployment first
  - defer hosted self-serve SaaS until auth, retention, accessibility, and tenant boundaries are materially stronger
- Highest-signal recommendations:
  - launch a paid baseline audit plus quarterly operating review service using current findings/reporting artifacts
  - offer managed private deployment before attempting multi-tenant hosted SaaS
  - package advanced reporting, exports, custom departments, and integrations as future premium tiers
  - avoid display ads and keep affiliate/sponsorship activity out of dashboard workflows
- Constraints:
  - this was a static repo audit plus official-web pricing/reference verification; no browser-authenticated live-session review of `admin.codyjo.com` was possible in the sandbox
  - revenue estimates are intentionally conservative and assume a low-volume, high-intent B2B audience rather than broad traffic
  - the prior monetization artifact in this repo was more optimistic; this pass intentionally re-based the numbers against the current implementation state
- Verification:
  - JSON structure was rewritten to the requested schema for this pass
  - the strategy memo includes current official reference links for pricing and integration docs
- Recommended next steps:
  - if monetization work continues, start in the marketing/public-site repo with service packaging and demand-capture pages
  - in Back Office itself, fix the auth, retention, and ADA blockers before exposing premium automation or customer-facing integrations
  - if a future agent revisits pricing, re-check official vendor pricing pages because those numbers are time-sensitive

## 2026-04-02 Compliance Audit Of Back Office

- Completed a static GDPR / ISO 27001 / age-verification applicability audit of the Back Office repo itself.
- Wrote the artifacts to:
  - [results/back-office/compliance-findings.json](/home/merm/projects/back-office/results/back-office/compliance-findings.json)
  - [results/back-office/compliance-summary.md](/home/merm/projects/back-office/results/back-office/compliance-summary.md)
- Audit scope:
  - repo context reviewed: [CLAUDE.md](/home/merm/projects/back-office/CLAUDE.md), [MASTER-PROMPT.md](/home/merm/projects/back-office/MASTER-PROMPT.md), [README.md](/home/merm/projects/back-office/README.md), [pyproject.toml](/home/merm/projects/back-office/pyproject.toml), [package.json](/home/merm/projects/back-office/package.json)
  - control surfaces reviewed: [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py), [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py), [backoffice/backlog.py](/home/merm/projects/back-office/backoffice/backlog.py), [backoffice/tasks.py](/home/merm/projects/back-office/backoffice/tasks.py), [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml), [config/api-config.yaml](/home/merm/projects/back-office/config/api-config.yaml), [docs/COMPLIANCE-CONTROLS.md](/home/merm/projects/back-office/docs/COMPLIANCE-CONTROLS.md)
- Result summary:
  - compliance score: `48`
  - findings: `5 total`
  - severity split: `1 critical`, `1 high`, `3 medium`
  - GDPR: `62` (`partial`)
  - ISO 27001: `34` (`non-compliant`)
  - age verification: `not-applicable`
- Highest-signal blockers:
  - [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml) and [config/api-config.yaml](/home/merm/projects/back-office/config/api-config.yaml) contain a committed API key despite the repo’s own controls saying secrets should not live in tracked config
  - [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py) protects privileged POST actions with one shared static API key and no per-user authorization
  - [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py) exposes `/api/status` and `/api/jobs` without authentication
  - [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py) and [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) accept request bodies with no size cap
  - [backoffice/backlog.py](/home/merm/projects/back-office/backoffice/backlog.py), [backoffice/tasks.py](/home/merm/projects/back-office/backoffice/tasks.py), and [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) retain and mirror sensitive findings/task history without enforced expiry
- Constraints:
  - this was a static source audit only; no live infrastructure checks, third-party contract review, or deployed endpoint verification was performed
  - the report intentionally treats age verification as not applicable because Back Office is an internal control-plane tool with no minor onboarding or restricted-content surface
- Recommended next steps:
  - rotate the committed API key immediately and move runtime auth secrets to environment or secret-manager injection
  - redesign the production API access model around authenticated operator identity plus role-based authorization
  - require auth for all non-health API endpoints and add request-size limits
  - define a real retention schedule for findings, task history, and mirrored dashboard artifacts, then enforce it in code

## 2026-04-02 ADA Audit Of Back Office

- Completed a static WCAG 2.1 / ADA / Section 508 audit of the shipped Back Office dashboard surfaces.
- Wrote the artifacts to:
  - [results/back-office/ada-findings.json](/home/merm/projects/back-office/results/back-office/ada-findings.json)
  - [results/back-office/ada-summary.md](/home/merm/projects/back-office/results/back-office/ada-summary.md)
- Audit scope:
  - shipped UI files reviewed: `dashboard/index.html`, `dashboard/deploy.html`, `dashboard/migration.html`, `dashboard/docs-content.html`, `dashboard/faq-content.html`, `dashboard/department-context.js`, `dashboard/site-branding.js`
  - serving path reviewed: [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py)
- Result summary:
  - compliance grade: `non-compliant`
  - compliance score: `57`
  - findings: `11 total`
  - severity split: `1 critical`, `1 high`, `6 medium`, `2 low`, `1 info`
- Highest-signal blockers:
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) uses mouse-only custom controls for core HQ navigation into department findings and filters
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) opens slide-over/detail overlays without dialog semantics or focus management
  - [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) auto-refreshes every `15s` without a pause control while also exposing editable fields
  - [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) update form fields lack persistent visible labels
  - [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html) and [dashboard/site-branding.js](/home/merm/projects/back-office/dashboard/site-branding.js) contain confirmed contrast failures (`2.63:1` deferred status pill, `2.78:1` FAQ trigger)
- Constraints:
  - this was a static code audit only; no browser automation or screen-reader runtime verification was performed in the sandbox
  - `scan_duration_seconds` was left at `0` in the JSON artifact because the audit was not instrumented as a timed pipeline run
- Recommended next steps:
  - first fix [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) keyboard access and modal semantics, because those are the only critical/high findings
  - then fix the migration page pause control + visible labels
  - then clean up the docs tab ARIA wiring, tooltip focus behavior, and small contrast/touch-target issues
  - after remediation, verify with an actual browser accessibility pass (`axe`, keyboard traversal, dialog focus checks, and a screen reader smoke test)

## 2026-04-02 QA Scan Of Back Office

- Completed a repo QA scan and wrote the artifacts to:
  - [results/back-office/findings.json](/home/merm/projects/back-office/results/back-office/findings.json)
  - [results/back-office/scan-summary.md](/home/merm/projects/back-office/results/back-office/scan-summary.md)
  - [results/back-office/dashboard.json](/home/merm/projects/back-office/results/back-office/dashboard.json)
- Scan summary:
  - total findings: `72`
  - high: `1`
  - medium: `3`
  - low: `7`
  - info: `61`
- Highest-signal issues:
  - [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py) accepts arbitrary existing directories as scan targets and disables auth when no API key is configured
  - [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) and [backoffice/api_server.py](/home/merm/projects/back-office/backoffice/api_server.py) read request bodies solely from `Content-Length` with no size cap
  - [backoffice/workflow.py](/home/merm/projects/back-office/backoffice/workflow.py) wraps `list-targets` in the exclusive workflow lock, which reproduces the failing regression in `tests/test_workflow.py::TestMain::test_argv_defaults_to_none`
  - [tests/test_bunny_provider.py](/home/merm/projects/back-office/tests/test_bunny_provider.py) contains seven Ruff failures from unused imports and locals
- Automated verification:
  - `ruff check .` failed with `7` errors
  - `pytest` failed with `2` failed tests and `60` errors
  - `node --test ci/server.test.mjs` passed
- Verification constraint in this environment:
  - [tests/test_servers.py](/home/merm/projects/back-office/tests/test_servers.py) uses real `HTTPServer` socket binding on `127.0.0.1`
  - this sandbox rejects that with `PermissionError: [Errno 1] Operation not permitted`
  - the report records each of those `61` server-test failures separately as environment-limited verification findings, not reproduced product defects
- Recommended next steps:
  - tighten API target resolution and fail closed when no API key is configured outside explicit local-dev mode
  - add bounded JSON-body parsing shared by the dashboard server and production API server
  - remove or relax the exclusive lock for read-only workflow commands like `list-targets`
  - clean `tests/test_bunny_provider.py` so Ruff is green
  - re-run `tests/test_servers.py` in an environment that permits local socket binding

## 2026-04-02 Forgejo History Backfill And GitHub Actions Archive

- All top-level git repos under [/home/merm/projects](/home/merm/projects) were backfilled into local Forgejo under `CodyJo/*`.
- Verified live Forgejo repo inventory count: `18`.
- Verified imported repo set:
  - `analogify`
  - `auth-service`
  - `back-office`
  - `certstudy`
  - `codyjo.com`
  - `continuum`
  - `cordivent`
  - `dustbunny`
  - `fuel`
  - `openclaude`
  - `pattern`
  - `pe-bootstrap`
  - `pe-dashboards`
  - `postal-gcp`
  - `search`
  - `selah`
  - `shared`
  - `thenewbeautifulme`
- Bulk backfill was performed with [scripts/backfill-forgejo-history.sh](/home/merm/projects/back-office/scripts/backfill-forgejo-history.sh).
- That script now:
  - creates missing Forgejo repos on demand
  - repoints local `origin` to Forgejo SSH
  - preserves GitHub remotes as `github-public` when they existed
  - force-pushes all branches and tags for initial import
- Important distinction:
  - git commit/branch/tag history is now backfilled into Forgejo
  - historical GitHub Actions run history is not part of git history and does not appear in Forgejo automatically
- Added a local archive path for that CI history:
  - [scripts/archive-github-actions-history.sh](/home/merm/projects/back-office/scripts/archive-github-actions-history.sh)
  - [docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md](/home/merm/projects/back-office/docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md)
- Added a first-class Back Office product surface for that archive:
  - [backoffice/github_actions_history.py](/home/merm/projects/back-office/backoffice/github_actions_history.py)
  - [dashboard/actions-history.html](/home/merm/projects/back-office/dashboard/actions-history.html)
  - API routes in [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py):
    - `GET /api/github-actions/history`
    - `POST /api/github-actions/archive`
- Navigation now exposes the new archive page from:
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html)
  - [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html)
- The archive script stores GitHub workflow/run metadata under ignored local results:
  - `/home/merm/projects/back-office/results/github-actions-history/`
- Archive run completed successfully on April 2, 2026.
- Current archive summary highlights:
  - `analogify`: `144` runs archived
  - `back-office`: `46` runs archived
  - `certstudy`: `34` runs archived
  - `codyjo.com`: `138` runs archived
  - `cordivent`: `89` runs archived
  - `fuel`: `90` runs archived
  - `openclaude`: `200` of `280` runs archived due the current per-repo cap
  - `pattern`: `5` runs archived
  - `pe-bootstrap`: `1` run archived
  - `selah`: `96` runs archived
  - `thenewbeautifulme`: `188` runs archived
- Repos with `0` archived GitHub runs currently appear to have no GitHub Actions run history in the API snapshot:
  - `auth-service`
  - `continuum`
  - `DustBunny`
  - `pe-dashboards`
  - `postal-gcp`
  - `search`
  - `shared`
- Current local server/UI endpoints remain:
  - Forgejo: `http://localhost:3300`
  - Back Office Forgejo mode: `http://localhost:8070`
  - Back Office archive view: `http://localhost:8070/actions-history.html`
- HQ now includes Forgejo as a first-class local status signal:
  - `GET /api/ops/status` now returns a `forgejo` block with base URL, health, description, user, and repo count
  - [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) now shows:
    - a topbar Forgejo link
    - a Forgejo score card in the main score row
- Navigation updates:
  - [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html) now uses the dark Back Office palette and includes a Forgejo nav link
  - [dashboard/actions-history.html](/home/merm/projects/back-office/dashboard/actions-history.html) includes a Forgejo nav link
  - [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) now includes Deploy, Actions Archive, and Forgejo nav links
- Added a short operator routine doc:
  - [docs/DAILY_USE.md](/home/merm/projects/back-office/docs/DAILY_USE.md)
- Added user-session autostart scaffolding:
  - [systemd-user/forgejo-local.service](/home/merm/projects/back-office/systemd-user/forgejo-local.service)
  - [systemd-user/back-office-forgejo.service](/home/merm/projects/back-office/systemd-user/back-office-forgejo.service)
  - [scripts/start-forgejo-local.sh](/home/merm/projects/back-office/scripts/start-forgejo-local.sh)
  - [scripts/install-local-platform-autostart.sh](/home/merm/projects/back-office/scripts/install-local-platform-autostart.sh)
  - [docs/AUTOSTART.md](/home/merm/projects/back-office/docs/AUTOSTART.md)
- Autostart is not just scaffolded now; it is installed and enabled for user-session startup on this machine.
- Current remaining gap:
  - local Forgejo shows the repos and will show future runs
  - old GitHub Actions runs must be archived locally if you want to keep them visible outside GitHub

## 2026-03-31 Resend Domain Cutover

- Added the live Resend sending domains for:
  - `fuel.codyjo.com`
  - `study.codyjo.com`
  - `selahscripture.com`
  - `cordivent.com`
  - `thenewbeautifulme.com`
- Created the required Bunny DNS records without changing Proton mailbox routing:
  - apex Proton `MX` records were left in place for `codyjo.com` and `thenewbeautifulme.com`
  - only Resend DKIM plus `send.*` SPF/MX records were added
- Bunny DNS zones used:
  - `codyjo.com` -> `759174`
  - `thenewbeautifulme.com` -> `759175`
  - `cordivent.com` -> `759176`
  - `selahscripture.com` -> `759178`
- Resend domain ids:
  - `fuel.codyjo.com` -> `37d69bd9-37cb-4db2-a641-9971e3c64803`
  - `study.codyjo.com` -> `3c0e36a2-48a9-4398-82ca-520e2b54fa91`
  - `selahscripture.com` -> `e41b3dbb-cc53-46bf-8576-efb699b4891f`
  - `cordivent.com` -> `8a31ba07-5485-4882-b17f-7baa6d691dfd`
  - `thenewbeautifulme.com` -> `04d1e200-b9b3-43e4-b393-398e3870ea54`
- Public DNS is already resolving correctly for all new records. Verified externally for:
  - `resend._domainkey.fuel.codyjo.com`
  - `send.fuel.codyjo.com`
  - `resend._domainkey.study.codyjo.com`
  - `send.study.codyjo.com`
  - `resend._domainkey.selahscripture.com`
  - `send.selahscripture.com`
  - `resend._domainkey.cordivent.com`
  - `send.cordivent.com`
  - `resend._domainkey.thenewbeautifulme.com`
  - `send.thenewbeautifulme.com`
- Current blocker:
  - Resend still reports all five domains as `pending` because DKIM verification has not completed on the Resend side yet.
  - `send` SPF/MX records are already `verified` for all except `fuel.codyjo.com`, which still shows `pending` even though the public DNS is visible.
  - branded smoke sends still return `403 domain is not verified`.
- Known successful Resend smoke send still on the already-verified shared domain:
  - `Account Services <no-reply@codyjo.com>` -> message id `506bd5d0-abf8-480f-90ca-806ad5a3e74e`
- Next step when resuming:
  - rerun `POST /domains/:id/verify` for the five pending domains
  - once they flip to `verified`, resend one smoke email from each branded sender and capture the message ids

## 2026-03-31 Bunny Production Recovery

- Resolved the Bunny production outage affecting `admin.codyjo.com` and `www.codyjo.com`.
- `admin.codyjo.com` was fixed by updating pull zone `5603475` from a self-referential CDN origin to storage-backed mode using storage zone `1445163`.
- `www.codyjo.com` was fixed by rerunning the gated Bunny release from `/home/merm/projects/codyjo.com`, which restored the missing root `index.html` in storage zone `1440489`.
- Read [docs/HANDOFF-BUNNY-PROD-FIX.md](/home/merm/projects/back-office/docs/HANDOFF-BUNNY-PROD-FIX.md) first if you need the exact Bunny API payload, verification commands, and current resource state.

## 2026-03-30 Deploy Control Product Surface

- Added a first deploy-control product surface to Back Office so portfolio deployment can live inside the existing control plane instead of becoming a separate tool.
- New backend module: [backoffice/deploy_control.py](/home/merm/projects/back-office/backoffice/deploy_control.py)
  - tracks deploy targets across Bunny, GCP, and deferred repos
  - pulls live GitHub repo metadata, secret counts, runner counts, and recent workflow runs through `gh`
  - pulls live Bunny app state through [scripts/bunny-cli-next.mjs](/home/merm/projects/back-office/scripts/bunny-cli-next.mjs)
  - computes a per-target `deploy_ready` flag for the dashboard
  - supports workflow dispatch through `gh workflow run`
- New dashboard page: [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html)
  - portfolio deploy overview
  - repo cards with GitHub status, Bunny status, health, and recent runs
  - filter chips for ready/blocked/Bunny/GCP/deferred
  - deploy dispatch button for repos with a configured workflow
- Updated [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) with:
  - `GET /api/deploy/control`
  - `POST /api/deploy/dispatch`
- Linked the new deploy page from the HQ dashboard top bar in [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html).

### Current limitations

- This is an MVP control plane, not a finished release manager yet.
- Rollback is not wired yet. The UI can dispatch deploy workflows, but it does not yet dispatch a previous image tag or cancel a running workflow.
- Repo visibility is hard-coded in `deploy_control.py` for now. If the portfolio target list changes frequently, move that inventory into a typed config source next.
- GitHub runner visibility currently reports `0` across the confirmed repos, so the dashboard intentionally shows the whole portfolio as blocked until runners and secrets are seeded.
- `pattern` remains unresolved at the GitHub slug level; the dashboard marks it as mapped to Bunny but without a confirmed GitHub repo.

### Files to read first for continuation

- [backoffice/deploy_control.py](/home/merm/projects/back-office/backoffice/deploy_control.py)
- [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py)
- [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html)
- [BUNNY_ROLLOUT_PLAN.md](/home/merm/projects/BUNNY_ROLLOUT_PLAN.md)
- [GITHUB_SECRETS_MANIFEST.md](/home/merm/projects/GITHUB_SECRETS_MANIFEST.md)
- [DEPLOY_CONTROL_PLANE_PLAN.md](/home/merm/projects/DEPLOY_CONTROL_PLANE_PLAN.md)

### Recommended next steps

1. Add one visible self-hosted GitHub runner and verify the dashboard flips at least one repo from blocked to ready.
2. Seed GitHub deploy secrets with [bootstrap-github-actions-secrets.sh](/home/merm/projects/bootstrap-github-actions-secrets.sh).
3. Add rollback support:
   - manual image tag input
   - workflow dispatch with override input
   - previous successful SHA surfaced from GitHub run history
4. Add workflow-run detail panels and live polling for in-progress deploys.
5. Add a first-class Back Office route or nav treatment if `deploy.html` becomes a core operator surface rather than a linked page.

## 2026-04-01 Local Forgejo Platform Direction

- Added a concrete local-first platform direction for private development, review, and workflow execution:
  - [docs/LOCAL_PLATFORM_ARCHITECTURE.md](/home/merm/projects/back-office/docs/LOCAL_PLATFORM_ARCHITECTURE.md)
  - [ops/forgejo-local/README.md](/home/merm/projects/back-office/ops/forgejo-local/README.md)
  - [ops/forgejo-local/compose.yaml](/home/merm/projects/back-office/ops/forgejo-local/compose.yaml)
  - [ops/forgejo-local/.env.example](/home/merm/projects/back-office/ops/forgejo-local/.env.example)
  - workspace file at [/home/merm/projects/codyjo-local-platform.code-workspace](/home/merm/projects/codyjo-local-platform.code-workspace)
- Recommended operating model:
  - Forgejo becomes the private git remote and review surface
  - Forgejo Actions becomes the private/local workflow engine
  - Back Office remains the portfolio dashboard and deploy controller
  - Bunny remains the runtime
  - GitHub becomes an optional public mirror only
- Extended the deploy-control backend toward that model in [backoffice/deploy_control.py](/home/merm/projects/back-office/backoffice/deploy_control.py):
  - source control provider now resolves as `forgejo` or `github`
  - Forgejo repo metadata and workflow runs can be read through `FORGEJO_BASE_URL` + `FORGEJO_TOKEN`
  - deploy dispatch now supports Forgejo workflow dispatch as well as `gh workflow run`
- Updated [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html) so the deploy dashboard renders source-control state generically instead of assuming GitHub-only control.
- Added local-forge operator helpers:
  - [scripts/bootstrap-forgejo-repos.sh](/home/merm/projects/back-office/scripts/bootstrap-forgejo-repos.sh)
  - [scripts/set-forgejo-remotes.sh](/home/merm/projects/back-office/scripts/set-forgejo-remotes.sh)
  - [scripts/mirror-public-repo.sh](/home/merm/projects/back-office/scripts/mirror-public-repo.sh)
  - [scripts/bootstrap-forgejo-runner.sh](/home/merm/projects/back-office/scripts/bootstrap-forgejo-runner.sh)
  - [scripts/run-back-office-forgejo.sh](/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh)
  - [docs/LOCAL_REVIEW_WORKFLOW.md](/home/merm/projects/back-office/docs/LOCAL_REVIEW_WORKFLOW.md)
- Added a focused resume packet for another agent at [docs/HANDOFF-OPEN-CLAUDE-LOCAL-FORGE.md](/home/merm/projects/back-office/docs/HANDOFF-OPEN-CLAUDE-LOCAL-FORGE.md).
- Updated the VSCodium workspace in [/home/merm/projects/codyjo-local-platform.code-workspace](/home/merm/projects/codyjo-local-platform.code-workspace) with a Forgejo bootstrap task.
- Completed the first live local-forge bootstrap:
  - Forgejo is installed and locked at `http://localhost:3300`
  - SSH is exposed at `localhost:2223`
  - admin user `CodyJo` exists
  - local credentials and token are stored in ignored files under `ops/forgejo-local/`
  - all top-level git repos were imported into Forgejo
  - local `origin` remotes were repointed to Forgejo across the imported repos
  - GitHub remotes were preserved as `github-public` where they existed
  - `selah` was pushed to Forgejo successfully and now tracks `origin/main`
  - local runner `codyjo-local-runner` is registered and running
  - a real Forgejo Actions run now exists for `CodyJo/selah` `deploy.yml` on push to `main`
  - that first run ended in `failure`, so the next task is run debugging rather than bootstrap
- Important current limitation:
  - the first observed `selah` workflow run failed and needs inspection before this can be called fully validated CI/CD.

### Immediate next steps

1. Run [scripts/archive-github-actions-history.sh](/home/merm/projects/back-office/scripts/archive-github-actions-history.sh) to capture old GitHub workflow metadata locally.
2. Open the local Forgejo UI and verify web login with the ignored credentials file.
3. Run Back Office through [scripts/run-back-office-forgejo.sh](/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh).
4. Inspect why the first `selah` Forgejo Actions run failed.
5. Add runner and PR visibility from Forgejo if the API surface exposes them cleanly enough for dashboard use.
6. Validate one full reviewed branch -> workflow -> Bunny deploy path.

## Current Direction

Back Office is centered on a human-centered approval model. The immediate product direction is: findings can be queued from the dashboard for approval, product additions are suggested instead of auto-added, draft GitHub PRs are opened only after explicit approval, and backlog visibility is isolated by product so queue counts do not bleed across repos.

For Bunny migration tooling, the active path is now [scripts/bunny-cli-next.mjs](/home/merm/projects/back-office/scripts/bunny-cli-next.mjs). Keep it self-contained and do not add new migration work to the old Bunny CLI. The old script may be removed after the remaining wrappers are cleaned up.

## 2026-03-27 Portfolio Auth/Legal Baseline

- Updated [docs/portfolio-engineering-standard.md](/home/merm/projects/back-office/docs/portfolio-engineering-standard.md) to make the portfolio auth/legal baseline explicit for Cordivent and future apps:
  - signup must require privacy-policy acknowledgement
  - signup must require explicit 16+ confirmation unless a documented exception exists
  - both checks must be enforced server-side, not only in UI
  - apps must store consent timestamp plus privacy policy version
  - signup should avoid birth-date collection unless there is a documented need
  - privacy/accessibility pages must reflect current hosting/processors rather than legacy infrastructure
- Updated [scripts/portfolio_drift_audit.py](/home/merm/projects/back-office/scripts/portfolio_drift_audit.py) so the audit now flags signup-flow apps that are missing:
  - UI privacy + 16+ acknowledgement
  - server-side privacy + 16+ enforcement
  - stored consent timestamp + policy version
- Current audit result after the change:
  - `pattern` is the remaining signup-flow app missing server-side enforcement and stored consent metadata

## 2026-03-28 Production Auth Smoke

- Added a portfolio-wide live auth smoke runner at [scripts/live-auth-smoke.mjs](/home/merm/projects/back-office/scripts/live-auth-smoke.mjs).
- The script exercises production:
  - `GET /health`
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `POST /api/auth/forgot-password`
  - full `reset-password -> login` where the reset code can be recovered from the live Bunny DB safely
- Live result on March 28, 2026:
  - initial full end-to-end pass: `certstudy`, `thenewbeautifulme`, `cordivent`
  - initial full end-to-end pass with deployment-drift note: `fuel`
    - production still required legacy DOB input during registration even though the repo had already been moved to the 16+ confirmation model
  - after deploying `ghcr.io/codyjo/fuel:authfix-20260328-1` to Bunny app `F8cKya950t3vhvH`, Fuel also passed full end to end with no DOB note
  - partial live pass: `selah`
    - register/login/forgot-password all passed
    - reset could not be completed automatically because Selah hashes reset codes before storage; full automation there needs inbox or Postal message retrieval
- The script retries transient network failures and exits non-zero only on real failures unless you disable partial allowances with `--no-allow-partial`.

## Completed

- Advanced [scripts/bunny-cli-next.mjs](/home/merm/projects/back-office/scripts/bunny-cli-next.mjs) into the actual migration CLI on March 27, 2026:
  - removed the dependency on the old Bunny CLI for unsupported commands; unsupported commands now fail explicitly instead of delegating
  - removed official `bunny` CLI passthrough so account state now comes from one code path instead of mixed tooling
  - added missing deploy/cutover commands that were previously only in the old script:
    - `app create`
    - `app delete`
    - `dns zones`
    - `dns zone`
    - `dns records`
    - `dns set`
    - `dns pullzone`
    - `dns delete`
    - `pz list`
    - `pz create`
    - `pz origin`
    - `pz hostname`
    - `pz ssl`
    - `pz purge`
    - `health`
  - carried forward the SSL ordering fix in `pz ssl`:
    - request the free certificate first
    - then enable force SSL
  - added DB operator helpers that were missing from the successor CLI:
    - `db group`
    - `db mirror`
  - updated `db create` so the primary-region argument can be a CSV list instead of only a single region code
  - live-validated with the new CLI:
    - `apps`
    - `db list`
    - `db group fuel`
    - `db create cordivent ...`
    - `db token cordivent`
  - important live DB control-plane finding:
    - Bunny rejects changing primary regions on an already-running DB group with `HTTP 409 Cannot change primary region while database is running`
    - the practical fix is to create the DB with the full desired primary-region list up front instead of creating single-region then mirroring later
  - used the new CLI to create Cordivent’s Bunny DB directly:
    - id: `db_01KMRP14VKC0G94G2VD2Q2CMFZ`
    - group: `group_01KMRP14S23A72T3CEQS159Z75`
    - URL: `libsql://01KMRP14S23A72T3CEQS159Z75-cordivent.lite.bunnydb.net/`
    - storage region: `us-east-1`
    - primary regions: `ASB, BO, CA, DEN, GA, IL, LA, MI, NY, SIL, TX, WA`
    - replica regions: `ASB, BO, CA, DEN, GA, IL, LA, MI, NY, SIL, TX, WA`
  - then used that DB for the live Cordivent DynamoDB-to-Bunny migration via `/home/merm/projects/fuel/scripts/migrate-to-bunny/cordivent/migrate.mjs`, which completed with `PASS`

- Added a safe Bunny CLI successor without touching the live migration script:
  - restored the live script at [scripts/bunny-cli.mjs](/home/merm/projects/back-office/scripts/bunny-cli.mjs) after an interrupted in-place refactor so the active migration path remains stable
  - created [scripts/bunny-cli-next.mjs](/home/merm/projects/back-office/scripts/bunny-cli-next.mjs) as the new work surface with explicit Magic Container management commands that the legacy/private Bunny workflows were missing:
    - `app spec`
    - `app image`
    - `app scale`
    - `app apply`
    - `env sync`
    - `env merge`
    - `env unset`
    - `endpoint list`
    - `endpoint remove`
    - `wait`
    - experimental database controls:
      - `db spec`
      - `db regions set`
      - `db replica add`
      - `db replica remove`
      - `db sql`
  - the new copy is structured as a testable module with exported helpers for env parsing, image parsing, endpoint normalization, patch payload generation, and app readiness polling
  - database notes:
    - `db sql` uses the documented Bunny Database SQL pipeline shape over the database URL with a bearer token
    - `db spec`, `db regions set`, and replica mutation commands use the same preview/private database control-plane endpoints the older script already depended on (`/database/v1/groups`, `/database/v1/databases`, `/database/v2/databases`)
    - the CLI prints an explicit experimental warning before those control-plane mutations because Bunny said the API may change
    - live validation on March 27, 2026:
      - `db list` works against the live account and enumerates `fuel`, `tnbm`, `certstudy`, and `selah`
      - `db spec fuel` works and returns both `/database/v2/databases/:id` and `/database/v1/groups/:id` data
      - `db token fuel read-only|full-access` works
      - SQL/data-plane commands work when `BUNNY_DB_BEARER_TOKEN` is set:
        - `db tables fuel`
        - `db schema fuel users`
        - `db pragma fuel journal_mode`
        - `db doctor fuel`
      - newly discovered hidden OpenAPI spec:
        - the dashboard docs page at `https://api.bunny.net/database/docs` embeds `Redoc.init("./docs/private/api.json", ...)`
        - `https://api.bunny.net/database/docs/private/api.json` exposes additional operations that were not yet in the CLI:
          - `/v1/config/limits`
          - `/v1/databases/{db_id}/fork`
          - `/v1/databases/{db_id}/restore`
          - `/v1/databases/{db_id}/list_versions`
          - `/v1/groups/{group_id}/auth/generate`
          - `/v1/groups/{group_id}/stats`
          - `/v2/databases/active_usage`
          - `/v2/databases/{db_id}/usage`
          - `/v2/databases/{db_id}/statistics`
      - implemented from the hidden spec in `bunny-cli-next.mjs`:
        - `db limits`
        - `db group-token`
        - `db versions`
        - `db fork`
        - `db restore`
        - `db usage`
        - `db stats`
        - `db group-stats`
        - `db active-usage`
        - `db api status`
        - `db api sync-spec`
      - live-validated on March 27, 2026:
        - `db limits`
        - `db active-usage`
        - `db usage fuel 2026-03-26T00:00:00Z 2026-03-27T23:59:59Z`
      - new drift-detection behavior in `bunny-cli-next.mjs`:
        - DB command failures that come back as Bunny Database `HTTP` errors now trigger a best-effort refresh of `https://api.bunny.net/database/docs/private/api.json`
        - the CLI caches that spec at `~/.cache/bunny-cli/bunny-database-private-api.json` by default, overridable with `BUNNY_DB_SPEC_CACHE`
        - when a DB call fails, the CLI compares the cached and fresh spec hashes, maps the failing concrete path back to its templated OpenAPI path, and appends a drift summary to the error
        - this does not self-modify the CLI; it tells the operator whether Bunny changed or removed the operation so the CLI can be updated quickly
        - explicit operator commands:
          - `db api status`
          - `db api sync-spec`
      - important auth finding: control-plane requests should use the Bunny access key only; including the bearer token on `/database/v1|v2` requests caused live `401` failures
      - important permission finding: the `doctor` checks failed under a read-only token with a write-permission error, but succeeded under a full-access token
      - current blocker: the hidden OpenAPI spec confirms the `CreateDatabaseV2Payload` shape you were already sending:
        - `name`
        - `storage_region`
        - `primary_regions`
        - `replicas_regions`
      - despite matching the documented schema, `db create codex-cli-probe-20260327` and `db create codex-cli-probe-20260327 DEN us-east-1` still returned Bunny-side `HTTP 500` responses under:
        - access-key auth
        - dashboard JWT auth
        - both headers together
      - inference: create-database is currently blocked by a Bunny backend issue or account-side gating, not by an obvious missing field in the documented payload
  - unsupported commands in the new copy delegate back to the live script so DNS, pull-zone, and database flows continue to work without reimplementing everything during the migration window
  - added regression coverage in [tests/test_bunny_cli_next.mjs](/home/merm/projects/back-office/tests/test_bunny_cli_next.mjs) for env parsing, image parsing, env sync patching, spec application, app wait polling, and CLI command dispatch
  - verified with:
    - `node --test /home/merm/projects/back-office/tests/test_bunny_cli_next.mjs`
    - `node --check /home/merm/projects/back-office/scripts/bunny-cli-next.mjs`
    - `BUNNY_API_KEY=test-key node /home/merm/projects/back-office/scripts/bunny-cli-next.mjs --help`
  - next recommended step after the current migration wave: exercise `bunny-cli-next.mjs` against one non-critical Bunny app first, then either rename it into place or keep it as the advanced/operator variant

- Repaired the HQ/migration dashboard shell on 2026-03-27:
  - fixed the stale `index-new.html` logo target in [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) so HQ nav resolves to the real dashboard entrypoint again
  - restyled [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) to use the same Back Office visual language as HQ instead of the detached one-off migration theme
  - added the same skip-link/main landmark structure to the migration page so navigation and accessibility behavior now match the rest of Back Office
  - preserved the existing migration API wiring and editable controls; this was a shell/style correction, not a data-model rewrite
  - verified the dashboard/server sync surface with `python3 -m pytest tests/test_sync_engine.py tests/test_servers.py` (`90 passed`)

- Refreshed the Back Office migration dashboard source of truth for the live Bunny wave:
  - updated [config/migration-plan.yaml](/home/merm/projects/back-office/config/migration-plan.yaml) so `app-redesign` is explicitly in progress
  - updated repo cards for `back-office`, `fuel`, `selah`, `certstudy`, and `thenewbeautifulme` to reflect the current live cutover state instead of the earlier staged-only wording
  - added live domain tracking for `fuel.codyjo.com` and `study.codyjo.com`, and marked `selahscripture.com` and `thenewbeautifulme.com` as active Bunny-facing cutovers
  - linked the active repo cards to the new deploy-audit docs in those repos so the migration page now points at concrete smoke/rollback guidance

- Added a reusable cloud migration comparison feature to Back Office:
  - new persisted model in [backoffice/cloud_migration_compare.py](/home/merm/projects/back-office/backoffice/cloud_migration_compare.py) backed by `config/cloud-cost-comparison.yaml` and mirrored to `results/` + `dashboard/`
  - added `GET /api/migration-plan/comparison` in [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py)
  - extended [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) to render scenario cost ranges and an AWS→GCP/Vercel/Netlify service mapping panel
  - seeded the current AWS month-to-date baseline from account `229678440188`, including a flagged CloudFront invalidation anomaly so scenario estimates do not blindly carry it forward
  - added regression coverage in [tests/test_cloud_migration_compare.py](/home/merm/projects/back-office/tests/test_cloud_migration_compare.py) and extended [tests/test_servers.py](/home/merm/projects/back-office/tests/test_servers.py)
- Added a new Back Office feature-plan seed for risk-based portfolio QA execution:
  - created [docs/superpowers/plans/2026-03-26-qa-remediation-planner.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-03-26-qa-remediation-planner.md)
  - documented the first remediation dataset using the March 26, 2026 portfolio QA backlog
  - added a corresponding ready task in [config/task-queue.yaml](/home/merm/projects/back-office/config/task-queue.yaml) so the feature exists in the approval/task workflow
- Implemented the first usable QA remediation planner surface in Back Office:
  - added persisted model [backoffice/remediation_plan.py](/home/merm/projects/back-office/backoffice/remediation_plan.py) backed by `config/remediation-plan.yaml` and mirrored to `results/remediation-plan.json` and `dashboard/remediation-plan.json`
  - the remediation plan is now generated from live `results/<repo>/findings.json` QA artifacts when present, with a seeded fallback only when no findings artifacts exist
  - added local API endpoints in [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) for:
    - `GET /api/remediation-plan`
    - `POST /api/remediation-plan/seed-wave-one`
    - `POST /api/remediation-plan/item/update`
    - `POST /api/remediation-plan/updates/add`
  - added an Operations dashboard tab in [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) that renders the remediation plan summary, wave breakdown, wave/repo status + notes controls, remediation updates, and a `Seed Wave 1 To Queue` action wired to the new API
  - tightened the finding-detail approval flow in [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) so `Queue for Approval` posts a stable finding hash, refreshes task-queue state, and re-renders the open detail panel after queuing
  - added regression coverage in [tests/test_remediation_plan.py](/home/merm/projects/back-office/tests/test_remediation_plan.py) and [tests/test_servers.py](/home/merm/projects/back-office/tests/test_servers.py)
  - intentionally limited edits to the remediation-planner slice plus the already-shared dashboard/server seams, leaving other unrelated in-progress Back Office worktree changes in place
- Removed the obsolete `admin.thenewbeautifulme.com` dashboard publish target from Back Office:
  - deleted the target from [config/backoffice.yaml](/home/merm/projects/back-office/config/backoffice.yaml) and [config/backoffice.codebuild.example.yaml](/home/merm/projects/back-office/config/backoffice.codebuild.example.yaml)
  - removed the old origin from [config/api-config.yaml](/home/merm/projects/back-office/config/api-config.yaml)
  - narrowed CodeBuild deploy permissions in [terraform/codebuild.tf](/home/merm/projects/back-office/terraform/codebuild.tf) so future CI/CD no longer needs access to the old bucket/distribution
  - re-ran the dashboard sync and confirmed only `admin.codyjo.com` published; `admin.thenewbeautifulme.com` is no longer a sync target
  - completed the AWS decommission for the old admin surface:
    - deleted Route53 `A` and `AAAA` alias records for `admin.thenewbeautifulme.com`
    - deleted the ACM validation CNAME for that hostname
    - deleted ACM certificate `bb9bf1b6-3190-4d08-afa7-14ca05630003`
    - deleted CloudFront distribution `E372ZR95FXKVT5`
    - deleted S3 bucket `admin-thenewbeautifulme-site`
    - verified final bucket removal with `aws s3api head-bucket --bucket admin-thenewbeautifulme-site`, which now returns `404 Not Found`
  - coordinated the final app-side cleanup live in `thenewbeautifulme`:
    - applied the API Gateway CORS removal for the retired hostname
    - updated the live API Lambda so it no longer emits `Access-Control-Allow-Origin` for `https://admin.thenewbeautifulme.com`
    - smoke verified that `useradmin.thenewbeautifulme.com` still receives the expected CORS header
- Added a first-class cloud migration planning surface to Back Office for the portfolio AWS exit plan:
  - new persisted model in [backoffice/migration_plan.py](/home/merm/projects/back-office/backoffice/migration_plan.py) backed by `config/migration-plan.yaml` and mirrored to `results/` + `dashboard/`
  - new local API endpoints in [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) for reading the plan, updating phase/repo/domain status, and appending update-log entries
  - dedicated full dashboard page at [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) linked from the HQ top bar, with auto-refresh every 15s and editable phases, repositories, domains, and update log
  - the original seeded content was GCP-first, but the current plan has now been updated to `Bunny static + edge`, `Scaleway backend/privacy core`, and `GCP email only`, with VM exceptions kept on Scaleway instances and `postal-aws` explicitly out of scope for this migration wave
  - added regression coverage in [tests/test_migration_plan.py](/home/merm/projects/back-office/tests/test_migration_plan.py) and extended [tests/test_servers.py](/home/merm/projects/back-office/tests/test_servers.py)
- Added execution bridging from the migration dashboard into the normal Back Office queue:
  - `POST /api/migration-plan/seed-wave-one` now seeds the first migration work wave into `task-queue`
  - the migration dashboard exposes `Seed Wave 1 Tasks`
  - live seed run already created 5 migration tasks in the queue for `back-office`, `codyjo.com`, `auth-service`, `certstudy`, and `fuel`
- Linked the migration dashboard to the live Back Office queue:
  - [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) now also reads `/api/tasks`
  - repository cards show inline queue state for seeded migration execution tasks and link back to the HQ queue
  - this keeps the migration plan page and the approval/execution queue visibly aligned during work
- Finished the shared-package cutover cleanup across the portfolio: removed the final checked-in mirror directory from `thenewbeautifulme`, retired `scripts/sync_shared_packages.py` and `tests/test_sync_shared_packages.py`, updated the portfolio audit to flag future mirror drift, and updated the engineering standard/roadmap to treat `/home/merm/projects/shared/packages` as the only approved shared package source.
- Added the missing legal/e2e baseline in the remaining apps: `continuum` now has top-level `/privacy` and `/accessibility` pages, `pattern` now has `/accessibility`, and `certstudy`, `selah`, `thenewbeautifulme`, `continuum`, and `pattern` now all have Playwright config plus a public smoke spec.
- Verified `continuum-ci` succeeds live with the `shared` secondary source attached, then removed the final fallback copy blocks from [continuum buildspecs](/home/merm/projects/continuum/buildspec-ci.yml). The Next app portfolio no longer depends on buildspec mirror fallbacks.
- Verified the new CodeBuild `shared` secondary source live in CI for `fuel`, `certstudy`, `selah`, and `thenewbeautifulme`, then removed the repo-local fallback copy blocks from those apps' buildspecs.
- Published `codebuild-module-v2` from `/home/merm/projects/codyjo.com` with secondary GitHub source support in the shared Terraform CodeBuild module, updated the app Terraform stacks to consume it, and applied the live CodeBuild project updates for `fuel`, `certstudy`, `selah`, `thenewbeautifulme`, and `continuum`.
- CodeBuild now provides `CodyJo/shared` as the `shared` secondary source for those apps; the remaining package-distribution work is just removing mirror fallbacks after live build verification.
- Moved all seven Next.js apps onto `/home/merm/projects/shared/packages` as their declared `@codyjo/*` dependency source. `fuel`, `certstudy`, `selah`, `thenewbeautifulme`, and `continuum` still keep mirrored package copies only as CI/bootstrap inputs, not as package.json source-of-truth.
- Closed the product-audit issues that were directly supported by code:
  - `backoffice.tasks.find_task()` now raises `ValueError` instead of `SystemExit`, and the local task CLI converts that back into a clean CLI exit message
  - `backoffice.server` now returns HTTP `404` for unknown task ids on approve, cancel, PR request, and product approval paths instead of letting task lookup abort the handler
  - `backoffice.api_server` now registers `cloud-ops` alongside the other production API departments
  - `backoffice.setup` no longer advertises `aider` as a supported runner because there is no implemented aider backend in the codebase today
  - `backoffice.setup.AGENT_USAGE` now includes `cloud-ops-audit.sh`
- Declared the missing package metadata surfaced by the product audit:
  - added runtime dependency `boto3` in `pyproject.toml`
  - added optional `dev` dependencies for `pytest` and `ruff`
- Closed the low-effort Cloud Ops items that matched the current Terraform:
  - `terraform/cost_guardrails.tf` now enables SNS topic encryption with `kms_master_key_id = "alias/aws/sns"`
  - `terraform/main.tf` and `terraform/variables.tf` now apply explicit `Owner`, `Environment`, and `CostCenter` default tags
- Verified the March 25 product/cloud-ops fixes with:
  - `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_setup.py tests/test_sync_providers.py`
  - `ruff check backoffice/tasks.py backoffice/server.py backoffice/api_server.py backoffice/setup.py backoffice/sync/providers/aws.py tests/test_tasks.py tests/test_servers.py tests/test_setup.py tests/test_sync_providers.py`
  - `terraform -chdir=terraform validate`
- Confirmed two cloud audit claims were stale versus the current Terraform:
  - `terraform/codebuild.tf` already scopes S3 deploy permissions to `PutObject`, `GetObject`, `DeleteObject`, and `ListBucket`
  - `terraform/codebuild.tf` already scopes CloudFront invalidation permissions to the two explicit dashboard distributions instead of `resources = ["*"]`
- Flipped the remaining vendored app manifests (`fuel`, `certstudy`, `selah`, `thenewbeautifulme`, `pattern`) to consume `@codyjo/*` from `/home/merm/projects/shared/packages`, and updated the CodeBuild-backed repos to bootstrap `../shared/packages` from their vendored mirrors before `npm ci`.
- Refreshed vendored mirrors with `scripts/sync_shared_packages.py`, reran `scripts/portfolio_drift_audit.py`, and reduced the shared-package-source backlog to only `continuum`'s repo-local `packages/` copies.
- Fixed the dashboard’s critical ADA skip-navigation issue in `dashboard/index.html`:
  - added a visible-on-focus skip link
  - wrapped primary dashboard content in `<main id="main-content">`
- Closed the compliance critical about explicit S3 encryption in `backoffice/sync/providers/aws.py`:
  - direct S3 uploads now set `ServerSideEncryption: AES256`
  - `aws s3 sync` now passes `--sse AES256`
- Added regression coverage in `tests/test_sync_providers.py` for both encrypted upload modes.
- Added `docs/COMPLIANCE-CONTROLS.md` to document:
  - local retention policy for findings and dashboard artifacts
  - privacy/transparency expectations for Back Office operators
  - storage and secret-handling controls
- Linked the new compliance controls doc from `README.md`.
- Verified the ADA/compliance changes with:
  - `python3 -m pytest tests/test_sync_providers.py tests/test_servers.py`
  - `ruff check backoffice/sync/providers/aws.py tests/test_sync_providers.py backoffice/server.py tests/test_servers.py`
- Closed the March 25 QA security findings in the product-add / PR-request path of `backoffice/server.py`:
  - local repo paths are now validated against approved roots instead of trusting arbitrary `local_path` or `target_path`
  - `github_repo` must now match `owner/repo` format before clone attempts
  - product config writes now use parsed YAML + `yaml.safe_dump` instead of interpolating user input directly into YAML text
  - empty `targets:` sections are normalized safely before writes
- Added regression coverage in `tests/test_servers.py` for:
  - rejecting product add paths outside approved roots
  - rejecting malformed `github_repo` values
  - YAML-safe product config writes
  - rejecting PR requests whose `target_path` falls outside approved roots
- Verified the server hardening changes with:
  - `python3 -m pytest tests/test_servers.py -q`
  - `ruff check backoffice/server.py tests/test_servers.py`
- Updated the target registry in both `config/targets.yaml` and `config/backoffice.yaml` so the newer `~/projects` repos are visible to Back Office:
  - added/synced `continuum`, `pattern`, `pe-bootstrap`, and `shared`
  - backfilled `config/backoffice.yaml` with targets that already existed in `config/targets.yaml` but were missing from the unified runtime config (`selah`, `analogify`, `cordivent`, `fuel`, `certstudy`, `auth-service`)
- Verified target config loading with:
  - `python3 -m backoffice list-targets`
  - `python3 -m backoffice config show`
  - YAML parse checks for `config/targets.yaml` and `config/backoffice.yaml`
- Fixed the top-level CLI bridge so `python3 -m backoffice audit` and `python3 -m backoffice audit-all` correctly translate to the workflow module’s `run-target` and `run-all` commands.
- Added regression coverage in `tests/test_main.py` for the `audit-all -> run-all` dispatch.
- Added a one-command safe local runner at `scripts/run-safe-local-backoffice.sh`:
  - lists configured targets
  - runs `python3 -m backoffice audit-all` locally against all configured targets or an explicit `--targets` subset
  - refreshes dashboard artifacts locally
  - starts `python3 -m backoffice serve`
  - force-sets `BACK_OFFICE_ENABLE_REMOTE_SYNC=0`, `BACK_OFFICE_ENABLE_AUTOFIX=0`, and `BACK_OFFICE_ENABLE_UNATTENDED=0`
- Verified the wrapper script syntax with:
  - `bash -n scripts/run-safe-local-backoffice.sh`
  - `python3 -m pytest tests/test_main.py tests/test_sync_engine.py tests/test_servers.py tests/test_tasks.py tests/test_backlog.py`
- Added local safety defaults so Back Office can be used against `~/projects` without accidental CloudFront cost or unattended execution:
  - `backoffice.sync.engine` now blocks remote publish by default unless `BACK_OFFICE_ENABLE_REMOTE_SYNC=1` is set, while still allowing CI/CodeBuild delivery paths
  - `backoffice.server` now blocks overnight start from the local dashboard unless `BACK_OFFICE_ENABLE_UNATTENDED=1` is set
  - `Makefile` now requires explicit opt-in for:
    - remote publish: `BACK_OFFICE_ENABLE_REMOTE_SYNC=1`
    - auto-fix: `BACK_OFFICE_ENABLE_AUTOFIX=1`
    - unattended workflows: `BACK_OFFICE_ENABLE_UNATTENDED=1`
  - `audit-all` and `audit-all-parallel` now refresh the local dashboard with `python3 -m backoffice refresh` instead of publishing remotely
  - `watch`, `scan-and-fix`, and `full-scan` no longer piggyback remote sync by default
- Added regression coverage for the new local safety defaults:
  - `tests/test_sync_engine.py` verifies remote sync is blocked unless explicitly enabled
  - `tests/test_servers.py` verifies overnight start is blocked by default
- Verified the local safety changes with:
  - `python3 -m pytest tests/test_sync_engine.py tests/test_servers.py tests/test_tasks.py tests/test_backlog.py`
  - `ruff check backoffice/sync/engine.py backoffice/server.py tests/test_sync_engine.py tests/test_servers.py`
- Audited the current GitHub-facing claims against the actual codebase and confirmed the main story is only partially supported:
  - approval queue, task persistence, per-product queue summaries, and draft PR creation are implemented
  - the repo still contains legacy autonomous and auto-fix paths (`overnight`, `watch --auto-fix`, `scan-and-fix`, `full-scan`) that contradict the strongest "nothing runs unattended" and "approval before execution" language in the README
  - GitHub PR creation is implemented, but the dashboard/server path only covers `pending_approval -> ready` and `ready_for_review -> pr_open`; moving work from `ready` to `ready_for_review` still depends on the task CLI or external workflow
  - cost-control claims around bounded CloudFront invalidation are supported in both `backoffice/sync/engine.py` and `backoffice/sync/providers/aws.py`
- Audited the dirty Back Office worktree and separated it into:
  - a coherent approval-workflow feature (`backoffice/tasks.py`, `backoffice/server.py`, `dashboard/index.html`, `tests/test_tasks.py`, `tests/test_servers.py`)
  - a coherent portfolio tooling set (`scripts/sync_shared_packages.py`, `tests/test_sync_shared_packages.py`, `scripts/portfolio_drift_audit.py`, `docs/portfolio-engineering-standard.md`)
  - generated or scratch artifacts that should not be blindly committed (`coverage.json`, `coverage.xml`, `lint-check.json`, `lint-output.json`, `pytest-output.txt`, `ruff-output.json`, one-off audit plans)
- Re-verified the approval workflow changes after the doc refresh with:
  - `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`
- Verified the shared package sync utility with:
  - `python3 -m pytest tests/test_sync_shared_packages.py`
- Refreshed the GitHub-facing documentation to present Back Office as a visibility-first, approval-driven control plane:
  - rewrote `README.md` around dashboard observability, approval queue behavior, GitHub review, and operator control
  - rewrote `docs/WORKFLOW-ARCHITECTURE.md` with deeper architecture detail and multiple diagrams for findings, backlog, queue, and delivery flow
  - rewrote `docs/CICD-REFERENCE.md` to explain CI/CD in the context of queue approval and GitHub review
- Migrated `selah` onto the same `@codyjo/app-config` / `@codyjo/app-shell` consumer pattern as Fuel and CertStudy, then synced vendored packages and verified Selah with targeted tests, typecheck, and a full build.
- Added approval-first task queue primitives in `backoffice/tasks.py`:
  - new statuses for `pending_approval`, `approved`, `queued`, and `pr_open`
  - per-product queue summaries so backlog counts stay isolated by `product_key`
  - helper constructors for queued finding fixes and product suggestions
- Added dashboard server endpoints in `backoffice/server.py` for:
  - queueing a finding from the dashboard into the human approval queue
  - approving or cancelling queued work
  - suggesting a product for approval
  - approving a suggested product and adding it to config
  - creating a draft GitHub PR for approved work so merge still requires GitHub review
- Reworked the dashboard UI in `dashboard/index.html`:
  - finding detail now includes `Queue for Approval`
  - Operations tab now shows `Approval Queue` as the primary decision surface
  - product onboarding now starts as `Suggest Product`, not direct add
  - approval cards surface per-product backlog numbers and explicit approval actions
- Added regression coverage in `tests/test_tasks.py` and `tests/test_servers.py` for the new queue summaries and approval endpoints.
- Verified the approval workflow changes with:
  - `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`

- Extended `@codyjo/app-config` with a shared metadata builder, adopted it in Fuel and CertStudy layouts, and added Fuel's missing accessibility page so the audit baseline closes that gap.
- Ran the first real consumer migration for `fuel` and `certstudy` onto `@codyjo/app-config` / `@codyjo/app-shell`, then verified both apps with targeted tests, typecheck, and full builds.
- Built `@codyjo/app-config` and `@codyjo/app-shell` in `/home/merm/projects/shared`, synced them into vendored app mirrors with `scripts/sync_shared_packages.py`, and confirmed the sync utility with `tests/test_sync_shared_packages.py`.
- Investigated the March 2026 AWS bill spike and confirmed it was not Lambda/runtime cost. `Amazon CloudFront` billed about `USD 1,012.35`, almost entirely from `Invalidations` on `203,470` paths.
- Confirmed the expensive path came from Back Office dashboard syncs targeting distributions `E30Z8D5XMDR1A9` (`admin.codyjo.com`) and `E372ZR95FXKVT5` (`admin.thenewbeautifulme.com`).
- Verified live invalidation batches on March 24, 2026 contained `22-23` file paths each, matching the old per-file invalidation behavior.
- Patched `backoffice/sync/engine.py` so sync invalidations collapse to one wildcard path per target:
  - root target: `/*`
  - prefixed target: `/<prefix>/*`
- Patched `backoffice/sync/providers/aws.py` so any future multi-path invalidation batch is normalized down to a single wildcard before it reaches CloudFront.
- Patched `buildspec-cd.yml` to seed `config/backoffice.yaml` from a tracked CodeBuild-safe config template so deploys no longer depend on the untracked local config file.
- Added `config/backoffice.codebuild.example.yaml` as the tracked CI/CD deploy config source.
- Added regression coverage in `tests/test_sync_engine.py` and `tests/test_sync_providers.py`.
- Verified the sync changes with:
  - `python3 -m pytest tests/test_sync_engine.py tests/test_sync_providers.py`
- Ran `bash /home/merm/projects/back-office/scripts/sync-dashboard.sh` locally on March 24, 2026 and confirmed both dashboard distributions invalidated exactly one path each.
- Audited the other AWS-backed portfolio repos for the same CloudFront invalidation failure mode and documented the result in `docs/COST_GUARDRAILS.md`.
  - `thenewbeautifulme`, `selah`, `fuel`, `certstudy`, `cordivent`, and `codyjo.com` currently invalidate one wildcard path (`/*`) in their CD pipelines, so they do not have the same unbounded per-file invalidation bug.
  - `analogify` invalidates a small fixed path list and already has an AWS budget configured.
- Added account-level billing guardrails in `terraform/cost_guardrails.tf` and applied them live on March 24, 2026:
  - Monthly account budget: `back-office-account-monthly` at `USD 250`
  - Monthly CloudFront budget: `back-office-cloudfront-monthly` at `USD 100`
  - Service-level Cost Anomaly monitor for `SERVICE`
  - Immediate SNS-backed anomaly subscription with `ANOMALY_TOTAL_IMPACT_ABSOLUTE >= USD 20`
  - SNS topic: `back-office-billing-alerts`
- Verified the Terraform changes with:
  - `terraform -chdir=/home/merm/projects/back-office/terraform validate`
  - `terraform -chdir=/home/merm/projects/back-office/terraform plan`
  - `terraform -chdir=/home/merm/projects/back-office/terraform apply -auto-approve`
- Added live per-project monthly AWS budgets for the remaining CloudFront-backed repos:
  - `thenewbeautifulme-monthly` at `USD 100`
  - `bible-app-monthly` at `USD 75`
  - `fuel-monthly` at `USD 50`
  - `certstudy-monthly` at `USD 50`
  - `etheos-app-monthly` at `USD 50`
  - `codyjo-com-monthly` at `USD 50`

## Pending

- Extend the QA remediation planner beyond the seeded static dataset:
  - refine the live planner heuristics beyond the current repo-to-wave rules if you want fully derived wave assignment instead of the current hybrid of live findings + curated repo execution policy
- Decide whether to bring the code in line with the approval-first docs or soften the docs to match reality. The current gap is specifically around:
  - `Makefile` targets: `watch`, `scan-and-fix`, `full-scan`, and all `overnight*` targets
  - `backoffice/server.py` overnight start/stop/status endpoints
  - dashboard copy that says "Nothing runs unattended" while direct fix commands still exist
- If the approval-first story is the product direction, add an explicit server/dashboard/worker path for `ready -> in_progress -> ready_for_review` so the GitHub PR flow is truly end-to-end from the queue.
- Generated and scratch files are still present locally and should stay out of normal pushes unless there is an explicit archival reason:
  - `coverage.json`, `coverage.xml`, `lint-check.json`, `lint-output.json`, `pytest-output.txt`, `ruff-output.json`
  - `2026-03-23-compliance-audit-plan.md`
  - `AUDIT_PLAN-analogify.md`
  - `docs/superpowers/plans/2026-03-23-fuel-monetization-audit.md`
  - `docs/superpowers/plans/2026-03-24-monetization-audit-tnbm.md`
  - `generate-codyjo-monetization.js`
  - `docs/email/` if you do not want cross-repo implementation notes living in Back Office
- Decide whether to remove the remaining legacy automation codepaths entirely or keep them as internal-only compatibility surfaces. The primary dashboard UX and GitHub docs now center on approval-driven operation.
- Browser-verify the new approval queue interactions in `dashboard/index.html`. The Python test suite passed, but the new UI flow was not exercised in a live browser in this pass.
- If draft PR creation will be used heavily, add a targeted server test for the `gh pr create` success/failure path with subprocess mocking.
- Consider refreshing secondary docs and generated dashboard documentation surfaces if you want the same approval-first story everywhere, not just in the core GitHub docs.
- Decide whether to address the remaining medium cloud findings if those resources move into this repo:
  - log retention for future Lambda/API log groups
  - alarms for future auth/API functions
  - runtime and memory tuning for future Lambda resources

## Key Decisions And Constraints

- The billing math matched exactly: CloudFront invalidation pricing is effectively `($0.005 * (paths - 1000 free))`; `203,470 - 1,000 = 202,470`, and `202,470 * 0.005 = USD 1,012.35`.
- The spike came from repeated dashboard syncs over a short window on March 24, 2026, not from normal traffic volume, Lambda usage, or origin transfer.
- Provider-level normalization is required in addition to engine-level shaping because Back Office has multiple sync invocation paths (`make dashboard`, `quick-sync`, `watch`, and CodeBuild CD).
- AWS Cost Anomaly Detection can use `IMMEDIATE` only when the subscriber is SNS. Direct email subscriptions require `DAILY` or `WEEKLY`.
- Do not assume the repo is clean; there were pre-existing modified and untracked files unrelated to this fix.
- The new approval workflow intentionally does not auto-run fixes when a finding is clicked. Clicking a finding now queues human-reviewable work; approval moves it to `ready`, and draft PR creation is a separate explicit action.
- `gh pr create` is executed from the task's `target_path` and intentionally refuses to open a PR from `main` or `master`.
- Product backlog isolation now comes from task queue summaries grouped by `product_key`; if future dashboards still show crossed counts, inspect product mapping in `dashboard/org-data.json` and `backoffice/tasks.py::infer_product_key`.

## Files To Read First

- `backoffice/migration_plan.py`
- `dashboard/migration.html`
- `dashboard/index.html`
- `backoffice/server.py`
- `tests/test_migration_plan.py`
- `README.md`
- `docs/WORKFLOW-ARCHITECTURE.md`
- `docs/CICD-REFERENCE.md`
- `backoffice/tasks.py`
- `backoffice/server.py`
- `dashboard/index.html`
- `tests/test_tasks.py`
- `tests/test_servers.py`
- `backoffice/sync/engine.py`
- `backoffice/sync/providers/aws.py`
- `tests/test_sync_engine.py`
- `tests/test_sync_providers.py`
- `config/backoffice.yaml`
- `buildspec-cd.yml`
- `docs/COST_GUARDRAILS.md`
- `terraform/cost_guardrails.tf`
- `terraform/variables.tf`

## Integration Points

- Approval queue artifacts:
  - `config/task-queue.yaml`
  - `results/task-queue.json`
  - `dashboard/task-queue.json`
- Approval actions served by:
  - `backoffice/server.py`
  - `dashboard/index.html`
- Dashboard target definitions: `config/backoffice.yaml`
- Dashboard publish entrypoints: `scripts/sync-dashboard.sh`, `scripts/quick-sync.sh`
- Sync caller paths:
  - `Makefile`
  - `agents/watch.sh`
  - `buildspec-cd.yml`
- CloudFront targets:
  - `E30Z8D5XMDR1A9`
  - `E372ZR95FXKVT5`
  - `EF4U8A7W3OH5K` if public publish is ever enabled

## Recommended Next Steps

1. Browser-test the new finding queue, product suggestion, approval, and draft PR actions end-to-end from the dashboard.
2. Decide whether to fully remove or formally deprecate the remaining legacy automation codepaths so the product story stays consistent with the approval-centric docs and UI.
3. Confirm the email subscription on `back-office-billing-alerts` is accepted by the mailbox recipient.
4. Keep new deploy code aligned with the checklist in `docs/COST_GUARDRAILS.md`.

## Verification

- `python3 -m pytest tests/test_tasks.py tests/test_servers.py tests/test_backlog.py`
- `python3 -m pytest tests/test_sync_engine.py tests/test_sync_providers.py`
- `terraform -chdir=/home/merm/projects/back-office/terraform validate`
- `terraform -chdir=/home/merm/projects/back-office/terraform plan`
- `terraform -chdir=/home/merm/projects/back-office/terraform apply -auto-approve`

## 2026-03-25 Portfolio Standards Kickoff

- Migrated `thenewbeautifulme` onto the same `@codyjo/app-config` / `@codyjo/app-shell` consumer pattern as Fuel, CertStudy, and Selah, then verified the app with the Plausible regression test, typecheck, and a full production build.
- Added `scripts/sync_shared_packages.py` to copy source-of-truth shared packages into app-local vendor directories for repos that still require self-contained builds.
- Added `/home/merm/projects/shared/packages/app-shell` with first-pass shared shell helpers for skip-link/main-content consistency and versioned onboarding state.
- Added `docs/portfolio-engineering-standard.md` to define the portfolio baseline for shared packages, accessibility, testing, and shell conventions.
- Added `scripts/portfolio_drift_audit.py` as the first-pass automated drift check for the Next.js app portfolio.
- Added `/home/merm/projects/shared/packages/app-config` as the first new shared package for config-driven app metadata and shell extraction.
- Intended next step: create `@codyjo/app-shell`, then migrate Fuel and CertStudy first.

## 2026-03-30 SEO Blog Draft Batch

- Added review-only draft blog posts under [docs/seo-blog-drafts](/home/merm/projects/back-office/docs/seo-blog-drafts) for the Back Office product story. No dashboard or public site assets were changed.
- Drafts created:
  - [2026-02-18-ai-code-review-dashboard.md](/home/merm/projects/back-office/docs/seo-blog-drafts/2026-02-18-ai-code-review-dashboard.md)
  - [2026-03-14-reviewable-ai-engineering-workflows.md](/home/merm/projects/back-office/docs/seo-blog-drafts/2026-03-14-reviewable-ai-engineering-workflows.md)
- The drafts are positioned for future marketing/docs publication and emphasize the product's approval-centric operating model rather than autonomous hype.
- Recommended next step:
  - decide whether approved pieces belong in the public product docs, a dedicated marketing/blog surface, or the CodyJo parent-site blog as product-linked thought-leadership posts

## 2026-04-02 Local Infrastructure Monitoring Chunk 1 Foundation

- Implemented Chunk 1 foundation tasks from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md) through the file-creation/provisioning steps only.
- Completed work:
  - added `monitoring/.env` to [.gitignore](/home/merm/projects/back-office/.gitignore)
  - created [monitoring/.env.example](/home/merm/projects/back-office/monitoring/.env.example)
  - created local untracked `monitoring/.env` with generated `openssl rand -base64 16` passwords
  - created [monitoring/timescaledb/init.sql](/home/merm/projects/back-office/monitoring/timescaledb/init.sql)
  - created [monitoring/ingest/requirements.txt](/home/merm/projects/back-office/monitoring/ingest/requirements.txt), [monitoring/ingest/main.py](/home/merm/projects/back-office/monitoring/ingest/main.py), and [monitoring/ingest/Dockerfile](/home/merm/projects/back-office/monitoring/ingest/Dockerfile)
  - replaced [monitoring/docker-compose.yml](/home/merm/projects/back-office/monitoring/docker-compose.yml) with the 4-service stack from the plan
  - created [monitoring/provisioning/datasources/timescaledb.yml](/home/merm/projects/back-office/monitoring/provisioning/datasources/timescaledb.yml)
- Current direction:
  - Chunk 1 file setup is in place; the next planned step is the smoke-test portion of Task 6 when container startup is allowed
  - later chunks still need the Vector collector scripts, Vector config, and Grafana dashboards from the same plan
- Pending work:
  - do not regenerate or commit `monitoring/.env`; it is intentionally local-only
  - start the stack and run the smoke tests from Task 6 when explicitly requested
  - continue with Chunk 2+ plan items afterward
- Constraints:
  - implementation followed the plan file bodies exactly, including the async ingest service and NDJSON parsing
  - no Docker containers were started in this pass
  - the compose file references later-chunk assets such as `monitoring/vector/vector.yaml` and dashboard JSON files that are not created yet
- Key files:
  - [monitoring/docker-compose.yml](/home/merm/projects/back-office/monitoring/docker-compose.yml)
  - [monitoring/timescaledb/init.sql](/home/merm/projects/back-office/monitoring/timescaledb/init.sql)
  - [monitoring/ingest/main.py](/home/merm/projects/back-office/monitoring/ingest/main.py)
  - [monitoring/provisioning/datasources/timescaledb.yml](/home/merm/projects/back-office/monitoring/provisioning/datasources/timescaledb.yml)
  - [monitoring/.env.example](/home/merm/projects/back-office/monitoring/.env.example)
- Integrations:
  - Vector is configured to post NDJSON batches to the ingest service over HTTP
  - ingest writes to TimescaleDB using `psycopg_pool.AsyncConnectionPool`
  - Grafana is provisioned with a PostgreSQL datasource against TimescaleDB
- Next steps:
  - if continuing this plan, create the collector scripts and Vector config before trying to launch the full compose stack
  - once the remaining referenced files exist, rerun `docker compose config --quiet` from `monitoring/`
  - when smoke testing is allowed, bring up only the services called for in Task 6 and validate DB schema plus ingest health
- Verification state:
  - file creation and commit boundaries were completed for the requested foundation tasks
  - requested local verification commands should be rerun after the remaining compose-referenced files are present

## 2026-04-02 Local Infrastructure Monitoring Chunk 9 Tests

- Implemented Task 23 and Task 24 from [docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md](/home/merm/projects/back-office/docs/superpowers/plans/2026-04-02-local-infrastructure-monitoring.md) exactly for file contents and Makefile target shape.
- Completed work:
  - created empty [tests/monitoring/__init__.py](/home/merm/projects/back-office/tests/monitoring/__init__.py)
  - created [tests/monitoring/test_collectors.py](/home/merm/projects/back-office/tests/monitoring/test_collectors.py) with the exact helpers and 10 planned tests
  - created executable [monitoring/scripts/smoke-test.sh](/home/merm/projects/back-office/monitoring/scripts/smoke-test.sh)
  - added `monitoring-test` to [Makefile](/home/merm/projects/back-office/Makefile)
- Constraints:
  - did not run the smoke test script
  - did not start Docker containers
  - left collector implementations unchanged even though some now fail the new tests
- Verification:
  - ran `python3 -m pytest tests/monitoring/test_collectors.py -v`
  - result: 7 passed, 3 failed
  - failing cases:
    - `TestGpuMetrics::test_produces_valid_json`
    - `TestGpuMetrics::test_has_expected_metrics`
    - `TestSystemSensors::test_has_vmstat_metrics`
  - observed causes from current repo state:
    - [monitoring/vector/collectors/gpu_metrics.sh](/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh) emitted invalid JSON on this host because the final parsed value expanded to `Not Active, 1, 8`
    - [monitoring/vector/collectors/system_sensors.sh](/home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh) returned an empty metric set for the vmstat assertions on this host
- Next steps:
  - fix the collector scripts if the goal is to make Chunk 9 green
  - rerun the same pytest command after collector fixes
