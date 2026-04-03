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
