# Local Infrastructure Monitoring & Remote Access

**Date:** 2026-04-02
**Status:** Draft
**Scope:** back-office/monitoring, back-office/ops/forgejo-local, host config (borg)

## Summary

Comprehensive local monitoring stack for the borg workstation (Ryzen 7 8700G, 60 GB RAM, RTX 3080) with Grafana dashboards for host metrics, GPU monitoring, Ollama LLM inference tracking, and Claude Code session visibility. Includes LAN remote access (SSH, Samba, RDP) from laptop and Forgejo git server integration. Mirrors the work stack (Vector → TimescaleDB → Grafana) for professional development.

## Goals

1. Monitor borg's health: CPU, RAM, disk, thermals, network
2. Monitor RTX 3080: temperature, VRAM, utilization, throttling, power
3. Monitor Ollama LLM inference: GPU vs CPU offload detection, tokens/sec, model status
4. Monitor Claude Code sessions: active agents, worktrees
5. Full LAN access from laptop: terminal (SSH), files (Samba), desktop (RDP)
6. Integrate Forgejo as accessible local git server
7. Learn the Vector → TimescaleDB → Grafana stack used at work

## Architecture

### Stack

```
Vector (collection + transport)
  → TimescaleDB (metrics + logs storage)
  → Grafana (dashboards + alerts)
```

Three containers. Vector collects all metrics via built-in host_metrics source and exec sources for GPU/Ollama/Claude/system sensors, then writes directly to TimescaleDB. Grafana reads TimescaleDB via native PostgreSQL datasource.

### Container Inventory

| Service | Image | Port | Purpose |
|---|---|---|---|
| vector | timberio/vector | 8686 | Collection, transforms, sinks |
| timescaledb | timescale/timescaledb:latest-pg16 | 5433 | Metrics + logs hypertables |
| grafana | grafana/grafana:11.6.0 | 3333 | Dashboards + alerts |

Port 5433 for TimescaleDB avoids conflict with any local PostgreSQL default (5432). Port 3333 is unchanged from existing Grafana config.

### Data Flow

```
Host (borg)
  │
  ├─ Vector host_metrics source ──→ host_normalize ──────┐
  ├─ gpu_metrics.sh (exec) ───────→ gpu_explode ─────────┤
  ├─ system_sensors.sh (exec) ────→ sensors_normalize ───┤
  ├─ ollama_metrics.sh (exec) ────→ ollama_normalize ────┤
  ├─ journald (ollama unit) ──────→ ollama_inference ────┤
  ├─ journald (kernel, oomd) ─────→ system_events ───────┤
  ├─ claude_sessions.sh (exec) ───→ claude_normalize ────┤
  └─ docker_logs ─────────────────→ docker_normalize ────┤
                                                         │
                                                      route
                                                     ╱      ╲
                                             metrics        logs
                                                │              │
                                                ▼              ▼
                                          TimescaleDB    TimescaleDB
                                          (metrics)      (logs)
                                                │
                                             Grafana (:3333)
```

## Data Model

### Metrics Hypertable

```sql
CREATE TABLE metrics (
    time        TIMESTAMPTZ NOT NULL,
    host        TEXT NOT NULL,
    source      TEXT NOT NULL,
    metric      TEXT NOT NULL,
    labels      JSONB DEFAULT '{}',
    value       DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('metrics', 'time');

-- Indexes for common query patterns
CREATE INDEX idx_metrics_source_metric ON metrics (source, metric, time DESC);
CREATE INDEX idx_metrics_labels ON metrics USING GIN (labels);
```

### Logs Hypertable

```sql
CREATE TABLE logs (
    time        TIMESTAMPTZ NOT NULL,
    host        TEXT NOT NULL,
    source      TEXT NOT NULL,
    service     TEXT,
    level       TEXT,
    message     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}'
);

SELECT create_hypertable('logs', 'time');

CREATE INDEX idx_logs_service ON logs (service, time DESC);
CREATE INDEX idx_logs_level ON logs (level, time DESC);
```

