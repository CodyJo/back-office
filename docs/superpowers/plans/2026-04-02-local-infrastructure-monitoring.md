# Local Infrastructure Monitoring & Remote Access — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a Vector → TimescaleDB → Grafana monitoring stack on borg with dashboards for host, GPU, Ollama, and Claude Code metrics, plus LAN remote access (SSH, Samba, RDP) and Forgejo exposure.

**Architecture:** Vector collects host metrics (built-in), GPU/sensors/Ollama/Claude metrics (exec scripts), and logs (journald/docker). It sends JSON batches via HTTP sink to a thin Python ingest service that batch-inserts into TimescaleDB hypertables. Grafana reads TimescaleDB via native PostgreSQL datasource. Four containers: Vector, ingest, TimescaleDB, Grafana.

**Tech Stack:** Vector (Rust), Python 3 / FastAPI (ingest), TimescaleDB (PostgreSQL 16), Grafana 11.6, Bash (collector scripts), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-04-02-local-infrastructure-monitoring-design.md`

**Key deviation from spec:** Vector has no native PostgreSQL sink. A thin Python ingest service (FastAPI, ~80 lines) bridges Vector's `http` sink to TimescaleDB. This adds a 4th container but keeps the architecture clean and mirrors the consumer pattern from the work stack.

---

## Chunk 1: Foundation (Docker Compose + TimescaleDB + Ingest Service)

### Task 1: Environment setup and .env files

**Files:**
- Create: `monitoring/.env.example`
- Create: `monitoring/.env` (gitignored)
- Modify: `.gitignore` — add `monitoring/.env`

- [ ] **Step 1: Add monitoring/.env to .gitignore**

Append to `/home/merm/projects/back-office/.gitignore`:

```
# Monitoring stack secrets
monitoring/.env
```

- [ ] **Step 2: Create .env.example**

Create `/home/merm/projects/back-office/monitoring/.env.example`:

```bash
# TimescaleDB
TSDB_PASSWORD=changeme

# Grafana
GRAFANA_ADMIN_PASSWORD=changeme

# AWS (optional, for CloudWatch datasource)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

- [ ] **Step 3: Create actual .env from example**

```bash
cd /home/merm/projects/back-office/monitoring
cp .env.example .env
```

Then edit `.env` and set real passwords (generate with `openssl rand -base64 16`).

- [ ] **Step 4: Commit**

```bash
git add .gitignore monitoring/.env.example
git commit -m "feat(monitoring): add .env template for monitoring stack"
```

---

### Task 2: TimescaleDB init schema

**Files:**
- Create: `monitoring/timescaledb/init.sql`

- [ ] **Step 1: Create init.sql with hypertables, indexes, compression, retention, continuous aggregate**

Create `/home/merm/projects/back-office/monitoring/timescaledb/init.sql`:

```sql
-- ============================================================
-- TimescaleDB schema for borg monitoring
-- Run automatically on first container start via
-- /docker-entrypoint-initdb.d/init.sql
-- ============================================================

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Metrics hypertable ──────────────────────────────────────

CREATE TABLE metrics (
    time        TIMESTAMPTZ NOT NULL,
    host        TEXT        NOT NULL DEFAULT 'borg',
    source      TEXT        NOT NULL,
    metric      TEXT        NOT NULL,
    labels      JSONB       DEFAULT '{}',
    value       DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('metrics', 'time',
    chunk_time_interval => INTERVAL '1 hour');

CREATE INDEX idx_metrics_source_metric
    ON metrics (source, metric, time DESC);
CREATE INDEX idx_metrics_labels
    ON metrics USING GIN (labels);

-- ── Logs hypertable ─────────────────────────────────────────

CREATE TABLE logs (
    time        TIMESTAMPTZ NOT NULL,
    host        TEXT        NOT NULL DEFAULT 'borg',
    source      TEXT        NOT NULL,
    service     TEXT,
    level       TEXT,
    message     TEXT        NOT NULL,
    metadata    JSONB       DEFAULT '{}'
);

SELECT create_hypertable('logs', 'time',
    chunk_time_interval => INTERVAL '1 hour');

CREATE INDEX idx_logs_service ON logs (service, time DESC);
CREATE INDEX idx_logs_level   ON logs (level, time DESC);

-- ── Continuous aggregate (5-min rollups) ────────────────────

CREATE MATERIALIZED VIEW metrics_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    host,
    source,
    metric,
    labels,
    avg(value)  AS avg_val,
    max(value)  AS max_val,
    min(value)  AS min_val,
    count(*)    AS sample_count
FROM metrics
GROUP BY bucket, host, source, metric, labels
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_5m',
    start_offset    => INTERVAL '1 hour',
    end_offset      => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes');

-- ── Compression ─────────────────────────────────────────────

ALTER TABLE metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source,metric',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('metrics', INTERVAL '1 day');

ALTER TABLE logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source,service',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('logs', INTERVAL '2 days');

-- ── Retention ───────────────────────────────────────────────

SELECT add_retention_policy('metrics', INTERVAL '90 days');
SELECT add_retention_policy('logs',    INTERVAL '30 days');

-- Grafana connects as the 'vector' user for simplicity in local setup.
-- For production, create a read-only role with a separate password.
```

- [ ] **Step 2: Verify SQL syntax locally**

```bash
# Quick syntax check — no running DB needed
docker run --rm -e POSTGRES_PASSWORD=test \
  timescale/timescaledb:latest-pg16 \
  bash -c "echo 'SELECT 1;' | psql -U postgres 2>&1 | head -5"
```

Expected: no crash. Full validation happens when the container starts.

- [ ] **Step 3: Commit**

```bash
git add monitoring/timescaledb/init.sql
git commit -m "feat(monitoring): add TimescaleDB init schema with hypertables and retention"
```

---

### Task 3: Python ingest service

**Files:**
- Create: `monitoring/ingest/requirements.txt`
- Create: `monitoring/ingest/main.py`
- Create: `monitoring/ingest/Dockerfile`

Vector has no native PostgreSQL sink. This thin FastAPI service receives JSON batches from Vector's `http` sink and batch-inserts into TimescaleDB.

- [ ] **Step 1: Create requirements.txt**

Create `/home/merm/projects/back-office/monitoring/ingest/requirements.txt`:

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
psycopg[binary]==3.2.9
psycopg-pool==3.2.6
```

- [ ] **Step 2: Create main.py**

Create `/home/merm/projects/back-office/monitoring/ingest/main.py`:

```python
"""Thin ingest service: receives NDJSON from Vector's http sink, batch-inserts into TimescaleDB.

Vector's http sink with codec: json sends newline-delimited JSON (one JSON object per line).
This service parses NDJSON and batch-inserts into TimescaleDB using async psycopg.
"""

import os
import json
import logging
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from fastapi import FastAPI, Request, Response

logger = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://vector:{password}@timescaledb:5432/monitoring".format(
        password=os.environ.get("TSDB_PASSWORD", "changeme")
    ),
)

pool: AsyncConnectionPool | None = None


def parse_ndjson(body: bytes) -> list[dict]:
    """Parse newline-delimited JSON (NDJSON) body into a list of dicts."""
    events = []
    for line in body.split(b"\n"):
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = AsyncConnectionPool(DB_DSN, min_size=2, max_size=10, open=False)
    await pool.open()
    logger.info("Connected to TimescaleDB")
    yield
    await pool.close()
    logger.info("Connection pool closed")


app = FastAPI(lifespan=lifespan)


