#!/usr/bin/env python3
"""Back Office API Server — Production scan trigger API.

Runs as a persistent service on the worker machine. Receives scan requests
from the dashboards (via API Gateway) and launches agent scripts.

Usage:
    python3 scripts/api-server.py --config config/api-config.yaml

    # Or via systemd:
    systemctl start backoffice-api
"""

import hashlib
import hmac
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

# ── Defaults ──────────────────────────────────────────────────────────────────

QA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = {
    "port": 8070,
    "api_key": "",
    "allowed_origins": ["http://localhost:8070", "http://127.0.0.1:8070"],
    "targets": {},
}

DEPT_SCRIPTS = {
    "qa": "agents/qa-scan.sh",
    "seo": "agents/seo-audit.sh",
    "ada": "agents/ada-audit.sh",
    "compliance": "agents/compliance-audit.sh",
    "monetization": "agents/monetization-audit.sh",
    "product": "agents/product-audit.sh",
}

ALL_DEPTS = list(DEPT_SCRIPTS.keys())

running_jobs = {}   # dept -> thread
running_lock = threading.Lock()


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path):
    global CONFIG
    try:
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        CONFIG["port"] = raw.get("port", CONFIG["port"])
        CONFIG["api_key"] = raw.get("api_key", CONFIG["api_key"])
        CONFIG["allowed_origins"] = raw.get("allowed_origins", CONFIG["allowed_origins"])
        # targets maps site name -> repo path
        CONFIG["targets"] = raw.get("targets", CONFIG["targets"])
        print(f"Config loaded from {path}")
    except FileNotFoundError:
        print(f"No config at {path} — using defaults")
    except ImportError:
        print("PyYAML not installed — using defaults")


# ── Agent Runner ──────────────────────────────────────────────────────────────

def resolve_target(site_hint):
    """Resolve a target repo path from a site hint or config."""
    # Direct path
    if site_hint and os.path.isdir(site_hint):
        return site_hint

    # Check configured targets
    targets = CONFIG.get("targets", {})
    if site_hint and site_hint in targets:
        return targets[site_hint]

    # Default: first configured target, or None
    if targets:
        return next(iter(targets.values()))

    return None


def run_agent(dept, target, sync=True):
    """Launch an agent script in a background thread."""
    script = os.path.join(QA_ROOT, DEPT_SCRIPTS[dept])
    args = ["bash", script, target]
    if sync:
        args.append("--sync")

    def _run():
        try:
            subprocess.run(args, cwd=QA_ROOT)
        finally:
            with running_lock:
                running_jobs.pop(dept, None)

    with running_lock:
        if dept in running_jobs:
            return False
        t = threading.Thread(target=_run, daemon=True)
        running_jobs[dept] = t

    t.start()
    return True


def init_jobs(target, departments):
    """Initialize the jobs status file."""
    subprocess.run(
        ["bash", os.path.join(QA_ROOT, "scripts/job-status.sh"),
         "init", target, " ".join(departments)],
        cwd=QA_ROOT,
    )