### Continuous Aggregate (5-min rollups)

```sql
CREATE MATERIALIZED VIEW metrics_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    host, source, metric, labels,
    avg(value) AS avg_val,
    max(value) AS max_val,
    min(value) AS min_val
FROM metrics
GROUP BY bucket, host, source, metric, labels;

-- Refresh policy: keep up to date within 10 minutes
SELECT add_continuous_aggregate_policy('metrics_5m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes');
```

Note: `labels` is included in the GROUP BY so per-label queries (specific CPU core, specific disk device) work against the rollup view.

### Retention & Compression

```sql
-- Compression after 1 day
ALTER TABLE metrics SET (timescaledb.compress);
SELECT add_compression_policy('metrics', INTERVAL '1 day');

-- Retention: 90 days for metrics, 30 days for logs
SELECT add_retention_policy('metrics', INTERVAL '90 days');
SELECT add_retention_policy('logs', INTERVAL '30 days');
```

| Policy | Value |
|---|---|
| Chunk interval | 1 hour |
| Compression | After 1 day |
| Metrics retention | 90 days |
| Logs retention | 30 days |

## Metrics Catalog

### Host Metrics — from Vector `host_metrics` source (source: `host`)

These come from Vector's built-in `host_metrics` collectors (cpu, memory, disk, filesystem, network, load).

| metric | labels | unit | notes |
|---|---|---|---|
| `cpu_usage_percent` | `{core: "0"}` | % | From cpu collector |
| `memory_used_bytes` | | bytes | From memory collector |
| `memory_total_bytes` | | bytes | From memory collector |
| `memory_available_bytes` | | bytes | From memory collector |
| `disk_used_bytes` | `{device, mount}` | bytes | From filesystem collector |
| `disk_total_bytes` | `{device, mount}` | bytes | From filesystem collector |
| `disk_io_read_bytes` | `{device}` | bytes (cumulative) | From disk collector; compute rate in Grafana |
| `disk_io_write_bytes` | `{device}` | bytes (cumulative) | From disk collector; compute rate in Grafana |
| `network_rx_bytes` | `{interface}` | bytes (cumulative) | From network collector; compute rate in Grafana |
| `network_tx_bytes` | `{interface}` | bytes (cumulative) | From network collector; compute rate in Grafana |
| `load_avg_1m` | | - | From load collector |
| `load_avg_5m` | | - | From load collector |
| `swap_used_bytes` | | bytes | From memory collector |
| `swap_total_bytes` | | bytes | From memory collector |

Note: disk I/O, network, and swap I/O are cumulative counters. Rate conversion (`value - lag(value)`) / interval) happens in Grafana SQL queries or in a Vector transform.

### System Sensor Metrics — from `system_sensors.sh` exec source (source: `sensors`)

These metrics are NOT available from Vector's `host_metrics` and require a dedicated collector script that reads from `/sys/` and `/proc/`.

| metric | labels | unit | data source |
|---|---|---|---|
| `cpu_temp_celsius` | `{sensor: "k10temp", core: "0"}` | C | `/sys/class/hwmon/*/temp*_input` (k10temp driver) |
| `cpu_freq_mhz` | `{core: "0"}` | MHz | `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq` |
| `memory_page_faults_major` | | count (cumulative) | `/proc/vmstat` → `pgmajfault` |
| `oom_kills_total` | | count (cumulative) | `/proc/vmstat` → `oom_kill` |
| `swap_io_in_pages` | | count (cumulative) | `/proc/vmstat` → `pswpin` |
| `swap_io_out_pages` | | count (cumulative) | `/proc/vmstat` → `pswpout` |

### GPU Metrics — from `gpu_metrics.sh` exec source (source: `gpu`)

All from `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`.

