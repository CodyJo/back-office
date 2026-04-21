"""Back Office API Server — Production scan trigger API.

Runs as a persistent service on the worker machine.  Receives scan requests
from the dashboards (via API Gateway or direct HTTP) and launches agent scripts.

Usage::

    python -m backoffice api-server [--port 8070] [--bind 127.0.0.1]

    # Or via systemd:
    systemctl start backoffice-api
"""
from __future__ import annotations

import hmac
import http.server
import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request body size limit (1 MB)
# ---------------------------------------------------------------------------

MAX_BODY_SIZE: int = 1_048_576

# ---------------------------------------------------------------------------
# Department registry
# ---------------------------------------------------------------------------

DEPT_SCRIPTS: dict[str, str] = {
    "qa": "agents/qa-scan.sh",
    "seo": "agents/seo-audit.sh",
    "ada": "agents/ada-audit.sh",
    "compliance": "agents/compliance-audit.sh",
    "monetization": "agents/monetization-audit.sh",
    "product": "agents/product-audit.sh",
    "cloud-ops": "agents/cloud-ops-audit.sh",
}

ALL_DEPTS: list[str] = list(DEPT_SCRIPTS.keys())

# ---------------------------------------------------------------------------
# Module-level state (replaced by main() / tests via injected config)
# ---------------------------------------------------------------------------

_root: Path = Path(__file__).resolve().parents[1]

# Track running jobs: dept -> Thread
running_jobs: dict[str, threading.Thread] = {}
running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(site_hint: str | None, targets: dict) -> str | None:
    """Resolve a target repo path from a site hint or targets mapping.

    Only named targets from the configured targets list are accepted.
    Raw filesystem paths are rejected to prevent arbitrary directory access.

    Resolution order:
    1. ``site_hint`` matches a key in *targets* → return ``targets[site_hint].path``
    2. *targets* is non-empty and no hint given → return the first entry's path
    3. Otherwise → ``None``
    """
    if site_hint and site_hint in targets:
        target = targets[site_hint]
        # Support both Target dataclass (has .path) and plain str
        return target.path if hasattr(target, "path") else str(target)

    if not site_hint and targets:
        first = next(iter(targets.values()))
        return first.path if hasattr(first, "path") else str(first)

    return None


# ---------------------------------------------------------------------------
# Agent runner helpers
# ---------------------------------------------------------------------------

def run_agent(dept: str, target: str, *, sync: bool = True,
              root: Path | None = None) -> bool:
    """Launch an agent script in a background thread.

    Returns ``True`` when the job was accepted, ``False`` if already running.
    """
    r = root or _root
    script = str(r / DEPT_SCRIPTS[dept])
    args = ["bash", script, target]
    if sync:
        args.append("--sync")

    def _run() -> None:
        try:
            subprocess.run(args, cwd=str(r))
        finally:
            with running_lock:
                running_jobs.pop(dept, None)

    with running_lock:
        if dept in running_jobs:
            return False
        t = threading.Thread(target=_run, daemon=True)
        running_jobs[dept] = t

    t.start()
    logger.info("Started agent dept=%s target=%s", dept, target)
    return True


running_fix: dict[str, threading.Thread] = {}
running_fix_lock = threading.Lock()


def run_fix_agent(target: str, *, preview: bool = False,
                  root: Path | None = None) -> bool:
    """Launch ``agents/fix-bugs.sh`` in a background thread.

    Returns ``True`` when accepted, ``False`` if a fix is already in
    flight against the same target.
    """
    r = root or _root
    args = ["bash", str(r / "agents" / "fix-bugs.sh"), target, "--sync"]
    if preview:
        args.append("--preview")

    def _run() -> None:
        try:
            subprocess.run(args, cwd=str(r))
        finally:
            with running_fix_lock:
                running_fix.pop(target, None)

    with running_fix_lock:
        if target in running_fix:
            return False
        t = threading.Thread(target=_run, daemon=True)
        running_fix[target] = t

    t.start()
    logger.info("Started fix agent target=%s preview=%s", target, preview)
    return True


def init_jobs(target: str, departments: list[str], root: Path | None = None) -> None:
    """Initialize the jobs status file for the given departments."""
    r = root or _root
    subprocess.run(
        [
            "bash",
            str(r / "scripts" / "job-status.sh"),
            "init",
            target,
            " ".join(departments),
        ],
        cwd=str(r),
    )


def finalize_jobs(root: Path | None = None) -> None:
    """Mark the current jobs run as finalized."""
    r = root or _root
    subprocess.run(
        ["bash", str(r / "scripts" / "job-status.sh"), "finalize"],
        cwd=str(r),
    )


