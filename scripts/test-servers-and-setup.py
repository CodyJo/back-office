#!/usr/bin/env python3
"""Regression tests for the API server, dashboard server, and setup helpers."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import types
from pathlib import Path
from unittest import mock

import yaml


def check(name, condition, detail=""):
    if condition:
        return True
    message = f"FAIL: {name}"
    if detail:
        message += f" ({detail})"
    raise AssertionError(message)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def make_handler(handler_cls, path="/", body=None, headers=None):
    instance = handler_cls.__new__(handler_cls)
    payload = b""
    if body is not None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    instance.path = path
    instance.headers = {"Content-Length": str(len(payload)), **(headers or {})}
    instance.rfile = io.BytesIO(payload)
    instance.wfile = io.BytesIO()
    instance.sent_headers = []
    instance.response_code = None
    instance.error_response = None

    def send_response(self, code, message=None):
        self.response_code = code

    def send_header(self, key, value):
        self.sent_headers.append((key, value))

    def end_headers(self):
        self.headers_ended = True

    def send_error(self, code, message=None):
        self.error_response = (code, message)

    instance.send_response = types.MethodType(send_response, instance)
    instance.send_header = types.MethodType(send_header, instance)
    instance.end_headers = types.MethodType(end_headers, instance)
    instance.send_error = types.MethodType(send_error, instance)
    return instance


def read_json_response(handler):
    return json.loads(handler.wfile.getvalue().decode())


def run_api_server_tests(repo_root: Path) -> None:
    module = load_module("api_server", repo_root / "scripts" / "api-server.py")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        config_path = tmpdir / "api-config.yaml"
        target_repo = tmpdir / "bible-app"
        target_repo.mkdir()
        config_path.write_text(
            yaml.safe_dump(
                {
                    "port": 9001,
                    "api_key": "secret",
                    "allowed_origins": ["https://admin.codyjo.com"],
                    "targets": {"bible-app": str(target_repo)},
                },
                sort_keys=False,
            )
        )

        original_config = dict(module.CONFIG)
        module.CONFIG = {"port": 8070, "api_key": "", "allowed_origins": [], "targets": {}}
        module.load_config(str(config_path))
        check("api_load_config_port", module.CONFIG["port"] == 9001, repr(module.CONFIG))
        check("api_load_config_target", module.CONFIG["targets"]["bible-app"] == str(target_repo), repr(module.CONFIG))
        module.CONFIG = original_config

        missing_capture = io.StringIO()
        with contextlib.redirect_stdout(missing_capture):
            module.load_config(str(config_path.with_name("missing.yaml")))
        check("api_load_config_missing", "using defaults" in missing_capture.getvalue(), missing_capture.getvalue())

        module.CONFIG = {"targets": {"bible-app": str(target_repo)}, "allowed_origins": [], "api_key": "", "port": 8070}
        check("api_resolve_direct_path", module.resolve_target(str(target_repo)) == str(target_repo))
        check("api_resolve_named_target", module.resolve_target("bible-app") == str(target_repo))
        check("api_resolve_default_target", module.resolve_target("") == str(target_repo))
        module.CONFIG = {"targets": {}, "allowed_origins": [], "api_key": "", "port": 8070}
        check("api_resolve_none", module.resolve_target("") is None)

        class IdleThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                return None

        module.running_jobs.clear()
        with mock.patch("threading.Thread", IdleThread):
            check("api_run_agent_starts", module.run_agent("qa", "/tmp/repo", sync=True) is True)
            check("api_run_agent_blocks_duplicate", module.run_agent("qa", "/tmp/repo", sync=True) is False)
        module.running_jobs.clear()

        module.CONFIG = {
            "targets": {"bible-app": str(target_repo)},
            "allowed_origins": ["https://admin.codyjo.com"],
            "api_key": "secret",
            "port": 8070,
        }

        auth_handler = make_handler(module.APIHandler, headers={"X-API-Key": "secret"})
        check("api_auth_valid", auth_handler._check_auth() is True)
        auth_handler.headers["X-API-Key"] = "wrong"
        check("api_auth_invalid", auth_handler._check_auth() is False)

        body_handler = make_handler(module.APIHandler, body=b"{bad json")
        check("api_read_body_invalid_json", body_handler._read_body() == {})

        status_handler = make_handler(module.APIHandler)
        module.running_jobs.clear()
        module.running_jobs["qa"] = object()
        status_handler._handle_status()
        status_payload = read_json_response(status_handler)
        check("api_status_lists_running", status_payload["running"] == ["qa"], repr(status_payload))
        module.running_jobs.clear()

        with mock.patch.object(module, "QA_ROOT", str(tmpdir)):
            jobs_handler = make_handler(module.APIHandler)
            jobs_handler._handle_get_jobs()
            check("api_jobs_idle", read_json_response(jobs_handler)["status"] == "idle")

            results_dir = tmpdir / "results"
            results_dir.mkdir()
            (results_dir / ".jobs.json").write_text(json.dumps({"status": "running", "jobs": {"qa": {"status": "running"}}}))
            jobs_handler = make_handler(module.APIHandler)
            jobs_handler._handle_get_jobs()
            check("api_jobs_reads_file", read_json_response(jobs_handler)["jobs"]["qa"]["status"] == "running")

        invalid_handler = make_handler(module.APIHandler, body={"department": "bad"})
        invalid_handler._handle_run_scan()
        invalid_payload = read_json_response(invalid_handler)
        check("api_run_scan_invalid_dept", invalid_handler.response_code == 400 and "Unknown department" in invalid_payload["error"])

        missing_target_handler = make_handler(module.APIHandler, body={"department": "qa"})
        with mock.patch.object(module, "resolve_target", return_value=None):
            missing_target_handler._handle_run_scan()
        missing_payload = read_json_response(missing_target_handler)
        check("api_run_scan_no_target", missing_target_handler.response_code == 400 and "No target repo configured" in missing_payload["error"])

        started_handler = make_handler(module.APIHandler, body={"department": "qa", "target": "bible-app"})
        with mock.patch.object(module, "resolve_target", return_value=str(target_repo)), \
             mock.patch.object(module, "init_jobs") as init_jobs, \
             mock.patch.object(module, "run_agent", return_value=True), \
             mock.patch("os.path.exists", return_value=False):
            started_handler._handle_run_scan()
        started_payload = read_json_response(started_handler)
        check("api_run_scan_started", started_handler.response_code == 200 and started_payload["status"] == "started", repr(started_payload))
        check("api_run_scan_init_called", init_jobs.called)

        run_all_handler = make_handler(module.APIHandler, body={"target": "bible-app", "parallel": True})
        started_departments = []
        with mock.patch.object(module, "resolve_target", return_value=str(target_repo)), \
             mock.patch.object(module, "init_jobs") as init_jobs, \
             mock.patch.object(module, "run_agent", side_effect=lambda dept, target, sync=True: started_departments.append((dept, target, sync)) or True):
            run_all_handler._handle_run_all()
        run_all_payload = read_json_response(run_all_handler)
        check("api_run_all_parallel", run_all_handler.response_code == 200 and run_all_payload["mode"] == "parallel", repr(run_all_payload))
        check("api_run_all_launches_all", len(started_departments) == len(module.ALL_DEPTS), repr(started_departments))
        check("api_run_all_init_called", init_jobs.called)

        stop_handler = make_handler(module.APIHandler)
        module.running_jobs.clear()
        module.running_jobs["qa"] = object()
        stop_handler._handle_stop()
        stop_payload = read_json_response(stop_handler)
        check("api_stop_reports_running", stop_payload["running"] == ["qa"], repr(stop_payload))
        module.running_jobs.clear()


def run_dashboard_server_tests(repo_root: Path) -> None:
    module = load_module("dashboard_server", repo_root / "scripts" / "dashboard-server.py")

    class IdleThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            return None

    module.running_jobs.clear()
    with mock.patch("threading.Thread", IdleThread):
        check("dashboard_run_agent_starts", module.run_agent("qa", "/tmp/repo", sync=True) is True)
        check("dashboard_run_agent_blocks_duplicate", module.run_agent("qa", "/tmp/repo", sync=True) is False)
    module.running_jobs.clear()

    handler = make_handler(module.DashboardHandler, headers={"Origin": "http://localhost:8070"})
    check("dashboard_origin_allowed", handler._origin_allowed() == "http://localhost:8070")
    handler._set_cors_headers()
    check("dashboard_cors_header_set", ("Access-Control-Allow-Origin", "http://localhost:8070") in handler.sent_headers, repr(handler.sent_headers))

    forbidden = make_handler(module.DashboardHandler, headers={"Origin": "https://evil.example"})
    forbidden.do_OPTIONS()
    check("dashboard_options_forbidden", forbidden.response_code == 403, repr(forbidden.response_code))

    module.TARGET_REPO = ""
    no_target = make_handler(module.DashboardHandler, body={"department": "qa"})
    no_target._handle_run_scan()
    check("dashboard_scan_requires_target", no_target.response_code == 400)

    module.TARGET_REPO = "/tmp/bible-app"
    invalid = make_handler(module.DashboardHandler, body={"department": "bad"})
    invalid._handle_run_scan()
    invalid_payload = read_json_response(invalid)
    check("dashboard_scan_invalid_dept", invalid.response_code == 400 and "Unknown department" in invalid_payload["error"])

    started = make_handler(module.DashboardHandler, body={"department": "qa"})
    with mock.patch.object(module, "init_jobs") as init_jobs, \
         mock.patch.object(module, "run_agent", return_value=True), \
         mock.patch("os.path.exists", return_value=False):
        started._handle_run_scan()
    started_payload = read_json_response(started)
    check("dashboard_scan_started", started.response_code == 200 and started_payload["status"] == "started", repr(started_payload))
    check("dashboard_scan_init_called", init_jobs.called)

    run_all = make_handler(module.DashboardHandler, body={"parallel": True})
    launched = []
    with mock.patch.object(module, "init_jobs") as init_jobs, \
         mock.patch.object(module, "run_agent", side_effect=lambda dept, target, sync=True: launched.append((dept, target, sync)) or True):
        run_all._handle_run_all()
    run_all_payload = read_json_response(run_all)
    check("dashboard_run_all_parallel", run_all.response_code == 200 and run_all_payload["parallel"] is True, repr(run_all_payload))
    check("dashboard_run_all_launches_all", len(launched) == len(module.ALL_DEPTS), repr(launched))
    check("dashboard_run_all_init_called", init_jobs.called)

    module.TARGET_REPO = ""


def run_setup_helper_tests(repo_root: Path) -> None:
    module = load_module("backoffice_setup_more", repo_root / "scripts" / "backoffice_setup.py")

    with tempfile.TemporaryDirectory(dir=repo_root) as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "example.yaml"
        dest = tmpdir / "actual.yaml"
        source.write_text("key: value\n")

        copied = module.maybe_copy_file(source, dest, enabled=True, interactive=False)
        check("setup_copies_missing_file", copied is True and dest.read_text() == "key: value\n")
        check("setup_skips_existing_file", module.maybe_copy_file(source, dest, enabled=True, interactive=False) is False)

        args = module.parse_args(["--check-only", "--interactive"])
        check("setup_parse_args", args.check_only is True and args.interactive is True)

        with mock.patch.dict("os.environ", {"BACK_OFFICE_AGENT_RUNNER": "codex", "BACK_OFFICE_AGENT_MODE": "stdin-text"}, clear=False), \
             mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in ("codex", "aider") else None):
            runner_cmd, runner_mode, available, _ = module.detect_runner_status()
        check("setup_detect_runner_env", runner_cmd == "codex" and runner_mode == "stdin-text", repr((runner_cmd, runner_mode)))
        check("setup_detect_runner_available", available == ["codex", "aider"], repr(available))

        results_dir = tmpdir / "results"
        results_dir.mkdir()
        audit_log = results_dir / "local-audit-log.json"
        audit_log.write_text(
            json.dumps(
                {
                    "recent_runs": [
                        {
                            "repo_name": "bible-app",
                            "status": "completed",
                            "jobs": {
                                "qa": {
                                    "status": "completed",
                                    "elapsed_seconds": 12,
                                    "findings_count": 3,
                                    "agent_runner": "codex",
                                    "agent_mode": "stdin-text",
                                }
                            },
                        }
                    ]
                }
            )
        )
        capture = io.StringIO()
        with mock.patch.object(module, "ROOT", tmpdir), contextlib.redirect_stdout(capture):
            module.summarize_recent_usage()
        output = capture.getvalue()
        check("setup_recent_usage_prints_repo", "bible-app" in output and "runner=codex" in output, output)

        prereq_capture = io.StringIO()
        with mock.patch("shutil.which", side_effect=lambda name: None if name == "aws" else f"/usr/bin/{name}"), \
             contextlib.redirect_stdout(prereq_capture):
            prereq_ok = module.summarize_prereqs()
        check("setup_prereqs_flags_missing_aws", prereq_ok is False and "aws: missing" in prereq_capture.getvalue(), prereq_capture.getvalue())


def main():
    repo_root = Path(__file__).resolve().parents[1]
    run_api_server_tests(repo_root)
    run_dashboard_server_tests(repo_root)
    run_setup_helper_tests(repo_root)
    print("server/setup tests passed")


if __name__ == "__main__":
    main()
