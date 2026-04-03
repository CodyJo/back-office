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