@app.post("/ingest/metrics")
async def ingest_metrics(request: Request):
    """Accept NDJSON metric events from Vector's http sink."""
    body = await request.body()
    events = parse_ndjson(body)

    if not events:
        return Response(status_code=204)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO metrics (time, host, source, metric, labels, value)
                VALUES (
                    COALESCE(%(time)s, now()),
                    COALESCE(%(host)s, 'borg'),
                    %(source)s,
                    %(metric)s,
                    COALESCE(%(labels)s, '{}')::jsonb,
                    %(value)s
                )
                """,
                events,
            )
        await conn.commit()

    return {"accepted": len(events)}


@app.post("/ingest/logs")
async def ingest_logs(request: Request):
    """Accept NDJSON log events from Vector's http sink."""
    body = await request.body()
    events = parse_ndjson(body)

    if not events:
        return Response(status_code=204)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO logs (time, host, source, service, level, message, metadata)
                VALUES (
                    COALESCE(%(time)s, now()),
                    COALESCE(%(host)s, 'borg'),
                    %(source)s,
                    %(service)s,
                    %(level)s,
                    %(message)s,
                    COALESCE(%(metadata)s, '{}')::jsonb
                )
                """,
                events,
            )
        await conn.commit()

    return {"accepted": len(events)}


@app.get("/health")
async def health():
    """Health check — verifies DB connectivity."""
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return Response(status_code=503, content=str(e))
```

- [ ] **Step 3: Create Dockerfile**

Create `/home/merm/projects/back-office/monitoring/ingest/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8087"]
```

- [ ] **Step 4: Commit**

```bash
git add monitoring/ingest/
git commit -m "feat(monitoring): add Python ingest service (Vector http sink → TimescaleDB)"
```

---

### Task 4: Docker Compose

**Files:**
- Modify: `monitoring/docker-compose.yml` (replace existing)

- [ ] **Step 1: Replace docker-compose.yml with full monitoring stack**

Replace the contents of `/home/merm/projects/back-office/monitoring/docker-compose.yml`:

```yaml
# BreakPoint Labs — Local Infrastructure Monitoring
# Vector → Ingest → TimescaleDB → Grafana
#
# Usage:
#   cd monitoring && docker compose up -d
#   Open http://localhost:3333

services:
  # ── TimescaleDB (metrics + logs storage) ───────────────────
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: breakpoint-timescaledb
    restart: unless-stopped
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: monitoring
      POSTGRES_USER: vector
      POSTGRES_PASSWORD: ${TSDB_PASSWORD:?Set TSDB_PASSWORD in .env}
    volumes:
      - tsdb-data:/var/lib/postgresql/data
      - ./timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vector -d monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Ingest service (Vector http sink → TimescaleDB) ────────
  ingest:
    build: ./ingest
    container_name: breakpoint-ingest
    restart: unless-stopped
    ports:
      - "8087:8087"
    environment:
      TSDB_PASSWORD: ${TSDB_PASSWORD}
      DATABASE_URL: "postgresql://vector:${TSDB_PASSWORD}@timescaledb:5432/monitoring"
    depends_on:
      timescaledb:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8087/health')"]
      interval: 15s
      timeout: 5s
      retries: 3

  # ── Vector (collection + transport) ────────────────────────
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
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
      - /usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1:/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1:ro
    environment:
      VECTOR_LOG: info
      HOST_PROC: /host/proc
      HOST_SYS: /host/sys
    pid: host
    # Note: Vector does NOT use network_mode: host. This means network metrics
    # from host_metrics will reflect the container's network namespace, not the
    # host's. This is acceptable because: (1) our system_sensors.sh reads
    # /host/proc/net/dev for host network stats if needed, and (2) not using
    # network_mode: host allows Vector to reach ingest via Docker DNS.
    # If host network metrics are critical, add a network stats collector script.
    depends_on:
      ingest:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "vector", "top", "--interval", "1", "--human-metrics", "false"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  # ── Grafana (dashboards + alerts) ──────────────────────────
  grafana:
    image: grafana/grafana:11.6.0
    container_name: breakpoint-grafana
    restart: unless-stopped
    ports:
      - "3333:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD in .env}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /etc/grafana/provisioning/dashboards/host-overview.json
      # AWS credentials for CloudWatch datasource (optional)
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
      AWS_DEFAULT_REGION: us-west-2
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

- [ ] **Step 2: Verify compose config parses**

```bash
cd /home/merm/projects/back-office/monitoring && docker compose config --quiet
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add monitoring/docker-compose.yml
git commit -m "feat(monitoring): expand docker-compose with full monitoring stack"
```

---

### Task 5: Grafana TimescaleDB datasource provisioning

**Files:**
- Create: `monitoring/provisioning/datasources/timescaledb.yml`

- [ ] **Step 1: Create TimescaleDB datasource provisioning file**

Create `/home/merm/projects/back-office/monitoring/provisioning/datasources/timescaledb.yml`:

```yaml
apiVersion: 1

datasources:
  - name: TimescaleDB
    type: postgres
    access: proxy
    uid: timescaledb
    url: timescaledb:5432
    user: vector
    jsonData:
      database: monitoring
      sslmode: disable
      maxOpenConns: 10
      maxIdleConns: 5
      connMaxLifetime: 14400
      postgresVersion: 1600
      timescaledb: true
    secureJsonData:
      password: ${TSDB_PASSWORD}
    isDefault: true
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/provisioning/datasources/timescaledb.yml
git commit -m "feat(monitoring): add TimescaleDB datasource provisioning for Grafana"
```

---

### Task 6: Smoke test the foundation stack

- [ ] **Step 1: Set passwords in .env**

```bash
cd /home/merm/projects/back-office/monitoring
cat > .env << 'EOF'
TSDB_PASSWORD=$(openssl rand -base64 16)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 16)
EOF
```

Actually, generate them properly:

```bash
cd /home/merm/projects/back-office/monitoring
TSDB_PW=$(openssl rand -base64 16)
GRAFANA_PW=$(openssl rand -base64 16)
cat > .env << EOF
TSDB_PASSWORD=$TSDB_PW
GRAFANA_ADMIN_PASSWORD=$GRAFANA_PW
EOF
echo "Grafana admin password: $GRAFANA_PW"
```

- [ ] **Step 2: Start the stack (TimescaleDB + ingest + Grafana, no Vector yet)**

```bash
cd /home/merm/projects/back-office/monitoring
docker compose up -d timescaledb ingest grafana
```

- [ ] **Step 3: Verify TimescaleDB schema**

```bash
docker exec breakpoint-timescaledb psql -U vector -d monitoring -c "\dt"
```

Expected: `metrics` and `logs` tables listed.

```bash
docker exec breakpoint-timescaledb psql -U vector -d monitoring -c "\d metrics"
```

Expected: columns time, host, source, metric, labels, value.

- [ ] **Step 4: Verify ingest service health**

```bash
curl -s http://localhost:8087/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Test ingest with a sample metric**

```bash
curl -s -X POST http://localhost:8087/ingest/metrics \
  -H 'Content-Type: application/json' \
  -d '[{"time": "2026-04-02T00:00:00Z", "host": "borg", "source": "test", "metric": "test_metric", "labels": {}, "value": 42.0}]'
```

Expected: `{"accepted":1}`

```bash
docker exec breakpoint-timescaledb psql -U vector -d monitoring \
  -c "SELECT * FROM metrics WHERE source = 'test';"
```

Expected: 1 row with value 42.0.

- [ ] **Step 6: Verify Grafana is running with TimescaleDB datasource**

```bash
curl -s http://localhost:3333/api/health
```

Expected: `{"commit":"...","database":"ok","version":"11.6.0"}`

- [ ] **Step 7: Clean up test data**

```bash
docker exec breakpoint-timescaledb psql -U vector -d monitoring \
  -c "DELETE FROM metrics WHERE source = 'test';"
```

---

## Chunk 2: Collector Scripts

### Task 7: GPU metrics collector

**Files:**
- Create: `monitoring/vector/collectors/gpu_metrics.sh`

- [ ] **Step 1: Create gpu_metrics.sh**

Create `/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh`:

```bash
#!/bin/bash
# Collects NVIDIA GPU metrics via nvidia-smi.
# Outputs JSON array of metric objects for Vector exec source.
# Exits 0 with zero-values if nvidia-smi is unavailable.
set -euo pipefail

NVIDIA_SMI="${NVIDIA_SMI:-nvidia-smi}"
GPU_LABEL="rtx3080"

if ! command -v "$NVIDIA_SMI" &>/dev/null; then
    echo '[]'
    exit 0
fi

RAW=$("$NVIDIA_SMI" --query-gpu=\
temperature.gpu,\
utilization.gpu,\
memory.used,\
memory.total,\
memory.free,\
power.draw,\
power.limit,\
clocks.current.graphics,\
clocks.max.graphics,\
fan.speed,\
clocks_throttle_reasons.gpu_idle,\
clocks_throttle_reasons.hw_thermal_slowdown,\
clocks_throttle_reasons.sw_thermal_slowdown,\
clocks_throttle_reasons.sw_power_cap,\
pcie.link.gen.current,\
pcie.link.width.current \
--format=csv,noheader,nounits 2>/dev/null) || { echo '[]'; exit 0; }

IFS=', ' read -r \
    temp util mem_used mem_total mem_free \
    power power_limit clock_cur clock_max fan \
    thr_idle thr_hw_thermal thr_sw_thermal thr_sw_power \
    pcie_gen pcie_width <<< "$RAW"

# Convert MiB to bytes
mem_used_b=$(( ${mem_used:-0} * 1048576 ))
mem_total_b=$(( ${mem_total:-0} * 1048576 ))
mem_free_b=$(( ${mem_free:-0} * 1048576 ))

# Map "Active"/"Not Active" to 1/0 for throttle reasons
thr_val() {
    case "${1,,}" in
        active|1) echo 1 ;;
        *) echo 0 ;;
    esac
}

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat << ENDJSON
[
  {"time":"$NOW","source":"gpu","metric":"gpu_temp_celsius","labels":{"gpu":"$GPU_LABEL"},"value":${temp:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_utilization_percent","labels":{"gpu":"$GPU_LABEL"},"value":${util:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_used_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_used_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_total_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_total_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_free_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_free_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_power_watts","labels":{"gpu":"$GPU_LABEL"},"value":${power:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_power_limit_watts","labels":{"gpu":"$GPU_LABEL"},"value":${power_limit:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_clock_current_mhz","labels":{"gpu":"$GPU_LABEL"},"value":${clock_cur:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_clock_max_mhz","labels":{"gpu":"$GPU_LABEL"},"value":${clock_max:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_fan_percent","labels":{"gpu":"$GPU_LABEL"},"value":${fan:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_idle","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_idle")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_hw_thermal","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_hw_thermal")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_sw_thermal","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_sw_thermal")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_sw_power_cap","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_sw_power")},
  {"time":"$NOW","source":"gpu","metric":"gpu_pcie_link_gen","labels":{"gpu":"$GPU_LABEL"},"value":${pcie_gen:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_pcie_link_width","labels":{"gpu":"$GPU_LABEL"},"value":${pcie_width:-0}}
]
ENDJSON
```

- [ ] **Step 2: Make executable and test locally**

```bash
chmod +x /home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh
/home/merm/projects/back-office/monitoring/vector/collectors/gpu_metrics.sh | python3 -m json.tool
```

Expected: valid JSON array with 16 metric objects, real values from the RTX 3080.

- [ ] **Step 3: Commit**

```bash
git add monitoring/vector/collectors/gpu_metrics.sh
git commit -m "feat(monitoring): add GPU metrics collector (nvidia-smi)"
```

---

### Task 8: System sensors collector

**Files:**
- Create: `monitoring/vector/collectors/system_sensors.sh`

- [ ] **Step 1: Create system_sensors.sh**

Create `/home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh`:

```bash
#!/bin/bash
# Collects CPU temperature, frequency, page faults, OOM kills, swap I/O
# from /sys/ and /proc/. These are NOT available from Vector's host_metrics.
# Outputs JSON array. Exits 0 with zero-values on failure.
set -euo pipefail

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
METRICS="["
FIRST=true

add_metric() {
    local source="$1" metric="$2" labels="$3" value="$4"
    if [ "$FIRST" = true ]; then FIRST=false; else METRICS+=","; fi
    METRICS+="$(printf '\n  {"time":"%s","source":"%s","metric":"%s","labels":%s,"value":%s}' \
        "$NOW" "$source" "$metric" "$labels" "$value")"
}

# ── CPU Temperature (k10temp) ────────────────────────────────
# Find the k10temp hwmon directory
HWMON_DIR=""
for d in /host/sys/class/hwmon/hwmon*/; do
    if [ -f "${d}name" ] && [ "$(cat "${d}name" 2>/dev/null)" = "k10temp" ]; then
        HWMON_DIR="$d"
        break
    fi
done

if [ -n "$HWMON_DIR" ]; then
    # Tctl (overall die temp) is usually temp1
    for temp_file in "${HWMON_DIR}"temp*_input; do
        [ -f "$temp_file" ] || continue
        label_file="${temp_file%_input}_label"
        label="unknown"
        [ -f "$label_file" ] && label=$(cat "$label_file" 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr ' ' '_')
        raw=$(cat "$temp_file" 2>/dev/null || echo 0)
        # /sys reports millidegrees
        temp_c=$(echo "scale=1; $raw / 1000" | bc 2>/dev/null || echo 0)
        add_metric "sensors" "cpu_temp_celsius" "{\"sensor\":\"k10temp\",\"label\":\"$label\"}" "$temp_c"
    done
fi

# ── CPU Frequency ────────────────────────────────────────────
core=0
for freq_file in /host/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do
    [ -f "$freq_file" ] || continue
    raw=$(cat "$freq_file" 2>/dev/null || echo 0)
    # /sys reports kHz
    freq_mhz=$(echo "scale=0; $raw / 1000" | bc 2>/dev/null || echo 0)
    add_metric "sensors" "cpu_freq_mhz" "{\"core\":\"$core\"}" "$freq_mhz"
    core=$((core + 1))
done

# ── /proc/vmstat counters ────────────────────────────────────
VMSTAT="/host/proc/vmstat"
if [ -f "$VMSTAT" ]; then
    pgmajfault=$(grep -w pgmajfault "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    oom_kill=$(grep -w oom_kill "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    pswpin=$(grep -w pswpin "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    pswpout=$(grep -w pswpout "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)

    add_metric "sensors" "memory_page_faults_major" "{}" "$pgmajfault"
    add_metric "sensors" "oom_kills_total" "{}" "$oom_kill"
    add_metric "sensors" "swap_io_in_pages" "{}" "$pswpin"
    add_metric "sensors" "swap_io_out_pages" "{}" "$pswpout"
fi

METRICS+="\n]"
echo -e "$METRICS"
```

- [ ] **Step 2: Make executable and test locally**

Note: when run outside the container, paths don't have `/host/` prefix. Test with adjusted paths:

```bash
chmod +x /home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh
# Quick test — will use /host/sys paths which don't exist on bare host,
# so it should output mostly zeros (graceful degradation)
HOST_SYS=/sys HOST_PROC=/proc \
  sed 's|/host/sys|/sys|g; s|/host/proc|/proc|g' \
  /home/merm/projects/back-office/monitoring/vector/collectors/system_sensors.sh | bash | python3 -m json.tool
```

Expected: valid JSON with CPU temps, frequencies, and vmstat counters.

- [ ] **Step 3: Commit**

```bash
git add monitoring/vector/collectors/system_sensors.sh
git commit -m "feat(monitoring): add system sensors collector (temp, freq, vmstat)"
```

---

### Task 9: Ollama metrics collector

**Files:**
- Create: `monitoring/vector/collectors/ollama_metrics.sh`

- [ ] **Step 1: Create ollama_metrics.sh**

Create `/home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh`:

```bash
#!/bin/bash
# Collects Ollama model status from /api/ps and /api/tags.
# Computes vram_ratio for GPU offload detection.
# Outputs JSON array. Exits 0 with zero-values if Ollama is down.
# Uses Python for JSON generation to avoid subshell variable scoping issues.
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

# Check if Ollama is reachable and generate all metrics in Python
# to avoid bash subshell variable scoping bugs with pipes.
python3 << 'PYEOF'
import json, sys, urllib.request, datetime

host = "${OLLAMA_HOST}" if "${OLLAMA_HOST}" != "" else "http://localhost:11434"
# Re-read from env since heredoc doesn't expand
import os
host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def metric(name, labels, value):
    return {"time": now, "source": "ollama", "metric": name, "labels": labels, "value": value}

metrics = []

# Check if Ollama is reachable
try:
    tags_raw = urllib.request.urlopen(f"{host}/api/tags", timeout=5).read()
    tags = json.loads(tags_raw)
except Exception:
    print(json.dumps([metric("ollama_running", {}, 0)]))
    sys.exit(0)

metrics.append(metric("ollama_running", {}, 1))
metrics.append(metric("ollama_models_available", {}, len(tags.get("models", []))))

# Get running models
try:
    ps_raw = urllib.request.urlopen(f"{host}/api/ps", timeout=5).read()
    ps = json.loads(ps_raw)
except Exception:
    ps = {"models": []}

for m in ps.get("models", []):
    name = m.get("name", "unknown")
    size = m.get("size", 0)
    size_vram = m.get("size_vram", 0)
    vram_ratio = round(size_vram / size, 4) if size > 0 else 0.0
    expires_at = m.get("expires_at", "")
    labels = {"model": name}

    metrics.append(metric("ollama_model_loaded", labels, 1))
    metrics.append(metric("ollama_model_size_bytes", labels, size))
    metrics.append(metric("ollama_model_vram_bytes", labels, size_vram))
    metrics.append(metric("ollama_model_vram_ratio", labels, vram_ratio))

    if expires_at:
        metrics.append(metric("ollama_model_expires_at", {**labels, "expires_at": expires_at}, 1))

print(json.dumps(metrics, indent=2))
PYEOF
```

- [ ] **Step 2: Make executable and test locally**

```bash
chmod +x /home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh
/home/merm/projects/back-office/monitoring/vector/collectors/ollama_metrics.sh | python3 -m json.tool
```

Expected: valid JSON with `ollama_running: 1`, model count, and loaded model details (if any models are currently loaded).

- [ ] **Step 3: Commit**

```bash
git add monitoring/vector/collectors/ollama_metrics.sh
git commit -m "feat(monitoring): add Ollama metrics collector (model status, VRAM ratio)"
```

---

### Task 10: Claude Code sessions collector

**Files:**
- Create: `monitoring/vector/collectors/claude_sessions.sh`

- [ ] **Step 1: Create claude_sessions.sh**

Create `/home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh`:

```bash
#!/bin/bash
# Collects Claude Code session count, worktree count, and per-session uptime.
# Outputs JSON array. Exits 0 with zeros if nothing is running.
set -euo pipefail

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NOW_EPOCH=$(date +%s)

METRICS="["
FIRST=true

add_metric() {
    local metric="$1" labels="$2" value="$3"
    if [ "$FIRST" = true ]; then FIRST=false; else METRICS+=","; fi
    METRICS+=$(printf '\n  {"time":"%s","source":"claude","metric":"%s","labels":%s,"value":%s}' \
        "$NOW" "$metric" "$labels" "$value")
}

# Count claude processes and get per-session info
session_count=0
while IFS= read -r line; do
    [ -z "$line" ] && continue
    pid=$(echo "$line" | awk '{print $1}')
    start_epoch=$(echo "$line" | awk '{print $2}')
    uptime_sec=$((NOW_EPOCH - start_epoch))
    add_metric "claude_session_uptime_sec" "{\"session_id\":\"$pid\"}" "$uptime_sec"
    session_count=$((session_count + 1))
done < <(ps -eo pid,lstart --no-headers -C claude 2>/dev/null | while read -r pid rest; do
    # Convert lstart to epoch
    epoch=$(date -d "$rest" +%s 2>/dev/null || echo "$NOW_EPOCH")
    echo "$pid $epoch"
done)

add_metric "claude_active_sessions" "{}" "$session_count"

# Count active git worktrees across projects
worktree_count=0
PROJECTS_DIR="${PROJECTS_DIR:-/home/merm/projects}"
if [ -d "$PROJECTS_DIR" ]; then
    for repo in "$PROJECTS_DIR"/*/; do
        [ -d "${repo}.git" ] || continue
        wt=$(cd "$repo" && git worktree list 2>/dev/null | wc -l || echo 1)
        extra=$((wt - 1))
        worktree_count=$((worktree_count + extra))
    done
fi

add_metric "claude_worktrees_active" "{}" "$worktree_count"

METRICS+="\n]"
echo -e "$METRICS"
```

- [ ] **Step 2: Make executable and test locally**

```bash
chmod +x /home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh
/home/merm/projects/back-office/monitoring/vector/collectors/claude_sessions.sh | python3 -m json.tool
```

Expected: valid JSON with session count > 0 (since Claude Code is running right now) and worktree count >= 0.

- [ ] **Step 3: Commit**

```bash
git add monitoring/vector/collectors/claude_sessions.sh
git commit -m "feat(monitoring): add Claude Code sessions collector"
```

---

## Chunk 3: Vector Pipeline Configuration

### Task 11: Vector configuration

**Files:**
- Create: `monitoring/vector/vector.yaml`

- [ ] **Step 1: Create the full Vector pipeline config**

Create `/home/merm/projects/back-office/monitoring/vector/vector.yaml`:

```yaml
# BreakPoint Labs — Vector Pipeline
# Collects host metrics, GPU, system sensors, Ollama, Claude Code, logs
# Sinks to ingest service → TimescaleDB

# ── API ──────────────────────────────────────────────────────
api:
  enabled: true
  address: "0.0.0.0:8686"

# ── Sources ──────────────────────────────────────────────────
sources:
  host_metrics:
    type: host_metrics
    collectors:
      - cpu
      - memory
      - disk
      - filesystem
      - network
      - load
    scrape_interval_secs: 15
    namespace: host

  gpu_metrics:
    type: exec
    command: ["/etc/vector/collectors/gpu_metrics.sh"]
    mode: scheduled
    scheduled:
      exec_interval_secs: 15
    decoding:
      codec: json

  system_sensors:
    type: exec
    command: ["/etc/vector/collectors/system_sensors.sh"]
    mode: scheduled
    scheduled:
      exec_interval_secs: 15
    decoding:
      codec: json

  ollama_metrics:
    type: exec
    command: ["/etc/vector/collectors/ollama_metrics.sh"]
    mode: scheduled
    scheduled:
      exec_interval_secs: 30
    decoding:
      codec: json

  claude_metrics:
    type: exec
    command: ["/etc/vector/collectors/claude_sessions.sh"]
    mode: scheduled
    scheduled:
      exec_interval_secs: 60
    decoding:
      codec: json

  ollama_journal:
    type: journald
    include_units:
      - ollama

  system_journal:
    type: journald
    include_units:
      - kernel
      - systemd-oomd
      - com.system76.PowerDaemon

  docker_logs:
    type: docker_logs
    include_containers:
      - "forgejo*"
      - "breakpoint-grafana"
      - "breakpoint-timescaledb"

# ── Transforms ───────────────────────────────────────────────
transforms:
  # -- Host metrics: Vector internal format → our schema --
  host_normalize:
    type: remap
    inputs: ["host_metrics"]
    source: |
      .host = "borg"
      .source = "host"
      metric_name = string!(.name)
      .metric = replace(metric_name, "host_", "")
      .labels = .tags ?? {}
      .value = to_float(.gauge.value ?? .counter.value ?? .distribution.avg ?? 0.0) ?? 0.0
      .time = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")
      del(.tags)
      del(.name)
      del(.gauge)
      del(.counter)
      del(.distribution)
      del(.namespace)
      del(.kind)
      del(.timestamp)

  # -- Exec sources already output our schema, just ensure host field --
  gpu_passthrough:
    type: remap
    inputs: ["gpu_metrics"]
    source: |
      .host = "borg"

  sensors_passthrough:
    type: remap
    inputs: ["system_sensors"]
    source: |
      .host = "borg"

  ollama_passthrough:
    type: remap
    inputs: ["ollama_metrics"]
    source: |
      .host = "borg"

  claude_passthrough:
    type: remap
    inputs: ["claude_metrics"]
    source: |
      .host = "borg"

  # -- Journald → logs schema --
  ollama_logs:
    type: remap
    inputs: ["ollama_journal"]
    source: |
      .host = "borg"
      .source = "journald"
      .service = "ollama"
      .level = downcase(to_string(.PRIORITY) ?? "info")
      # Map systemd priority numbers to level names
      .level = if .level == "3" { "error" }
               else if .level == "4" { "warning" }
               else if .level == "6" { "info" }
               else if .level == "7" { "debug" }
               else { .level }
      .message = to_string(.MESSAGE) ?? ""
      .metadata = {}
      .time = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")
      del(.MESSAGE)
      del(.PRIORITY)
      del(.timestamp)
      del(._SYSTEMD_UNIT)

  # -- Ollama inference metrics from journald logs --
  # Ollama logs inference timing per request. Parse eval_count, eval_duration, etc.
  ollama_inference_parse:
    type: remap
    inputs: ["ollama_journal"]
    drop_on_abort: true
    source: |
      msg = to_string(.MESSAGE) ?? ""
      # Ollama logs lines like: "eval_count=42 eval_duration=1234567890 ..."
      # Only process lines that contain eval timing data
      if !contains(msg, "eval_duration") { abort }

      .host = "borg"
      .source = "ollama_inference"
      now = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")

      # Extract model name (Ollama logs it as the first field or in a model= tag)
      model = "unknown"
      model_match, err = parse_regex(msg, r'model=(?P<m>[^\s]+)')
      if err == null { model = model_match.m }

      # Extract numeric fields (nanoseconds in Ollama logs)
      eval_count = 0
      eval_dur_ns = 0
      prompt_eval_count = 0
      prompt_eval_dur_ns = 0
      total_dur_ns = 0

      ec, err = parse_regex(msg, r'eval_count=(?P<v>\d+)')
      if err == null { eval_count = to_int!(ec.v) }
      ed, err = parse_regex(msg, r'eval_duration=(?P<v>\d+)')
      if err == null { eval_dur_ns = to_int!(ed.v) }
      pec, err = parse_regex(msg, r'prompt_eval_count=(?P<v>\d+)')
      if err == null { prompt_eval_count = to_int!(pec.v) }
      ped, err = parse_regex(msg, r'prompt_eval_duration=(?P<v>\d+)')
      if err == null { prompt_eval_dur_ns = to_int!(ped.v) }
      td, err = parse_regex(msg, r'total_duration=(?P<v>\d+)')
      if err == null { total_dur_ns = to_int!(td.v) }

      labels = {"model": model}
      eval_dur_ms = to_float(eval_dur_ns) / 1000000.0
      prompt_eval_dur_ms = to_float(prompt_eval_dur_ns) / 1000000.0
      total_dur_ms = to_float(total_dur_ns) / 1000000.0
      eval_rate = if eval_dur_ns > 0 { to_float(eval_count) / (to_float(eval_dur_ns) / 1000000000.0) } else { 0.0 }
      prompt_eval_rate = if prompt_eval_dur_ns > 0 { to_float(prompt_eval_count) / (to_float(prompt_eval_dur_ns) / 1000000000.0) } else { 0.0 }

      . = [
        {"time": now, "source": "ollama_inference", "metric": "ollama_eval_rate", "labels": labels, "value": eval_rate},
        {"time": now, "source": "ollama_inference", "metric": "ollama_prompt_eval_rate", "labels": labels, "value": prompt_eval_rate},
        {"time": now, "source": "ollama_inference", "metric": "ollama_time_to_first_token_ms", "labels": labels, "value": prompt_eval_dur_ms},
        {"time": now, "source": "ollama_inference", "metric": "ollama_eval_duration_ms", "labels": labels, "value": eval_dur_ms},
        {"time": now, "source": "ollama_inference", "metric": "ollama_prompt_eval_duration_ms", "labels": labels, "value": prompt_eval_dur_ms},
        {"time": now, "source": "ollama_inference", "metric": "ollama_total_duration_ms", "labels": labels, "value": total_dur_ms},
        {"time": now, "source": "ollama_inference", "metric": "ollama_tokens_generated", "labels": labels, "value": to_float(eval_count)}
      ]

  system_logs:
    type: remap
    inputs: ["system_journal"]
    source: |
      .host = "borg"
      .source = "journald"
      .service = to_string(._SYSTEMD_UNIT) ?? "kernel"
      .level = downcase(to_string(.PRIORITY) ?? "info")
      .level = if .level == "3" { "error" }
               else if .level == "4" { "warning" }
               else if .level == "6" { "info" }
               else if .level == "7" { "debug" }
               else { .level }
      .message = to_string(.MESSAGE) ?? ""
      .metadata = {}
      .time = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")
      del(.MESSAGE)
      del(.PRIORITY)
      del(.timestamp)
      del(._SYSTEMD_UNIT)

  # -- System events: detect OOM kills from kernel journal → metrics --
  system_event_metrics:
    type: remap
    inputs: ["system_journal"]
    drop_on_abort: true
    source: |
      msg = to_string(.MESSAGE) ?? ""
      # Only process OOM and thermal events
      if !contains(msg, "Out of memory") && !contains(msg, "oom_kill") && !contains(msg, "thermal") { abort }

      .host = "borg"
      .source = "sensors"
      now = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")

      if contains(msg, "Out of memory") || contains(msg, "oom_kill") {
        .time = now
        .metric = "oom_kills_total"
        .labels = {}
        .value = 1.0
      } else {
        abort
      }

  docker_normalize:
    type: remap
    inputs: ["docker_logs"]
    source: |
      .host = "borg"
      .source = "docker"
      .service = .container_name ?? "unknown"
      .level = "info"
      .message = to_string(.message) ?? ""
      .metadata = {"container_id": to_string(.container_id) ?? ""}
      .time = format_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%SZ")
      del(.container_name)
      del(.container_id)
      del(.timestamp)

# ── Sinks ────────────────────────────────────────────────────
sinks:
  ingest_metrics:
    type: http
    inputs:
      - host_normalize
      - gpu_passthrough
      - sensors_passthrough
      - ollama_passthrough
      - claude_passthrough
      - ollama_inference_parse
      - system_event_metrics
    uri: "http://localhost:8087/ingest/metrics"
    method: post
    encoding:
      codec: json
    batch:
      max_events: 100
      timeout_secs: 15
    request:
      retry_max_duration_secs: 30
    healthcheck:
      enabled: false

  ingest_logs:
    type: http
    inputs:
      - ollama_logs
      - system_logs
      - docker_normalize
    uri: "http://localhost:8087/ingest/logs"
    method: post
    encoding:
      codec: json
    batch:
      max_events: 50
      timeout_secs: 30
    request:
      retry_max_duration_secs: 30
    healthcheck:
      enabled: false
```

- [ ] **Step 2: Validate Vector config**

```bash
docker run --rm \
  -v /home/merm/projects/back-office/monitoring/vector/vector.yaml:/etc/vector/vector.yaml:ro \
  timberio/vector:latest-debian \
  vector validate /etc/vector/vector.yaml
```

Expected: `Loaded ["/etc/vector/vector.yaml"]` with no errors. Warnings about unreachable sources (journald, docker) are expected in a container without those mounts.

- [ ] **Step 3: Commit**

```bash
git add monitoring/vector/vector.yaml
git commit -m "feat(monitoring): add Vector pipeline config (sources, transforms, http sinks)"
```

---

### Task 12: Start Vector and verify end-to-end data flow

- [ ] **Step 1: Start the full stack**

```bash
cd /home/merm/projects/back-office/monitoring
docker compose up -d
```

- [ ] **Step 2: Check all containers are running**

```bash
docker compose ps
```

Expected: 4 containers running (timescaledb, ingest, vector, grafana), all healthy or starting.

- [ ] **Step 3: Wait 30 seconds, then check metrics are flowing**

```bash
sleep 30
docker exec breakpoint-timescaledb psql -U vector -d monitoring \
  -c "SELECT source, metric, count(*) FROM metrics GROUP BY source, metric ORDER BY source, metric;"
```

Expected: rows from `host`, `gpu`, `sensors`, `ollama`, `claude` sources.

- [ ] **Step 4: Check logs are flowing**

```bash
docker exec breakpoint-timescaledb psql -U vector -d monitoring \
  -c "SELECT source, service, count(*) FROM logs GROUP BY source, service ORDER BY source, service;"
```

Expected: rows from `journald` and/or `docker` sources.

- [ ] **Step 5: Check Vector health**

```bash
curl -s http://localhost:8686/health
```

Expected: `{"ok":true}`

---

## Chunk 4: Grafana Dashboards

### Task 13: Host Overview dashboard

**Files:**
- Create: `monitoring/provisioning/dashboards/host-overview.json`

- [ ] **Step 1: Create the Host Overview dashboard JSON**

Create `/home/merm/projects/back-office/monitoring/provisioning/dashboards/host-overview.json`.

This is a Grafana provisioned dashboard. The JSON is large — create it with these panels:

1. **CPU Usage per Core** — stacked time series
   - Query: `SELECT bucket AS time, labels->>'core' AS core, avg_val AS value FROM metrics_5m WHERE metric = 'cpu_usage_percent' AND $__timeFilter(bucket) ORDER BY bucket`
2. **Load Average** — time series overlay (1m + 5m)
   - Query: `SELECT bucket AS time, metric, avg_val AS value FROM metrics_5m WHERE metric IN ('load_avg_1m', 'load_avg_5m') AND $__timeFilter(bucket) ORDER BY bucket`
3. **RAM Usage** — gauge + time series
   - Query: `SELECT bucket AS time, avg_val AS value FROM metrics_5m WHERE metric = 'memory_used_bytes' AND $__timeFilter(bucket) ORDER BY bucket`
4. **Swap Usage** — time series
   - Query: `SELECT bucket AS time, avg_val AS value FROM metrics_5m WHERE metric = 'swap_used_bytes' AND $__timeFilter(bucket) ORDER BY bucket`
5. **Disk Usage per Device** — bar gauge
   - Query: `SELECT labels->>'device' AS device, max(avg_val) AS value FROM metrics_5m WHERE metric = 'disk_used_bytes' AND bucket > now() - interval '5 minutes' GROUP BY device`
6. **Disk I/O** — time series (read + write)
   - Query: `SELECT bucket AS time, metric, labels->>'device' AS device, avg_val AS value FROM metrics_5m WHERE metric IN ('disk_io_read_bytes', 'disk_io_write_bytes') AND $__timeFilter(bucket) ORDER BY bucket`
7. **Network Traffic** — time series (rx + tx)
   - Query: `SELECT bucket AS time, metric, avg_val AS value FROM metrics_5m WHERE metric IN ('network_rx_bytes', 'network_tx_bytes') AND labels->>'device' = 'wlp8s0' AND $__timeFilter(bucket) ORDER BY bucket`
8. **CPU Temperature** — time series with 90C threshold
   - Query: `SELECT bucket AS time, labels->>'label' AS sensor, avg_val AS value FROM metrics_5m WHERE source = 'sensors' AND metric = 'cpu_temp_celsius' AND $__timeFilter(bucket) ORDER BY bucket`
9. **OOM Kills** — stat (big red number)
   - Query: `SELECT max(avg_val) AS value FROM metrics_5m WHERE metric = 'oom_kills_total' AND bucket > now() - interval '5 minutes'`
10. **Page Faults** — time series
    - Query: `SELECT bucket AS time, avg_val AS value FROM metrics_5m WHERE metric = 'memory_page_faults_major' AND $__timeFilter(bucket) ORDER BY bucket`

Use Grafana dashboard JSON model with:
- `"uid": "host-overview"`
- `"title": "Host Overview — borg"`
- `"datasource": {"uid": "timescaledb", "type": "postgres"}`
- Dark theme compatible (Grafana default)
- Time range: last 6 hours default

The actual JSON generation should be done by creating the dashboard structure programmatically. Create a minimal but complete dashboard JSON file.

- [ ] **Step 2: Verify dashboard loads in Grafana**

Open `http://localhost:3333` in a browser, log in with admin credentials.
Dashboard should appear as the home dashboard.

- [ ] **Step 3: Commit**

```bash
git add monitoring/provisioning/dashboards/host-overview.json
git commit -m "feat(monitoring): add Host Overview Grafana dashboard"
```

---

### Task 14: GPU Monitoring dashboard

**Files:**
- Create: `monitoring/provisioning/dashboards/gpu-monitoring.json`

- [ ] **Step 1: Create GPU Monitoring dashboard JSON**

Create `/home/merm/projects/back-office/monitoring/provisioning/dashboards/gpu-monitoring.json`.

Panels:

1. **GPU Temperature** — gauge (semicircle), green 0-60, yellow 60-80, red 80+
   - Query: `SELECT avg_val FROM metrics_5m WHERE metric = 'gpu_temp_celsius' AND bucket > now() - interval '5 minutes' ORDER BY bucket DESC LIMIT 1`
2. **GPU Temp History** — time series with 83C threshold line
3. **VRAM Usage** — gauge (used/total)
4. **VRAM Free** — stat
5. **GPU Utilization** — time series
6. **Power Draw vs Limit** — time series with power_limit as threshold
7. **Clock Speed** — time series (current vs max)
8. **Fan Speed** — time series
9. **Throttle Status** — 4 stat panels (idle, hw_thermal, sw_thermal, sw_power_cap)
10. **PCIe Link** — stat (gen + width)

- `"uid": "gpu-monitoring"`
- `"title": "GPU Monitoring — RTX 3080"`

- [ ] **Step 2: Verify dashboard loads**

Navigate to `http://localhost:3333/d/gpu-monitoring` in browser.

- [ ] **Step 3: Commit**

```bash
git add monitoring/provisioning/dashboards/gpu-monitoring.json
git commit -m "feat(monitoring): add GPU Monitoring Grafana dashboard"
```

---

### Task 15: LLM Inference dashboard

**Files:**
- Create: `monitoring/provisioning/dashboards/llm-inference.json`

- [ ] **Step 1: Create LLM Inference dashboard JSON**

Create `/home/merm/projects/back-office/monitoring/provisioning/dashboards/llm-inference.json`.

Panels:

1. **VRAM Ratio per Model** — gauge (1.0 = green, <1.0 = red), repeating per model
   - Query: `SELECT labels->>'model' AS model, avg_val FROM metrics_5m WHERE metric = 'ollama_model_vram_ratio' AND bucket > now() - interval '5 minutes' ORDER BY bucket DESC`
2. **Models Status Table** — table (name, loaded, vram_ratio, size)
   - Query: `SELECT DISTINCT ON (labels->>'model') labels->>'model' AS model, avg_val AS vram_ratio FROM metrics_5m WHERE metric = 'ollama_model_vram_ratio' ORDER BY labels->>'model', bucket DESC`
3. **VRAM Ratio History** — time series per model
4. **Ollama Service Status** — stat (up/down)
5. **Available Models** — stat (count)
6. **VRAM Headroom** — stat (gpu_memory_free_bytes)
7. **Generation Speed** — time series (ollama_eval_rate tokens/s) — from inference logs
8. **Prompt Processing Speed** — time series (ollama_prompt_eval_rate)
9. **Time to First Token** — time series
10. **Tokens Generated** — time series
11. **VRAM vs Eval Rate Correlation** — dual-axis time series

- `"uid": "llm-inference"`
- `"title": "LLM Inference — Ollama"`

- [ ] **Step 2: Verify dashboard loads**

Navigate to `http://localhost:3333/d/llm-inference` in browser.

- [ ] **Step 3: Commit**

```bash
git add monitoring/provisioning/dashboards/llm-inference.json
git commit -m "feat(monitoring): add LLM Inference Grafana dashboard"
```

---

### Task 16: Claude Code Sessions dashboard

**Files:**
- Create: `monitoring/provisioning/dashboards/claude-sessions.json`

- [ ] **Step 1: Create Claude Code Sessions dashboard JSON**

Create `/home/merm/projects/back-office/monitoring/provisioning/dashboards/claude-sessions.json`.

Panels:

1. **Active Sessions** — stat (big number)
2. **Active Worktrees** — stat
3. **Session History** — time series
4. **System Impact** — dual-axis time series (CPU + RAM vs session count)

- `"uid": "claude-sessions"`
- `"title": "Claude Code Sessions"`

- [ ] **Step 2: Verify dashboard loads**

Navigate to `http://localhost:3333/d/claude-sessions` in browser.

- [ ] **Step 3: Commit**

```bash
git add monitoring/provisioning/dashboards/claude-sessions.json
git commit -m "feat(monitoring): add Claude Code Sessions Grafana dashboard"
```

---

### Task 17: Update dashboards.yml provisioning

**Files:**
- Modify: `monitoring/provisioning/dashboards/dashboards.yml`

- [ ] **Step 1: Verify existing dashboards.yml works for new dashboards**

The existing `dashboards.yml` already provisions all JSON files from the dashboards directory via `path: /etc/grafana/provisioning/dashboards`. New JSON files will be picked up automatically. No change needed unless folder organization is desired.

Read the file to confirm:

```bash
cat /home/merm/projects/back-office/monitoring/provisioning/dashboards/dashboards.yml
```

If it already has `foldersFromFilesStructure: false` and the path includes the dashboards directory, no modification needed.

---

## Chunk 5: Grafana Alerts

### Task 18: Configure Grafana alert rules

**Files:**
- Create: `monitoring/provisioning/alerting/alerts.yml`

- [ ] **Step 1: Create alert rules provisioning file**

Create directory and file `/home/merm/projects/back-office/monitoring/provisioning/alerting/alerts.yml`:

```yaml
apiVersion: 1

groups:
  - orgId: 1
    name: Infrastructure Alerts
    folder: Alerts
    interval: 1m
    rules:
      - uid: disk-critical
        title: "Disk Critical (>90%)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, labels->>'device' AS device,
                       avg_val / NULLIF((SELECT avg_val FROM metrics_5m m2
                         WHERE m2.metric = 'disk_total_bytes'
                         AND m2.labels->>'device' = metrics_5m.labels->>'device'
                         AND m2.bucket > now() - interval '5 minutes'
                         ORDER BY m2.bucket DESC LIMIT 1), 0) AS ratio
                FROM metrics_5m
                WHERE metric = 'disk_used_bytes'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [0.90]
        for: 5m
        annotations:
          summary: "Disk usage above 90%"
        labels:
          severity: critical

      - uid: gpu-thermal
        title: "GPU Thermal (>83°C)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'gpu_temp_celsius'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [83]
        for: 2m
        annotations:
          summary: "RTX 3080 temperature exceeds 83°C"
        labels:
          severity: critical

      - uid: ram-pressure
        title: "RAM Pressure (<4GB free)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'memory_available_bytes'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: lt
                    params: [4294967296]
        for: 5m
        annotations:
          summary: "Less than 4GB RAM available"
        labels:
          severity: warning

      - uid: gpu-offload
        title: "GPU Offload Detected"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'ollama_model_vram_ratio'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: lt
                    params: [1.0]
        for: 1m
        annotations:
          summary: "Model partially on CPU — VRAM ratio below 1.0"
        labels:
          severity: warning

      - uid: vram-exhausted
        title: "VRAM Exhausted (<500MB free)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'gpu_memory_free_bytes'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: lt
                    params: [524288000]
        for: 2m
        annotations:
          summary: "Less than 500MB VRAM free"
        labels:
          severity: warning

      - uid: ollama-down
        title: "Ollama Down"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'ollama_running'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: lt
                    params: [1]
        for: 1m
        annotations:
          summary: "Ollama service is not responding"
        labels:
          severity: critical

      - uid: disk-warning
        title: "Disk Warning (>85%)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, labels->>'device' AS device,
                       avg_val / NULLIF((SELECT avg_val FROM metrics_5m m2
                         WHERE m2.metric = 'disk_total_bytes'
                         AND m2.labels->>'device' = metrics_5m.labels->>'device'
                         AND m2.bucket > now() - interval '5 minutes'
                         ORDER BY m2.bucket DESC LIMIT 1), 0) AS ratio
                FROM metrics_5m
                WHERE metric = 'disk_used_bytes'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [0.85]
        for: 10m
        annotations:
          summary: "Disk usage above 85%"
        labels:
          severity: warning

      - uid: gpu-throttling
        title: "GPU Throttling (non-idle)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time,
                       greatest(
                         max(CASE WHEN metric = 'gpu_throttle_hw_thermal' THEN avg_val END),
                         max(CASE WHEN metric = 'gpu_throttle_sw_thermal' THEN avg_val END),
                         max(CASE WHEN metric = 'gpu_throttle_sw_power_cap' THEN avg_val END)
                       ) AS value
                FROM metrics_5m
                WHERE metric IN ('gpu_throttle_hw_thermal', 'gpu_throttle_sw_thermal', 'gpu_throttle_sw_power_cap')
                AND $__timeFilter(bucket)
                GROUP BY bucket
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [0]
        for: 1m
        annotations:
          summary: "GPU clock throttling active (thermal or power cap)"
        labels:
          severity: warning

      - uid: swap-thrashing
        title: "Swap Thrashing"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time,
                       (avg_val - lag(avg_val) OVER (ORDER BY bucket)) /
                       EXTRACT(EPOCH FROM bucket - lag(bucket) OVER (ORDER BY bucket)) AS rate
                FROM metrics_5m
                WHERE metric = 'swap_io_in_pages'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [1000]
        for: 1m
        annotations:
          summary: "Swap I/O rate exceeds 1000 pages/s — system is thrashing"
        labels:
          severity: critical

      - uid: inference-degraded
        title: "Inference Degraded (<15 tokens/s)"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time, avg_val AS value
                FROM metrics_5m
                WHERE metric = 'ollama_eval_rate'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: lt
                    params: [15]
        for: 2m
        annotations:
          summary: "LLM generation speed below 15 tokens/s — possible CPU offload"
        labels:
          severity: warning

      - uid: oom-kill
        title: "OOM Kill Detected"
        condition: C
        data:
          - refId: A
            datasourceUid: timescaledb
            model:
              rawSql: |
                SELECT bucket AS time,
                       avg_val - lag(avg_val) OVER (ORDER BY bucket) AS delta
                FROM metrics_5m
                WHERE metric = 'oom_kills_total'
                AND $__timeFilter(bucket)
                ORDER BY bucket
              format: time_series
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    type: gt
                    params: [0]
        for: 0s
        annotations:
          summary: "OOM killer fired — check which process was killed"
        labels:
          severity: critical
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/provisioning/alerting/
git commit -m "feat(monitoring): add Grafana alert rules (disk, GPU, RAM, VRAM, Ollama)"
```

---

## Chunk 6: Makefile Targets

### Task 19: Add monitoring Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add monitoring section to Makefile**

Add after the existing `grafana-logs` target (around line 231) in `/home/merm/projects/back-office/Makefile`:

```makefile
# ── Monitoring Stack ─────────────────────────────────────────

.PHONY: monitoring-up monitoring-down monitoring-logs monitoring-status monitoring-restart

monitoring-up: ## Start full monitoring stack (Vector + TimescaleDB + Grafana)
	cd monitoring && docker compose up -d
	@echo "Monitoring stack starting..."
	@echo "  Grafana:     http://localhost:3333"
	@echo "  TimescaleDB: localhost:5433"
	@echo "  Vector API:  http://localhost:8686"
	@echo "  Ingest API:  http://localhost:8087"

monitoring-down: ## Stop monitoring stack
	cd monitoring && docker compose down

monitoring-logs: ## Tail monitoring stack logs
	cd monitoring && docker compose logs -f

monitoring-status: ## Health check all monitoring services
	@echo "=== Monitoring Stack Status ==="
	@echo -n "TimescaleDB: " && (docker exec breakpoint-timescaledb pg_isready -U vector -d monitoring 2>/dev/null && echo "OK") || echo "DOWN"
	@echo -n "Ingest:      " && (curl -sf http://localhost:8087/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null) || echo "DOWN"
	@echo -n "Vector:      " && (curl -sf http://localhost:8686/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('ok') else 'DOWN')" 2>/dev/null) || echo "DOWN"
	@echo -n "Grafana:     " && (curl -sf http://localhost:3333/api/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('database','DOWN'))" 2>/dev/null) || echo "DOWN"

monitoring-restart: ## Restart monitoring stack
	cd monitoring && docker compose restart
```

- [ ] **Step 2: Update the existing grafana targets to point to monitoring-up/down**

Replace the existing grafana targets in the Makefile:

```makefile
grafana: ## Start Grafana monitoring dashboard (alias for monitoring-up)
	$(MAKE) monitoring-up

grafana-stop: ## Stop Grafana (alias for monitoring-down)
	$(MAKE) monitoring-down

grafana-logs: ## Tail Grafana logs
	cd monitoring && docker compose logs -f grafana
```

- [ ] **Step 3: Add .PHONY declarations**

Add to the `.PHONY` line at the top of the Makefile:

```makefile
.PHONY: monitoring-up monitoring-down monitoring-logs monitoring-status monitoring-restart
```

- [ ] **Step 4: Verify targets work**

```bash
cd /home/merm/projects/back-office && make monitoring-status
```

Expected: status output for all 4 services.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "feat(monitoring): add Makefile targets for monitoring stack"
```

---

## Chunk 7: Remote Access Setup

### Task 20: SSH setup script

**Files:**
- Create: `monitoring/scripts/setup-remote-access.sh`
- Create: `monitoring/scripts/undo-remote-access.sh`

- [ ] **Step 1: Create setup-remote-access.sh**

Create `/home/merm/projects/back-office/monitoring/scripts/setup-remote-access.sh`:

```bash
#!/bin/bash
# One-time setup for LAN remote access to borg.
# Configures: SSH (key-only, LAN-restricted), Samba (home + media), RDP (gnome-remote-desktop).
# Idempotent — safe to re-run.
# Requires: sudo
set -euo pipefail

echo "=== borg Remote Access Setup ==="
echo "This script configures SSH, Samba, and RDP for LAN access."
echo ""

# ── SSH ──────────────────────────────────────────────────────
echo "[1/3] Configuring SSH..."

if ! dpkg -l openssh-server &>/dev/null; then
    echo "  Installing openssh-server..."
    sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server
fi

# Backup original config
SSHD_CONFIG="/etc/ssh/sshd_config"
if [ ! -f "${SSHD_CONFIG}.bak.remote-access" ]; then
    sudo cp "$SSHD_CONFIG" "${SSHD_CONFIG}.bak.remote-access"
    echo "  Backed up $SSHD_CONFIG"
fi

# Create drop-in config for LAN access
sudo tee /etc/ssh/sshd_config.d/99-lan-access.conf > /dev/null << 'SSHEOF'
# LAN remote access config (managed by setup-remote-access.sh)
PasswordAuthentication no
PubkeyAuthentication yes
AllowUsers merm@10.0.0.0/24 merm@127.0.0.1
SSHEOF

sudo systemctl enable ssh
sudo systemctl restart ssh
echo "  SSH configured (key-only, LAN-restricted)"

# ── Samba ────────────────────────────────────────────────────
echo "[2/3] Configuring Samba..."

if ! dpkg -l samba &>/dev/null; then
    echo "  Installing samba..."
    sudo apt-get install -y -qq samba
fi

SMB_CONFIG="/etc/samba/smb.conf"
if [ ! -f "${SMB_CONFIG}.bak.remote-access" ]; then
    sudo cp "$SMB_CONFIG" "${SMB_CONFIG}.bak.remote-access"
    echo "  Backed up $SMB_CONFIG"
fi

# Check if our shares already exist
if ! grep -q '\[home\]' "$SMB_CONFIG" 2>/dev/null; then
    sudo tee -a "$SMB_CONFIG" > /dev/null << 'SMBEOF'

# ── LAN shares (managed by setup-remote-access.sh) ──
[home]
   comment = Home Directory
   path = /home/merm
   browseable = yes
   read only = no
   valid users = merm
   hosts allow = 10.0.0.0/24 127.0.0.1
   hosts deny = 0.0.0.0/0
   follow symlinks = yes
   wide links = yes

[media]
   comment = USB Drives
   path = /media/merm
   browseable = yes
   read only = no
   valid users = merm
   hosts allow = 10.0.0.0/24 127.0.0.1
   hosts deny = 0.0.0.0/0
   follow symlinks = yes
   wide links = yes
SMBEOF
    echo "  Samba shares added"
else
    echo "  Samba shares already configured"
fi

# Set Samba password for merm (prompts for password)
echo "  Setting Samba password for merm..."
sudo smbpasswd -a merm

sudo systemctl enable smbd
sudo systemctl restart smbd
echo "  Samba configured (home + media shares, LAN-restricted)"

# ── RDP (gnome-remote-desktop) ───────────────────────────────
echo "[3/3] Configuring RDP..."

# gnome-remote-desktop is already running on borg
if systemctl --user is-active gnome-remote-desktop.service &>/dev/null; then
    echo "  gnome-remote-desktop is already active"
    echo "  Configure RDP credentials via: Settings > Sharing > Remote Desktop"
    echo "  Or use: grdctl rdp set-credentials <username> <password>"
else
    echo "  gnome-remote-desktop not active. Start it via Settings > Sharing > Remote Desktop"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "From your laptop:"
echo "  SSH:    ssh merm@borg.local"
echo "  Files:  smb://borg.local/home"
echo "  USB:    smb://borg.local/media"
echo "  RDP:    borg.local:3389 (via Remmina)"
echo ""
echo "First: copy your laptop's SSH key to borg:"
echo "  ssh-copy-id merm@borg.local"
```

- [ ] **Step 2: Create undo-remote-access.sh**

Create `/home/merm/projects/back-office/monitoring/scripts/undo-remote-access.sh`:

```bash
#!/bin/bash
# Reverses LAN remote access setup.
# Restores SSH, Samba configs from backups, disables services.
# Requires: sudo
set -euo pipefail

echo "=== Undoing Remote Access Setup ==="

# ── SSH ──────────────────────────────────────────────────────
echo "[1/3] Reverting SSH..."
if [ -f /etc/ssh/sshd_config.d/99-lan-access.conf ]; then
    sudo rm /etc/ssh/sshd_config.d/99-lan-access.conf
    sudo systemctl restart ssh
    echo "  SSH LAN config removed"
else
    echo "  No LAN config found"
fi

# ── Samba ────────────────────────────────────────────────────
echo "[2/3] Reverting Samba..."
SMB_CONFIG="/etc/samba/smb.conf"
if [ -f "${SMB_CONFIG}.bak.remote-access" ]; then
    sudo cp "${SMB_CONFIG}.bak.remote-access" "$SMB_CONFIG"
    sudo systemctl restart smbd
    echo "  Samba config restored from backup"
else
    echo "  No Samba backup found"
fi

# ── RDP ──────────────────────────────────────────────────────
echo "[3/3] RDP..."
echo "  RDP is managed via GNOME Settings — disable manually if desired"

echo ""
echo "=== Undo Complete ==="
```

- [ ] **Step 3: Make executable**

```bash
chmod +x /home/merm/projects/back-office/monitoring/scripts/setup-remote-access.sh
chmod +x /home/merm/projects/back-office/monitoring/scripts/undo-remote-access.sh
```

- [ ] **Step 4: Commit**

```bash
git add monitoring/scripts/
git commit -m "feat(monitoring): add remote access setup/undo scripts (SSH, Samba, RDP)"
```

---

## Chunk 8: Forgejo LAN Exposure

### Task 21: Expose Forgejo on LAN

**Files:**
- Modify: `ops/forgejo-local/.env`

- [ ] **Step 1: Update Forgejo domain to allow LAN access**

The Forgejo compose uses environment variables for port binding. The ports are already mapped as `${FORGEJO_HTTP_PORT}:3000` which Docker binds to `0.0.0.0` by default. Verify:

```bash
docker port forgejo-local
```

If it shows `0.0.0.0:3300->3000/tcp`, Forgejo is already exposed on LAN. The only change needed is updating the domain for correct URL generation:

Edit `/home/merm/projects/back-office/ops/forgejo-local/.env`:

Change `FORGEJO_DOMAIN=localhost` to `FORGEJO_DOMAIN=borg.local`

- [ ] **Step 2: Restart Forgejo with new domain**

```bash
cd /home/merm/projects/back-office/ops/forgejo-local
docker compose down && docker compose up -d
```

- [ ] **Step 3: Verify LAN access**

From borg itself:

```bash
curl -s http://borg.local:3300/ | head -5
```

Expected: HTML response from Forgejo.

- [ ] **Step 4: Commit**

Note: `.env` is gitignored for Forgejo. Update the example file instead:

Edit `ops/forgejo-local/back-office.env.example` (if it exists) or document the change. Since the `.env` is gitignored, just note the change was made.

---

### Task 22: Add Forgejo Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add forgejo targets to Makefile**

Add after the monitoring section in `/home/merm/projects/back-office/Makefile`:

```makefile
# ── Forgejo (Local Git Forge) ────────────────────────────────

.PHONY: forgejo-up forgejo-down forgejo-mirror

forgejo-up: ## Start Forgejo local git server
	cd ops/forgejo-local && docker compose up -d
	@echo "Forgejo running at http://borg.local:3300"

forgejo-down: ## Stop Forgejo
	cd ops/forgejo-local && docker compose down

forgejo-mirror: ## Mirror a local repo to Forgejo (make forgejo-mirror REPO=selah)
	@test -n "$(REPO)" || (echo "Usage: make forgejo-mirror REPO=<target-name>" && exit 1)
	@REPO_PATH=$$(python3 -c "import yaml; ts=yaml.safe_load(open('config/targets.yaml')); t=[x for x in ts.get('targets',[]) if x['name']=='$(REPO)']; print(t[0]['path'] if t else '')" 2>/dev/null) && \
	test -n "$$REPO_PATH" || (echo "Target '$(REPO)' not found in targets.yaml" && exit 1) && \
	cd "$$REPO_PATH" && \
	(git remote get-url forgejo 2>/dev/null || git remote add forgejo http://borg.local:3300/merm/$(REPO).git) && \
	git push forgejo --all && \
	echo "Pushed $$REPO_PATH to Forgejo"
```

- [ ] **Step 2: Add .PHONY declarations**

```makefile
.PHONY: forgejo-up forgejo-down forgejo-mirror
```

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(monitoring): add Forgejo Makefile targets (up, down, mirror)"
```

---

## Chunk 9: Tests

### Task 23: Collector script tests

**Files:**
- Create: `tests/monitoring/test_collectors.py`

- [ ] **Step 1: Create collector test file**

Create `/home/merm/projects/back-office/tests/monitoring/__init__.py` (empty) and `/home/merm/projects/back-office/tests/monitoring/test_collectors.py`:

```python
"""Tests for monitoring collector scripts.