| metric | labels | unit | nvidia-smi field |
|---|---|---|---|
| `gpu_temp_celsius` | `{gpu: "rtx3080"}` | C | `temperature.gpu` |
| `gpu_utilization_percent` | `{gpu}` | % | `utilization.gpu` |
| `gpu_memory_used_bytes` | `{gpu}` | bytes | `memory.used` (MiB, converted) |
| `gpu_memory_total_bytes` | `{gpu}` | bytes | `memory.total` (MiB, converted) |
| `gpu_memory_free_bytes` | `{gpu}` | bytes | `memory.free` (MiB, converted) |
| `gpu_power_watts` | `{gpu}` | W | `power.draw` |
| `gpu_power_limit_watts` | `{gpu}` | W | `power.limit` |
| `gpu_fan_percent` | `{gpu}` | % | `fan.speed` |
| `gpu_clock_current_mhz` | `{gpu}` | MHz | `clocks.current.graphics` |
| `gpu_clock_max_mhz` | `{gpu}` | MHz | `clocks.max.graphics` |
| `gpu_throttle_idle` | `{gpu}` | 0/1 | `clocks_throttle_reasons.gpu_idle` |
| `gpu_throttle_hw_thermal` | `{gpu}` | 0/1 | `clocks_throttle_reasons.hw_thermal_slowdown` |
| `gpu_throttle_sw_thermal` | `{gpu}` | 0/1 | `clocks_throttle_reasons.sw_thermal_slowdown` |
| `gpu_throttle_sw_power_cap` | `{gpu}` | 0/1 | `clocks_throttle_reasons.sw_power_cap` |
| `gpu_pcie_link_gen` | `{gpu}` | gen | `pcie.link.gen.current` |
| `gpu_pcie_link_width` | `{gpu}` | lanes | `pcie.link.width.current` |

Note: nvidia-smi does not expose PCIe throughput counters. `pcie.link.gen` and `pcie.link.width` indicate the link capability (e.g., Gen4 x16) but not active bandwidth. For throughput monitoring, `nvidia-smi dmon` could be used but adds parsing complexity — deferred to a future enhancement.

### Ollama Status Metrics — from `ollama_metrics.sh` exec source (source: `ollama`)

These come from polling `GET localhost:11434/api/ps` and `GET localhost:11434/api/tags`.

| metric | labels | unit | API source |
|---|---|---|---|
| `ollama_running` | | 0/1 | HTTP response from /api/tags (0 if curl fails) |
| `ollama_models_available` | | count | `/api/tags` → length of `models` array |
| `ollama_model_loaded` | `{model}` | 0/1 | `/api/ps` → model present in `models` array |
| `ollama_model_size_bytes` | `{model}` | bytes | `/api/ps` → `size` |
| `ollama_model_vram_bytes` | `{model}` | bytes | `/api/ps` → `size_vram` |
| `ollama_model_vram_ratio` | `{model}` | 0.0-1.0 | Computed: `size_vram / size` |
| `ollama_model_expires_at` | `{model: "...", expires_at: "2026-..."}` | 0/1 | Stored as label (not float value); value is 1 if model has expiry set |

Note: `ollama_model_expires_at` is stored as a label rather than a float value to avoid epoch timestamp precision loss in DOUBLE PRECISION.

### Ollama Inference Metrics — from `ollama_journal` journald source (source: `ollama_inference`)

These are parsed from Ollama's journald logs. Ollama logs inference timing stats per request. These are NOT available from the `/api/ps` or `/api/tags` endpoints — they appear only in per-request responses and log output.

| metric | labels | unit | parsed from |
|---|---|---|---|
| `ollama_eval_rate` | `{model}` | tokens/s | Log line: computed from `eval_count / eval_duration` |
| `ollama_prompt_eval_rate` | `{model}` | tokens/s | Log line: `prompt_eval_count / prompt_eval_duration` |
| `ollama_time_to_first_token_ms` | `{model}` | ms | Log line: `prompt_eval_duration` (approximation) |
| `ollama_eval_duration_ms` | `{model}` | ms | Log line: `eval_duration` |
| `ollama_prompt_eval_duration_ms` | `{model}` | ms | Log line: `prompt_eval_duration` |
| `ollama_total_duration_ms` | `{model}` | ms | Log line: `total_duration` |
| `ollama_tokens_generated` | `{model}` | count | Log line: `eval_count` |

