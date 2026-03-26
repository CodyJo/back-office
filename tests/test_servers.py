"""Tests for backoffice.server — local dashboard dev server."""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from backoffice.server import (
    ALL_DEPTS,
    DEPT_SCRIPTS,
    _load_manual_items,
    _manual_items_paths,
    _save_manual_items,
    create_handler,
    run_agent,
    running_jobs,
    running_lock,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    """Return a temp tree that mirrors the real project layout."""
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "agents").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "backoffice.yaml").write_text("targets:\n")
    return tmp_path


@pytest.fixture()
def live_server(tmp_root: Path):
    """Spin up a real HTTPServer bound to a random port; yield (host, port)."""
    import http.server

    handler_cls = create_handler(
        root=tmp_root,
        target_repo=str(tmp_root / "fake-repo"),
        allowed_origins={"http://localhost:0"},  # will be replaced below
    )

    # Bind to port 0 so the OS picks a free port
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]

    # Fix up allowed origins to match the actual port
    actual_origin = f"http://localhost:{port}"
    server.RequestHandlerClass._allowed_origins = {
        actual_origin,
        f"http://127.0.0.1:{port}",
    }

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "127.0.0.1", port
    server.shutdown()


@pytest.fixture()
def _clean_running_jobs():
    """Ensure running_jobs is empty before and after each test."""
    with running_lock:
        running_jobs.clear()
    yield
    with running_lock:
        running_jobs.clear()


# ---------------------------------------------------------------------------
# Unit: manual items helpers
# ---------------------------------------------------------------------------


class TestManualItemsHelpers:
    def test_load_returns_empty_when_file_missing(self, tmp_root: Path) -> None:
        items = _load_manual_items(root=tmp_root)
        assert items == []

    def test_load_returns_empty_on_invalid_json(self, tmp_root: Path) -> None:
        results_path, _ = _manual_items_paths(tmp_root)
        results_path.write_text("not json")
        items = _load_manual_items(root=tmp_root)
        assert items == []

    def test_round_trip(self, tmp_root: Path) -> None:
        _save_manual_items([{"id": "MAN-001", "title": "hello"}], root=tmp_root)
        loaded = _load_manual_items(root=tmp_root)
        assert len(loaded) == 1
        assert loaded[0]["title"] == "hello"

    def test_save_writes_to_both_locations(self, tmp_root: Path) -> None:
        _save_manual_items([{"id": "MAN-001", "title": "test"}], root=tmp_root)
        results_path, dashboard_path = _manual_items_paths(tmp_root)
        assert results_path.exists()
        assert dashboard_path.exists()

    def test_save_payload_has_generated_at(self, tmp_root: Path) -> None:
        _save_manual_items([], root=tmp_root)
        results_path, _ = _manual_items_paths(tmp_root)
        data = json.loads(results_path.read_text())
        assert "generated_at" in data
        assert data["generated_at"].endswith("Z")

    def test_load_handles_dict_wrapper(self, tmp_root: Path) -> None:
        """Handles files that store {generated_at, items: [...]}."""
        results_path, _ = _manual_items_paths(tmp_root)
        payload = {"generated_at": "2026-01-01T00:00:00Z", "items": [{"id": "MAN-001", "title": "x"}]}
        results_path.write_text(json.dumps(payload))
        items = _load_manual_items(root=tmp_root)
        assert len(items) == 1

    def test_load_filters_non_dict_entries(self, tmp_root: Path) -> None:
        results_path, _ = _manual_items_paths(tmp_root)
        results_path.write_text(json.dumps(["bad", {"id": "ok"}]))
        items = _load_manual_items(root=tmp_root)
        assert items == [{"id": "ok"}]

    def test_id_increments(self, tmp_root: Path) -> None:
        _save_manual_items(
            [{"id": "MAN-001"}, {"id": "MAN-002"}], root=tmp_root
        )
        items = _load_manual_items(root=tmp_root)
        # Simulate what the handler does
        new_id = f"MAN-{len(items) + 1:03d}"
        assert new_id == "MAN-003"


# ---------------------------------------------------------------------------
# Unit: run_agent guard
# ---------------------------------------------------------------------------