Each test mocks the underlying tool and verifies:
1. Valid JSON output
2. Correct metric names and structure
3. Graceful degradation (zero-values) when tools are unavailable
"""

import json
import subprocess
import os
import tempfile

COLLECTORS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "monitoring", "vector", "collectors"
)


def run_collector(name: str, env: dict | None = None) -> list[dict]:
    """Run a collector script and return parsed JSON output."""
    script = os.path.join(COLLECTORS_DIR, name)
    result = subprocess.run(
        ["bash", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
    )
    assert result.returncode == 0, f"Script exited {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
    return data


def validate_metric(m: dict):
    """Validate a single metric dict has required fields."""
    assert "time" in m, f"Missing 'time': {m}"
    assert "source" in m, f"Missing 'source': {m}"
    assert "metric" in m, f"Missing 'metric': {m}"
    assert "labels" in m, f"Missing 'labels': {m}"
    assert "value" in m, f"Missing 'value': {m}"
    assert isinstance(m["labels"], dict), f"labels must be dict: {m}"
    assert isinstance(m["value"], (int, float)), f"value must be number: {m}"


class TestGpuMetrics:
    def test_produces_valid_json(self):
        metrics = run_collector("gpu_metrics.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_expected_metrics(self):
        metrics = run_collector("gpu_metrics.sh")
        names = {m["metric"] for m in metrics}
        expected = {"gpu_temp_celsius", "gpu_utilization_percent", "gpu_memory_used_bytes",
                    "gpu_memory_total_bytes", "gpu_memory_free_bytes", "gpu_power_watts"}
        assert expected.issubset(names), f"Missing metrics: {expected - names}"

    def test_graceful_without_nvidia_smi(self):
        """When nvidia-smi is not found, should output empty array."""
        metrics = run_collector("gpu_metrics.sh", env={**os.environ, "NVIDIA_SMI": "/nonexistent"})
        assert metrics == []


class TestSystemSensors:
    def test_produces_valid_json(self):
        metrics = run_collector("system_sensors.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_vmstat_metrics(self):
        metrics = run_collector("system_sensors.sh")
        names = {m["metric"] for m in metrics}
        # vmstat metrics should always be available
        assert "oom_kills_total" in names
        assert "memory_page_faults_major" in names


class TestOllamaMetrics:
    def test_produces_valid_json(self):
        metrics = run_collector("ollama_metrics.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_running_status(self):
        metrics = run_collector("ollama_metrics.sh")
        names = {m["metric"] for m in metrics}
        assert "ollama_running" in names

    def test_graceful_when_ollama_down(self):
        """When Ollama is unreachable, should output ollama_running: 0."""
        metrics = run_collector("ollama_metrics.sh", env={**os.environ, "OLLAMA_HOST": "http://localhost:99999"})
        assert len(metrics) == 1
        assert metrics[0]["metric"] == "ollama_running"
        assert metrics[0]["value"] == 0


class TestClaudeSessions:
    def test_produces_valid_json(self):
        metrics = run_collector("claude_sessions.sh")
        for m in metrics:
            validate_metric(m)

    def test_has_expected_metrics(self):
        metrics = run_collector("claude_sessions.sh")
        names = {m["metric"] for m in metrics}
        assert "claude_active_sessions" in names
        assert "claude_worktrees_active" in names
```

- [ ] **Step 2: Run collector tests**

```bash
cd /home/merm/projects/back-office && python3 -m pytest tests/monitoring/test_collectors.py -v
```

Expected: all tests pass (some GPU tests may be skipped if nvidia-smi is unavailable).

- [ ] **Step 3: Commit**

```bash
git add tests/monitoring/
git commit -m "test(monitoring): add collector script unit tests"
```

---

### Task 24: Smoke test Makefile target

**Files:**
- Create: `monitoring/scripts/smoke-test.sh`
- Modify: `Makefile` — add `monitoring-test` target

- [ ] **Step 1: Create smoke-test.sh**

Create `/home/merm/projects/back-office/monitoring/scripts/smoke-test.sh`:

```bash
#!/bin/bash
# Smoke test for the monitoring stack.
# Starts stack, verifies data flow, tears down.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$COMPOSE_DIR"

cleanup() {
    echo "[cleanup] Stopping stack..."
    docker compose down --timeout 10 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Monitoring Stack Smoke Test ==="

echo "[1/7] Starting stack..."
docker compose up -d

echo "[2/7] Waiting for TimescaleDB..."
for i in $(seq 1 30); do
    if docker exec breakpoint-timescaledb pg_isready -U vector -d monitoring &>/dev/null; then
        echo "  TimescaleDB ready"
        break
    fi
    [ "$i" -eq 30 ] && { echo "FAIL: TimescaleDB not ready"; exit 1; }
    sleep 2
done

echo "[3/7] Waiting for Ingest service..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8087/health &>/dev/null; then
        echo "  Ingest ready"
        break
    fi
    [ "$i" -eq 20 ] && { echo "FAIL: Ingest not ready"; exit 1; }
    sleep 2
done

echo "[4/7] Waiting for Grafana..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3333/api/health &>/dev/null; then
        echo "  Grafana ready"
        break
    fi
    [ "$i" -eq 30 ] && { echo "FAIL: Grafana not ready"; exit 1; }
    sleep 2
done

echo "[5/7] Waiting for Vector..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8686/health &>/dev/null; then
        echo "  Vector ready"
        break
    fi
    [ "$i" -eq 20 ] && { echo "FAIL: Vector not ready"; exit 1; }
    sleep 2
done

echo "[6/7] Waiting for data (30s)..."
sleep 30

METRIC_COUNT=$(docker exec breakpoint-timescaledb psql -U vector -d monitoring -t \
    -c "SELECT count(*) FROM metrics;" 2>/dev/null | tr -d ' ')
echo "  Metrics rows: $METRIC_COUNT"
[ "${METRIC_COUNT:-0}" -gt 0 ] || { echo "FAIL: No metrics in database"; exit 1; }

echo "[7/7] Checking Grafana datasource..."
DS_COUNT=$(curl -sf http://localhost:3333/api/datasources \
    -H "Authorization: Basic $(echo -n admin:$(grep GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2) | base64)" \
    2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
[ "${DS_COUNT:-0}" -gt 0 ] || { echo "FAIL: No datasources in Grafana"; exit 1; }
echo "  Datasources: $DS_COUNT"

echo ""
echo "=== SMOKE TEST PASSED ==="
```

- [ ] **Step 2: Add Makefile target**

Add to the monitoring section of `/home/merm/projects/back-office/Makefile`:

```makefile
monitoring-test: ## Run monitoring stack smoke test
	bash monitoring/scripts/smoke-test.sh
```

- [ ] **Step 3: Make executable and commit**

```bash
chmod +x /home/merm/projects/back-office/monitoring/scripts/smoke-test.sh
git add monitoring/scripts/smoke-test.sh Makefile
git commit -m "test(monitoring): add smoke test for monitoring stack"
```

---

## Chunk 10: Final Verification & Cleanup

### Task 25: End-to-end verification

- [ ] **Step 1: Start the full monitoring stack**

```bash
cd /home/merm/projects/back-office && make monitoring-up
```

- [ ] **Step 2: Verify all services are healthy**

```bash
make monitoring-status
```

Expected: all 4 services report OK.

- [ ] **Step 3: Wait 2 minutes for data accumulation, then verify dashboards**

Open `http://localhost:3333` in browser:
- Host Overview dashboard should show CPU, RAM, disk, network, temperature data
- GPU Monitoring dashboard should show RTX 3080 metrics
- LLM Inference dashboard should show Ollama status (and VRAM ratio if a model is loaded)
- Claude Code Sessions dashboard should show active session count

- [ ] **Step 4: Verify alerts are provisioned**

In Grafana: navigate to Alerting → Alert Rules. Verify 11 rules are loaded.

- [ ] **Step 5: Run setup-remote-access.sh**

```bash
sudo bash /home/merm/projects/back-office/monitoring/scripts/setup-remote-access.sh
```

Follow the prompts to set Samba password. Then copy SSH key from laptop.

- [ ] **Step 6: Verify Forgejo from browser**

Open `http://borg.local:3300` — Forgejo UI should load.

- [ ] **Step 7: Final commit**

```bash
cd /home/merm/projects/back-office
git add -A
git status  # verify nothing sensitive
git commit -m "feat(monitoring): complete local infrastructure monitoring stack

Vector → Ingest → TimescaleDB → Grafana with dashboards for host,
GPU, Ollama LLM inference, and Claude Code sessions. Includes
remote access scripts (SSH, Samba, RDP) and Forgejo LAN exposure."
```

---

## Task Dependency Graph

```
Task 1 (env)
  ↓
Task 2 (schema) → Task 3 (ingest) → Task 4 (compose) → Task 5 (datasource)
  ↓                                                          ↓
Task 6 (smoke test foundation)                              |
  ↓                                                          |
Task 7-10 (collectors, parallel) ─────────────────────────→  |
  ↓                                                          |
Task 11 (vector config) → Task 12 (e2e data flow)           |
                              ↓                              |
                    Task 13-16 (dashboards, parallel) ←──────┘
                              ↓
                    Task 17 (dashboards.yml)
                              ↓
                    Task 18 (alerts)
                              ↓
                    Task 19 (makefile)
                              ↓
              Task 20 (remote access) ─── Task 21-22 (forgejo, parallel)
                              ↓
                    Task 23-24 (tests)
                              ↓
                    Task 25 (verification)
```

**Parallelizable groups:**
- Tasks 7, 8, 9, 10 (collector scripts — independent)
- Tasks 13, 14, 15, 16 (dashboards — independent)
- Tasks 20, 21 (remote access + forgejo — independent)
- Tasks 23, 24 (unit tests + smoke test — independent)