### Claude Code Metrics — from `claude_sessions.sh` exec source (source: `claude`)

| metric | labels | unit |
|---|---|---|
| `claude_active_sessions` | | count |
| `claude_worktrees_active` | | count |
| `claude_session_uptime_sec` | `{session_id}` | seconds |

## Vector Pipeline

### Sources

| Source | Type | Interval | Collects |
|---|---|---|---|
| `host_metrics` | host_metrics (built-in) | 15s | CPU, RAM, disk, network, filesystem, load, swap |
| `gpu_metrics` | exec | 15s | nvidia-smi output (temp, VRAM, clocks, throttle, power) |
| `system_sensors` | exec | 15s | CPU temp, CPU freq, page faults, OOM kills, swap I/O |
| `ollama_metrics` | exec | 30s | /api/ps + /api/tags (model status, VRAM ratio) |
| `claude_metrics` | exec | 60s | pgrep claude, worktree count |
| `ollama_journal` | journald | stream | Ollama unit logs (inference timing stats) |
| `system_journal` | journald | stream | kernel, oomd, system76-power (OOM, thermal events) |
| `docker_logs` | docker_logs | stream | forgejo, grafana containers |

### Collector Scripts

All collector scripts follow these rules:
1. **Check tool availability** before running (e.g., `command -v nvidia-smi`)
2. **Output valid JSON with zero-values on failure** (e.g., `{"ollama_running": 0}` if Ollama is down)
3. **Exit 0 even on partial failure** so Vector doesn't mark the exec source as failed

**`gpu_metrics.sh`** — runs `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,memory.free,power.draw,power.limit,clocks.current.graphics,clocks.max.graphics,fan.speed,clocks_throttle_reasons.gpu_idle,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.sw_power_cap,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits`. Parses CSV, converts MiB to bytes, outputs JSON array of metric objects. If `nvidia-smi` is not found, outputs all-zero JSON.

**`system_sensors.sh`** — reads `/sys/class/hwmon/*/temp*_input` for CPU temps (k10temp), `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq` for CPU frequency, `/proc/vmstat` for `pgmajfault`, `oom_kill`, `pswpin`, `pswpout`. Outputs JSON array. Falls back to zeros for any unreadable path.

**`ollama_metrics.sh`** — polls `curl -s localhost:11434/api/ps` and `curl -s localhost:11434/api/tags`. Computes `vram_ratio = size_vram / size`. Outputs JSON. If curl fails (Ollama down), outputs `{"ollama_running": 0}`.

**`claude_sessions.sh`** — counts `claude` processes via `pgrep -c claude`, counts git worktrees via `find /home/merm/projects -name .git -type d` and `git worktree list`. Outputs JSON. If no sessions, outputs `{"claude_active_sessions": 0, "claude_worktrees_active": 0}`.

### Transforms

- `host_normalize` — maps Vector's host_metrics events to `{host, source, metric, labels, value}` schema
- `gpu_explode` — splits single GPU JSON event into individual metric events per field
- `sensors_normalize` — maps system_sensors.sh JSON to metric events
- `ollama_normalize` — computes derived metrics (vram_ratio), splits into individual metric events
- `ollama_inference_parse` — parses Ollama journald log lines for eval_count, eval_duration, prompt_eval_count, prompt_eval_duration, total_duration; computes rates (tokens/s)
- `system_events` — detects OOM kills and thermal events from kernel journal; routes events as both metrics (counter increments) and logs
- `claude_normalize` — maps claude_sessions.sh JSON to metric events
- `docker_normalize` — maps Docker container log events to `{time, host, source, service, level, message, metadata}` log schema; extracts container name as `service`, parses log level if present
- `route` — splits metrics vs logs to separate sinks based on event type

#### Example VRL Transform (host_normalize)