# ---------------------------------------------------------------------------
# HTTP handler factory
# ---------------------------------------------------------------------------

def create_api_handler(
    root: Path,
    api_key: str,
    allowed_origins: list[str],
    targets: dict,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Return an APIHandler subclass pre-configured for the given runtime."""

    class _APIHandler(APIHandler):
        _root = root
        _api_key = api_key
        _allowed_origins = allowed_origins
        _targets = targets

    return _APIHandler


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class APIHandler(http.server.BaseHTTPRequestHandler):
    """Production API handler with auth, CORS, and scan triggering."""

    # Class-level attributes injected by create_api_handler()
    _root: Path = _root
    _api_key: str = ""
    _allowed_origins: list[str] = ["http://localhost:8070", "http://127.0.0.1:8070"]
    _targets: dict = {}

    # ------------------------------------------------------------------
    # CORS helpers
    # ------------------------------------------------------------------

    def _cors_headers(self) -> None:
        """Emit Access-Control-* headers based on the request Origin."""
        origin = self.headers.get("Origin", "")
        allowed = self._allowed_origins
        if "*" in allowed or origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin or "*")
        elif allowed:
            self.send_header("Access-Control-Allow-Origin", allowed[0])
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _check_auth(self) -> bool:
        """Return True if the request passes auth checks.

        When no ``api_key`` is configured auth is disabled (open access).
        Comparison uses :func:`hmac.compare_digest` to prevent timing attacks.
        """
        key = self._api_key
        if not key:
            return True
        provided = self.headers.get("X-API-Key", "")
        return hmac.compare_digest(provided, key)

    # ------------------------------------------------------------------
    # Request parsing helpers
    # ------------------------------------------------------------------

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > MAX_BODY_SIZE:
            self._json_response(413, {"error": "Payload Too Large", "max_bytes": MAX_BODY_SIZE})
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json_response(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/health":
            self._json_response(200, {"status": "ok"})
        elif path == "/api/status":
            self._handle_status()
        elif path == "/api/jobs":
            self._handle_get_jobs()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if not self._check_auth():
            self._json_response(401, {"error": "Invalid API key"})
            return

        # Body size gate
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_SIZE:
            self._json_response(413, {"error": "Payload Too Large", "max_bytes": MAX_BODY_SIZE})
            return

        if path == "/api/run-scan":
            self._handle_run_scan()
        elif path == "/api/run-all":
            self._handle_run_all()
        elif path == "/api/run-fix":
            self._handle_run_fix()
        elif path == "/api/stop":
            self._handle_stop()
        else:
            self.send_error(404)

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------

    def _handle_status(self) -> None:
        with running_lock:
            active = list(running_jobs.keys())
        # Expose target names (keys) rather than internal Target objects
        target_names = list(self._targets.keys())
        self._json_response(200, {
            "running": active,
            "available_departments": ALL_DEPTS,
            "targets": target_names,
        })

    def _handle_get_jobs(self) -> None:
        jobs_file = self._root / "results" / ".jobs.json"
        if jobs_file.exists():
            try:
                with open(jobs_file) as f:
                    data = json.load(f)
                self._json_response(200, data)
                return
            except (json.JSONDecodeError, OSError):
                pass
        self._json_response(200, {"status": "idle", "jobs": {}})

    # ------------------------------------------------------------------
    # POST handlers
    # ------------------------------------------------------------------

    def _handle_run_scan(self) -> None:
        body = self._read_body()
        if body is None:
            return
        dept = body.get("department", "")
        site = body.get("target", body.get("site", ""))

        if dept not in DEPT_SCRIPTS:
            self._json_response(400, {
                "error": f"Unknown department: {dept}",
                "valid": ALL_DEPTS,
            })
            return

        target = resolve_target(site, self._targets)
        if not target:
            self._json_response(400, {
                "error": "No target repo configured. Add targets to config/backoffice.yaml.",
            })
            return

        with running_lock:
            if dept in running_jobs:
                self._json_response(409, {"error": f"{dept} is already running"})
                return

        # Merge into an existing jobs file if present; otherwise init fresh.
        jobs_file = self._root / "results" / ".jobs.json"
        needs_init = True
        if jobs_file.exists():
            try:
                with open(jobs_file) as f:
                    jobs_data = json.load(f)
                if jobs_data.get("status") == "running":
                    needs_init = False
            except (json.JSONDecodeError, OSError):
                pass

        if needs_init:
            init_jobs(target, [dept], root=self._root)

        started = run_agent(dept, target, sync=True, root=self._root)
        self._json_response(200 if started else 409, {
            "status": "started" if started else "already_running",
            "department": dept,
            "target": target,
        })

    def _handle_run_all(self) -> None:
        body = self._read_body()
        if body is None:
            return
        site = body.get("target", body.get("site", ""))
        parallel = body.get("parallel", False)

        target = resolve_target(site, self._targets)
        if not target:
            self._json_response(400, {
                "error": "No target repo configured. Add targets to config/backoffice.yaml.",
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

        init_jobs(target, ALL_DEPTS, root=self._root)

        root_snapshot = self._root

        if parallel:
            for dept in ALL_DEPTS:
                run_agent(dept, target, sync=True, root=root_snapshot)
            self._json_response(200, {
                "status": "started",
                "mode": "parallel",
                "departments": ALL_DEPTS,
                "target": target,
            })
        else:
            def _run_sequential() -> None:
                for dept in ALL_DEPTS:
                    run_agent(dept, target, sync=True, root=root_snapshot)
                    while True:
                        with running_lock:
                            if dept not in running_jobs:
                                break
                        time.sleep(2)
                finalize_jobs(root=root_snapshot)

            t = threading.Thread(target=_run_sequential, daemon=True)
            t.start()
            self._json_response(200, {
                "status": "started",
                "mode": "sequential",
                "departments": ALL_DEPTS,
                "target": target,
            })

    def _handle_run_fix(self) -> None:
        body = self._read_body()
        if body is None:
            return
        site = body.get("target", body.get("site", ""))
        preview = bool(body.get("preview", False))

        target = resolve_target(site, self._targets)
        if not target:
            self._json_response(400, {
                "error": "Unknown target. Check config/backoffice.yaml.",
                "targets": list(self._targets.keys()),
            })
            return

        started = run_fix_agent(target, preview=preview, root=self._root)
        self._json_response(200 if started else 409, {
            "status": "started" if started else "already_running",
            "target": target,
            "preview": preview,
        })

    def _handle_stop(self) -> None:
        """Report status; we cannot safely kill claude --print mid-run."""
        with running_lock:
            active = list(running_jobs.keys())
        self._json_response(200, {
            "message": "Stop requested. Active agents will finish their current scan.",
            "running": active,
        })

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Suppress noisy polling logs; route the rest through stdlib logging."""
        first_arg = str(args[0]) if args else ""
        if "/api/jobs" in first_arg or "/api/health" in first_arg:
            return
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        logger.debug("[%s] %s", ts, format % args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None, config=None) -> int:
    """Start the production API server.

    Parameters
    ----------
    argv:
        Command-line arguments (defaults to ``sys.argv[1:]``).
    config:
        A :class:`backoffice.config.Config` instance.  When *None* the
        function attempts to load one from disk; falls back to built-in
        defaults so the server starts even without a config file.
    """
    from backoffice.log_config import setup_logging  # noqa: PLC0415
    setup_logging()

    args = list(argv if argv is not None else sys.argv[1:])

    # Default bind address — loopback only for security
    bind_addr = "127.0.0.1"
    port_override: int | None = None

    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port_override = int(args[i + 1])
            i += 2
        elif args[i] == "--bind" and i + 1 < len(args):
            bind_addr = args[i + 1]
            i += 2
        else:
            i += 1

    # Load config
    if config is None:
        try:
            from backoffice.config import load_config  # noqa: PLC0415
            config = load_config()
        except Exception as exc:
            logger.warning("Could not load config: %s — using defaults", exc)
            from backoffice.config import Config  # noqa: PLC0415
            config = Config()

    port = port_override if port_override is not None else config.api.port
    api_key = config.api.api_key
    allowed_origins = list(config.api.allowed_origins) or [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    targets = config.targets
    root = config.root

    # Security gate: non-loopback bind requires an API key
    if bind_addr not in ("127.0.0.1", "localhost", "::1") and not api_key:
        logger.error(
            "Binding to non-loopback address requires api_key in config/backoffice.yaml"
        )
        return 1

    handler_cls = create_api_handler(
        root=root,
        api_key=api_key,
        allowed_origins=allowed_origins,
        targets=targets,
    )

    logger.info(
        "Back Office API Server — bind=%s port=%d auth=%s targets=%d",
        bind_addr,
        port,
        "key-required" if api_key else "open",
        len(targets),
    )
    logger.info("GET  /api/health   — health check")
    logger.info("GET  /api/status   — running jobs & available departments")
    logger.info("GET  /api/jobs     — current jobs.json data")
    logger.info("POST /api/run-scan — run single department scan")
    logger.info("POST /api/run-all  — run all department scans")
    logger.info("Press Ctrl+C to stop")

    server = http.server.HTTPServer((bind_addr, port), handler_cls)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped.")
    return 0
