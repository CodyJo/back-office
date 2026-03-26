"""Local dashboard server with scan API.

Serves dashboard files from the ``dashboard/`` directory and provides POST
endpoints for triggering agent scans and managing manual backlog items.

Usage::

    python -m backoffice serve [--port 8070]

    # Or via make:
    make jobs TARGET=/path/to/repo
"""
from __future__ import annotations

import http.server
import json
import logging
import subprocess
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
# Module-level state (overridden by main())
# ---------------------------------------------------------------------------

_root: Path = Path(__file__).resolve().parents[1]
_dashboard_dir: Path = _root / "dashboard"
_target_repo: str = ""
_allowed_origins: set[str] = {"http://localhost:8070", "http://127.0.0.1:8070"}

# Track running processes to prevent double-starts
running_jobs: set[str] = set()
running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Manual items helpers
# ---------------------------------------------------------------------------

def _manual_items_paths(root: Path) -> tuple[Path, Path]:
    """Return (results_path, dashboard_path) for manual-items.json."""
    return (
        root / "results" / "manual-items.json",
        root / "dashboard" / "manual-items.json",
    )


def _load_manual_items(root: Path | None = None) -> list[dict]:
    """Load manual items list from the results file."""
    results_path, _ = _manual_items_paths(root or _root)
    try:
        with open(results_path) as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    if isinstance(raw, dict):
        items = raw.get("items", [])
    else:
        items = raw

    return [item for item in items if isinstance(item, dict)]


def _save_manual_items(items: list[dict], root: Path | None = None) -> None:
    """Persist manual items to both results/ and dashboard/."""
    results_path, dashboard_path = _manual_items_paths(root or _root)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    # Mirror into dashboard directory so the front-end can fetch it directly.
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dashboard_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Agent runner helpers
# ---------------------------------------------------------------------------

def run_agent(dept: str, target: str, *, sync: bool = False,
              root: Path | None = None) -> bool:
    """Launch an agent script in a background thread.

    Returns ``True`` when the job was accepted, ``False`` if it was already
    running.
    """
    r = root or _root
    script = str(r / DEPT_SCRIPTS[dept])
    args = [script, target]
    if sync:
        args.append("--sync")

    def _run() -> None:
        try:
            subprocess.run(["bash"] + args, cwd=str(r))
        finally:
            with running_lock:
                running_jobs.discard(dept)

    with running_lock:
        if dept in running_jobs:
            return False  # Already running
        running_jobs.add(dept)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Started agent dept=%s target=%s", dept, target)
    return True