```vrl
# Map Vector host_metrics events to our schema
.host = "borg"
.source = "host"

# Vector host_metrics events have .name (e.g., "host_cpu_seconds_total")
# and .tags (e.g., {"cpu": "0", "collector": "cpu"})
.metric = replace(.name, "host_", "")
.labels = .tags ?? {}
.value = .gauge.value ?? .counter.value ?? 0.0

# Keep only fields we need
del(.tags)
del(.name)
del(.gauge)
del(.counter)
del(.namespace)
del(.kind)
```

### Sinks

The Vector sink type is `postgres` (not `postgresql`). Note: this sink is currently in beta status in Vector.

```yaml
sinks:
  timescaledb_metrics:
    type: postgres
    inputs: ["route.metrics"]
    endpoint: "postgresql://vector:${TSDB_PASSWORD}@timescaledb:5433/monitoring"
    table: metrics
    encoding:
      codec: json

  timescaledb_logs:
    type: postgres
    inputs: ["route.logs"]
    endpoint: "postgresql://vector:${TSDB_PASSWORD}@timescaledb:5433/monitoring"
    table: logs
    encoding:
      codec: json
```

### Docker Compose Skeleton

```yaml
services:
  vector:
    image: timberio/vector:latest-debian
    container_name: breakpoint-vector
    restart: unless-stopped
    ports:
      - "8686:8686"
    volumes:
      - ./vector/vector.yaml:/etc/vector/vector.yaml:ro
      - ./vector/collectors:/etc/vector/collectors:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /run/log/journal:/run/log/journal:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - TSDB_PASSWORD=${TSDB_PASSWORD}
      - HOST_PROC=/host/proc
      - HOST_SYS=/host/sys
    # nvidia-smi access: collector scripts exec on host via mounted /usr/bin/nvidia-smi
    # Alternative: use network_mode: host for full host access
    pid: host
    network_mode: host  # Required for host_metrics accuracy
    # Note: with network_mode: host, use localhost:5433 for TimescaleDB
    # and add depends_on for service ordering

  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: breakpoint-timescaledb
    restart: unless-stopped
    ports:
      - "5433:5432"
    environment:
      - POSTGRES_DB=monitoring
      - POSTGRES_USER=vector
      - POSTGRES_PASSWORD=${TSDB_PASSWORD}
    volumes:
      - tsdb-data:/var/lib/postgresql/data
      - ./timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vector -d monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  grafana:
    image: grafana/grafana:11.6.0
    container_name: breakpoint-grafana
    restart: unless-stopped
    ports:
      - "3333:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/grafana/provisioning/dashboards/host-overview.json
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
      - AWS_DEFAULT_REGION=us-west-2
    volumes:
      - grafana-data:/var/lib/grafana
      - ./provisioning:/etc/grafana/provisioning
    depends_on:
      timescaledb:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  tsdb-data:
  grafana-data:
```

Key volume mounts for Vector:
- `/proc` and `/sys` (read-only) — host metrics and sensor data
- `/run/log/journal` (read-only) — journald access for Ollama and kernel logs
- `/var/run/docker.sock` (read-only) — Docker container log access
- Collector scripts directory (read-only)

## Grafana Dashboards

### Dashboard 1: Host Overview

System vitals at a glance. Panels: CPU per-core (stacked time series), load average, RAM gauge + history, swap usage + I/O, disk usage per device (bar gauge), disk I/O, network traffic (wlp8s0), CPU temperature with threshold lines, page faults, OOM kills (big red stat), uptime.

### Dashboard 2: GPU Monitoring

RTX 3080 health and throttle detection. Hero: temperature gauge (semicircle, green/yellow/red zones at 0-60/60-80/80+). Panels: temp history with 83C threshold, VRAM gauge + history, VRAM free stat, utilization time series, power draw vs power limit, clock speed current vs max (gap = throttle), fan speed, throttle status indicators (4 reasons: idle, hw_thermal, sw_thermal, sw_power_cap), PCIe link generation and width.

### Dashboard 3: LLM Inference

