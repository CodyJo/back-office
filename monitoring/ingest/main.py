"""Thin ingest service: receives JSON batches from Vector's http sink, batch-inserts into TimescaleDB.

Vector may send either a JSON array batch or newline-delimited JSON.
This service normalizes either form and batch-inserts into TimescaleDB using async psycopg.
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


def parse_events(body: bytes) -> list[dict]:
    """Parse Vector payloads as either a JSON array or NDJSON objects."""
    if not body.strip():
        return []

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        decoded = None
    else:
        if isinstance(decoded, list):
            return decoded
        if isinstance(decoded, dict):
            return [decoded]

    events = []
    for line in body.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, list):
            events.extend(parsed)
        else:
            events.append(parsed)
    return events


def metric_rows(events: list[dict]) -> list[tuple]:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if "source" not in event and "name" in event:
            value = 0.0
            if isinstance(event.get("gauge"), dict) and "value" in event["gauge"]:
                value = event["gauge"]["value"]
            elif isinstance(event.get("counter"), dict) and "value" in event["counter"]:
                value = event["counter"]["value"]
            elif isinstance(event.get("distribution"), dict) and "avg" in event["distribution"]:
                value = event["distribution"]["avg"]
            if value is None:
                logger.warning("Skipping null-valued raw metric event: %s", event)
                continue

            rows.append(
                (
                    event.get("timestamp") or event.get("time"),
                    event.get("host"),
                    "host",
                    event["name"],
                    json.dumps(event.get("tags", {})),
                    value,
                )
            )
            continue
        if "source" not in event or "metric" not in event or "value" not in event:
            logger.warning("Skipping malformed metric event: %s", event)
            continue
        if event["value"] is None:
            logger.warning("Skipping null-valued metric event: %s", event)
            continue
        rows.append(
            (
                event.get("time"),
                event.get("host"),
                event["source"],
                event["metric"],
                json.dumps(event.get("labels", {})),
                event["value"],
            )
        )
    return rows


def log_rows(events: list[dict]) -> list[tuple]:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if "source" not in event or "message" not in event:
            logger.warning("Skipping malformed log event: %s", event)
            continue
        rows.append(
            (
                event.get("time"),
                event.get("host"),
                event["source"],
                event.get("service"),
                event.get("level"),
                event["message"],
                json.dumps(event.get("metadata", {})),
            )
        )
    return rows


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
    events = parse_events(body)

    if not events:
        return Response(status_code=204)

    rows = metric_rows(events)

    if not rows:
        return Response(status_code=204)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO metrics (time, host, source, metric, labels, value)
                VALUES (COALESCE(%s, now()), COALESCE(%s, 'borg'), %s, %s, %s::jsonb, %s)
                """,
                rows,
            )
        await conn.commit()

    return {"accepted": len(rows)}


@app.post("/ingest/logs")
async def ingest_logs(request: Request):
    """Accept NDJSON log events from Vector's http sink."""
    body = await request.body()
    events = parse_events(body)

    if not events:
        return Response(status_code=204)

    rows = log_rows(events)

    if not rows:
        return Response(status_code=204)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO logs (time, host, source, service, level, message, metadata)
                VALUES (COALESCE(%s, now()), COALESCE(%s, 'borg'), %s, %s, %s, %s, %s::jsonb)
                """,
                rows,
            )
        await conn.commit()

    return {"accepted": len(rows)}


@app.get("/health")
async def health():
    """Health check — verifies DB connectivity."""
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return Response(status_code=503, content=str(e))
