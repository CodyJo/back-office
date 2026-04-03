"""Portfolio QA remediation planning model for Back Office.

Stores a version-controlled remediation plan in ``config/remediation-plan.yaml``
and mirrors a dashboard-friendly JSON artifact into ``results/`` and
``dashboard/``. The plan is generated from the current QA findings artifacts
when they are available, and falls back to a seeded baseline when they are not.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml


STATUS_ORDER = ["planned", "in_progress", "blocked", "complete"]
DISPOSITION_ORDER = ["must_fix_now", "fix_this_wave", "can_defer"]
CHECKPOINTS = [
    {
        "id": "checkpoint-1",
        "title": "Wave 1 approval",
        "scope": "back-office, auth-service, continuum, pe-bootstrap",
    },
    {
        "id": "checkpoint-2",
        "title": "Wave 2 approval",
        "scope": "cordivent, certstudy, codyjo.com",
    },
    {
        "id": "checkpoint-3",
        "title": "Wave 3+ approval",
        "scope": "selah, fuel, thenewbeautifulme, analogify",
    },
]
WAVE_BLUEPRINTS = {
    "wave-1": {
        "title": "Must Fix Now",
        "summary": (
            "Server-side exploitability, auth hardening, and production-risk issues "
            "that should be resolved before broader cleanup."
        ),
        "approval_checkpoint": "checkpoint-1",
    },
    "wave-2": {
        "title": "Build / Deployment Reliability",
        "summary": "Restore clean CI and production build reliability after the security baseline is stable.",
        "approval_checkpoint": "checkpoint-2",
    },
    "wave-3": {
        "title": "Security Hardening With Product Impact",
        "summary": "Address user-facing auth, header, and product-flow weaknesses once core platform risk is down.",
        "approval_checkpoint": "checkpoint-3",
    },
    "wave-4": {
        "title": "Low-Risk Cleanup",
        "summary": "Finish low-risk cleanup once the higher-signal security and build work is complete.",
        "approval_checkpoint": "checkpoint-3",
    },
}
REPO_RULES = {
    "back-office": {
        "wave": "wave-1",
        "priority": "critical",
        "disposition": "must_fix_now",
        "summary": "Harden product approval and PR-request endpoints.",
    },
    "auth-service": {
        "wave": "wave-1",
        "priority": "critical",
        "disposition": "must_fix_now",
        "summary": "Unify email canonicalization and harden the auth registration path.",
    },
    "continuum": {
        "wave": "wave-1",
        "priority": "critical",
        "disposition": "must_fix_now",
        "summary": "Lock down API input handling and prevent insecure production secret fallback.",
    },
    "pe-bootstrap": {
        "wave": "wave-1",
        "priority": "critical",
        "disposition": "must_fix_now",
        "summary": "Fix hidden auth failures and tighten passphrase/project validation paths.",
    },
    "cordivent": {
        "wave": "wave-2",
        "priority": "high",
        "disposition": "must_fix_now",
        "summary": "Fix build-breaking shared package resolution and adjacent dependency/lint issues.",
    },
    "certstudy": {
        "wave": "wave-2",
        "priority": "high",
        "disposition": "must_fix_now",
        "summary": "Fix React correctness issues, broken test runner boundaries, and the vulnerable Next.js baseline.",
    },
    "codyjo.com": {
        "wave": "wave-2",
        "priority": "high",
        "disposition": "must_fix_now",
        "summary": "Resolve vulnerable dependencies and the current Astro typecheck break.",
    },
    "selah": {
        "wave": "wave-3",
        "priority": "high",
        "disposition": "must_fix_now",
        "summary": "Strengthen auth policy, headers, and abuse controls.",
    },
    "fuel": {
        "wave": "wave-3",
        "priority": "high",
        "disposition": "fix_this_wave",
        "summary": "Replace weak identifier generation and tighten markdown/API error handling.",
    },
    "thenewbeautifulme": {
        "wave": "wave-3",
        "priority": "medium",
        "disposition": "fix_this_wave",
        "summary": "Close correctness, accessibility, hydration, and motion-prop issues together.",
    },
    "analogify": {
        "wave": "wave-4",
        "priority": "low",
        "disposition": "can_defer",
        "summary": "Test-only import and formatting cleanup.",
    },
}
DEFER_TITLES = {
    "continuum": {"JWT Token Stored in Browser LocalStorage Without HttpOnly Protection"},
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "config" / "remediation-plan.yaml",
        root / "results" / "remediation-plan.json",
        root / "dashboard" / "remediation-plan.json",
    )


def _default_payload() -> dict:
    now = iso_now()
    return {
        "version": 1,
        "updated_at": now,
        "goal": (
            "Turn portfolio QA findings into risk-based execution waves so "
            "security, auth, and build blockers are handled before lower-value cleanup."
        ),
        "principles": [
            "Do not prioritize findings by severity labels alone.",
            "Exploitability and production blast radius outrank effort labels like easy.",
            "Group related findings into repo hardening passes to reduce verification cost.",
            "Defer architecture migrations only when they require larger auth or session redesign work.",
            "Preserve approval checkpoints between waves.",
        ],
        "approval_checkpoints": CHECKPOINTS,
        "waves": [
            {
                "id": "wave-1",
                "title": "Must Fix Now",
                "status": "planned",
                "approval_checkpoint": "checkpoint-1",
                "summary": (
                    "Server-side exploitability, auth hardening, and production-risk issues "
                    "that should be resolved before broader cleanup."
                ),
                "repositories": [
                    {
                        "repo": "back-office",
                        "priority": "critical",
                        "disposition": "must_fix_now",
                        "summary": "Harden product approval and PR-request endpoints.",
                        "findings": [
                            {"severity": "critical", "title": "Path Traversal via user-supplied local_path parameter in product approval endpoint"},
                            {"severity": "critical", "title": "YAML Injection via unescaped user input in configuration file writing"},
                            {"severity": "high", "title": "Insufficient validation of github_repo parameter before command execution"},
                            {"severity": "high", "title": "Missing validation of target_path in PR creation endpoint"},
                            {"severity": "high", "title": "Flaky test: test_argv_defaults_to_none fails due to lock file race condition"},
                        ],
                        "verification": [
                            "python3 -m pytest tests/test_servers.py tests/test_workflow.py",
                        ],
                    },
                    {
                        "repo": "auth-service",
                        "priority": "critical",
                        "disposition": "must_fix_now",
                        "summary": "Unify email canonicalization and harden the auth registration path.",
                        "findings": [
                            {"severity": "critical", "title": "Case-Insensitive Admin Allowlist Check Is Vulnerable to Homograph Attacks"},
                            {"severity": "critical", "title": "Insufficient Email Address Validation Allows Email Spoofing"},
                            {"severity": "high", "title": "Missing Email Validation Code Flow Issue"},
                            {"severity": "low", "title": "Missing Error Handling for Secrets Manager Failures"},
                            {"severity": "high", "title": "Unused Import 'QueryCommand' in admin.mjs"},
                            {"severity": "high", "title": "Unused Import 'BatchWriteCommand' in index.mjs"},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                        ],
                    },
                    {
                        "repo": "continuum",
                        "priority": "critical",
                        "disposition": "must_fix_now",
                        "summary": "Lock down API input handling and prevent insecure production secret fallback.",
                        "findings": [
                            {"severity": "critical", "title": "Reversible Base64 Encoding Used for Secrets in Development Mode"},
                            {"severity": "high", "title": "Missing Request Body Size Limits on API Endpoints"},
                            {"severity": "high", "title": "Overly Broad Exception Handling Masks Real Errors"},
                            {"severity": "high", "title": "Vulnerable Next.js Dependencies (Moderate Severity Advisories)"},
                            {"severity": "medium", "title": "Missing Content-Type Validation on POST Endpoints"},
                            {"severity": "medium", "title": "Missing Pagination Limits on Memory Query Endpoint"},
                            {"severity": "high", "title": "JWT Token Stored in Browser LocalStorage Without HttpOnly Protection", "deferred": True},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                            "npm run typecheck",
                        ],
                    },
                    {
                        "repo": "pe-bootstrap",
                        "priority": "critical",
                        "disposition": "must_fix_now",
                        "summary": "Fix hidden auth failures and tighten passphrase/project validation paths.",
                        "findings": [
                            {"severity": "critical", "title": "Bare except clause catching all exceptions without logging"},
                            {"severity": "critical", "title": "Password stored in plaintext in environment before Secret Manager write"},
                            {"severity": "high", "title": "Multiple bare except clauses swallowing all exceptions"},
                            {"severity": "high", "title": "Inadequate regex validation for GCP Project IDs"},
                            {"severity": "high", "title": "Recursion in classification script without depth limit"},
                            {"severity": "high", "title": "No error handling for file I/O in classification transformation"},
                            {"severity": "medium", "title": "Insecure passphrase comparison timing vulnerability"},
                        ],
                        "verification": [
                            "python3 -m pytest",
                        ],
                    },
                ],
            },
            {
                "id": "wave-2",
                "title": "Build / Deployment Reliability",
                "status": "planned",
                "approval_checkpoint": "checkpoint-2",
                "summary": "Restore clean CI and production build reliability after the security baseline is stable.",
                "repositories": [
                    {
                        "repo": "cordivent",
                        "priority": "high",
                        "disposition": "must_fix_now",
                        "summary": "Fix build-breaking shared package resolution and adjacent dependency/lint issues.",
                        "findings": [
                            {"severity": "critical", "title": "Build failure due to unresolved module imports"},
                            {"severity": "high", "title": "Moderate severity vulnerability in fast-xml-parser dependency"},
                            {"severity": "high", "title": "CommonJS require() statements in ES module context"},
                            {"severity": "medium", "title": "Image optimization warning - use Next.js Image component"},
                        ],
                        "verification": [
                            "npm run build",
                            "npm test",
                        ],
                    },
                    {
                        "repo": "certstudy",
                        "priority": "high",
                        "disposition": "must_fix_now",
                        "summary": "Fix React correctness issues, broken test runner boundaries, and vulnerable Next.js baseline.",
                        "findings": [
                            {"severity": "critical", "title": "Impure function called during render in SessionTimeout component"},
                            {"severity": "high", "title": "setState called synchronously within useEffect in Navigation component"},
                            {"severity": "high", "title": "Component definition missing display name in navigation.test.tsx"},
                            {"severity": "high", "title": "navigation.test.tsx test suite fails: Missing LayoutDashboard export from lucide-react mock"},
                            {"severity": "high", "title": "e2e/smoke.spec.ts test suite fails: Playwright version conflict"},
                            {"severity": "high", "title": "Next.js 16.1.6: Multiple moderate security vulnerabilities"},
                            {"severity": "medium", "title": "dangerouslySetInnerHTML used in root layout for analytics"},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                            "npm run typecheck",
                        ],
                    },
                    {
                        "repo": "codyjo.com",
                        "priority": "high",
                        "disposition": "must_fix_now",
                        "summary": "Resolve vulnerable dependencies and the current Astro typecheck break.",
                        "findings": [
                            {"severity": "high", "title": "High-severity vulnerability in picomatch dependency"},
                            {"severity": "medium", "title": "Method Injection vulnerability in picomatch POSIX character classes"},
                            {"severity": "medium", "title": "Denial of Service vulnerability in smol-toml"},
                            {"severity": "medium", "title": "TypeScript type checking errors in blog/index.astro"},
                        ],
                        "verification": [
                            "npm run build",
                        ],
                    },
                ],
            },
            {
                "id": "wave-3",
                "title": "Security Hardening With Product Impact",
                "status": "planned",
                "approval_checkpoint": "checkpoint-3",
                "summary": "Address user-facing auth, header, and product-flow weaknesses once core platform risk is down.",
                "repositories": [
                    {
                        "repo": "selah",
                        "priority": "high",
                        "disposition": "must_fix_now",
                        "summary": "Strengthen auth policy, headers, and abuse controls.",
                        "findings": [
                            {"severity": "high", "title": "Insufficient JWT token expiration"},
                            {"severity": "medium", "title": "Weak password requirements"},
                            {"severity": "medium", "title": "Insufficient rate limiting on login"},
                            {"severity": "medium", "title": "Missing Content Security Policy header"},
                            {"severity": "low", "title": "Missing HSTS header"},
                            {"severity": "low", "title": "Error messages reveal account existence"},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                            "npm run typecheck",
                        ],
                    },
                    {
                        "repo": "fuel",
                        "priority": "high",
                        "disposition": "fix_this_wave",
                        "summary": "Replace weak identifier generation and tighten markdown/API error handling.",
                        "findings": [
                            {"severity": "high", "title": "Insecure Random ID Generation with Math.random()"},
                            {"severity": "medium", "title": "ReactMarkdown Without Explicit XSS Protection Configuration"},
                            {"severity": "low", "title": "Potentially Sensitive Information Exposed in API Error Messages"},
                            {"severity": "low", "title": "Use of dangerouslySetInnerHTML in Layout Component"},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                        ],
                    },
                    {
                        "repo": "thenewbeautifulme",
                        "priority": "medium",
                        "disposition": "fix_this_wave",
                        "summary": "Close correctness, accessibility, hydration, and motion-prop issues together.",
                        "findings": [
                            {"severity": "high", "title": "React Hook dependency array missing dependencies causing stale closures"},
                            {"severity": "high", "title": "Missing alt text on image elements creates accessibility barrier"},
                            {"severity": "medium", "title": "Using <img> instead of Next.js <Image> component reduces LCP performance"},
                            {"severity": "medium", "title": "Nested button elements cause HTML hydration mismatch"},
                            {"severity": "medium", "title": "Framer Motion props passed to DOM elements cause React warnings"},
                        ],
                        "verification": [
                            "npm test",
                            "npm run lint",
                            "npm run typecheck",
                        ],
                    },
                ],
            },
            {
                "id": "wave-4",
                "title": "Low-Risk Cleanup",
                "status": "planned",
                "approval_checkpoint": "checkpoint-3",
                "summary": "Finish low-risk cleanup once the higher-signal security and build work is complete.",
                "repositories": [
                    {
                        "repo": "analogify",
                        "priority": "low",
                        "disposition": "can_defer",
                        "summary": "Test-only import and formatting cleanup.",
                        "findings": [
                            {"severity": "low", "title": "Unused imports in test files (F401)"},
                            {"severity": "low", "title": "Unnecessary encode() calls in test_auth_download.py (UP012)"},
                            {"severity": "low", "title": "Import organization issue in test_auth_download.py (I001)"},
                        ],
                        "verification": [
                            "python3 -m pytest",
                        ],
                    },
                ],
            },
        ],
        "updates": [
            {
                "at": now,
                "actor": "codex",
                "kind": "seed",
                "message": "Initialized the first portfolio QA remediation plan from the March 26, 2026 Back Office findings backlog.",
            }
        ],
    }


def _read_findings_artifacts(root: Path) -> dict[str, dict]:
    results_dir = root / "results"
    findings_by_repo: dict[str, dict] = {}
    if not results_dir.exists():
        return findings_by_repo

    for findings_path in results_dir.glob("*/findings.json"):
        try:
            payload = json.loads(findings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        repo = payload.get("repo_name") or findings_path.parent.name
        findings = payload.get("findings")
        if not repo or not isinstance(findings, list):
            continue
        findings_by_repo[repo] = payload
    return findings_by_repo


def _load_saved_payload(root: Path) -> dict:
    config_path, _, _ = _paths(root)
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def _saved_wave_overrides(root: Path) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    saved = _load_saved_payload(root)
    wave_map: dict[str, dict] = {}
    repo_map: dict[str, dict] = {}
    for wave in saved.get("waves", []) if isinstance(saved.get("waves"), list) else []:
        if not isinstance(wave, dict):
            continue
        wave_id = str(wave.get("id") or "").strip()
        if not wave_id:
            continue
        wave_map[wave_id] = {
            "status": wave.get("status"),
            "notes": wave.get("notes", ""),
        }
        repos = wave.get("repositories", [])
        if not isinstance(repos, list):
            continue
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            repo_id = str(repo.get("repo") or "").strip()
            if not repo_id:
                continue
            repo_map[repo_id] = {
                "status": repo.get("status"),
                "notes": repo.get("notes", ""),
            }
    updates = saved.get("updates", [])
    return wave_map, repo_map, updates if isinstance(updates, list) else []


def _build_payload_from_findings(root: Path) -> dict | None:
    findings_by_repo = _read_findings_artifacts(root)
    if not findings_by_repo:
        return None

    now = iso_now()
    saved_waves, saved_repos, saved_updates = _saved_wave_overrides(root)
    waves: dict[str, dict] = {
        wave_id: {
            "id": wave_id,
            "title": blueprint["title"],
            "status": saved_waves.get(wave_id, {}).get("status") or "planned",
            "approval_checkpoint": blueprint["approval_checkpoint"],
            "summary": blueprint["summary"],
            "notes": saved_waves.get(wave_id, {}).get("notes", ""),
            "repositories": [],
        }
        for wave_id, blueprint in WAVE_BLUEPRINTS.items()
    }

    for repo in sorted(findings_by_repo):
        payload = findings_by_repo[repo]
        rule = REPO_RULES.get(repo)
        if not rule:
            continue
        findings = []
        for finding in payload.get("findings", []):
            if not isinstance(finding, dict):
                continue
            title = (finding.get("title") or "").strip()
            if not title:
                continue
            findings.append(
                {
                    "severity": str(finding.get("severity", "")).lower() or "unknown",
                    "title": title,
                    "deferred": title in DEFER_TITLES.get(repo, set()),
                }
            )
        if not findings:
            continue
        wave = waves[rule["wave"]]
        wave["repositories"].append(
            {
                "repo": repo,
                "priority": rule["priority"],
                "disposition": rule["disposition"],
                "status": saved_repos.get(repo, {}).get("status") or "planned",
                "summary": rule["summary"],
                "notes": saved_repos.get(repo, {}).get("notes", ""),
                "findings": findings,
                "verification": _verification_commands_for_repo(repo),
            }
        )

    ordered_waves = [waves[wave_id] for wave_id in ("wave-1", "wave-2", "wave-3", "wave-4") if waves[wave_id]["repositories"]]
    if not ordered_waves:
        return None

    return {
        "version": 1,
        "updated_at": now,
        "goal": (
            "Turn portfolio QA findings into risk-based execution waves so "
            "security, auth, and build blockers are handled before lower-value cleanup."
        ),
        "principles": [
            "Do not prioritize findings by severity labels alone.",
            "Exploitability and production blast radius outrank effort labels like easy.",
            "Group related findings into repo hardening passes to reduce verification cost.",
            "Defer architecture migrations only when they require larger auth or session redesign work.",
            "Preserve approval checkpoints between waves.",
        ],
        "approval_checkpoints": CHECKPOINTS,
        "waves": ordered_waves,
        "updates": saved_updates or [
            {
                "at": now,
                "actor": "codex",
                "kind": "refresh",
                "message": "Refreshed remediation plan from current Back Office QA findings artifacts.",
            }
        ],
    }


def _verification_commands_for_repo(repo: str) -> list[str]:
    commands = {
        "back-office": ["python3 -m pytest tests/test_servers.py tests/test_workflow.py"],
        "auth-service": ["npm test", "npm run lint"],
        "continuum": ["npm test", "npm run lint", "npm run typecheck"],
        "pe-bootstrap": ["python3 -m pytest"],
        "cordivent": ["npm run build", "npm test"],
        "certstudy": ["npm test", "npm run lint", "npm run typecheck"],
        "codyjo.com": ["npm run build"],
        "selah": ["npm test", "npm run lint", "npm run typecheck"],
        "fuel": ["npm test", "npm run lint"],
        "thenewbeautifulme": ["npm test", "npm run lint", "npm run typecheck"],
        "analogify": ["python3 -m pytest"],
    }
    return commands.get(repo, [])


def _normalize_repository(item: dict) -> dict:
    repo = dict(item)
    repo.setdefault("repo", "")
    repo.setdefault("priority", "medium")
    repo.setdefault("disposition", "fix_this_wave")
    repo.setdefault("status", "planned")
    if repo["status"] not in STATUS_ORDER:
        repo["status"] = "planned"
    if repo["disposition"] not in DISPOSITION_ORDER:
        repo["disposition"] = "fix_this_wave"
    repo.setdefault("summary", "")
    repo.setdefault("findings", [])
    repo.setdefault("verification", [])
    repo.setdefault("notes", "")
    normalized_findings = []
    for finding in repo.get("findings", []):
        if not isinstance(finding, dict):
            continue
        normalized_findings.append(
            {
                "severity": str(finding.get("severity", "")).lower() or "unknown",
                "title": finding.get("title", "").strip(),
                "deferred": bool(finding.get("deferred", False)),
            }
        )
    repo["findings"] = normalized_findings
    return repo


def _normalize_wave(item: dict) -> dict:
    wave = dict(item)
    wave.setdefault("id", "")
    wave.setdefault("title", wave.get("id", ""))
    wave.setdefault("status", "planned")
    if wave["status"] not in STATUS_ORDER:
        wave["status"] = "planned"
    wave.setdefault("summary", "")
    wave.setdefault("notes", "")
    wave.setdefault("approval_checkpoint", "")
    wave["repositories"] = [_normalize_repository(repo) for repo in wave.get("repositories", [])]
    return wave


def _build_dashboard_payload(raw: dict) -> dict:
    payload = deepcopy(raw)
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", iso_now())
    payload.setdefault("goal", "")
    payload.setdefault("principles", [])
    payload.setdefault("approval_checkpoints", [])
    payload["waves"] = [_normalize_wave(wave) for wave in payload.get("waves", [])]
    payload.setdefault("updates", [])

    total_repos = 0
    disposition_counts = {key: 0 for key in DISPOSITION_ORDER}
    severity_counts: dict[str, int] = {}
    deferred_findings = 0
    for wave in payload["waves"]:
        total_repos += len(wave["repositories"])
        for repo in wave["repositories"]:
            disposition = repo.get("disposition", "fix_this_wave")
            disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
            for finding in repo.get("findings", []):
                severity = finding.get("severity", "unknown")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
                if finding.get("deferred"):
                    deferred_findings += 1

    payload["summary"] = {
        "goal": payload["goal"],
        "updated_at": payload["updated_at"],
        "wave_count": len(payload["waves"]),
        "repository_count": total_repos,
        "approval_checkpoint_count": len(payload["approval_checkpoints"]),
        "by_status": {
            status: sum(1 for wave in payload["waves"] if wave.get("status") == status)
            for status in STATUS_ORDER
        },
        "by_disposition": disposition_counts,
        "finding_severity_counts": severity_counts,
        "deferred_findings": deferred_findings,
    }
    return payload


def load(root: Path) -> dict:
    findings_payload = _build_payload_from_findings(root)
    if findings_payload is not None:
        return save(root, findings_payload)

    config_path, _, _ = _paths(root)
    if not config_path.exists():
        payload = _default_payload()
        save(root, payload)
        return _build_dashboard_payload(payload)

    with config_path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return _build_dashboard_payload(payload)


def save(root: Path, payload: dict) -> dict:
    config_path, results_path, dashboard_path = _paths(root)
    normalized = _build_dashboard_payload(payload)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {
                "version": normalized["version"],
                "updated_at": normalized["updated_at"],
                "goal": normalized["goal"],
                "principles": normalized["principles"],
                "approval_checkpoints": normalized["approval_checkpoints"],
                "waves": normalized["waves"],
                "updates": normalized["updates"],
            },
            handle,
            sort_keys=False,
        )

    for path in (results_path, dashboard_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

    return normalized


def update_item(
    root: Path,
    collection: str,
    item_id: str,
    *,
    status: str | None = None,
    notes: str | None = None,
) -> dict:
    if collection not in {"waves", "repositories"}:
        raise ValueError("collection must be one of: waves, repositories")
    payload = load(root)
    if collection == "waves":
        for wave in payload.get("waves", []):
            if wave.get("id") != item_id:
                continue
            if status is not None:
                if status not in STATUS_ORDER:
                    raise ValueError(f"unsupported status: {status}")
                wave["status"] = status
            if notes is not None:
                wave["notes"] = notes
            payload["updated_at"] = iso_now()
            return save(root, payload)
        raise ValueError(f"Unknown remediation wave id: {item_id}")

    for wave in payload.get("waves", []):
        for repo in wave.get("repositories", []):
            if repo.get("repo") != item_id:
                continue
            if status is not None:
                if status not in STATUS_ORDER:
                    raise ValueError(f"unsupported status: {status}")
                repo["status"] = status
            if notes is not None:
                repo["notes"] = notes
            payload["updated_at"] = iso_now()
            return save(root, payload)
    raise ValueError(f"Unknown remediation repository id: {item_id}")


def add_update(root: Path, *, actor: str, message: str, kind: str = "note") -> dict:
    if not message.strip():
        raise ValueError("message is required")
    payload = load(root)
    payload.setdefault("updates", [])
    payload["updates"].insert(
        0,
        {
            "at": iso_now(),
            "actor": actor.strip() or "operator",
            "kind": kind.strip() or "note",
            "message": message.strip(),
        },
    )
    payload["updates"] = payload["updates"][:50]
    payload["updated_at"] = iso_now()
    return save(root, payload)


def seed_wave_one_tasks(root: Path) -> dict:
    """Seed Wave 1 remediation tasks into the Back Office task queue."""
    from backoffice import tasks as task_module  # noqa: PLC0415

    payload = load(root)
    wave = next((item for item in payload["waves"] if item.get("id") == "wave-1"), None)
    if not wave:
        return {"created_task_ids": [], "summary": {}}

    context = task_module.load_context(
        root / "config" / "task-queue.yaml",
        root / "config" / "targets.yaml",
        root / "results",
        root / "dashboard",
    )
    existing_ids = {task.get("id") for task in context.payload.get("tasks", [])}
    created_task_ids: list[str] = []

    for repo_plan in wave.get("repositories", []):
        task_id = f"qa-remediation:{wave['id']}:{repo_plan['repo']}"
        if task_id in existing_ids:
            continue
        findings = [finding.get("title", "") for finding in repo_plan.get("findings", []) if finding.get("title")]
        task = task_module.ensure_task_defaults(
            {
                "id": task_id,
                "repo": repo_plan["repo"],
                "title": f"Execute {wave['title']} remediation pass for {repo_plan['repo']}",
                "category": "feature",
                "task_type": "qa_remediation_execution",
                "priority": "high" if repo_plan.get("priority") in {"critical", "high"} else "medium",
                "status": "pending_approval",
                "created_by": "codex",
                "notes": repo_plan.get("summary", ""),
                "acceptance_criteria": [
                    "must-fix-now findings for this repo are addressed or explicitly re-triaged",
                    "repo verification commands pass",
                    "handoff notes are updated with status, risks, and next steps",
                ],
                "verification_command": " && ".join(repo_plan.get("verification", [])),
                "repo_handoff_path": str(root / "docs" / "HANDOFF.md") if repo_plan["repo"] == "back-office" else "",
                "source_finding": {
                    "department": "qa",
                    "severity": repo_plan.get("priority", ""),
                    "category": "portfolio-remediation-plan",
                    "hash": task_id,
                    "id": wave["id"],
                    "file": "config/remediation-plan.yaml",
                    "line": None,
                    "fixable_by_agent": True,
                    "titles": findings,
                },
            },
            context.targets,
        )
        task_module.append_history(
            task,
            "pending_approval",
            "codex",
            f"Seeded from remediation plan {wave['id']} for {repo_plan['repo']}",
        )
        context.payload.setdefault("tasks", []).append(task)
        existing_ids.add(task_id)
        created_task_ids.append(task_id)

    summary = task_module.save_payload(
        context.payload,
        context.targets,
        context.config_path,
        context.results_dir,
        context.dashboard_dir,
    )
    return {"created_task_ids": created_task_ids, "summary": summary.get("summary", {})}