def finalize_jobs():
    """Mark the jobs run as finalized."""
    subprocess.run(
        ["bash", os.path.join(QA_ROOT, "scripts/job-status.sh"), "finalize"],
        cwd=QA_ROOT,
    )


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class APIHandler(http.server.BaseHTTPRequestHandler):

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        allowed = CONFIG["allowed_origins"]
        if "*" in allowed or origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin or "*")
        elif allowed:
            self.send_header("Access-Control-Allow-Origin", allowed[0])
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")

    def _check_auth(self):
        """Check API key if configured."""
        key = CONFIG.get("api_key", "")
        if not key:
            return True
        provided = self.headers.get("X-API-Key", "")
        return hmac.compare_digest(provided, key)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json_response(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/status":
            self._handle_status()
        elif path == "/api/health":
            self._json_response(200, {"status": "ok"})
        elif path == "/api/jobs":
            self._handle_get_jobs()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if not self._check_auth():
            self._json_response(401, {"error": "Invalid API key"})
            return

        if path == "/api/run-scan":
            self._handle_run_scan()
        elif path == "/api/run-all":
            self._handle_run_all()
        elif path == "/api/stop":
            self._handle_stop()
        else:
            self.send_error(404)

    def _handle_status(self):
        with running_lock:
            active = list(running_jobs.keys())
        self._json_response(200, {
            "running": active,
            "available_departments": ALL_DEPTS,
            "targets": CONFIG.get("targets", {}),
        })

    def _handle_get_jobs(self):
        jobs_file = os.path.join(QA_ROOT, "results/.jobs.json")
        if os.path.exists(jobs_file):
            with open(jobs_file) as f:
                data = json.load(f)
            self._json_response(200, data)
        else:
            self._json_response(200, {"status": "idle", "jobs": {}})

    def _handle_run_scan(self):
        body = self._read_body()
        dept = body.get("department", "")
        site = body.get("target", body.get("site", ""))

        if dept not in DEPT_SCRIPTS:
            self._json_response(400, {
                "error": f"Unknown department: {dept}",
                "valid": ALL_DEPTS,
            })
            return

        target = resolve_target(site)
        if not target:
            self._json_response(400, {
                "error": "No target repo configured. Set targets in api-config.yaml.",
            })
            return

        with running_lock:
            if dept in running_jobs:
                self._json_response(409, {
                    "error": f"{dept} is already running",
                })
                return

        # Ensure jobs file exists — add this department
        jobs_file = os.path.join(QA_ROOT, "results/.jobs.json")
        needs_init = True
        if os.path.exists(jobs_file):
            with open(jobs_file) as f:
                jobs_data = json.load(f)
            # If there's an active run, just add this dept
            if jobs_data.get("status") == "running":
                needs_init = False

        if needs_init:
            init_jobs(target, [dept])

        started = run_agent(dept, target, sync=True)
        self._json_response(200 if started else 409, {
            "status": "started" if started else "already_running",
            "department": dept,
            "target": target,
        })

    def _handle_run_all(self):
        body = self._read_body()
        site = body.get("target", body.get("site", ""))
        parallel = body.get("parallel", False)

        target = resolve_target(site)
        if not target:
            self._json_response(400, {
                "error": "No target repo configured. Set targets in api-config.yaml.",
            })
            return

        with running_lock:
            already = [d for d in ALL_DEPTS if d in running_jobs]
        if already:
            self._json_response(409, {
                "error": f"Jobs already running: {', '.join(already)}",
                "running": already,
            })
            return

        init_jobs(target, ALL_DEPTS)

        if parallel:
            for dept in ALL_DEPTS:
                run_agent(dept, target, sync=True)
            self._json_response(200, {
                "status": "started",
                "mode": "parallel",
                "departments": ALL_DEPTS,
                "target": target,
            })
        else:
            def _run_sequential():
                for dept in ALL_DEPTS:
                    run_agent(dept, target, sync=True)
                    while True:
                        with running_lock:
                            if dept not in running_jobs:
                                break
                        time.sleep(2)
                finalize_jobs()

            t = threading.Thread(target=_run_sequential, daemon=True)
            t.start()

            self._json_response(200, {
                "status": "started",
                "mode": "sequential",
                "departments": ALL_DEPTS,
                "target": target,
            })

    def _handle_stop(self):
        # We can't kill claude --print safely, just report status
        with running_lock:
            active = list(running_jobs.keys())
        self._json_response(200, {
            "message": "Stop requested. Active agents will finish their current scan.",
            "running": active,
        })

    def log_message(self, format, *args):
        msg = args[0] if args else ""
        # Suppress noisy polling
        if "/api/jobs" in msg or "/api/health" in msg:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        sys.stderr.write(f"[{timestamp}] {format % args}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config_path = os.path.join(QA_ROOT, "config/api-config.yaml")

    # Default to localhost for security — use --bind to override
    bind_addr = "127.0.0.1"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            CONFIG["port"] = int(args[i + 1])
            i += 2
        elif args[i] == "--bind" and i + 1 < len(args):
            bind_addr = args[i + 1]
            i += 2
        else:
            i += 1

    load_config(config_path)
    port = CONFIG["port"]

    # Require API key when binding to non-loopback addresses
    if bind_addr not in ("127.0.0.1", "localhost", "::1") and not CONFIG.get("api_key"):
        print("ERROR: Binding to non-loopback address requires api_key in config.", file=sys.stderr)
        sys.exit(1)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  Back Office API Server                                  ║
╚══════════════════════════════════════════════════════════╝

  Bind:     {bind_addr}
  Port:     {port}
  Targets:  {json.dumps(CONFIG.get('targets', {}), indent=2) if CONFIG.get('targets') else 'None (set in api-config.yaml)'}
  Auth:     {'API key required' if CONFIG.get('api_key') else 'No auth (add api_key to config)'}

  Endpoints:
    GET  /api/health      — Health check
    GET  /api/status      — Running jobs & available departments
    GET  /api/jobs        — Current jobs.json data
    POST /api/run-scan    — Run single department scan
    POST /api/run-all     — Run all department scans

  Press Ctrl+C to stop
""")

    server = http.server.HTTPServer((bind_addr, port), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