Model health and GPU vs CPU offload detection. Hero row: VRAM ratio gauges per model (1.0 = green, <1.0 = red). Panels: models status table (name, loaded, vram_ratio, size, expires_at), VRAM ratio time series per model, generation speed (eval_rate tokens/s), prompt processing speed, time to first token, total request duration, tokens generated, Ollama service status, available models table, VRAM headroom stat, correlation overlay (VRAM usage vs eval_rate).

### Dashboard 4: Claude Code Sessions

Agent activity. Panels: active sessions stat, active worktrees stat, session history time series, session list table (ID, uptime, project), system impact correlation (CPU + RAM vs session count).

## Alerts

| Alert | Condition | Severity |
|---|---|---|
| Disk Critical | `disk_used / disk_total > 0.90` | Critical |
| Disk Warning | `disk_used / disk_total > 0.85` | Warning |
| GPU Thermal | `gpu_temp_celsius > 83` for 2m | Critical |
| GPU Throttling | any `gpu_throttle_*` (non-idle) == 1 | Warning |
| RAM Pressure | `memory_available_bytes < 4GB` for 5m | Warning |
| Swap Thrashing | `swap_io_in_pages` rate > 1000/s for 1m | Critical |
| GPU Offload | `ollama_model_vram_ratio < 1.0` | Warning |
| Inference Degraded | `ollama_eval_rate < 15` for 2m | Warning |
| VRAM Exhausted | `gpu_memory_free_bytes < 500MB` | Warning |
| OOM Kill | `oom_kills_total` counter increases | Critical |
| Ollama Down | `ollama_running == 0` for 1m | Critical |

Notification: Grafana built-in UI notifications. Extensible to email/Slack later.

## Remote Access (LAN)

### SSH

- Install `openssh-server` on borg
- Key-based auth only (disable password after key setup)
- Restrict to LAN: `AllowUsers merm@10.0.0.0/24`
- Port 22

### Samba (File Sharing)

Two shares:
- `home` → `/home/merm` (read/write, merm only)
- `media` → `/media/merm` (read/write, merm only — USB drives)

Restrict to LAN: `hosts allow = 10.0.0.0/24 127.0.0.1`. No guest access. Follow symlinks enabled.

From laptop: `smb://borg.local/home` in file manager, or fstab mount.

### RDP (Desktop)

- Configure gnome-remote-desktop (already running) with RDP credentials
- Port 3389
- From laptop: Remmina → `borg.local:3389`
- Fallback if COSMIC RDP has issues: RustDesk

### mDNS

Avahi already running on borg. Laptop resolves `borg.local` automatically. No IP memorization needed.

### Remote Access Script

`scripts/setup-remote-access.sh` is a one-time host configuration script (not part of the autonomous loop). It is idempotent — safe to re-run. It configures SSH, Samba, and RDP. A companion `scripts/undo-remote-access.sh` reverses all changes (disables sshd, removes Samba shares, disables RDP). Both scripts require sudo and log all changes to stdout.

## Forgejo Integration

### Current State

Already running at `localhost:3300` with PostgreSQL backend and Actions runner.

### Changes

1. **Expose on LAN** — change port binding from `127.0.0.1:3300` to `0.0.0.0:3300` and `0.0.0.0:2223` for SSH
2. **Mirror repos** — script to `git remote add forgejo` + `git push --all` for each back-office target repo
3. **Metrics** — optional: scrape Forgejo's `/metrics` endpoint via Vector exec source

### From Laptop

- Web UI: `http://borg.local:3300`
- Git SSH: `ssh://git@borg.local:2223/merm/repo.git`
- Git HTTP: `http://borg.local:3300/merm/repo.git`

## Back-Office Integration

### File Structure

The existing `monitoring/provisioning/` directory is preserved and extended. New subdirectories are added for Vector, TimescaleDB, and collector scripts.

