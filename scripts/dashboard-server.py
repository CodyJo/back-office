#!/usr/bin/env python3
"""Local dashboard server with scan API.

Serves dashboard files and handles POST /api/run-scan to launch agent scripts.

Usage:
    python3 scripts/dashboard-server.py [--port 8070] [--target /path/to/repo]

    # Or via make:
    make jobs TARGET=/path/to/repo
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

PORT = 8070
QA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_DIR = os.path.join(QA_ROOT, "dashboard")
TARGET_REPO = ""
ALLOWED_ORIGINS = {"http://localhost:8070", "http://127.0.0.1:8070"}

DEPT_SCRIPTS = {
    "qa": "agents/qa-scan.sh",
    "seo": "agents/seo-audit.sh",
    "ada": "agents/ada-audit.sh",
    "compliance": "agents/compliance-audit.sh",
    "monetization": "agents/monetization-audit.sh",
    "product": "agents/product-audit.sh",
}

ALL_DEPTS = list(DEPT_SCRIPTS.keys())

# Track running processes to prevent double-starts
running_jobs = set()
running_lock = threading.Lock()


def run_agent(dept, target, sync=False):
    """Launch an agent script in a background thread."""
    script = os.path.join(QA_ROOT, DEPT_SCRIPTS[dept])
    args = [script, target]
    if sync:
        args.append("--sync")

    def _run():
        try:
            subprocess.run(["bash"] + args, cwd=QA_ROOT)
        finally:
            with running_lock:
                running_jobs.discard(dept)

    with running_lock:
        if dept in running_jobs:
            return False  # Already running
        running_jobs.add(dept)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True


def init_jobs(target, departments):
    """Initialize the jobs file for a set of departments."""
    subprocess.run(
        ["bash", os.path.join(QA_ROOT, "scripts/job-status.sh"),
         "init", target, " ".join(departments)],
        cwd=QA_ROOT,
    )


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DASHBOARD_DIR, **kwargs)

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return None
        return origin if origin in ALLOWED_ORIGINS else False

    def _set_cors_headers(self):
        origin = self._origin_allowed()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/run-scan":
            self._handle_run_scan()
        elif path == "/api/run-all":
            self._handle_run_all()
        else:
            self.send_error(404, "Not found")

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
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_run_scan(self):
        if not TARGET_REPO:
            self._json_response(400, {
                "error": "No TARGET set. Start server with: make jobs TARGET=/path/to/repo"
            })
            return

        body = self._read_body()
        dept = body.get("department", "")

        if dept not in DEPT_SCRIPTS:
            self._json_response(400, {
                "error": f"Unknown department: {dept}",
                "valid": ALL_DEPTS,
            })
            return

        with running_lock:
            if dept in running_jobs:
                self._json_response(409, {
                    "error": f"{dept} is already running",
                    "status": "running",
                })
                return

        # Initialize jobs file with just this department if no active run
        jobs_file = os.path.join(QA_ROOT, "results/.jobs.json")
        if os.path.exists(jobs_file):
            with open(jobs_file) as f:
                jobs_data = json.load(f)
            # Add department to existing run if not present
            if dept not in jobs_data.get("jobs", {}):
                subprocess.run(
                    ["bash", os.path.join(QA_ROOT, "scripts/job-status.sh"),
                     "start", dept],
                    cwd=QA_ROOT,
                )
        else:
            init_jobs(TARGET_REPO, [dept])

        started = run_agent(dept, TARGET_REPO, sync=True)
        if started:
            self._json_response(200, {
                "status": "started",
                "department": dept,
                "target": TARGET_REPO,
            })
        else:
            self._json_response(409, {
                "error": f"{dept} is already running",
            })

    def _handle_run_all(self):
        if not TARGET_REPO:
            self._json_response(400, {
                "error": "No TARGET set. Start server with: make jobs TARGET=/path/to/repo"
            })
            return

        body = self._read_body()
        parallel = body.get("parallel", False)

        # Check if anything is already running
        with running_lock:
            already = [d for d in ALL_DEPTS if d in running_jobs]
        if already:
            self._json_response(409, {
                "error": f"Jobs already running: {', '.join(already)}",
                "running": already,
            })
            return

        # Initialize all departments
        init_jobs(TARGET_REPO, ALL_DEPTS)

        if parallel:
            # Launch all at once
            for dept in ALL_DEPTS:
                run_agent(dept, TARGET_REPO, sync=True)
        else:
            # Launch sequentially in a background thread
            def _run_sequential():
                for dept in ALL_DEPTS:
                    run_agent(dept, TARGET_REPO, sync=True)
                    # Wait for this one to finish before starting next
                    while True:
                        with running_lock:
                            if dept not in running_jobs:
                                break
                        time.sleep(1)
                # Finalize
                subprocess.run(
                    ["bash", os.path.join(QA_ROOT, "scripts/job-status.sh"),
                     "finalize"],
                    cwd=QA_ROOT,
                )

            t = threading.Thread(target=_run_sequential, daemon=True)
            t.start()

        self._json_response(200, {
            "status": "started",
            "departments": ALL_DEPTS,
            "target": TARGET_REPO,
            "parallel": parallel,
        })

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        if self._origin_allowed() is False:
            self.send_response(403)
            self.end_headers()
            return

        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy polling logs for .jobs.json
        if ".jobs.json" in (args[0] if args else ""):
            return
        super().log_message(format, *args)


if __name__ == "__main__":
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            PORT = int(args[i + 1])
            i += 2
        elif args[i] == "--target" and i + 1 < len(args):
            TARGET_REPO = args[i + 1]
            i += 2
        else:
            TARGET_REPO = args[i]
            i += 1

    if TARGET_REPO:
        TARGET_REPO = os.path.abspath(TARGET_REPO)
        print(f"Target repo: {TARGET_REPO}")
    else:
        print("No TARGET specified — Run Scan buttons will prompt for one.")
        print("Usage: python3 scripts/dashboard-server.py --target /path/to/repo")

    print(f"\nDashboard server: http://localhost:{PORT}/")
    print(f"Jobs dashboard:   http://localhost:{PORT}/jobs.html")
    print(f"HQ dashboard:     http://localhost:{PORT}/index.html")
    print("\nPress Ctrl+C to stop\n")

    server = http.server.HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
