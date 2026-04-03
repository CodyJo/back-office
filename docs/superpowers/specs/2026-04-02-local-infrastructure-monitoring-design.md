# Local Infrastructure Monitoring & Remote Access

**Date:** 2026-04-02
**Status:** Design approved
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

Three containers. Vector collects all metrics via built-in host_metrics source and exec sources for GPU/Ollama/Claude, then writes directly to TimescaleDB. Grafana reads TimescaleDB via native PostgreSQL datasource.

### Container Inventory

| Service | Image | Port | Purpose |
|---|---|---|---|
| vector | timberio/vector | 8686 | Collection, transforms, sinks |
| timescaledb | timescale/timescaledb:latest-pg16 | 5433 | Metrics + logs hypertables |
| grafana | grafana/grafana:11.6.0 | 3333 | Dashboards + alerts |

Port 5433 for TimescaleDB avoids conflict with Forgejo's PostgreSQL. Port 3333 is unchanged from existing Grafana config.

### Data Flow

```
Host (borg)
  │
  ├─ Vector host_metrics source ──→ host_normalize ──┐
  ├─ gpu_metrics.sh (exec) ───────→ gpu_explode ─────┤
  ├─ ollama_metrics.sh (exec) ────→ ollama_normalize ─┤
  ├─ journald (ollama unit) ──────→ ollama_inference ─┤
  ├─ journald (kernel, oomd) ─────→ system_events ────┤
  ├─ claude_sessions.sh (exec) ───→ claude_normalize ─┤
  └─ docker_logs ─────────────────────────────────────┤
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
```

### Continuous Aggregate (5-min rollups)

```sql
CREATE MATERIALIZED VIEW metrics_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    host, source, metric,
    avg(value) AS avg_val,
    max(value) AS max_val,
    min(value) AS min_val
FROM metrics
GROUP BY bucket, host, source, metric;
```

### Retention & Compression

| Policy | Value |
|---|---|
| Chunk interval | 1 hour |
| Compression | After 1 day |
| Metrics retention | 90 days |
| Logs retention | 30 days |

## Metrics Catalog

### Host Metrics (source: `host`)

| metric | labels | unit |
|---|---|---|
| `cpu_usage_percent` | `{core: "0"}` | % |
| `memory_used_bytes` | | bytes |
| `memory_total_bytes` | | bytes |
| `memory_available_bytes` | | bytes |
| `disk_used_bytes` | `{device, mount}` | bytes |
| `disk_total_bytes` | `{device, mount}` | bytes |
| `disk_io_read_bytes` | `{device}` | bytes/s |
| `disk_io_write_bytes` | `{device}` | bytes/s |
| `network_rx_bytes` | `{interface}` | bytes/s |
| `network_tx_bytes` | `{interface}` | bytes/s |
| `cpu_temp_celsius` | `{sensor, core}` | C |
| `cpu_freq_mhz` | `{core}` | MHz |
| `load_avg_1m` | | - |
| `load_avg_5m` | | - |
| `swap_used_bytes` | | bytes |
| `swap_io_in_bytes` | | bytes/s |
| `swap_io_out_bytes` | | bytes/s |
| `memory_page_faults` | | count/s |
| `oom_kills_total` | | count |

### GPU Metrics (source: `gpu`)

| metric | labels | unit |
|---|---|---|
| `gpu_temp_celsius` | `{gpu: "rtx3080"}` | C |
| `gpu_utilization_percent` | `{gpu}` | % |
| `gpu_memory_used_bytes` | `{gpu}` | bytes |
| `gpu_memory_total_bytes` | `{gpu}` | bytes |
| `gpu_memory_free_bytes` | `{gpu}` | bytes |
| `gpu_power_watts` | `{gpu}` | W |
| `gpu_power_limit_watts` | `{gpu}` | W |
| `gpu_fan_percent` | `{gpu}` | % |
| `gpu_clock_current_mhz` | `{gpu}` | MHz |
| `gpu_clock_max_mhz` | `{gpu}` | MHz |
| `gpu_clock_throttle_reason` | `{gpu, reason}` | 0/1 |
| `gpu_pcie_rx_bytes` | `{gpu}` | bytes/s |
| `gpu_pcie_tx_bytes` | `{gpu}` | bytes/s |

