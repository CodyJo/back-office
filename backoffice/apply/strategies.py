"""Fix strategy resolver: finding → how to apply a fix.

A strategy is a function that mutates a worktree. Strategies are
deterministic (a tool flag like ``ruff --fix``) or AI-delegated
(invoke the existing Fix Agent against the worktree). ``manual``
strategies do nothing — they exist so the resolver always returns a
strategy and the caller can record "skipped: not auto-fixable".

We deliberately keep the registry as a flat dict of plain functions —
six entries today, room for ~20 before this needs to become a class
hierarchy.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ApplyContext:
    finding: dict
    repo_path: str  # the WORKTREE path (not the original target dir)
    target_name: str


@dataclass
class ApplyResult:
    success: bool
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""


@dataclass
class FixStrategy:
    name: str
    kind: str  # "deterministic" | "ai" | "manual"
    description: str
    apply: Callable[[ApplyContext], ApplyResult] | None  # None for "manual"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _run(cmd: list[str], cwd: str, *, timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _git_changed_files(cwd: str) -> list[str]:
    rc, out, _ = _run(["git", "diff", "--name-only"], cwd=cwd)
    if rc != 0:
        return []
    return [line for line in out.splitlines() if line.strip()]


# ──────────────────────────────────────────────────────────────────────
# Strategy implementations
# ──────────────────────────────────────────────────────────────────────


def _apply_ruff_fix(ctx: ApplyContext) -> ApplyResult:
    if not shutil.which("ruff"):
        return ApplyResult(False, error="ruff binary not in PATH")
    file_path = ctx.finding.get("file") or ""
    rule_id = ctx.finding.get("rule_id") or ""
    args = ["ruff", "check", "--fix-only", "--exit-zero"]
    if rule_id:
        args += ["--select", rule_id]
    if file_path:
        args.append(file_path)
    else:
        args.append(".")
    rc, out, err = _run(args, cwd=ctx.repo_path)
    if rc != 0:
        return ApplyResult(False, error=(err.strip() or out.strip() or f"exit {rc}")[:500])
    changed = _git_changed_files(ctx.repo_path)
    if not changed:
        return ApplyResult(False, error=f"ruff --fix made no changes for rule {rule_id} in {file_path}")
    return ApplyResult(True, files_changed=changed, summary=f"ruff --fix applied {rule_id}")


def _apply_npm_audit_fix(ctx: ApplyContext) -> ApplyResult:
    if not shutil.which("npm"):
        return ApplyResult(False, error="npm binary not in PATH")
    rc, out, err = _run(["npm", "audit", "fix", "--no-fund", "--no-audit"], cwd=ctx.repo_path, timeout=300)
    if rc != 0:
        return ApplyResult(False, error=(err.strip() or out.strip() or f"exit {rc}")[:500])
    changed = _git_changed_files(ctx.repo_path)
    if not changed:
        return ApplyResult(False, error="npm audit fix made no changes")
    return ApplyResult(True, files_changed=changed, summary="npm audit fix applied")


def _apply_semgrep_autofix(ctx: ApplyContext) -> ApplyResult:
    if not shutil.which("semgrep"):
        return ApplyResult(False, error="semgrep binary not in PATH")
    rule_id = ctx.finding.get("rule_id") or ""
    file_path = ctx.finding.get("file") or "."
    args = ["semgrep", "scan", "--config", "auto", "--autofix", "--quiet"]
    if rule_id:
        args += ["--include", file_path]
    else:
        args.append(file_path)
    rc, _out, err = _run(args, cwd=ctx.repo_path, timeout=300)
    changed = _git_changed_files(ctx.repo_path)
    if not changed:
        return ApplyResult(False, error="semgrep --autofix made no changes")
    if rc not in (0, 1):
        return ApplyResult(False, error=err.strip()[:500] or f"exit {rc}")
    return ApplyResult(True, files_changed=changed, summary="semgrep --autofix applied")


# ──────────────────────────────────────────────────────────────────────
# Registry + resolver
# ──────────────────────────────────────────────────────────────────────


RUFF_FIX = FixStrategy(
    name="ruff-fix",
    kind="deterministic",
    description="Apply ruff --fix for a single rule on a single file.",
    apply=_apply_ruff_fix,
)

NPM_AUDIT_FIX = FixStrategy(
    name="npm-audit-fix",
    kind="deterministic",
    description="Run `npm audit fix` to apply available dependency upgrades.",
    apply=_apply_npm_audit_fix,
)

SEMGREP_AUTOFIX = FixStrategy(
    name="semgrep-autofix",
    kind="deterministic",
    description="Apply semgrep's autofix patches where available.",
    apply=_apply_semgrep_autofix,
)

AI_DELEGATE = FixStrategy(
    name="ai-delegate",
    kind="ai",
    description="Delegate to the existing Fix Agent (agents/fix-bugs.sh).",
    apply=None,  # Phase 2.5 wires this; until then it reports as 'pending'.
)

MANUAL = FixStrategy(
    name="manual",
    kind="manual",
    description="Cannot be auto-fixed (e.g. secret rotation, architectural change).",
    apply=None,
)


def resolve_strategy(finding: dict) -> FixStrategy:
    """Pick the right strategy for *finding*.

    Order matters: deterministic strategies preferred over AI delegation;
    AI delegation preferred over manual.
    """
    source = (finding.get("source_tool") or "").lower()
    fixable = bool(finding.get("fixable_by_agent"))

    if source == "ruff" and fixable:
        return RUFF_FIX
    if source == "npm-audit" and fixable:
        return NPM_AUDIT_FIX
    if source == "semgrep" and fixable:
        return SEMGREP_AUTOFIX
    if fixable:
        return AI_DELEGATE
    return MANUAL
