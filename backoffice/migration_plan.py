"""Migration planning data model for local dashboard management.

Stores a version-controlled migration plan in ``config/migration-plan.yaml`` and
mirrors a dashboard-friendly JSON artifact into ``results/`` and ``dashboard/``.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


STATUS_ORDER = ["planned", "in_progress", "blocked", "complete"]
TARGET_ORDER = ["scaleway", "bunny", "hybrid", "defer"]
DOMAIN_TARGET_ORDER = ["route53-temporary", "bunny", "keep-current", "defer"]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "config" / "migration-plan.yaml",
        root / "results" / "migration-plan.json",
        root / "dashboard" / "migration-plan.json",
    )


def _default_payload() -> dict:
    now = iso_now()
    return {
        "version": 1,
        "updated_at": now,
        "goal": (
            "Exit AWS account 229678440188 by re-architecting each app around a "
            "Bunny-first model for static delivery and edge, using Bunny Database "
            "where it genuinely fits, using Magic Containers where always-on "
            "container runtimes fit, using Scaleway only for backend, state, and "
            "privacy-sensitive workloads Bunny should not own, while keeping GCP "
            "only for email continuity."
        ),
        "principles": [
            "Bunny is the default home for static sites, CDN, cache, and public edge delivery.",
            "Bunny Database is the default data candidate for lightweight relational app state when SQLite-over-HTTP is a real fit.",
            "Magic Containers is the first runtime candidate for containerized workloads that fit Bunny's operating model.",
            "Scaleway is the EU core for backend workloads, secrets, storage, and privacy-sensitive state that Bunny should not own.",
            "Redesign each app around the new split instead of preserving AWS-era service boundaries by default.",
            "Do not migrate shared auth or primary data stores in the same weekend as low-risk edge cutovers.",
            "GCP remains only for email continuity. postal-aws is out of scope for the active migration wave.",
        ],
        "phases": [
            {
                "id": "foundation",
                "title": "Provider Foundation",
                "status": "in_progress",
                "target": "hybrid",
                "summary": "Keep Bunny and Scaleway ready as the only active non-email migration providers.",
                "next_step": "Use the existing Bunny and Scaleway access to establish reusable patterns for app redesign and cutover.",
                "notes": "No new providers. GCP stays email-only.",
            },
            {
                "id": "bunny-wave",
                "title": "Bunny Wave",
                "status": "in_progress",
                "target": "bunny",
                "summary": "Move static and edge-heavy properties to Bunny first, then simplify the origin behind them.",
                "next_step": "Finish the codyjo.com non-AWS origin path behind Bunny, then apply the same Bunny-first redesign pattern to the next static property.",
                "notes": "This is now the default lane for normal sites.",
            },
            {
                "id": "scaleway-core",
                "title": "Scaleway Core",
                "status": "planned",
                "target": "scaleway",
                "summary": "Use Scaleway only for backend, storage, state, and justified runtimes that do not fit Bunny, Bunny Database, or Magic Containers well.",
                "next_step": "After the first Bunny-first success, redesign search and other justified exceptions onto Scaleway with the smallest workable footprint.",
                "notes": "Use this lane for backend ownership, not as a default replacement for every app.",
            },
            {
                "id": "app-redesign",
                "title": "App Redesign",
                "status": "in_progress",
                "target": "hybrid",
                "summary": "Re-architect app backends one by one instead of reproducing Lambda, API Gateway, and DynamoDB wholesale.",
                "next_step": "Track the live Bunny Database plus Magic Containers cutovers for Fuel, Selah, CertStudy, and The New Beautiful Me, and keep AWS only as rollback until authenticated smoke tests pass.",
                "notes": "analogify remains special-case. auth-service remains high-risk shared infrastructure.",
            },
            {
                "id": "aws-drain",
                "title": "AWS Drain",
                "status": "planned",
                "target": "hybrid",
                "summary": "Remove AWS only after Bunny-first and Scaleway-core replacements are live, verified, and no longer depend on AWS origins.",
                "next_step": "Retire AWS per repo after smoke tests, DNS checks, and rollback confidence are in place.",
                "notes": "Do not count Bunny-fronting-CloudFront as full exit.",
            },
        ],
        "repositories": [
            {
                "id": "back-office",
                "label": "Back Office",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "bunny-wave",
                "priority": "high",
                "domain": "admin.codyjo.com",
                "blockers": [
                    "The dashboard state is refreshed locally, but the current publish path for admin.codyjo.com still runs through the legacy hosting path.",
                    "Do not republish mid-cutover unless the live app migration status is captured accurately.",
                ],
                "next_step": "Keep the migration dashboard current locally while the live Bunny app cutovers run, then publish admin.codyjo.com once the active app status is reviewable.",
                "notes": "Admin control plane is being refreshed during the live migration wave.",
            },
            {
                "id": "codyjo.com",
                "label": "codyjo.com",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "bunny-wave",
                "priority": "high",
                "domain": "codyjo.com",
                "blockers": [
                    "Bunny still pulls from the legacy AWS CloudFront hostname while the attempted Scaleway bucket origin returns 403.",
                ],
                "next_step": "Finish the redesign by replacing the temporary AWS origin behind Bunny with a validated non-AWS origin and keep AWS only as rollback until that passes smoke tests.",
                "notes": "First low-risk redesign target. Public edge cutover to Bunny is complete.",
            },
            {
                "id": "search",
                "label": "Search",
                "current_platform": "aws-old",
                "target": "scaleway",
                "status": "planned",
                "phase": "scaleway-core",
                "priority": "high",
                "domain": "search.codyjo.com",
                "blockers": [
                    "Needs a deliberate runtime design rather than a blind EC2 clone.",
                    "DNS and TLS cutover plan still needs to be written.",
                ],
                "next_step": "Decide whether search fits Bunny Magic Containers first; use Scaleway only if the service shape does not fit Bunny's container model.",
                "notes": "First real runtime exception candidate. Bunny Magic Containers should be evaluated before falling back to Scaleway.",
            },
            {
                "id": "plausible-aws-ce",
                "label": "Plausible",
                "current_platform": "aws-old",
                "target": "scaleway",
                "status": "planned",
                "phase": "scaleway-core",
                "priority": "medium",
                "domain": "",
                "blockers": ["Analytics data migration and operator time are still required."],
                "next_step": "Assess after search; evaluate Bunny Magic Containers first and use Scaleway only if the runtime shape demands it.",
                "notes": "Do not introduce another provider.",
            },
            {
                "id": "auth-service",
                "label": "auth-service",
                "current_platform": "aws-old",
                "target": "scaleway",
                "status": "blocked",
                "phase": "app-redesign",
                "priority": "critical",
                "domain": "auth.*",
                "blockers": [
                    "Shared blast radius across multiple apps.",
                    "Current runtime depends on Lambda, API Gateway, DynamoDB, and Route53-coupled custom domains.",
                ],
                "next_step": "Do not move this weekend. Redesign the shared auth model only after low-risk Bunny-first cuts succeed.",
                "notes": "High-risk shared infrastructure.",
            },
            {
                "id": "certstudy",
                "label": "CertStudy",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "app-redesign",
                "priority": "high",
                "domain": "study.codyjo.com",
                "blockers": [
                    "Tutor, planner, SRS, study-plan, and share-link flows all need real authenticated verification after the Bunny cutover.",
                    "Lambda and DynamoDB assumptions still exist in code while the live redesign is in progress.",
                ],
                "next_step": "Finish the Bunny Database plus Magic Containers cutover and verify tutor chat, planner generation, SRS updates, share links, and export before dropping the AWS rollback path.",
                "notes": "Active Bunny Database + Magic Containers migration. Deploy audit: certstudy/docs/bunny-cutover-audit-2026-03-26.md",
            },
            {
                "id": "fuel",
                "label": "Fuel",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "app-redesign",
                "priority": "high",
                "domain": "fuel.codyjo.com",
                "blockers": [
                    "Food search, AI routes, and auth flows still depend on backend semantics that were Lambda and DynamoDB shaped.",
                    "Privacy copy and repo docs still describe the old AWS runtime.",
                ],
                "next_step": "Finish the Bunny Database plus Magic Containers cutover and verify login, USDA food search, AI requests, core writes, and password reset before dropping the AWS rollback path.",
                "notes": "Active Bunny Database + Magic Containers migration. Deploy audit: fuel/docs/bunny-cutover-audit-2026-03-26.md",
            },
            {
                "id": "selah",
                "label": "Selah",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "app-redesign",
                "priority": "medium",
                "domain": "selahscripture.com",
                "blockers": [
                    "Journal, study, encryption-recovery, and account flows still depend on backend semantics that were Lambda and DynamoDB shaped.",
                    "Canonical domain and DNS state need to stay aligned during the live cutover.",
                ],
                "next_step": "Finish the Bunny Database plus Magic Containers cutover and verify login, AI study, journal saves, preferred Bible version updates, and recovery flows before dropping the AWS rollback path.",
                "notes": "Active Bunny Database + Magic Containers migration. Deploy audit: selah/docs/bunny-cutover-audit-2026-03-26.md",
            },
            {
                "id": "cordivent",
                "label": "Cordivent",
                "current_platform": "aws-old",
                "target": "scaleway",
                "status": "planned",
                "phase": "app-redesign",
                "priority": "medium",
                "domain": "cordivent.com",
                "blockers": ["Scheduler and backend state make full migration unsafe for this weekend."],
                "next_step": "Redesign after the first Bunny-first wins; do not drag scheduler/state complexity into the first wave, and only use Scaleway if Bunny plus Bunny Database and Magic Containers cannot cover the app shape.",
                "notes": "Later redesign target.",
            },
            {
                "id": "thenewbeautifulme",
                "label": "The New Beautiful Me",
                "current_platform": "aws-old",
                "target": "bunny",
                "status": "in_progress",
                "phase": "app-redesign",
                "priority": "medium",
                "domain": "thenewbeautifulme.com",
                "blockers": [
                    "Uploads, admin, analytics scheduling, OG generation, and share links make this a platform-shaped migration instead of a normal app move.",
                    "The repo still carries strong AWS assumptions in docs and some runtime surfaces.",
                ],
                "next_step": "Finish the Bunny Database plus Magic Containers cutover and verify uploads, admin, AI interpretation, OG images, and shared-reading flows before dropping the AWS rollback path.",
                "notes": "Active Bunny Database + Magic Containers migration. Deploy audit: thenewbeautifulme/docs/bunny-cutover-audit-2026-03-26.md",
            },
            {
                "id": "analogify",
                "label": "Analogify",
                "current_platform": "aws-old",
                "target": "defer",
                "status": "blocked",
                "phase": "app-redesign",
                "priority": "medium",
                "domain": "analogifystudio.com",
                "blockers": [
                    "Most bespoke storage, gallery, signing, and media workflow behavior in the portfolio.",
                ],
                "next_step": "Defer. Reassess only after the standard Bunny-first and Scaleway-core patterns are stable.",
                "notes": "Special-case platform.",
            },
            {
                "id": "postal-aws",
                "label": "postal-aws",
                "current_platform": "aws-old",
                "target": "defer",
                "status": "complete",
                "phase": "retirement",
                "priority": "low",
                "domain": "",
                "blockers": [],
                "next_step": "No migration work planned in this wave.",
                "notes": "Explicitly out of scope. You said we do not have to move postal-aws.",
            },
        ],
        "domains": [
            {
                "id": "codyjo.com",
                "label": "codyjo.com",
                "dns_target": "bunny",
                "registration_target": "keep-current",
                "status": "in_progress",
                "next_step": "Keep Route53 as the registrar/DNS control point for now, but leave `www` on Bunny while the non-AWS origin path is finalized.",
                "notes": "Parent zone for fuel, study, auth, admin, and redirects. `www` now points at Bunny.",
            },
            {
                "id": "thenewbeautifulme.com",
                "label": "thenewbeautifulme.com",
                "dns_target": "bunny",
                "registration_target": "keep-current",
                "status": "in_progress",
                "next_step": "Keep the Bunny DNS cutover aligned with the live app migration and do not remove the AWS rollback path until uploads, admin, and OG verification pass.",
                "notes": "Live Bunny-facing cutover in progress.",
            },
            {
                "id": "selahscripture.com",
                "label": "selahscripture.com",
                "dns_target": "bunny",
                "registration_target": "keep-current",
                "status": "in_progress",
                "next_step": "Keep the Bunny DNS cutover aligned with the live Selah migration and verify canonical host, auth, and study flows before removing rollback.",
                "notes": "Live Bunny-facing cutover in progress.",
            },
            {
                "id": "fuel.codyjo.com",
                "label": "fuel.codyjo.com",
                "dns_target": "bunny",
                "registration_target": "keep-current",
                "status": "in_progress",
                "next_step": "Keep the Bunny DNS cutover aligned with the live Fuel migration and verify auth, food search, and AI flows before removing rollback.",
                "notes": "Live Bunny-facing cutover in progress.",
            },
            {
                "id": "study.codyjo.com",
                "label": "study.codyjo.com",
                "dns_target": "bunny",
                "registration_target": "keep-current",
                "status": "in_progress",
                "next_step": "Keep the Bunny DNS cutover aligned with the live CertStudy migration and verify tutor, planner, share, and SRS flows before removing rollback.",
                "notes": "Live Bunny-facing cutover in progress.",
            },
            {
                "id": "cordivent.com",
                "label": "cordivent.com",
                "dns_target": "route53-temporary",
                "registration_target": "keep-current",
                "status": "planned",
                "next_step": "Defer DNS changes until the static pattern is proven elsewhere.",
                "notes": "",
            },
            {
                "id": "analogifystudio.com",
                "label": "analogifystudio.com",
                "dns_target": "route53-temporary",
                "registration_target": "keep-current",
                "status": "blocked",
                "next_step": "Do not change DNS this weekend.",
                "notes": "Analogify is deferred.",
            },
        ],
        "updates": [
            {
                "at": now,
                "actor": "codex",
                "kind": "note",
                "message": (
                    "Initialized the redesign-first migration plan around Bunny-first delivery, "
                    "Bunny Database where feasible, Magic Containers for fitting runtime workloads, Scaleway fallback/core, and GCP email continuity."
                ),
            }
        ],
    }


def _normalize_item(item: dict, *, item_type: str) -> dict:
    item = dict(item)
    item.setdefault("id", "")
    item.setdefault("label", item.get("title", item.get("id", "")))
    item.setdefault("status", "planned")
    if item["status"] not in STATUS_ORDER:
        item["status"] = "planned"
    item.setdefault("notes", "")
    item.setdefault("next_step", "")
    if item_type in {"phases", "repositories"}:
        item.setdefault("target", "hybrid")
        if item["target"] not in TARGET_ORDER:
            item["target"] = "hybrid"
    if item_type == "domains":
        item.setdefault("dns_target", "route53-temporary")
        item.setdefault("registration_target", "keep-current")
        if item["dns_target"] not in DOMAIN_TARGET_ORDER:
            item["dns_target"] = "route53-temporary"
        if item["registration_target"] not in DOMAIN_TARGET_ORDER:
            item["registration_target"] = "keep-current"
    return item


def _build_dashboard_payload(raw: dict) -> dict:
    payload = deepcopy(raw)
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", iso_now())
    payload.setdefault("goal", "")
    payload.setdefault("principles", [])
    payload["phases"] = [_normalize_item(item, item_type="phases") for item in payload.get("phases", [])]
    payload["repositories"] = [_normalize_item(item, item_type="repositories") for item in payload.get("repositories", [])]
    payload["domains"] = [_normalize_item(item, item_type="domains") for item in payload.get("domains", [])]
    payload.setdefault("updates", [])

    def counts(items: list[dict]) -> dict[str, int]:
        bucket = {status: 0 for status in STATUS_ORDER}
        for item in items:
            bucket[item.get("status", "planned")] = bucket.get(item.get("status", "planned"), 0) + 1
        return bucket

    repo_counts = counts(payload["repositories"])
    phase_counts = counts(payload["phases"])
    domain_counts = counts(payload["domains"])
    total_work_items = len(payload["repositories"]) + len(payload["domains"])
    completed_work_items = repo_counts.get("complete", 0) + domain_counts.get("complete", 0)

    payload["summary"] = {
        "goal": payload["goal"],
        "updated_at": payload["updated_at"],
        "repository_counts": repo_counts,
        "phase_counts": phase_counts,
        "domain_counts": domain_counts,
        "total_work_items": total_work_items,
        "completed_work_items": completed_work_items,
        "completion_pct": round((completed_work_items / total_work_items) * 100) if total_work_items else 0,
        "scaleway_targets": sum(1 for item in payload["repositories"] if item.get("target") == "scaleway"),
        "bunny_targets": sum(1 for item in payload["repositories"] if item.get("target") == "bunny"),
        "hybrid_targets": sum(1 for item in payload["repositories"] if item.get("target") == "hybrid"),
        "deferred_targets": sum(1 for item in payload["repositories"] if item.get("target") == "defer"),
    }
    return payload


def load(root: Path) -> dict:
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
                "phases": normalized["phases"],
                "repositories": normalized["repositories"],
                "domains": normalized["domains"],
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
    target: str | None = None,
    dns_target: str | None = None,
    registration_target: str | None = None,
    notes: str | None = None,
    next_step: str | None = None,
) -> dict:
    if collection not in {"phases", "repositories", "domains"}:
        raise ValueError("collection must be one of: phases, repositories, domains")
    payload = load(root)
    items = payload.get(collection, [])
    for item in items:
        if item.get("id") == item_id:
            if status is not None:
                if status not in STATUS_ORDER:
                    raise ValueError(f"unsupported status: {status}")
                item["status"] = status
            if target is not None and collection in {"phases", "repositories"}:
                if target not in TARGET_ORDER:
                    raise ValueError(f"unsupported target: {target}")
                item["target"] = target
            if dns_target is not None and collection == "domains":
                if dns_target not in DOMAIN_TARGET_ORDER:
                    raise ValueError(f"unsupported dns_target: {dns_target}")
                item["dns_target"] = dns_target
            if registration_target is not None and collection == "domains":
                if registration_target not in DOMAIN_TARGET_ORDER:
                    raise ValueError(f"unsupported registration_target: {registration_target}")
                item["registration_target"] = registration_target
            if notes is not None:
                item["notes"] = notes
            if next_step is not None:
                item["next_step"] = next_step
            payload["updated_at"] = iso_now()
            return save(root, payload)
    raise ValueError(f"Unknown migration plan item id: {item_id}")


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
    """Seed the first cloud migration wave into the Back Office task queue."""
    from backoffice import tasks as task_module  # noqa: PLC0415

    context = task_module.load_context(
        root / "config" / "task-queue.yaml",
        root / "config" / "targets.yaml",
        root / "results",
        root / "dashboard",
    )
    existing_ids = {task.get("id") for task in context.payload.get("tasks", [])}
    blueprints = [
        {
            "id": "cloud-migration:provider-foundation",
            "repo": "back-office",
            "title": "Stand up Scaleway and Bunny migration foundation",
            "category": "infrastructure",
            "task_type": "migration_execution",
            "priority": "high",
            "status": "in_progress",
            "created_by": "codex",
            "owner": "codex",
            "notes": (
                "Establish Bunny static-delivery baseline plus Scaleway backend/secrets baseline."
            ),
            "product_key": "back-office",
            "target_path": str(root),
            "acceptance_criteria": [
                "provider bootstrap checklist is finalized",
                "portfolio migration dependencies are mapped to Bunny, Scaleway, and GCP email continuity",
                "next implementation repo or terraform target is identified",
                "migration dashboard is updated with current progress and blockers",
            ],
            "verification_command": "python3 -m pytest tests/test_migration_plan.py tests/test_servers.py",
            "repo_handoff_path": str(root / "docs" / "HANDOFF.md"),
        },
        {
            "id": "cloud-migration:codyjo-scaleway-cutover",
            "repo": "codyjo.com",
            "title": "Prepare codyjo.com Bunny static cutover",
            "category": "infrastructure",
            "task_type": "migration_execution",
            "priority": "high",
            "status": "pending_approval",
            "created_by": "codex",
            "notes": (
                "Deploy codyjo.com to Bunny as the primary static destination and "
                "prepare cutover without deleting the current AWS fallback."
            ),
            "acceptance_criteria": [
                "Bunny deploy path works",
                "Bunny cutover steps are documented",
                "rollback to current AWS edge is documented",
            ],
        },
        {
            "id": "cloud-migration:auth-service-replacement-design",
            "repo": "auth-service",
            "title": "Design and prepare non-AWS replacement path for shared auth service",
            "category": "infrastructure",
            "task_type": "migration_execution",
            "priority": "high",
            "status": "pending_approval",
            "created_by": "codex",
            "notes": (
                "Replace Route53/ACM/API Gateway/DynamoDB coupling with a non-AWS auth "
                "runtime and custom-domain plan that works across product domains."
            ),
            "acceptance_criteria": [
                "target runtime is chosen",
                "custom-domain and certificate plan is documented",
                "consumer apps have a cutover dependency list",
            ],
        },
        {
            "id": "cloud-migration:search-scaleway-instance-cutover",
            "repo": "search",
            "title": "Prepare search Scaleway instance cutover",
            "category": "infrastructure",
            "task_type": "migration_execution",
            "priority": "high",
            "status": "pending_approval",
            "created_by": "codex",
            "notes": (
                "Rebuild the current AWS EC2 search runtime on a Scaleway instance after the first "
                "static migration succeeds."
            ),
            "acceptance_criteria": [
                "Scaleway instance blueprint is documented",
                "cutover and rollback are documented",
                "AWS instance remains intact until validation passes",
            ],
        },
        {
            "id": "cloud-migration:certstudy-runtime-review",
            "repo": "certstudy",
            "title": "Review CertStudy split-origin migration after shared services are ready",
            "category": "feature",
            "task_type": "migration_execution",
            "priority": "medium",
            "status": "pending_approval",
            "created_by": "codex",
            "notes": (
                "Only consider a static-origin move while the AWS API remains live."
            ),
            "acceptance_criteria": [
                "frontend/backend split risks are documented",
                "shared-service dependencies are listed",
                "rollback plan is written",
            ],
        },
    ]

    created = []
    tasks_list = context.payload.setdefault("tasks", [])
    for blueprint in blueprints:
        if blueprint["id"] in existing_ids:
            continue
        created.append(blueprint["id"])
        task = task_module.ensure_task_defaults(blueprint, context.targets)
        task_module.append_history(task, task.get("status", "pending_approval"), "codex", "Seeded from migration plan wave one")
        tasks_list.append(task)
    task_queue = task_module.save_payload(
        context.payload,
        context.targets,
        context.config_path,
        context.results_dir,
        context.dashboard_dir,
    )

    return {
        "created_task_ids": created,
        "migration_plan": load(root),
        "task_queue": task_queue,
    }