### Ollama Metrics (source: `ollama`)

| metric | labels | unit |
|---|---|---|
| `ollama_running` | | 0/1 |
| `ollama_models_available` | | count |
| `ollama_model_loaded` | `{model}` | 0/1 |
| `ollama_model_size_bytes` | `{model}` | bytes |
| `ollama_model_vram_bytes` | `{model}` | bytes |
| `ollama_model_vram_ratio` | `{model}` | 0.0-1.0 |
| `ollama_model_layers_gpu` | `{model}` | count |
| `ollama_model_layers_total` | `{model}` | count |
| `ollama_model_expires_at` | `{model}` | epoch |
| `ollama_eval_rate` | `{model}` | tokens/s |
| `ollama_prompt_eval_rate` | `{model}` | tokens/s |
| `ollama_time_to_first_token_ms` | `{model}` | ms |
| `ollama_eval_duration_ms` | `{model}` | ms |
| `ollama_prompt_eval_duration_ms` | `{model}` | ms |
| `ollama_total_duration_ms` | `{model}` | ms |
| `ollama_tokens_generated` | `{model}` | count |

### Claude Code Metrics (source: `claude`)

| metric | labels | unit |
|---|---|---|
| `claude_active_sessions` | | count |
| `claude_worktrees_active` | | count |
| `claude_session_uptime_sec` | `{session_id}` | seconds |

## Vector Pipeline

### Sources

| Source | Type | Interval | Collects |
|---|---|---|---|
| `host_metrics` | host_metrics (built-in) | 15s | CPU, RAM, disk, network, filesystem, load |
| `gpu_metrics` | exec | 15s | nvidia-smi output (all GPU fields) |
| `ollama_metrics` | exec | 30s | /api/ps + /api/tags (model status, VRAM) |
| `claude_metrics` | exec | 60s | pgrep claude, worktree count |
| `ollama_journal` | journald | stream | Ollama unit logs (inference stats) |
| `system_journal` | journald | stream | kernel, oomd, system76-power (OOM, thermal) |
| `docker_logs` | docker_logs | stream | forgejo, grafana containers |

### Collector Scripts

**`gpu_metrics.sh`** — runs `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,memory.free,power.draw,power.limit,clocks.gr,clocks.max.gr,fan.speed,clocks_throttle_reasons.gpu_idle,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.sw_power_cap --format=csv,noheader,nounits`. Parses CSV, outputs JSON.

**`ollama_metrics.sh`** — polls `curl -s localhost:11434/api/ps` and `/api/tags`. Computes `vram_ratio = size_vram / size`. Outputs JSON with all model metrics.

**`claude_sessions.sh`** — counts `claude` processes via `pgrep`, counts git worktrees under `/home/merm/projects/`, outputs JSON.

### Transforms

- `host_normalize` — maps Vector's host_metrics events to `{host, source, metric, labels, value}` schema
- `gpu_explode` — splits single GPU JSON event into individual metric events
- `ollama_normalize` — computes derived metrics (vram_ratio), splits into metric events
- `ollama_inference_parse` — parses journald logs for eval_rate, duration, tokens stats
- `system_events` — detects OOM kills and thermal events from kernel logs
- `route` — splits metrics vs logs to separate sinks

### Sinks

- `timescaledb_metrics` — batch INSERT into `metrics` hypertable
- `timescaledb_logs` — batch INSERT into `logs` hypertable

## Grafana Dashboards

### Dashboard 1: Host Overview

System vitals at a glance. Panels: CPU per-core (stacked time series), load average, RAM gauge + history, swap usage + I/O, disk usage per device (bar gauge), disk I/O, network traffic (wlp8s0), CPU temperature with threshold lines, page faults, OOM kills (big red stat), uptime.

### Dashboard 2: GPU Monitoring

RTX 3080 health and throttle detection. Hero: temperature gauge (semicircle, green/yellow/red zones). Panels: temp history with 83C threshold, VRAM gauge + history, VRAM free stat, utilization time series, power draw vs power limit, clock speed current vs max (gap = throttle), fan speed, throttle status indicators (4 reasons), PCIe bandwidth.

