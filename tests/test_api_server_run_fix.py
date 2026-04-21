"""/api/run-fix launches agents/fix-bugs.sh for a configured target."""
from __future__ import annotations

import http.server
import json
import threading
import urllib.error
import urllib.request

import pytest

import backoffice.api_server as api


class _FakeTarget:
    def __init__(self, path):
        self.path = path


@pytest.fixture
def server(tmp_path, monkeypatch):
    calls = []

    def fake_run_fix_agent(target, *, preview=False, root=None):
        calls.append([target, str(preview)])
        return True

    monkeypatch.setattr(api, "run_fix_agent", fake_run_fix_agent)

    handler_cls = api.create_api_handler(
        root=tmp_path,
        api_key="k",
        allowed_origins=["*"],
        targets={"myrepo": _FakeTarget("/tmp/myrepo")},
    )
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, calls
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
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


def test_run_fix_happy_path(server):
    srv, calls = server
    port = srv.server_address[1]
    code, body = _post(
        f"http://127.0.0.1:{port}/api/run-fix",
        {"target": "myrepo"},
        headers={"X-API-Key": "k"},
    )
    assert code == 200
    assert body["status"] == "started"
    assert body["target"] == "/tmp/myrepo"
    assert calls == [["/tmp/myrepo", "False"]]


def test_run_fix_preview_flag_is_forwarded(server):
    srv, calls = server
    port = srv.server_address[1]
    code, _ = _post(
        f"http://127.0.0.1:{port}/api/run-fix",
        {"target": "myrepo", "preview": True},
        headers={"X-API-Key": "k"},
    )
    assert code == 200
    assert calls == [["/tmp/myrepo", "True"]]


def test_run_fix_unknown_target(server):
    srv, _ = server
    port = srv.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/run-fix",
        data=json.dumps({"target": "ghost"}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": "k"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
