"""Auth contract for the API server.

Production-bound traffic cannot trigger scans without a valid X-API-Key,
and the server refuses to start in an insecure configuration.
"""
from __future__ import annotations

import http.server
import json
import threading
import urllib.error
import urllib.request

import pytest

from backoffice.api_server import create_api_handler


@pytest.fixture
def server(tmp_path):
    handler_cls = create_api_handler(
        root=tmp_path,
        api_key="test-key-abc",
        allowed_origins=["*"],
        targets={},
    )
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _post(url, body, headers=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_post_without_key_is_rejected(server):
    port = server.server_address[1]
    code, body = _post(f"http://127.0.0.1:{port}/api/run-scan", {"department": "qa"})
    assert code == 401
    assert "error" in body


def test_post_with_wrong_key_is_rejected(server):
    port = server.server_address[1]
    code, _ = _post(
        f"http://127.0.0.1:{port}/api/run-scan",
        {"department": "qa"},
        headers={"X-API-Key": "nope"},
    )
    assert code == 401


def test_get_jobs_does_not_require_key(server):
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs") as resp:
        assert resp.status == 200


def test_main_refuses_public_bind_without_key():
    import dataclasses

    from backoffice.api_server import main
    from backoffice.config import ApiConfig, Config

    base = Config()
    cfg = dataclasses.replace(base, api=ApiConfig(port=0, api_key="", allowed_origins=[]))

    code = main(argv=["--bind", "0.0.0.0"], config=cfg)
    assert code == 1