def init_jobs(target: str, departments: list[str], root: Path | None = None) -> None:
    """Initialize the jobs file for a set of departments."""
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


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler serving the dashboard directory with a lightweight scan API."""

    # Instance attributes injected by create_handler()
    _root: Path
    _target_repo: str
    _allowed_origins: set[str]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(self._dashboard_dir), **kwargs)

    # Override so subclasses built by create_handler() can supply their own dir
    @property
    def _dashboard_dir(self) -> str:
        return str(self._root / "dashboard")

    # ------------------------------------------------------------------
    # CORS helpers
    # ------------------------------------------------------------------

    def _origin_allowed(self) -> str | None | bool:
        """Return the origin string if allowed, None if absent, False if blocked."""
        origin = self.headers.get("Origin")
        if not origin:
            return None
        return origin if origin in self._allowed_origins else False

    def _set_cors_headers(self) -> None:
        origin = self._origin_allowed()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    # ------------------------------------------------------------------
    # Request parsing helpers
    # ------------------------------------------------------------------

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json_response(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
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

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/ops/status":
            self._handle_ops_status()
        elif path == "/api/ops/backends":
            self._handle_ops_backends()
        elif path == "/api/tasks":
            self._handle_tasks_get()
        else:
            # Fall through to SimpleHTTPRequestHandler for static files
            super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/run-scan":
            self._handle_run_scan()
        elif path == "/api/run-all":
            self._handle_run_all()
        elif path == "/api/run-regression":
            self._handle_run_regression()
        elif path == "/api/manual-item":
            self._handle_manual_item()
        elif path == "/api/ops/audit":
            self._handle_ops_audit()
        elif path == "/api/ops/overnight/start":
            self._handle_ops_overnight_start()
        elif path == "/api/ops/overnight/stop":
            self._handle_ops_overnight_stop()
        elif path == "/api/ops/product/add":
            self._handle_ops_product_add()
        elif path == "/api/ops/product/suggest":
            self._handle_ops_product_suggest()
        elif path == "/api/ops/product/approve":
            self._handle_ops_product_approve()
        elif path == "/api/tasks/queue-finding":
            self._handle_task_queue_finding()
        elif path == "/api/tasks/approve":
            self._handle_task_approve()
        elif path == "/api/tasks/cancel":
            self._handle_task_cancel()
        elif path == "/api/tasks/request-pr":
            self._handle_task_request_pr()
        else:
            self.send_error(404, "Not found")

    # ------------------------------------------------------------------
    # POST handlers
    # ------------------------------------------------------------------

    def _handle_run_scan(self) -> None:
        if not self._target_repo:
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

        # Merge into an existing jobs file if present; otherwise init fresh.
        jobs_file = self._root / "results" / ".jobs.json"
        if jobs_file.exists():
            try:
                with open(jobs_file) as f:
                    jobs_data = json.load(f)
                if dept not in jobs_data.get("jobs", {}):
                    subprocess.run(
                        [
                            "bash",
                            str(self._root / "scripts" / "job-status.sh"),
                            "start",
                            dept,
                        ],
                        cwd=str(self._root),
                    )
            except (json.JSONDecodeError, OSError):
                pass
        else:
            init_jobs(self._target_repo, [dept], root=self._root)

        started = run_agent(dept, self._target_repo, sync=True, root=self._root)
        if started:
            self._json_response(200, {
                "status": "started",
                "department": dept,
                "target": self._target_repo,
            })
        else:
            self._json_response(409, {"error": f"{dept} is already running"})

    def _handle_run_all(self) -> None:
        if not self._target_repo:
            self._json_response(400, {
                "error": "No TARGET set. Start server with: make jobs TARGET=/path/to/repo"
            })
            return

        body = self._read_body()
        parallel = body.get("parallel", False)

        with running_lock:
            already = [d for d in ALL_DEPTS if d in running_jobs]
        if already:
            self._json_response(409, {
                "error": f"Jobs already running: {', '.join(already)}",
                "running": already,
            })
            return

        init_jobs(self._target_repo, ALL_DEPTS, root=self._root)

        if parallel:
            for dept in ALL_DEPTS:
                run_agent(dept, self._target_repo, sync=True, root=self._root)
        else:
            root_snapshot = self._root

            def _run_sequential() -> None:
                for dept in ALL_DEPTS:
                    run_agent(dept, self._target_repo, sync=True, root=root_snapshot)
                    while True:
                        with running_lock:
                            if dept not in running_jobs:
                                break
                        time.sleep(1)
                subprocess.run(
                    [
                        "bash",
                        str(root_snapshot / "scripts" / "job-status.sh"),
                        "finalize",
                    ],
                    cwd=str(root_snapshot),
                )

            t = threading.Thread(target=_run_sequential, daemon=True)
            t.start()

        self._json_response(200, {
            "status": "started",
            "departments": ALL_DEPTS,
            "target": self._target_repo,
            "parallel": parallel,
        })

    def _handle_run_regression(self) -> None:
        """Run portfolio regression in the background."""
        if self._origin_allowed() is False:
            self.send_error(403, "Origin not allowed")
            return

        runner = self._root / "scripts" / "regression-runner.py"
        if not runner.exists():
            self._json_response(500, {"error": "regression-runner.py not found"})
            return

        def _run() -> None:
            try:
                subprocess.run(["python3", str(runner)], cwd=str(self._root))
            except Exception:
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._json_response(200, {"status": "started"})

    def _handle_manual_item(self) -> None:
        """Append a manual backlog item and mirror to the dashboard directory."""
        if self._origin_allowed() is False:
            self.send_error(403, "Origin not allowed")
            return

        body = self._read_body()
        title = (body.get("title") or "").strip()
        if not title:
            self._json_response(400, {"error": "title is required"})
            return

        repo = (body.get("repo") or "").strip()
        department = (body.get("department") or "").strip()
        severity = (body.get("severity") or "medium").strip().lower()
        category = (body.get("category") or "").strip()
        bucket = (body.get("bucket") or "").strip()
        notes = (body.get("notes") or "").strip()
        product_key = (body.get("product_key") or "").strip()
        categories = body.get("categories") or []
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",") if c.strip()]

        items = _load_manual_items(root=self._root)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        new_id = f"MAN-{len(items) + 1:03d}"
        item = {
            "id": new_id,
            "title": title,
            "repo": repo,
            "department": department,
            "severity": severity,
            "category": category,
            "categories": categories,
            "bucket": bucket,
            "notes": notes,
            "product_key": product_key,
            "created_at": now,
        }
        items.append(item)
        _save_manual_items(items, root=self._root)
        logger.info("Manual item added id=%s title=%r", new_id, title)
        self._json_response(200, {"ok": True, "items": items})

    # ------------------------------------------------------------------
    # Ops GET handlers
    # ------------------------------------------------------------------

    def _handle_tasks_get(self) -> None:
        """GET /api/tasks — current task queue payload."""
        payload = _read_json(self._root / "results" / "task-queue.json")
        if not isinstance(payload, dict):
            payload = {"generated_at": None, "summary": {}, "tasks": []}
        self._json_response(200, payload)

    def _handle_ops_status(self) -> None:
        """GET /api/ops/status — current operational status."""
        r = self._root
        results_dir = r / "results"

        # Jobs
        jobs: dict = {}
        jobs_file = results_dir / ".jobs.json"
        if jobs_file.exists():
            try:
                with open(jobs_file) as f:
                    jobs = json.load(f)
            except (json.JSONDecodeError, OSError):
                jobs = {}

        # Jobs history — last 10 entries
        jobs_history: list = []
        jobs_history_file = results_dir / ".jobs-history.json"
        if jobs_history_file.exists():
            try:
                with open(jobs_history_file) as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    jobs_history = raw[-10:]
                elif isinstance(raw, dict):
                    jobs_history = raw.get("history", [])[-10:]
            except (json.JSONDecodeError, OSError):
                jobs_history = []

        # Overnight
        stop_file = results_dir / ".overnight-stop"
        overnight_plan: dict | None = None
        plan_file = results_dir / "overnight-plan.json"
        if plan_file.exists():
            try:
                with open(plan_file) as f:
                    overnight_plan = json.load(f)
            except (json.JSONDecodeError, OSError):
                overnight_plan = None

        overnight_history: list = []
        history_file = results_dir / "overnight-history.json"
        if history_file.exists():
            try:
                with open(history_file) as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    overnight_history = raw[-5:]
                elif isinstance(raw, dict):
                    overnight_history = raw.get("history", [])[-5:]
            except (json.JSONDecodeError, OSError):
                overnight_history = []

        task_queue = _read_json(results_dir / "task-queue.json")
        if not isinstance(task_queue, dict):
            task_queue = {"generated_at": None, "summary": {"total": 0}, "tasks": []}

        # Backends
        backends: dict = {}
        try:
            from backoffice.backends import get_backend  # noqa: PLC0415
            from backoffice.config import load_config  # noqa: PLC0415
            cfg = load_config()
            for name, backend_cfg in cfg.agent_backends.items():
                be = get_backend(name, {
                    "command": backend_cfg.command,
                    "model": backend_cfg.model,
                    "mode": backend_cfg.mode,
                    "local_budget": backend_cfg.local_budget,
                })
                health = be.health_check()
                caps = be.capabilities()
                limits = be.check_limits()
                backends[name] = {
                    "healthy": health.healthy,
                    "status": limits.status,
                    "capabilities": asdict(caps),
                    "limits": asdict(limits),
                }
        except Exception as exc:
            logger.warning("Could not load backends for ops/status: %s", exc)
            # Fall back to showing known backends as unavailable
            for name in ("claude", "codex"):
                backends[name] = {
                    "healthy": False,
                    "status": "unavailable",
                    "capabilities": {},
                    "limits": {},
                }

        # Targets — load from config
        targets: list = []
        try:
            from backoffice.config import load_config  # noqa: PLC0415
            cfg = load_config()
            for name, target in cfg.targets.items():
                targets.append({
                    "name": name,
                    "path": target.path,
                    "language": target.language,
                    "departments": target.default_departments,
                })
        except Exception as exc:
            logger.warning("Could not load targets for ops/status: %s", exc)

        self._json_response(200, {
            "jobs": jobs,
            "jobs_history": jobs_history,
            "overnight": {
                "running": False,  # Best-effort: no PID tracking currently
                "stop_file_exists": stop_file.exists(),
                "plan": overnight_plan,
                "history": overnight_history,
            },
            "task_queue": task_queue,
            "backends": backends,
            "targets": targets,
        })

    def _handle_ops_backends(self) -> None:
        """GET /api/ops/backends — backend health and routing info."""
        backends: dict = {}
        routing_policy: dict = {}
        try:
            from backoffice.backends import get_backend  # noqa: PLC0415
            from backoffice.config import load_config  # noqa: PLC0415
            cfg = load_config()
            routing_policy = dict(cfg.routing_policy.fallback_order)
            for name, backend_cfg in cfg.agent_backends.items():
                be = get_backend(name, {
                    "command": backend_cfg.command,
                    "model": backend_cfg.model,
                    "mode": backend_cfg.mode,
                    "local_budget": backend_cfg.local_budget,
                })
                health = be.health_check()
                caps = be.capabilities()
                limits = be.check_limits()
                backends[name] = {
                    "healthy": health.healthy,
                    "capabilities": asdict(caps),
                    "limits": asdict(limits),
                }
        except Exception as exc:
            logger.warning("Could not load backends for ops/backends: %s", exc)
            self._json_response(500, {"error": f"Failed to load backends: {exc}"})
            return

        self._json_response(200, {
            "backends": backends,
            "routing_policy": routing_policy,
        })

    # ------------------------------------------------------------------
    # Ops POST handlers
    # ------------------------------------------------------------------

    def _handle_ops_audit(self) -> None:
        """POST /api/ops/audit — trigger an audit run."""
        body = self._read_body()
        if not body:
            self._json_response(400, {"error": "Request body required"})
            return

        target_name = (body.get("target") or "").strip()
        if not target_name:
            self._json_response(400, {"error": "target is required"})
            return

        departments: list[str] = body.get("departments") or ALL_DEPTS
        if isinstance(departments, str):
            departments = [d.strip() for d in departments.split(",") if d.strip()]
        invalid_depts = [d for d in departments if d not in DEPT_SCRIPTS]
        if invalid_depts:
            self._json_response(400, {
                "error": f"Unknown departments: {', '.join(invalid_depts)}",
                "valid": ALL_DEPTS,
            })
            return

        mode = (body.get("mode") or "parallel").strip()
        if mode not in ("parallel", "sequential", "full-scan"):
            self._json_response(400, {
                "error": f"Invalid mode: {mode}",
                "valid": ["parallel", "sequential", "full-scan"],
            })
            return

        # Resolve target path from config
        target_path = ""
        try:
            from backoffice.config import load_config  # noqa: PLC0415
            cfg = load_config()
            t = cfg.targets.get(target_name)
            if t and t.path:
                target_path = t.path
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

        if not target_path:
            self._json_response(400, {
                "error": f"Unknown target: {target_name}. Register it in config/backoffice.yaml",
            })
            return

        # Build the make command
        if mode == "parallel":
            make_target = "audit-all-parallel"
        elif mode == "full-scan":
            make_target = "full-scan"
        else:
            make_target = "audit-all"

        cmd_str = f"make {make_target} TARGET={target_path}"

        try:
            subprocess.Popen(
                ["make", make_target, f"TARGET={target_path}"],
                cwd=str(self._root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._json_response(500, {"error": f"Failed to launch audit: {exc}"})
            return

        logger.info("ops/audit started: %s", cmd_str)
        self._json_response(200, {
            "status": "started",
            "command": cmd_str,
            "target": target_name,
            "target_path": target_path,
            "departments": departments,
            "mode": mode,
        })

    def _handle_ops_overnight_start(self) -> None:
        """POST /api/ops/overnight/start — start the overnight loop."""
        body = self._read_body()

        interval = int(body.get("interval") or 120)
        targets_str = (body.get("targets") or "").strip()
        dry_run = bool(body.get("dry_run", False))

        overnight_script = self._root / "scripts" / "overnight.sh"
        if not overnight_script.exists():
            self._json_response(500, {"error": "scripts/overnight.sh not found"})
            return

        cmd_parts = ["bash", str(overnight_script), "--interval", str(interval)]
        if targets_str:
            cmd_parts += ["--targets", targets_str]
        if dry_run:
            cmd_parts.append("--dry-run")

        cmd_str = " ".join(cmd_parts)

        try:
            subprocess.Popen(
                cmd_parts,
                cwd=str(self._root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._json_response(500, {"error": f"Failed to launch overnight loop: {exc}"})
            return

        logger.info("ops/overnight/start: %s", cmd_str)
        self._json_response(200, {
            "status": "started",
            "command": cmd_str,
            "interval": interval,
            "targets": targets_str or "all",
            "dry_run": dry_run,
        })

    def _handle_ops_overnight_stop(self) -> None:
        """POST /api/ops/overnight/stop — stop the overnight loop gracefully."""
        stop_file = self._root / "results" / ".overnight-stop"
        try:
            stop_file.parent.mkdir(parents=True, exist_ok=True)
            stop_file.touch()
        except OSError as exc:
            self._json_response(500, {"error": f"Failed to create stop file: {exc}"})
            return

        logger.info("ops/overnight/stop: stop file created at %s", stop_file)
        self._json_response(200, {
            "status": "stop_requested",
            "stop_file": str(stop_file),
            "message": "Overnight loop will stop after the current phase completes.",
        })

    def _task_queue_context(self):
        from backoffice.tasks import load_context  # noqa: PLC0415

        return load_context(
            self._root / "config" / "task-queue.yaml",
            self._root / "config" / "targets.yaml",
            self._root / "results",
            self._root / "dashboard",
        )

    def _save_task_queue(self, context) -> dict:
        from backoffice.tasks import save_payload  # noqa: PLC0415

        return save_payload(
            context.payload,
            context.targets,
            context.config_path,
            context.results_dir,
            context.dashboard_dir,
        )

    def _task_response(self, task: dict, message: str, status: int = 200) -> None:
        self._json_response(status, {"ok": True, "message": message, "task": task})

    def _add_product_from_payload(self, body: dict) -> dict:
        name = (body.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")

        source = (body.get("source") or "local").strip()
        github_repo = (body.get("github_repo") or "").strip()
        local_path = (body.get("local_path") or "").strip()
        language = (body.get("language") or "").strip()
        departments: list[str] = body.get("departments") or ALL_DEPTS
        if isinstance(departments, str):
            departments = [d.strip() for d in departments.split(",") if d.strip()]
        autonomy: dict = body.get("autonomy") or {}

        if source in ("github", "both"):
            if not github_repo:
                raise ValueError("github_repo is required when source is 'github' or 'both'")
            clone_dest = local_path or str(Path.home() / "projects" / name)
            clone_dest_path = Path(clone_dest)
            if not clone_dest_path.exists():
                try:
                    result = subprocess.run(
                        ["gh", "repo", "clone", github_repo, clone_dest],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        result = subprocess.run(
                            ["git", "clone", f"https://github.com/{github_repo}.git", clone_dest],
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                    if result.returncode != 0:
                        raise OSError(f"Clone failed: {result.stderr.strip()}")
                except subprocess.TimeoutExpired as exc:
                    raise OSError("Clone timed out after 120s") from exc
            resolved_path = clone_dest
        else:
            resolved_path = local_path or str(Path.home() / "projects" / name)

        depts_yaml = ", ".join(f'"{d}"' for d in departments)
        autonomy_block = ""
        if autonomy:
            lines = ["    autonomy:"]
            for k, v in autonomy.items():
                lines.append(f"      {k}: {'true' if v else 'false'}")
            autonomy_block = "\n" + "\n".join(lines)

        new_entry = (
            f"\n  {name}:\n"
            f"    path: {resolved_path}\n"
            f"    language: {language or 'unknown'}\n"
            f"    default_departments: [{depts_yaml}]\n"
            f"    lint_command: \"\"\n"
            f"    test_command: \"\"\n"
            f"    deploy_command: \"\"\n"
            f"    context: |\n"
            f"      {name} — added via Back Office approval workflow.\n"
            f"{autonomy_block}"
        )

        config_path = self._root / "config" / "backoffice.yaml"
        with open(config_path, "a", encoding="utf-8") as f:
            f.write(new_entry)

        return {
            "status": "added",
            "name": name,
            "path": resolved_path,
            "language": language or "unknown",
            "departments": departments,
        }

    def _handle_task_queue_finding(self) -> None:
        """POST /api/tasks/queue-finding — queue a finding for human approval."""
        body = self._read_body()
        finding = body.get("finding") if isinstance(body.get("finding"), dict) else body
        if not finding or not (finding.get("title") or "").strip() or not (finding.get("repo") or "").strip():
            self._json_response(400, {"error": "finding title and repo are required"})
            return

        from backoffice.tasks import create_finding_task, ensure_task_defaults  # noqa: PLC0415

        context = self._task_queue_context()
        task, created = create_finding_task(context, finding, actor=(body.get("by") or "dashboard"))
        payload = self._save_task_queue(context)
        task = ensure_task_defaults(task, context.targets)
        self._json_response(200 if created else 409, {
            "ok": created,
            "created": created,
            "task": task,
            "summary": payload.get("summary", {}),
            "message": "Finding queued for approval." if created else "Finding already exists in queue.",
        })

    def _handle_task_approve(self) -> None:
        """POST /api/tasks/approve — approve a queue item for human-reviewed execution."""
        body = self._read_body()
        task_id = (body.get("id") or "").strip()
        if not task_id:
            self._json_response(400, {"error": "id is required"})
            return

        from backoffice.tasks import append_history, find_task, iso_now  # noqa: PLC0415

        context = self._task_queue_context()
        task = find_task(context.payload.setdefault("tasks", []), task_id)
        actor = (body.get("by") or "operator").strip()
        note = (body.get("note") or "Approved for queued implementation").strip()
        task["status"] = "ready"
        task["updated_at"] = iso_now()
        task["approval"] = {
            **task.get("approval", {}),
            "approved_at": iso_now(),
            "approved_by": actor,
            "note": note,
        }
        append_history(task, "ready", actor, note)
        self._save_task_queue(context)
        self._task_response(task, "Task approved and moved to ready queue.")

    def _handle_task_cancel(self) -> None:
        """POST /api/tasks/cancel — reject or cancel a queue item."""
        body = self._read_body()
        task_id = (body.get("id") or "").strip()
        if not task_id:
            self._json_response(400, {"error": "id is required"})
            return

        from backoffice.tasks import append_history, find_task, iso_now  # noqa: PLC0415

        context = self._task_queue_context()
        task = find_task(context.payload.setdefault("tasks", []), task_id)
        actor = (body.get("by") or "operator").strip()
        note = (body.get("note") or "Cancelled during approval review").strip()
        task["status"] = "cancelled"
        task["updated_at"] = iso_now()
        append_history(task, "cancelled", actor, note)
        self._save_task_queue(context)
        self._task_response(task, "Task cancelled.")

    def _handle_task_request_pr(self) -> None:
        """POST /api/tasks/request-pr — create a draft GitHub PR for approval."""
        body = self._read_body()
        task_id = (body.get("id") or "").strip()
        if not task_id:
            self._json_response(400, {"error": "id is required"})
            return

        from backoffice.tasks import append_history, find_task, iso_now  # noqa: PLC0415

        context = self._task_queue_context()
        task = find_task(context.payload.setdefault("tasks", []), task_id)
        repo_path = task.get("target_path") or ""
        if not repo_path or not Path(repo_path).exists():
            self._json_response(400, {"error": f"task target_path is missing or does not exist: {repo_path}"})
            return

        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._json_response(500, {"error": f"Could not determine current branch: {exc}"})
            return

        branch = branch_result.stdout.strip()
        if branch_result.returncode != 0 or not branch:
            self._json_response(500, {"error": branch_result.stderr.strip() or "Could not determine current branch"})
            return
        if branch in {"main", "master"}:
            self._json_response(409, {"error": "Refusing to create PR from default branch. Use a review branch first."})
            return

        pr_title = (body.get("title") or f"Review: {task.get('title', 'Queued work')}").strip()
        pr_body = (body.get("body") or "").strip()
        if not pr_body:
            pr_body = (
                "## Approval Request\n"
                f"- Task: {task.get('id')}\n"
                f"- Repo: {task.get('repo')}\n"
                f"- Status: {task.get('status')}\n"
                "\n"
                "This PR was opened from the Back Office human approval workflow and requires GitHub review before merge."
            )

        try:
            pr_result = subprocess.run(
                ["gh", "pr", "create", "--draft", "--title", pr_title, "--body", pr_body],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._json_response(500, {"error": f"Failed to create GitHub PR: {exc}"})
            return

        if pr_result.returncode != 0:
            self._json_response(500, {"error": pr_result.stderr.strip() or "gh pr create failed"})
            return

        pr_url = pr_result.stdout.strip().splitlines()[-1] if pr_result.stdout.strip() else ""
        task["status"] = "pr_open"
        task["updated_at"] = iso_now()
        task["pr"] = {
            "url": pr_url,
            "title": pr_title,
            "branch": branch,
            "created_at": iso_now(),
        }
        append_history(task, "pr_open", body.get("by") or "operator", f"Draft PR opened on branch {branch}")
        self._save_task_queue(context)
        self._json_response(200, {"ok": True, "task": task, "pr_url": pr_url})

    def _handle_ops_product_suggest(self) -> None:
        """POST /api/ops/product/suggest — submit a product suggestion for approval."""
        body = self._read_body()
        if not (body.get("name") or "").strip():
            self._json_response(400, {"error": "name is required"})
            return

        from backoffice.tasks import create_product_suggestion_task  # noqa: PLC0415

        context = self._task_queue_context()
        task = create_product_suggestion_task(context, body, actor=(body.get("by") or "product-owner"))
        self._save_task_queue(context)
        self._task_response(task, "Product suggestion queued for human approval.")

    def _handle_ops_product_approve(self) -> None:
        """POST /api/ops/product/approve — approve and add a suggested product."""
        body = self._read_body()
        task_id = (body.get("id") or "").strip()
        if not task_id:
            self._json_response(400, {"error": "id is required"})
            return

        from backoffice.tasks import append_history, find_task, iso_now  # noqa: PLC0415

        context = self._task_queue_context()
        task = find_task(context.payload.setdefault("tasks", []), task_id)
        suggestion = task.get("approval", {}).get("suggested_product", {})
        if not isinstance(suggestion, dict) or not suggestion.get("name"):
            self._json_response(400, {"error": "task does not contain a suggested product payload"})
            return

        payload = dict(suggestion)
        payload.update({k: v for k, v in body.items() if k not in {"id", "by", "note"}})
        try:
            add_result = self._add_product_from_payload(payload)
        except (OSError, ValueError) as exc:
            self._json_response(500, {"error": str(exc)})
            return

        actor = (body.get("by") or "operator").strip()
        note = (body.get("note") or "Approved product suggestion and added target").strip()
        task["status"] = "approved"
        task["updated_at"] = iso_now()
        task["approval"] = {
            **task.get("approval", {}),
            "approved_at": iso_now(),
            "approved_by": actor,
            "activation": add_result,
        }
        append_history(task, "approved", actor, note)
        self._save_task_queue(context)
        self._json_response(200, {"ok": True, "task": task, "product": add_result})

    def _handle_ops_product_add(self) -> None:
        """POST /api/ops/product/add — add a new product/target."""
        body = self._read_body()
        if not body:
            self._json_response(400, {"error": "Request body required"})
            return
        try:
            result = self._add_product_from_payload(body)
        except ValueError as exc:
            self._json_response(400, {"error": str(exc)})
            return
        except OSError as exc:
            self._json_response(500, {"error": str(exc)})
            return

        logger.info("ops/product/add: added target %s at %s", result["name"], result["path"])
        self._json_response(200, {
            **result,
            "next_steps": [
                f"Run initial audit: make audit-all-parallel TARGET={result['path']}",
                "Refresh dashboard: python -m backoffice refresh",
            ],
        })

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Suppress noisy polling logs for .jobs.json."""
        first_arg = str(args[0]) if args else ""
        if ".jobs.json" in first_arg:
            return
        logger.debug("HTTP %s", format % args)


