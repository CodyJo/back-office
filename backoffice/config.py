"""Unified configuration loader for the backoffice package.

Loads config/backoffice.yaml into a frozen dataclass hierarchy.
Replaces: config/targets.yaml, config/qa-config.yaml,
          config/api-config.yaml, config/agent-runner.env
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when config is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class RunnerConfig:
    command: str = "codex"
    mode: str = "stdin-text"


@dataclass(frozen=True)
class BackendConfig:
    enabled: bool = True
    command: str = ""
    model: str = ""
    mode: str = ""
    local_budget: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingPolicy:
    fallback_order: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ApiConfig:
    port: int = 8070
    api_key: str = ""
    allowed_origins: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardTarget:
    cdn_id: str = ""
    base_path: str = ""
    subdomain: str = ""
    filter_repo: str | None = None
    allow_public_read: bool = False


@dataclass(frozen=True)
class BunnyConfig:
    storage_zone: str = ""
    storage_region: str = "ny"
    storage_key: str | None = None
    dashboard_targets: list[DashboardTarget] = field(default_factory=list)


@dataclass(frozen=True)
class DeployConfig:
    provider: str = "bunny"
    bunny: BunnyConfig = field(default_factory=BunnyConfig)

    @property
    def dashboard_targets(self) -> list[DashboardTarget]:
        """Return dashboard targets for the active provider."""
        if self.provider == "bunny":
            return self.bunny.dashboard_targets
        return []


@dataclass(frozen=True)
class ScanConfig:
    run_linter: bool = True
    run_tests: bool = True
    security_audit: bool = True
    performance_review: bool = True
    code_quality: bool = True
    min_severity: str = "low"
    max_findings: int = 200
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FixConfig:
    auto_fix_severity: str = "high"
    run_tests_after_fix: bool = True
    run_linter_after_fix: bool = True
    max_parallel_fixes: int = 4
    auto_commit: bool = True
    auto_push: bool = False


@dataclass(frozen=True)
class NotificationsConfig:
    sync_to_storage: bool = True


VALID_DEPLOY_MODES = ("disabled", "manual", "staging-only", "production-allowed")


@dataclass(frozen=True)
class Autonomy:
    """Per-target autonomy policy for the overnight loop.

    Conservative defaults match MASTER-PROMPT.md §Per-Target Autonomy Policy:
    fixes allowed; feature dev, auto-merge, auto-deploy, and production
    deploys all OFF unless the target explicitly opts in.
    """
    allow_fix: bool = True
    allow_feature_dev: bool = False
    allow_auto_commit: bool = True
    allow_auto_merge: bool = False
    allow_auto_deploy: bool = False
    require_clean_worktree: bool = True
    require_tests: bool = True
    max_changes_per_cycle: int = 3
    deploy_mode: str = "disabled"

    def __post_init__(self):
        if self.deploy_mode not in VALID_DEPLOY_MODES:
            raise ValueError(
                f"deploy_mode must be one of {VALID_DEPLOY_MODES}, got: {self.deploy_mode!r}"
            )


@dataclass(frozen=True)
class Target:
    path: str = ""
    language: str = ""
    default_departments: list[str] = field(default_factory=list)
    lint_command: str = ""
    test_command: str = ""
    coverage_command: str = ""
    deploy_command: str = ""
    context: str = ""
    autonomy: Autonomy = field(default_factory=Autonomy)


@dataclass(frozen=True)
class Config:
    root: Path = field(default_factory=lambda: Path.cwd())
    runner: RunnerConfig = field(default_factory=RunnerConfig)
    agent_backends: dict[str, BackendConfig] = field(default_factory=dict)
    routing_policy: RoutingPolicy = field(default_factory=RoutingPolicy)
    api: ApiConfig = field(default_factory=ApiConfig)
    deploy: DeployConfig = field(default_factory=DeployConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    fix: FixConfig = field(default_factory=FixConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    targets: dict[str, Target] = field(default_factory=dict)


REQUIRED_SECTIONS = ("runner", "deploy", "targets")


def _build_autonomy(raw: dict | None) -> Autonomy:
    """Build an Autonomy block from a raw mapping, applying conservative defaults.

    Unknown fields are ignored; invalid values raise ConfigError via
    Autonomy.__post_init__. ``None`` or missing yields the default policy.
    """
    if not raw or not isinstance(raw, dict):
        return Autonomy()
    kwargs = {}
    bool_fields = (
        "allow_fix", "allow_feature_dev", "allow_auto_commit",
        "allow_auto_merge", "allow_auto_deploy",
        "require_clean_worktree", "require_tests",
    )
    for name in bool_fields:
        if name in raw:
            kwargs[name] = bool(raw[name])
    if "max_changes_per_cycle" in raw:
        kwargs["max_changes_per_cycle"] = int(raw["max_changes_per_cycle"])
    if "deploy_mode" in raw:
        kwargs["deploy_mode"] = str(raw["deploy_mode"])
    try:
        return Autonomy(**kwargs)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _build_targets(raw: dict) -> dict[str, Target]:
    targets = {}
    for name, data in (raw or {}).items():
        if not isinstance(data, dict):
            continue
        deps = data.get("default_departments", [])
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",")]
        try:
            autonomy = _build_autonomy(data.get("autonomy"))
        except ConfigError as exc:
            raise ConfigError(f"Target {name!r}: {exc}") from exc
        targets[name] = Target(
            path=str(data.get("path", "")),
            language=str(data.get("language", "")),
            default_departments=deps,
            lint_command=str(data.get("lint_command", "")),
            test_command=str(data.get("test_command", "")),
            coverage_command=str(data.get("coverage_command", "")),
            deploy_command=str(data.get("deploy_command", "")),
            context=str(data.get("context", "")),
            autonomy=autonomy,
        )
    return targets


def _build_bunny_dashboard_targets(raw: list | None) -> list[DashboardTarget]:
    if not raw:
        return []
    return [
        DashboardTarget(
            cdn_id=str(t.get("cdn_id", t.get("pull_zone_id", ""))),
            base_path=str(t.get("base_path", "")),
            subdomain=str(t.get("subdomain", "")),
            filter_repo=t.get("filter_repo"),
            allow_public_read=bool(t.get("allow_public_read", False)),
        )
        for t in raw
        if isinstance(t, dict)
    ]


def _build_agent_backends(
    raw: dict | None, runner_raw: dict
) -> dict[str, BackendConfig]:
    """Build agent_backends from explicit config or fall back to runner: compat."""
    if raw and isinstance(raw, dict):
        backends = {}
        for name, data in raw.items():
            if not isinstance(data, dict):
                continue
            backends[name] = BackendConfig(
                enabled=bool(data.get("enabled", True)),
                command=str(data.get("command", "")),
                model=str(data.get("model", "")),
                mode=str(data.get("mode", "")),
                local_budget=dict(data.get("local_budget", {})),
            )
        return backends

    # Backward compat: synthesize a single backend from legacy runner: section
    runner_cmd = str(runner_raw.get("command", "codex"))
    runner_mode = str(runner_raw.get("mode", "stdin-text"))
    runner_bin = runner_cmd.split()[0] if runner_cmd else "codex"

    # Detect which backend type from the runner binary name
    if runner_bin == "codex":
        backend_name = "codex"
    else:
        backend_name = "claude"

    return {
        backend_name: BackendConfig(
            enabled=True,
            command=runner_cmd,
            model="",
            mode=runner_mode,
            local_budget={},
        )
    }


def load_config(path: Path | None = None) -> Config:
    if path is None:
        override = os.environ.get("BACK_OFFICE_CONFIG")
        if override:
            path = Path(override)
        else:
            root = Path(os.environ.get("BACK_OFFICE_ROOT", Path(__file__).resolve().parents[1]))
            path = root / "config" / "backoffice.yaml"

    if not path.exists():
        raise ConfigError(
            f"Config not found at {path} — run 'python -m backoffice setup' to create one"
        )

    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config at {path} is malformed YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config at {path} is malformed — expected a YAML mapping")

    missing = [s for s in REQUIRED_SECTIONS if s not in raw]
    if missing:
        raise ConfigError(
            f"Config at {path} is missing required sections: {', '.join(missing)}"
        )

    runner_raw = raw.get("runner", {}) or {}
    api_raw = raw.get("api", {}) or {}
    deploy_raw = raw.get("deploy", {}) or {}
    bunny_raw = deploy_raw.get("bunny", {}) or {}
    scan_raw = raw.get("scan", {}) or {}
    fix_raw = raw.get("fix", {}) or {}
    notif_raw = raw.get("notifications", {}) or {}

    root = Path(os.environ.get(
        "BACK_OFFICE_ROOT",
        str(path.resolve().parents[1]),
    ))

    targets = _build_targets(raw.get("targets"))

    for name, target in targets.items():
        if target.path and not Path(target.path).exists():
            logger.warning("Target '%s' path does not exist: %s", name, target.path)

    # Parse agent_backends — fall back to constructing from runner: for compat
    agent_backends = _build_agent_backends(
        raw.get("agent_backends"), runner_raw
    )

    # Parse routing_policy
    routing_policy_raw = raw.get("routing_policy", {}) or {}
    routing_policy = RoutingPolicy(
        fallback_order=dict(routing_policy_raw.get("fallback_order", {})),
    )

    return Config(
        root=root,
        runner=RunnerConfig(
            command=str(runner_raw.get("command", "claude")),
            mode=str(runner_raw.get("mode", "claude-print")),
        ),
        agent_backends=agent_backends,
        routing_policy=routing_policy,
        api=ApiConfig(
            port=int(api_raw.get("port", 8070)),
            api_key=str(api_raw.get("api_key", "")) or os.environ.get("BACKOFFICE_API_KEY", ""),
            allowed_origins=list(api_raw.get("allowed_origins", [])),
        ),
        deploy=DeployConfig(
            provider=str(deploy_raw.get("provider", "bunny")),
            bunny=BunnyConfig(
                storage_zone=str(bunny_raw.get("storage_zone", "")),
                storage_region=str(bunny_raw.get("storage_region", "ny")),
                storage_key=bunny_raw.get("storage_key"),
                dashboard_targets=_build_bunny_dashboard_targets(
                    bunny_raw.get("dashboard_targets")
                ),
            ),
        ),
        scan=ScanConfig(
            run_linter=bool(scan_raw.get("run_linter", True)),
            run_tests=bool(scan_raw.get("run_tests", True)),
            security_audit=bool(scan_raw.get("security_audit", True)),
            performance_review=bool(scan_raw.get("performance_review", True)),
            code_quality=bool(scan_raw.get("code_quality", True)),
            min_severity=str(scan_raw.get("min_severity", "low")),
            max_findings=int(scan_raw.get("max_findings", 200)),
            exclude_patterns=list(scan_raw.get("exclude_patterns", [])),
        ),
        fix=FixConfig(
            auto_fix_severity=str(fix_raw.get("auto_fix_severity", "high")),
            run_tests_after_fix=bool(fix_raw.get("run_tests_after_fix", True)),
            run_linter_after_fix=bool(fix_raw.get("run_linter_after_fix", True)),
            max_parallel_fixes=int(fix_raw.get("max_parallel_fixes", 4)),
            auto_commit=bool(fix_raw.get("auto_commit", True)),
            auto_push=bool(fix_raw.get("auto_push", False)),
        ),
        notifications=NotificationsConfig(
            sync_to_storage=bool(notif_raw.get("sync_to_storage", True)),
        ),
        targets=targets,
    )


_SHELL_UNSAFE = re.compile(r'[;|&`$(){}!\\\n\r]')


def is_shell_safe(value: str) -> bool:
    if not value:
        return True
    return not _SHELL_UNSAFE.search(value)


def shell_export(config: Config, target_name: str | None = None,
                 fields: list[str] | None = None) -> str:
    if target_name and fields:
        target = config.targets.get(target_name)
        if not target:
            return "\0".join([""] * len(fields))
        values = []
        for f in fields:
            raw = getattr(target, f, "")
            val = str(raw) if raw else ""
            if not is_shell_safe(val):
                logger.warning("Rejected unsafe config value for field %s: %r", f, val)
                val = ""
            values.append(val)
        return "\0".join(values)

    lines = [
        f'BACK_OFFICE_AGENT_RUNNER="{config.runner.command}"',
        f'BACK_OFFICE_AGENT_MODE="{config.runner.mode}"',
    ]
    return "\n".join(lines)