```
monitoring/
├── docker-compose.yml              # Expanded: vector, timescaledb, grafana
├── .env.example                    # Template for required env vars
├── .env                            # Actual secrets (gitignored)
├── vector/
│   ├── vector.yaml                 # Full pipeline config
│   └── collectors/
│       ├── gpu_metrics.sh
│       ├── system_sensors.sh
│       ├── ollama_metrics.sh
│       └── claude_sessions.sh
├── timescaledb/
│   ├── init.sql                    # Schema: hypertables, retention, aggregates
│   └── migrations/                 # Future schema changes
├── provisioning/                   # Existing Grafana provisioning (preserved)
│   ├── datasources/
│   │   ├── cloudwatch.yml          # Existing
│   │   └── timescaledb.yml         # New
│   └── dashboards/
│       ├── dashboards.yml          # Existing (updated)
│       ├── projects-overview.json  # Existing
│       ├── host-overview.json      # New
│       ├── gpu-monitoring.json     # New
│       ├── llm-inference.json      # New
│       └── claude-sessions.json    # New
└── scripts/
    ├── setup-remote-access.sh      # SSH + Samba + RDP one-time setup (idempotent)
    └── undo-remote-access.sh       # Reverse remote access setup
```

### Environment Variables

`.env.example` template:

```bash
# TimescaleDB
TSDB_PASSWORD=changeme

# Grafana
GRAFANA_ADMIN_PASSWORD=changeme

# AWS (optional, for CloudWatch datasource)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

The monitoring stack has its own `.env`, separate from any other project config.

### New Makefile Targets

```makefile
# Monitoring stack
make monitoring-up          # docker compose up -d
make monitoring-down        # docker compose down
make monitoring-logs        # docker compose logs -f
make monitoring-status      # health check all services

# Forgejo
make forgejo-up             # forgejo stack up
make forgejo-mirror REPO=x  # git remote add forgejo + git push --all for target repo
```

### What Does Not Change

- HQ dashboard (audit findings, backlog, scores)
- Audit agents and prompts
- Overnight loop
- Deployment to Bunny CDN

Grafana at :3333 is the infrastructure dashboard. HQ at admin.codyjo.com is the code health dashboard. Complementary, not overlapping.

## Testing

### Collector Script Tests

Each collector script has a corresponding test that:
- Mocks the underlying tool (e.g., fake `nvidia-smi` output, mock Ollama API response via a local HTTP fixture)
- Verifies valid JSON output
- Verifies graceful degradation (zero-values) when the tool is unavailable
- Tests: `tests/monitoring/test_gpu_metrics.sh`, `test_system_sensors.sh`, `test_ollama_metrics.sh`, `test_claude_sessions.sh`

### Stack Smoke Test

`make monitoring-test` target:
1. Starts the monitoring stack (`docker compose up -d`)
2. Waits for TimescaleDB healthcheck to pass
3. Waits for Grafana healthcheck to pass
4. Verifies Vector is running and its healthcheck endpoint (`localhost:8686/health`) responds
5. Queries TimescaleDB for at least 1 row in `metrics` table (proves data is flowing)
6. Queries Grafana API (`/api/datasources`) to verify TimescaleDB datasource is provisioned
7. Tears down the stack

### Integration Test

`make monitoring-integration-test` target:
1. Starts stack
2. Waits 60 seconds for data accumulation
3. Queries `metrics` table for expected metric names from each source (host, gpu, sensors, ollama, claude)
4. Queries `logs` table for at least 1 journald and 1 docker log entry
5. Verifies `metrics_5m` continuous aggregate has data
6. Tears down

## Access Summary (from laptop)

| Service | URL | Purpose |
|---|---|---|
| Grafana | `http://borg.local:3333` | Machine health dashboards |
| Forgejo | `http://borg.local:3300` | Local git server |
| HQ Dashboard | `http://borg.local:8070` | Audit findings |
| SSH | `ssh merm@borg.local` | Terminal |
| Samba | `smb://borg.local/home` | File browser |
| RDP | `borg.local:3389` | Full desktop |
| Ollama | `http://borg.local:11434` | LLM API (if exposed) |