# ---------------------------------------------------------------------------
# Factory — creates a handler class bound to a specific runtime config
# ---------------------------------------------------------------------------

def create_handler(
    root: Path,
    target_repo: str,
    allowed_origins: set[str],
) -> type[DashboardHandler]:
    """Return a DashboardHandler subclass pre-configured for the given runtime."""

    class _Handler(DashboardHandler):
        _root = root
        _target_repo = target_repo
        _allowed_origins = allowed_origins

    return _Handler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(port: int = 8070, target: str | None = None) -> int:
    """Start the local dashboard dev server.

    Parameters
    ----------
    port:
        TCP port to listen on (default 8070).
    target:
        Absolute path to the target repository.  When *None* the server
        still starts but ``/api/run-scan`` will return 400 until a target
        is provided.
    """
    # Try to pull allowed_origins from the package config; fall back to
    # the built-in localhost defaults so the server works without a config.
    try:
        from backoffice.config import load_config  # noqa: PLC0415
        cfg = load_config()
        allowed_origins: set[str] = set(cfg.api.allowed_origins) or {
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        }
        root = cfg.root
    except Exception:
        allowed_origins = {
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        }
        root = Path(__file__).resolve().parents[1]

    target_repo = ""
    if target:
        target_repo = str(Path(target).resolve())
        logger.info("Target repo: %s", target_repo)
    else:
        logger.info(
            "No TARGET specified — Run Scan buttons will prompt for one. "
            "Usage: python -m backoffice serve --target /path/to/repo"
        )

    logger.info("Dashboard server: http://localhost:%d/", port)
    logger.info("Jobs dashboard:   http://localhost:%d/jobs.html", port)
    logger.info("HQ dashboard:     http://localhost:%d/index.html", port)

    handler_cls = create_handler(root, target_repo, allowed_origins)
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    logger.info("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped.")
    return 0
