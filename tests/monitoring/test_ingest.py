import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import httpx


INGEST_PATH = (
    Path(__file__).resolve().parents[2] / "monitoring" / "ingest" / "main.py"
)


def load_ingest_module():
    fake_psycopg_pool = types.ModuleType("psycopg_pool")

    class AsyncConnectionPool:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    fake_psycopg_pool.AsyncConnectionPool = AsyncConnectionPool
    sys.modules["psycopg_pool"] = fake_psycopg_pool

    spec = importlib.util.spec_from_file_location("monitoring_ingest_main", INGEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self):
        self.calls = []

    async def executemany(self, query, events):
        self.calls.append((query, events))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.executed = []
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    async def execute(self, query):
        self.executed.append(query)

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection=None, error=None):
        self.connection_obj = connection or FakeConnection()
        self.error = error

    def connection(self):
        if self.error is not None:
            raise self.error
        return self.connection_obj


def test_parse_events_handles_json_array():
    module = load_ingest_module()

    events = module.parse_events(
        b'[{"source":"host","metric":"cpu","value":1},{"source":"host","metric":"ram","value":2}]'
    )

    assert events == [
        {"source": "host", "metric": "cpu", "value": 1},
        {"source": "host", "metric": "ram", "value": 2},
    ]


def test_parse_events_handles_blank_lines():
    module = load_ingest_module()

    events = module.parse_events(
        b'{"source":"host","metric":"cpu","value":1}\n\n{"source":"host","metric":"ram","value":2}\n'
    )

    assert events == [
        {"source": "host", "metric": "cpu", "value": 1},
        {"source": "host", "metric": "ram", "value": 2},
    ]


def test_health_uses_async_pool_connection():
    module = load_ingest_module()
    fake_conn = FakeConnection()
    module.pool = FakePool(connection=fake_conn)

    async def run():
        transport = httpx.ASGITransport(app=module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert fake_conn.executed == ["SELECT 1"]

    asyncio.run(run())


def test_ingest_metrics_inserts_batch_and_commits():
    module = load_ingest_module()
    fake_conn = FakeConnection()
    module.pool = FakePool(connection=fake_conn)

    async def run():
        transport = httpx.ASGITransport(app=module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/ingest/metrics",
                content=(
                    '{"time":"2026-04-03T00:00:00Z","source":"host","metric":"cpu","labels":{},"value":1}\n'
                    '{"time":"2026-04-03T00:00:01Z","source":"host","metric":"ram","labels":{},"value":2}\n'
                ),
            )

        assert response.status_code == 200
        assert response.json() == {"accepted": 2}
        assert len(fake_conn.cursor_obj.calls) == 1
        _, rows = fake_conn.cursor_obj.calls[0]
        assert [row[3] for row in rows] == ["cpu", "ram"]
        assert fake_conn.committed is True

    asyncio.run(run())


def test_metric_rows_skips_malformed_events():
    module = load_ingest_module()

    rows = module.metric_rows(
        [
            {"source": "host", "metric": "cpu", "value": 1, "labels": {}},
            {"metric": "ram", "value": 2},
            "bad-event",
        ]
    )

    assert len(rows) == 1
    assert rows[0][2:4] == ("host", "cpu")


def test_metric_rows_normalizes_raw_vector_host_metrics():
    module = load_ingest_module()

    rows = module.metric_rows(
        [
            {
                "name": "memory_total_bytes",
                "gauge": {"value": 123.0},
                "tags": {"device": "mem"},
                "timestamp": "2026-04-03T00:00:00Z",
            }
        ]
    )

    assert len(rows) == 1
    assert rows[0][2] == "host"
    assert rows[0][3] == "memory_total_bytes"
    assert rows[0][5] == 123.0
