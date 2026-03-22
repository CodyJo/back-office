"""Unified configuration loader for the backoffice package.

Loads config/backoffice.yaml into a frozen dataclass hierarchy.
Replaces: config/targets.yaml, config/qa-config.yaml,
          config/api-config.yaml, config/agent-runner.env
"""
from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when config is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class RunnerConfig:
    command: str = "claude"
    mode: str = "claude-print"


@dataclass(frozen=True)
class ApiConfig:
    port: int = 8070
    api_key: str = ""
    allowed_origins: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardTarget:
    bucket: str = ""
    base_path: str = ""
    distribution_id: str = ""
    subdomain: str = ""
    filter_repo: str | None = None
    allow_public_read: bool = False


@dataclass(frozen=True)
class AWSConfig:
    region: str = "us-east-1"
    dashboard_targets: list[DashboardTarget] = field(default_factory=list)


@dataclass(frozen=True)
class DeployConfig:
    provider: str = "aws"
    aws: AWSConfig = field(default_factory=AWSConfig)


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
    sync_to_s3: bool = True


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


@dataclass(frozen=True)
class Config:
    root: Path = field(default_factory=lambda: Path.cwd())
    runner: RunnerConfig = field(default_factory=RunnerConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    deploy: DeployConfig = field(default_factory=DeployConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    fix: FixConfig = field(default_factory=FixConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    targets: dict[str, Target] = field(default_factory=dict)


REQUIRED_SECTIONS = ("runner", "deploy", "targets")


def _build_targets(raw: dict) -> dict[str, Target]:
    targets = {}
    for name, data in (raw or {}).items():
        if not isinstance(data, dict):
            continue
        deps = data.get("default_departments", [])
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",")]
        targets[name] = Target(
            path=str(data.get("path", "")),
            language=str(data.get("language", "")),
            default_departments=deps,
            lint_command=str(data.get("lint_command", "")),
            test_command=str(data.get("test_command", "")),
            coverage_command=str(data.get("coverage_command", "")),
            deploy_command=str(data.get("deploy_command", "")),
            context=str(data.get("context", "")),
        )
    return targets


def _build_dashboard_targets(raw: list | None) -> list[DashboardTarget]:
    if not raw:
        return []
    return [
        DashboardTarget(
            bucket=str(t.get("bucket", "")),
            base_path=str(t.get("base_path", "")),
            distribution_id=str(t.get("distribution_id", "")),
            subdomain=str(t.get("subdomain", "")),
            filter_repo=t.get("filter_repo"),
            allow_public_read=bool(t.get("allow_public_read", False)),
        )
        for t in raw
        if isinstance(t, dict)
    ]


def load_config(path: Path | None = None) -> Config:
    if path is None:
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
    aws_raw = deploy_raw.get("aws", {}) or {}
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

    return Config(
        root=root,
        runner=RunnerConfig(
            command=str(runner_raw.get("command", "claude")),
            mode=str(runner_raw.get("mode", "claude-print")),
        ),
        api=ApiConfig(
            port=int(api_raw.get("port", 8070)),
            api_key=str(api_raw.get("api_key", "")),
            allowed_origins=list(api_raw.get("allowed_origins", [])),
        ),
        deploy=DeployConfig(
            provider=str(deploy_raw.get("provider", "aws")),
            aws=AWSConfig(
                region=str(aws_raw.get("region", "us-east-1")),
                dashboard_targets=_build_dashboard_targets(
                    aws_raw.get("dashboard_targets")
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
            sync_to_s3=bool(notif_raw.get("sync_to_s3", True)),
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