class TestRunAgent:
    def test_returns_false_when_already_running(
        self, tmp_root: Path, _clean_running_jobs
    ) -> None:
        with running_lock:
            running_jobs.add("qa")
        result = run_agent("qa", "/fake", root=tmp_root)
        assert result is False

    def test_adds_dept_to_running_jobs(
        self, tmp_root: Path, _clean_running_jobs, monkeypatch
    ) -> None:
        """dept is added to running_jobs and the agent thread is started."""
        started_events: list[str] = []

        def fake_run(cmd, cwd=None):
            started_events.append(cmd[1])  # script path

        monkeypatch.setattr("subprocess.run", fake_run)

        # We need an agent script to exist so the handler logic passes
        result = run_agent("qa", "/fake", root=tmp_root)
        assert result is True
        # running_jobs will be cleared by _run() eventually, but we can't
        # guarantee timing here — just confirm it started successfully.


# ---------------------------------------------------------------------------
# Integration: HTTP server
# ---------------------------------------------------------------------------


class TestServerStartsAndServesFiles:
    def test_serves_dashboard_index(self, live_server, tmp_root: Path) -> None:
        """GET / should return a file from the dashboard directory."""
        # Create a minimal index file in the dashboard dir
        (tmp_root / "dashboard" / "index.html").write_text(
            "<html><body>hello</body></html>"
        )
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/index.html")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode()
        assert "hello" in body

    def test_missing_file_returns_404(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/nonexistent-xyz.html")
        resp = conn.getresponse()
        assert resp.status == 404


class TestCORSHeaders:
    def test_options_preflight_allowed_origin(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "OPTIONS",
            "/api/run-scan",
            headers={
                "Origin": f"http://localhost:{port}",
                "Access-Control-Request-Method": "POST",
            },
        )
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200
        acao = resp.getheader("Access-Control-Allow-Origin")
        assert acao == f"http://localhost:{port}"

    def test_options_preflight_disallowed_origin(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "OPTIONS",
            "/api/run-scan",
            headers={"Origin": "http://evil.example.com"},
        )
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 403

    def test_cors_header_on_json_response(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        body = json.dumps({"department": "qa"}).encode()
        conn.request(
            "POST",
            "/api/run-scan",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Origin": f"http://localhost:{port}",
            },
        )
        resp = conn.getresponse()
        resp.read()
        acao = resp.getheader("Access-Control-Allow-Origin")
        assert acao == f"http://localhost:{port}"

    def test_no_cors_header_when_no_origin(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        body = json.dumps({"department": "qa"}).encode()
        conn.request(
            "POST",
            "/api/run-scan",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        resp.read()
        acao = resp.getheader("Access-Control-Allow-Origin")
        assert acao is None


class TestManualItemEndpoint:
    def _post_manual_item(self, host, port, payload: dict, origin: str | None = None):
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if origin:
            headers["Origin"] = origin
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/manual-item", body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_create_item_returns_200(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {"title": "Fix the flicker"},
            origin=f"http://localhost:{port}",
        )
        assert status == 200
        assert data["ok"] is True

    def test_item_has_expected_fields(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {
                "title": "My item",
                "repo": "etheos",
                "department": "qa",
                "severity": "high",
                "category": "performance",
                "bucket": "sprint-1",
                "notes": "some notes",
                "product_key": "PKG-42",
            },
            origin=f"http://localhost:{port}",
        )
        assert status == 200
        items = data["items"]
        assert len(items) == 1
        item = items[0]
        assert item["title"] == "My item"
        assert item["repo"] == "etheos"
        assert item["department"] == "qa"
        assert item["severity"] == "high"
        assert item["bucket"] == "sprint-1"
        assert item["product_key"] == "PKG-42"
        assert item["id"] == "MAN-001"
        assert "created_at" in item

    def test_missing_title_returns_400(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {"notes": "no title here"},
            origin=f"http://localhost:{port}",
        )
        assert status == 400
        assert "title" in data["error"]

    def test_categories_string_split(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {"title": "Cat test", "categories": "ux, perf, a11y"},
            origin=f"http://localhost:{port}",
        )
        assert status == 200
        assert data["items"][0]["categories"] == ["ux", "perf", "a11y"]

    def test_categories_list_passthrough(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {"title": "Cat list", "categories": ["ux", "perf"]},
            origin=f"http://localhost:{port}",
        )
        assert status == 200
        assert data["items"][0]["categories"] == ["ux", "perf"]

    def test_severity_defaults_to_medium(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_manual_item(
            host, port,
            {"title": "Default sev"},
            origin=f"http://localhost:{port}",
        )
        assert status == 200
        assert data["items"][0]["severity"] == "medium"

    def test_items_persist_across_requests(self, live_server) -> None:
        host, port = live_server
        origin = f"http://localhost:{port}"
        self._post_manual_item(host, port, {"title": "First"}, origin=origin)
        status, data = self._post_manual_item(
            host, port, {"title": "Second"}, origin=origin
        )
        assert status == 200
        assert len(data["items"]) == 2
        assert data["items"][0]["id"] == "MAN-001"
        assert data["items"][1]["id"] == "MAN-002"

    def test_blocked_origin_returns_403(self, live_server) -> None:
        host, port = live_server
        body = json.dumps({"title": "x"}).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Origin": "http://evil.example.com",
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/manual-item", body=body, headers=headers)
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 403

    def test_files_mirrored_to_dashboard_dir(self, live_server, tmp_root: Path) -> None:
        host, port = live_server
        origin = f"http://localhost:{port}"
        self._post_manual_item(host, port, {"title": "Mirror me"}, origin=origin)
        dashboard_file = tmp_root / "dashboard" / "manual-items.json"
        assert dashboard_file.exists()
        data = json.loads(dashboard_file.read_text())
        assert len(data["items"]) == 1


class TestRunScanEndpoint:
    def _post_run_scan(self, host, port, payload: dict):
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-scan", body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_unknown_department_returns_400(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_run_scan(host, port, {"department": "unknown-dept"})
        assert status == 400
        assert "Unknown department" in data["error"]
        assert "valid" in data

    def test_valid_departments_listed(self, live_server) -> None:
        host, port = live_server
        status, data = self._post_run_scan(host, port, {"department": "bogus"})
        assert status == 400
        for dept in ALL_DEPTS:
            assert dept in data["valid"]


class TestRunAllEndpoint:
    def _post_run_all(self, host, port, payload: dict | None = None):
        body = json.dumps(payload or {}).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-all", body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_returns_error_when_jobs_already_running(
        self, live_server, _clean_running_jobs
    ) -> None:
        host, port = live_server
        with running_lock:
            running_jobs.add("qa")
        status, data = self._post_run_all(host, port)
        assert status == 409
        assert "qa" in data["running"]

    def test_unknown_post_path_returns_404(self, live_server) -> None:
        host, port = live_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/does-not-exist")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404


class TestApprovalQueueEndpoints:
    def _post(self, host, port, path, payload):
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_queue_finding_creates_pending_approval_task(self, live_server, tmp_root: Path) -> None:
        host, port = live_server
        status, data = self._post(host, port, "/api/tasks/queue-finding", {
            "finding": {
                "repo": "fuel",
                "title": "Fix CloudFront invalidation guardrails",
                "id": "QA-7",
                "department": "qa",
                "severity": "high",
                "file": "terraform/main.tf",
            }
        })
        assert status == 200
        assert data["task"]["status"] == "pending_approval"
        queue_file = tmp_root / "results" / "task-queue.json"
        assert queue_file.exists()
        queue_payload = json.loads(queue_file.read_text())
        assert queue_payload["summary"]["pending_approval"] == 1

    def test_queue_finding_duplicate_returns_conflict(self, live_server) -> None:
        host, port = live_server
        payload = {
            "finding": {
                "repo": "fuel",
                "title": "Fix duplicate queue item",
                "id": "QA-8",
                "department": "qa",
                "severity": "medium",
                "file": "src/app.ts",
            }
        }
        self._post(host, port, "/api/tasks/queue-finding", payload)
        status, data = self._post(host, port, "/api/tasks/queue-finding", payload)
        assert status == 409
        assert data["created"] is False

    def test_approve_task_moves_it_to_ready(self, live_server) -> None:
        host, port = live_server
        _, created = self._post(host, port, "/api/tasks/queue-finding", {
            "finding": {
                "repo": "selah",
                "title": "Review approval flow",
                "id": "QA-9",
                "department": "qa",
                "severity": "high",
                "file": "src/page.tsx",
            }
        })
        task_id = created["task"]["id"]
        status, data = self._post(host, port, "/api/tasks/approve", {"id": task_id, "by": "owner"})
        assert status == 200
        assert data["task"]["status"] == "ready"

    def test_product_suggestion_enters_queue(self, live_server) -> None:
        host, port = live_server
        status, data = self._post(host, port, "/api/ops/product/suggest", {
            "name": "puppet-observability-demo",
            "description": "Human-in-the-loop repo operations pilot",
            "source": "local",
            "local_path": "/tmp/puppet-demo",
        })
        assert status == 200
        assert data["task"]["task_type"] == "product_suggestion"
        assert data["task"]["status"] == "pending_approval"


class TestLocalSafetyGuards:
    def _post(self, host, port, path, payload):
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_overnight_start_disabled_by_default(self, live_server, monkeypatch) -> None:
        monkeypatch.delenv("BACK_OFFICE_ENABLE_UNATTENDED", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("CODEBUILD_BUILD_ID", raising=False)
        host, port = live_server
        status, data = self._post(host, port, "/api/ops/overnight/start", {"interval": 60})
        assert status == 403
        assert "disabled by default" in data["error"]


class TestRunRegressionEndpoint:
    def _post_run_regression(self, host, port, origin: str | None = None):
        headers: dict[str, str] = {"Content-Length": "0"}
        if origin:
            headers["Origin"] = origin
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-regression", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_missing_runner_returns_500(self, live_server) -> None:
        # regression-runner.py does not exist in tmp_root
        host, port = live_server
        status, data = self._post_run_regression(
            host, port, origin=f"http://localhost:{port}"
        )
        assert status == 500
        assert "not found" in data["error"]

    def test_blocked_origin_returns_403(self, live_server) -> None:
        host, port = live_server
        headers = {
            "Content-Length": "0",
            "Origin": "http://evil.example.com",
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-regression", headers=headers)
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 403


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_dept_scripts_keys_match_all_depts(self) -> None:
        assert set(DEPT_SCRIPTS.keys()) == set(ALL_DEPTS)

    def test_expected_departments_present(self) -> None:
        for dept in ("qa", "seo", "ada", "compliance", "monetization", "product"):
            assert dept in DEPT_SCRIPTS


# ===========================================================================
# backoffice.api_server tests
# ===========================================================================

import http.server as _http_server  # noqa: E402 (needed by api_server fixtures)

from backoffice.api_server import (  # noqa: E402
    ALL_DEPTS as API_ALL_DEPTS,
    DEPT_SCRIPTS as API_DEPT_SCRIPTS,
    APIHandler,
    create_api_handler,
    resolve_target,
    running_jobs as api_running_jobs,
    running_lock as api_running_lock,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_tmp_root(tmp_path: Path) -> Path:
    """Return a temp tree that mirrors the real project layout."""
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "agents").mkdir()
    (tmp_path / "scripts").mkdir()
    return tmp_path


@pytest.fixture()
def _clean_api_running_jobs():
    """Ensure api_running_jobs is empty before and after each test."""
    with api_running_lock:
        api_running_jobs.clear()
    yield
    with api_running_lock:
        api_running_jobs.clear()


def _make_api_server(tmp_root: Path, api_key: str = "", origins: list[str] | None = None):
    """Spin up a real HTTPServer for the API server; return (server, host, port)."""
    if origins is None:
        origins = []  # will be patched after binding

    handler_cls = create_api_handler(
        root=tmp_root,
        api_key=api_key,
        allowed_origins=origins,
        targets={},
    )
    server = _http_server.HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]

    # Patch origins to the real port if caller left them empty
    if not origins:
        server.RequestHandlerClass._allowed_origins = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]

    return server, "127.0.0.1", port


@pytest.fixture()
def live_api_server(api_tmp_root: Path):
    """Spin up a real API HTTPServer on a random port; yield (host, port)."""
    server, host, port = _make_api_server(api_tmp_root)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield host, port
    server.shutdown()


@pytest.fixture()
def live_api_server_with_key(api_tmp_root: Path):
    """Spin up a real API server requiring X-API-Key; yield (host, port, key)."""
    secret = "test-secret-key-42"
    server, host, port = _make_api_server(api_tmp_root, api_key=secret)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield host, port, secret
    server.shutdown()


# ---------------------------------------------------------------------------
# Unit: resolve_target
# ---------------------------------------------------------------------------


class TestResolveTarget:
    def test_direct_path_when_directory_exists(self, tmp_path: Path) -> None:
        result = resolve_target(str(tmp_path), targets={})
        assert result == str(tmp_path)

    def test_named_target_lookup(self) -> None:
        class _T:
            path = "/some/repo"

        result = resolve_target("mysite", targets={"mysite": _T()})
        assert result == "/some/repo"

    def test_first_target_fallback(self) -> None:
        class _T:
            path = "/fallback/repo"

        result = resolve_target(None, targets={"only": _T()})
        assert result == "/fallback/repo"

    def test_returns_none_when_no_targets(self) -> None:
        result = resolve_target(None, targets={})
        assert result is None

    def test_unknown_hint_with_no_targets_returns_none(self) -> None:
        result = resolve_target("bogus-site", targets={})
        assert result is None

    def test_unknown_hint_falls_back_to_first_target(self) -> None:
        class _T:
            path = "/first/repo"

        result = resolve_target("unknown", targets={"first": _T()})
        assert result == "/first/repo"


# ---------------------------------------------------------------------------
# Integration: health endpoint
# ---------------------------------------------------------------------------


class TestAPIHealthEndpoint:
    def test_get_health_returns_200(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        body = json.loads(resp.read().decode())
        assert resp.status == 200
        assert body["status"] == "ok"

    def test_health_does_not_require_auth(self, live_api_server_with_key) -> None:
        host, port, _key = live_api_server_with_key
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        assert resp.status == 200

    def test_health_content_type_is_json(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        resp.read()
        assert "application/json" in (resp.getheader("Content-Type") or "")


# ---------------------------------------------------------------------------
# Integration: auth enforcement
# ---------------------------------------------------------------------------


class TestAPIAuthEnforcement:
    def _post(self, host: str, port: int, path: str, body: dict,
              api_key: str | None = None) -> tuple[int, dict]:
        encoded = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        if api_key is not None:
            headers["X-API-Key"] = api_key
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", path, body=encoded, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_post_without_key_returns_401(self, live_api_server_with_key) -> None:
        host, port, _key = live_api_server_with_key
        status, data = self._post(host, port, "/api/run-scan", {"department": "qa"})
        assert status == 401
        assert "Invalid API key" in data["error"]

    def test_post_with_wrong_key_returns_401(self, live_api_server_with_key) -> None:
        host, port, _key = live_api_server_with_key
        status, data = self._post(
            host, port, "/api/run-scan", {"department": "qa"}, api_key="wrong-key"
        )
        assert status == 401

    def test_post_with_correct_key_passes_auth(self, live_api_server_with_key) -> None:
        host, port, key = live_api_server_with_key
        # No target configured — but auth should pass (error is 400, not 401)
        status, data = self._post(
            host, port, "/api/run-scan", {"department": "qa"}, api_key=key
        )
        assert status != 401

    def test_no_key_configured_allows_requests(self, live_api_server) -> None:
        """When api_key is empty, all POST requests pass auth."""
        host, port = live_api_server
        encoded = json.dumps({"department": "qa"}).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-scan", body=encoded, headers=headers)
        resp = conn.getresponse()
        resp.read()
        # Not a 401 — auth is disabled
        assert resp.status != 401

    def test_timing_safe_comparison_used(self) -> None:
        """_check_auth uses hmac.compare_digest (timing-safe)."""
        import inspect
        src = inspect.getsource(APIHandler._check_auth)
        assert "compare_digest" in src


# ---------------------------------------------------------------------------
# Integration: target resolution via HTTP
# ---------------------------------------------------------------------------


class TestAPITargetResolution:
    def _post_run_scan(self, host: str, port: int, payload: dict) -> tuple[int, dict]:
        encoded = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/run-scan", body=encoded, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        return resp.status, data

    def test_no_target_returns_400(self, live_api_server) -> None:
        host, port = live_api_server
        status, data = self._post_run_scan(host, port, {"department": "qa"})
        assert status == 400
        assert "target" in data["error"].lower() or "No target" in data["error"]

    def test_unknown_department_returns_400(self, live_api_server) -> None:
        host, port = live_api_server
        status, data = self._post_run_scan(host, port, {"department": "bogus"})
        assert status == 400
        assert "Unknown department" in data["error"]
        assert "valid" in data

    def test_valid_departments_listed_in_error(self, live_api_server) -> None:
        host, port = live_api_server
        status, data = self._post_run_scan(host, port, {"department": "bogus"})
        assert status == 400
        for dept in API_ALL_DEPTS:
            assert dept in data["valid"]

    def test_target_path_accepted_directly(self, live_api_server,
                                           api_tmp_root: Path) -> None:
        """Passing an existing directory path as target is accepted."""
        host, port = live_api_server
        # Target path exists but no agent script → agent start fails gracefully
        status, data = self._post_run_scan(host, port, {
            "department": "qa",
            "target": str(api_tmp_root),
        })
        # May be 200 (started) or 409 (already_running) but NOT 400 (no target)
        assert status in (200, 409)
        assert data.get("target") == str(api_tmp_root)


# ---------------------------------------------------------------------------
# Integration: CORS headers
# ---------------------------------------------------------------------------


class TestAPICORSHeaders:
    def test_options_preflight_returns_200(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "OPTIONS",
            "/api/run-scan",
            headers={
                "Origin": f"http://localhost:{port}",
                "Access-Control-Request-Method": "POST",
            },
        )
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200

    def test_allowed_origin_reflected_in_cors_header(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "OPTIONS",
            "/api/health",
            headers={"Origin": f"http://localhost:{port}"},
        )
        resp = conn.getresponse()
        resp.read()
        acao = resp.getheader("Access-Control-Allow-Origin")
        assert acao == f"http://localhost:{port}"

    def test_cors_methods_header_present(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "OPTIONS",
            "/api/health",
            headers={"Origin": f"http://localhost:{port}"},
        )
        resp = conn.getresponse()
        resp.read()
        acam = resp.getheader("Access-Control-Allow-Methods")
        assert acam is not None
        assert "POST" in acam

    def test_cors_headers_present_on_json_response(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/api/health",
            headers={"Origin": f"http://localhost:{port}"},
        )
        resp = conn.getresponse()
        resp.read()
        acao = resp.getheader("Access-Control-Allow-Origin")
        assert acao == f"http://localhost:{port}"

    def test_wildcard_origin_passes_any_origin(self, api_tmp_root: Path) -> None:
        handler_cls = create_api_handler(
            root=api_tmp_root,
            api_key="",
            allowed_origins=["*"],
            targets={},
        )
        server = _http_server.HTTPServer(("127.0.0.1", 0), handler_cls)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "OPTIONS",
                "/api/health",
                headers={"Origin": "http://any.example.com"},
            )
            resp = conn.getresponse()
            resp.read()
            acao = resp.getheader("Access-Control-Allow-Origin")
            assert acao == "http://any.example.com"
        finally:
            server.shutdown()

    def test_status_endpoint_returns_200(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        assert resp.status == 200
        assert "available_departments" in data
        assert "running" in data

    def test_unknown_get_path_returns_404(self, live_api_server) -> None:
        host, port = live_api_server
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/does-not-exist")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Unit: API server module constants
# ---------------------------------------------------------------------------


class TestAPIModuleConstants:
    def test_dept_scripts_keys_match_all_depts(self) -> None:
        assert set(API_DEPT_SCRIPTS.keys()) == set(API_ALL_DEPTS)

    def test_expected_departments_present(self) -> None:
        for dept in ("qa", "seo", "ada", "compliance", "monetization", "product"):
            assert dept in API_DEPT_SCRIPTS
