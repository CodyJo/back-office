"""Safe-apply orchestrator: worktree → apply → verify → commit / rollback.

Default behavior is **dry-run** — the runner creates a worktree,
applies the strategy, captures the diff, and tears the worktree down
without committing anything. ``--apply`` flips to a real run, but the
target's :class:`backoffice.config.Autonomy` policy still has to allow
``fix`` (and ``auto_commit`` for the commit step).

Pushing branches, opening PRs, and deploying are NOT performed here —
those are operator-consent touchpoints.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backoffice.apply.strategies import (
    ApplyContext,
    ApplyResult,
    FixStrategy,
    resolve_strategy,
)
from backoffice.apply.verifier import VerifyResult, verify
from backoffice.audit_rotation import maybe_rotate
from backoffice.policy import evaluate_gate
from backoffice.store.atomic import append_jsonl_line, atomic_write_json
from backoffice.workflow import iso_now, read_json

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Outcome record (one per attempted finding)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ApplyOutcome:
    finding_id: str
    finding_title: str
    target: str
    strategy: str
    status: str  # dry-run | applied | applied-uncommitted | rolled-back | blocked | skipped | failed
    reason: str
    branch: str = ""
    worktree_path: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff_excerpt: str = ""
    pre_verify: dict | None = None
    post_verify: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# Git worktree helpers
# ──────────────────────────────────────────────────────────────────────


def _git(repo_path: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _worktree_clean(repo_path: str) -> bool:
    res = _git(repo_path, "status", "--porcelain")
    return res.returncode == 0 and not res.stdout.strip()


def _current_branch(repo_path: str) -> str:
    res = _git(repo_path, "symbolic-ref", "--short", "HEAD")
    return res.stdout.strip() if res.returncode == 0 else "HEAD"


def _short_diff(worktree_path: str, max_bytes: int = 4000) -> str:
    res = _git(worktree_path, "diff")
    out = res.stdout
    return out if len(out) <= max_bytes else out[:max_bytes] + "\n…(truncated)"


def _make_worktree(repo_path: str, branch: str, base_ref: str) -> str:
    """Create a temporary git worktree on a new branch. Returns the worktree path."""
    wt_root = Path(tempfile.gettempdir()) / "back-office-apply"
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path = wt_root / f"{Path(repo_path).name}-{uuid.uuid4().hex[:8]}"
    res = _git(repo_path, "worktree", "add", "-b", branch, str(wt_path), base_ref)
    if res.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {res.stderr.strip()}")
    return str(wt_path)


def _cleanup_worktree(repo_path: str, worktree_path: str, branch: str, *, delete_branch: bool) -> None:
    _git(repo_path, "worktree", "remove", "--force", worktree_path)
    if delete_branch:
        _git(repo_path, "branch", "-D", branch)
    # Best-effort: if git left orphan files (it shouldn't), nuke them.
    if os.path.isdir(worktree_path):
        shutil.rmtree(worktree_path, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────────────────────────────


def _audit_log_path() -> Path:
    root = Path(os.environ.get("BACK_OFFICE_ROOT", Path(__file__).resolve().parents[2]))
    return root / "results" / "audit-events.jsonl"


def _record(outcome: ApplyOutcome) -> None:
    path = _audit_log_path()
    maybe_rotate(path)
    payload = {
        "at": iso_now(),
        "actor_id": "backoffice.apply",
        "action": f"apply.{outcome.status}",
        "subject_kind": "finding",
        "subject_id": outcome.finding_id,
        "after": outcome.to_dict(),
    }
    try:
        append_jsonl_line(path, payload)
    except OSError:
        logger.exception("failed to append audit event for %s", outcome.finding_id)


# ──────────────────────────────────────────────────────────────────────
# Per-finding apply
# ──────────────────────────────────────────────────────────────────────


def _branch_name(target_name: str, finding_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in finding_id)[:40]
    return f"back-office/apply/{target_name}-{safe}-{uuid.uuid4().hex[:6]}"


def apply_finding(
    finding: dict,
    *,
    target_name: str,
    target_path: str,
    lint_command: str,
    test_command: str,
    dry_run: bool,
    auto_commit_allowed: bool,
    ai_budget_blocked: bool = False,
) -> ApplyOutcome:
    """Resolve a strategy, apply it in a worktree, verify, commit-or-rollback.

    Caller is responsible for the autonomy ``fix`` gate; this function
    assumes it has already been allowed. ``auto_commit_allowed`` reflects
    the ``auto_commit`` gate decision. ``ai_budget_blocked`` causes
    AI-delegate strategies to be skipped (deterministic strategies still run).
    """
    fid = finding.get("id") or "(no id)"
    title = finding.get("title") or "(no title)"
    strategy: FixStrategy = resolve_strategy(finding)

    if strategy.kind == "manual":
        out = ApplyOutcome(fid, title, target_name, strategy.name, "skipped", "not-auto-fixable")
        _record(out)
        return out

    if strategy.kind == "ai" and ai_budget_blocked:
        out = ApplyOutcome(fid, title, target_name, strategy.name, "skipped", "ai-budget-blocked")
        _record(out)
        return out

    if strategy.apply is None:
        out = ApplyOutcome(fid, title, target_name, strategy.name, "skipped", "strategy-not-implemented")
        _record(out)
        return out

    base_ref = _current_branch(target_path)
    branch = _branch_name(target_name, fid)
    try:
        worktree = _make_worktree(target_path, branch, base_ref)
    except RuntimeError as exc:
        out = ApplyOutcome(fid, title, target_name, strategy.name, "failed", f"worktree-failed: {exc}")
        _record(out)
        return out

    try:
        pre = verify(worktree, lint_command, test_command)
        result: ApplyResult = strategy.apply(ApplyContext(finding, worktree, target_name))

        if not result.success:
            out = ApplyOutcome(
                fid, title, target_name, strategy.name, "failed", result.error or "apply-returned-no-change",
                branch=branch, worktree_path=worktree,
                pre_verify=asdict(pre),
            )
            _cleanup_worktree(target_path, worktree, branch, delete_branch=True)
            out.worktree_path = ""  # cleaned
            _record(out)
            return out

        diff = _short_diff(worktree)
        post = verify(worktree, lint_command, test_command)

        # Regression check: any check that was passing pre but failing post is a fail.
        regressed = (
            (pre.lint_passed in (True, None) and post.lint_passed is False)
            or (pre.tests_passed in (True, None) and post.tests_passed is False)
        )

        if dry_run:
            out = ApplyOutcome(
                fid, title, target_name, strategy.name, "dry-run",
                "dry-run-ok" if not regressed else "dry-run-regression",
                branch=branch, worktree_path=worktree,
                files_changed=result.files_changed,
                diff_excerpt=diff,
                pre_verify=asdict(pre),
                post_verify=asdict(post),
            )
            _cleanup_worktree(target_path, worktree, branch, delete_branch=True)
            out.worktree_path = ""
            _record(out)
            return out

        if regressed:
            out = ApplyOutcome(
                fid, title, target_name, strategy.name, "rolled-back",
                "verify-regressed",
                branch=branch, worktree_path=worktree,
                files_changed=result.files_changed,
                diff_excerpt=diff,
                pre_verify=asdict(pre),
                post_verify=asdict(post),
            )
            _cleanup_worktree(target_path, worktree, branch, delete_branch=True)
            out.worktree_path = ""
            _record(out)
            return out

        if not auto_commit_allowed:
            # Leave the worktree + branch in place for human inspection.
            out = ApplyOutcome(
                fid, title, target_name, strategy.name, "applied-uncommitted",
                "auto_commit-not-allowed",
                branch=branch, worktree_path=worktree,
                files_changed=result.files_changed,
                diff_excerpt=diff,
                pre_verify=asdict(pre),
                post_verify=asdict(post),
            )
            _record(out)
            return out

        # Commit. Stage everything in the worktree.
        _git(worktree, "add", "-A")
        commit_msg = (
            f"fix({target_name}): {title}\n\n"
            f"Strategy: {strategy.name}\n"
            f"Finding: {fid}\n"
            f"Source tool: {finding.get('source_tool', 'unknown')}\n"
            f"Auto-applied by Back Office safe-apply framework."
        )
        commit_res = _git(worktree, "commit", "-m", commit_msg)
        if commit_res.returncode != 0:
            out = ApplyOutcome(
                fid, title, target_name, strategy.name, "rolled-back",
                f"commit-failed: {commit_res.stderr.strip()[:300]}",
                branch=branch, worktree_path=worktree,
                files_changed=result.files_changed,
                diff_excerpt=diff,
                pre_verify=asdict(pre),
                post_verify=asdict(post),
            )
            _cleanup_worktree(target_path, worktree, branch, delete_branch=True)
            out.worktree_path = ""
            _record(out)
            return out

        # Leave the branch in place (committed). Remove the worktree
        # checkout so subsequent runs aren't confused by stale state;
        # the branch persists in the target repo for human review/PR.
        _cleanup_worktree(target_path, worktree, branch, delete_branch=False)
        out = ApplyOutcome(
            fid, title, target_name, strategy.name, "applied",
            "committed-to-branch",
            branch=branch, worktree_path="",
            files_changed=result.files_changed,
            diff_excerpt=diff,
            pre_verify=asdict(pre),
            post_verify=asdict(post),
        )
        _record(out)
        return out

    except Exception as exc:  # never let one finding kill the batch
        logger.exception("apply_finding crashed for %s", fid)
        try:
            _cleanup_worktree(target_path, worktree, branch, delete_branch=True)
        except Exception:
            pass
        out = ApplyOutcome(
            fid, title, target_name, strategy.name, "failed",
            f"crash: {type(exc).__name__}: {exc}",
        )
        _record(out)
        return out


# ──────────────────────────────────────────────────────────────────────
# Batch + CLI
# ──────────────────────────────────────────────────────────────────────


SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _load_findings(target_name: str, results_dir: str) -> list[dict]:
    """Load both AI and deterministic findings for the target, deduped."""
    repo_dir = Path(results_dir) / target_name
    out: list[dict] = []
    seen_ids: set[str] = set()
    for filename in ("findings.json", "qa-deterministic-findings.json"):
        data = read_json(str(repo_dir / filename))
        if not data:
            continue
        for f in data.get("findings", []):
            fid = f.get("id") or ""
            if fid and fid in seen_ids:
                continue
            if fid:
                seen_ids.add(fid)
            out.append(f)
    return out


def _select(
    findings: list[dict],
    *,
    finding_id: str | None,
    source_tool: str | None,
    severity: str,
    max_changes: int,
) -> list[dict]:
    if finding_id:
        return [f for f in findings if f.get("id") == finding_id]
    sev_max = SEVERITY_RANK.get(severity, 99)
    matches: list[dict] = []
    for f in findings:
        if source_tool and (f.get("source_tool") or "") != source_tool:
            continue
        if SEVERITY_RANK.get(f.get("severity", "info"), 99) > sev_max:
            continue
        if f.get("category") == "scanner-status":
            continue
        matches.append(f)
    matches.sort(key=lambda f: SEVERITY_RANK.get(f.get("severity", "info"), 99))
    return matches[:max_changes]


def handle_apply_cli(args: argparse.Namespace) -> int:
    from backoffice.config import load_config

    cfg = load_config()
    target = cfg.targets.get(args.target)
    if target is None:
        print(f"Unknown target: {args.target!r}", file=sys.stderr)
        return 2
    if not target.path or not os.path.isdir(target.path):
        print(f"Target {args.target} path missing: {target.path!r}", file=sys.stderr)
        return 2

    # Policy gate (fix). Worktree-clean check applies to the *target's* working
    # tree — we don't want to touch a repo that has uncommitted operator work.
    autonomy = target.autonomy
    fix_decision = evaluate_gate(autonomy, "fix", {"worktree_clean": _worktree_clean(target.path)})
    if not fix_decision.allow and not args.dry_run and args.apply:
        print(f"Policy blocked: {fix_decision.reason}", file=sys.stderr)
        return 1
    auto_commit_decision = evaluate_gate(autonomy, "auto_commit", {})
    auto_commit_allowed = auto_commit_decision.allow

    # AI-spend budget — only matters for AI-delegate strategies; deterministic
    # strategies (ruff --fix, npm audit fix, etc.) cost nothing and run regardless.
    from backoffice.budget_check import is_blocked as _budget_blocked
    ai_budget_blocked = _budget_blocked(args.target, "qa")

    results_dir = str(cfg.root / "results")
    findings = _load_findings(args.target, results_dir)
    if not findings:
        print(f"No findings for {args.target}. Run `python -m backoffice scan {args.target}` first.")
        return 0

    max_changes = args.max_changes or autonomy.max_changes_per_cycle or 3
    selected = _select(
        findings,
        finding_id=args.finding,
        source_tool=args.source_tool,
        severity=args.severity,
        max_changes=max_changes,
    )
    if not selected:
        print("No findings match the filter.")
        return 0

    # Resolve dry-run vs apply: dry-run wins when both are set; apply wins
    # only when explicit. Default = dry-run.
    dry_run = True
    if args.apply and not args.dry_run:
        dry_run = False

    print(f"\n{'DRY-RUN' if dry_run else 'APPLY'} • {args.target} • {len(selected)} finding(s)")
    if not dry_run:
        print(f"Policy: fix={fix_decision.reason}, auto_commit={'allow' if auto_commit_allowed else 'block'}")
    print("─" * 60)

    outcomes: list[ApplyOutcome] = []
    for f in selected:
        outcome = apply_finding(
            f,
            target_name=args.target,
            target_path=target.path,
            lint_command=target.lint_command,
            test_command=target.test_command,
            dry_run=dry_run,
            auto_commit_allowed=auto_commit_allowed,
            ai_budget_blocked=ai_budget_blocked,
        )
        outcomes.append(outcome)
        files = ", ".join(outcome.files_changed[:3]) or "—"
        print(
            f"  [{outcome.status:<22}] {outcome.finding_id:<30} via {outcome.strategy:<18} "
            f"({outcome.reason})  files: {files}"
        )

    # Write a per-run summary so the dashboard / operator can review.
    run_id = f"apply-{iso_now().replace(':', '').replace('-', '').split('.')[0]}"
    summary_path = Path(results_dir) / args.target / f"apply-runs/{run_id}.json"
    atomic_write_json(summary_path, {
        "run_id": run_id,
        "target": args.target,
        "at": iso_now(),
        "mode": "dry-run" if dry_run else "apply",
        "outcomes": [o.to_dict() for o in outcomes],
    })

    summary_counts: dict[str, int] = {}
    for o in outcomes:
        summary_counts[o.status] = summary_counts.get(o.status, 0) + 1
    print("─" * 60)
    print("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(summary_counts.items())))
    print(f"Run record: {summary_path}")
    if dry_run:
        print("(Re-run with --apply to actually commit changes.)")
    return 0