### Dashboard 3: LLM Inference

Model health and GPU vs CPU offload detection. Hero row: VRAM ratio gauges per model (1.0 = green, <1.0 = red). Panels: models status table (name, loaded, vram_ratio, size, expires_at), GPU vs CPU layers stacked bar, generation speed (eval_rate tokens/s), prompt processing speed, time to first token, total request duration, tokens generated, Ollama service status, available models table, VRAM headroom stat, correlation overlay (VRAM usage vs eval_rate).

### Dashboard 4: Claude Code Sessions

Agent activity. Panels: active sessions stat, active worktrees stat, session history time series, session list table (ID, uptime, project), system impact correlation (CPU + RAM vs session count).

## Alerts

| Alert | Condition | Severity |
|---|---|---|
| Disk Critical | `disk_used / disk_total > 0.90` | Critical |
| Disk Warning | `disk_used / disk_total > 0.85` | Warning |
| GPU Thermal | `gpu_temp_celsius > 83` for 2m | Critical |
| GPU Throttling | `gpu_clock_throttle_reason{thermal} == 1` | Warning |
| RAM Pressure | `memory_available_bytes < 4GB` for 5m | Warning |
| Swap Thrashing | `swap_io_in_bytes > 10MB/s` for 1m | Critical |
| GPU Offload | `ollama_model_vram_ratio < 1.0` | Warning |
| Inference Degraded | `ollama_eval_rate < 15` for 2m | Warning |
| VRAM Exhausted | `gpu_memory_free_bytes < 500MB` | Warning |
| OOM Kill | `oom_kills_total` increases | Critical |
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

## Forgejo Integration

### Current State

Already running at `localhost:3300` with PostgreSQL backend and Actions runner.

### Changes

1. **Expose on LAN** — change port binding from `127.0.0.1:3300` to `0.0.0.0:3300`
2. **Mirror repos** — push local repos to Forgejo (or configure GitHub mirror sync)
3. **Metrics** — optional: scrape Forgejo's `/metrics` endpoint via Vector exec source

### From Laptop

- Web UI: `http://borg.local:3300`
- Git SSH: `ssh://git@borg.local:2223/merm/repo.git`
- Git HTTP: `http://borg.local:3300/merm/repo.git`

## Back-Office Integration

### New Files

```
monitoring/
├── docker-compose.yml              # Expanded: vector, timescaledb, grafana
├── .env                            # TSDB_PASSWORD, GRAFANA_ADMIN_PASSWORD
├── vector/
│   ├── vector.yaml                 # Full pipeline config
│   └── collectors/
│       ├── gpu_metrics.sh
│       ├── ollama_metrics.sh
│       ├── claude_sessions.sh
│       └── forgejo_metrics.sh      # Optional
├── timescaledb/
│   ├── init.sql                    # Schema: hypertables, retention, aggregates
│   └── migrations/                 # Future schema changes
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   ├── cloudwatch.yml      # Existing
│       │   └── timescaledb.yml     # New
│       └── dashboards/
│           ├── dashboards.yml           # Existing (updated)
│           ├── projects-overview.json   # Existing
│           ├── host-overview.json       # New
│           ├── gpu-monitoring.json      # New
│           ├── llm-inference.json       # New
│           └── claude-sessions.json     # New
└── scripts/
    └── setup-remote-access.sh      # SSH + Samba + RDP one-time setup
```

### New Makefile Targets

```makefile
make monitoring-up          # docker compose up -d
make monitoring-down        # docker compose down
make monitoring-logs        # docker compose logs -f
make monitoring-status      # health check all services
make forgejo-up             # forgejo stack up
make forgejo-mirror REPO=x  # push local repo to forgejo
```

### What Does Not Change

- HQ dashboard (audit findings, backlog, scores)
- Audit agents and prompts
- Overnight loop
- Deployment to Bunny CDN

Grafana at :3333 is the infrastructure dashboard. HQ at admin.codyjo.com is the code health dashboard. Complementary, not overlapping.

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
