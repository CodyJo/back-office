"""Deterministic mentorship planning for operator education goals."""
from __future__ import annotations

from datetime import datetime, timezone

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, normalized))


def _cert_focus(target_cloud: str) -> str:
    if target_cloud == 'aws':
        return 'AWS'
    return 'Google Cloud Associate Cloud Engineer'


def _concept_map(target_cloud: str) -> list[dict[str, str]]:
    if target_cloud == 'aws':
        return [
            {'current': 'Terraform + shared modules', 'target': 'AWS Organizations, IAM, and IaC discipline', 'why': 'Keep the same ops habits while tightening account and permission boundaries.'},
            {'current': 'Cloud Run / App Runner analog thinking', 'target': 'Lambda, ECS Fargate, and App Runner decision-making', 'why': 'Choose the simplest execution model per service instead of defaulting to one runtime.'},
            {'current': 'Cloud Monitoring habits', 'target': 'CloudWatch metrics, logs, and alarms', 'why': 'Translate observability into AWS-native primitives.'},
        ]
    return [
        {'current': 'Route53 + CloudFront', 'target': 'Cloud DNS + Cloud CDN + Load Balancing', 'why': 'Map your current edge and DNS model into Google Cloud equivalents.'},
        {'current': 'CodeBuild + App Runner', 'target': 'Cloud Build + Cloud Run', 'why': 'Translate deployment automation into GCP services you can operate directly.'},
        {'current': 'Lambda + scheduled jobs', 'target': 'Cloud Run jobs and Cloud Functions', 'why': 'Understand when Google Cloud wants containers versus functions.'},
        {'current': 'IAM roles and service roles', 'target': 'IAM roles, service accounts, and project boundaries', 'why': 'This is the biggest practical recertification topic for managing your own environment.'},
        {'current': 'CloudWatch + budgets', 'target': 'Cloud Monitoring, Logging, and budgets/quotas', 'why': 'Operate safely without losing cost or runtime visibility.'},
    ]


def _portfolio_labs(targets: dict[str, dict], use_portfolio_context: bool) -> list[dict[str, str]]:
    if not use_portfolio_context:
        return []

    labs: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, target in targets.items():
        departments = target.get('default_departments') or []
        language = (target.get('language') or '').strip()
        if name in seen:
            continue
        if language == 'terraform' or 'cloud-ops' in departments or name in {'back-office', 'continuum', 'fuel', 'certstudy'}:
            labs.append({
                'repo': name,
                'path': target.get('path', ''),
                'focus': target.get('context', '').strip().splitlines()[0] if target.get('context', '').strip() else 'Use this repo to translate your current environment into explicit cloud concepts.' or 'Use this repo to translate your current environment into explicit cloud concepts.',
            })
            seen.add(name)
        if len(labs) >= 5:
            break
    return labs


def _milestones(goal: str, target_cloud: str, horizon_weeks: int) -> list[dict[str, object]]:
    default = [
        ('Inventory and map your current environment', 'Write down how your AWS-heavy portfolio maps into core GCP services, IAM boundaries, billing, and project structure.', ['Environment inventory', 'AWS-to-GCP concept map', 'List of unknowns to close']),
        ('Projects, IAM, and org fundamentals', 'Practice the account, identity, service account, and least-privilege topics that usually separate theoretical knowledge from real operator competence.', ['Create a study sheet for IAM and projects', 'Document service-account patterns you actually use', 'Explain roles versus policies in your own words']),
        ('Compute and application deployment', 'Cover Compute Engine, Cloud Run, containers, and deployment workflows using your current App Runner and CodeBuild experience as comparison points.', ['Compare App Runner to Cloud Run', 'Deploy one tiny app or dry-run deployment', 'Summarize where each service fits']),
        ('Networking, storage, and operations', 'Work through VPCs, load balancing, storage, logging, monitoring, quotas, and budgets until you can explain how you would operate a small app safely.', ['Network and storage flashcards', 'Monitoring checklist', 'Budget/quota checklist']),
        ('Exam rehearsal and targeted repair', 'Use practice questions to find weak spots, then go back to docs and your own environment map to repair understanding.', ['Practice set review', 'Weak-area list', 'Final study notes']),
    ]
    if target_cloud == 'aws':
        default[1] = ('Accounts, IAM, and guardrails', 'Refresh the AWS identity and account-boundary model before touching deeper architecture review.', ['IAM summary notes', 'Least-privilege checklist', 'Guardrail review'])
    if horizon_weeks <= len(default):
        selected = default[:horizon_weeks]
    else:
        selected = default + [(f'Confidence week {i}', 'Re-run labs, docs, and practice questions with less support until the workflow feels obvious.', ['Practice exam review', 'Gap repair notes', 'Hands-on walkthrough']) for i in range(1, horizon_weeks - len(default) + 1)]
    milestones = []
    for idx, (title, focus, deliverables) in enumerate(selected, start=1):
        milestones.append({
            'week': idx,
            'title': title,
            'focus': focus,
            'deliverables': deliverables,
        })
    return milestones


def build_mentor_plan(request: dict, targets: dict[str, dict]) -> dict:
    target_cloud = (request.get('target_cloud') or 'gcp').strip().lower()
    if target_cloud not in {'gcp', 'aws'}:
        target_cloud = 'gcp'
    goal = (request.get('goal') or '').strip() or f'Renew {_cert_focus(target_cloud)} and operate the environment independently'
    current_state = (request.get('current_state') or '').strip() or 'Existing certification has expired; operator wants stronger hands-on understanding rather than just a test pass.'
    weekly_hours = _normalize_int(request.get('weekly_hours'), 6, 2, 20)
    horizon_weeks = _normalize_int(request.get('horizon_weeks'), 8, 2, 16)
    use_portfolio_context = bool(request.get('use_portfolio_context', True))
    renew_aws = bool(request.get('renew_aws', False))
    labs = _portfolio_labs(targets, use_portfolio_context)
    cert_focus = _cert_focus(target_cloud)
    summary = (
        f'{goal}. Focus on {cert_focus}, use the current portfolio as the lab environment, '
        f'and treat AWS knowledge as comparison context rather than as a second renewal track.'
        if target_cloud == 'gcp' and not renew_aws
        else f'{goal}. Use the current portfolio as the lab environment and translate existing cloud experience into the target certification domain.'
    )
    return {
        'generated_at': _iso_now(),
        'title': goal,
        'target_cloud': target_cloud,
        'cert_focus': cert_focus,
        'current_state': current_state,
        'weekly_hours': weekly_hours,
        'horizon_weeks': horizon_weeks,
        'use_portfolio_context': use_portfolio_context,
        'renew_aws': renew_aws,
        'summary': summary,
        'concept_map': _concept_map(target_cloud),
        'portfolio_labs': labs,
        'milestones': _milestones(goal, target_cloud, horizon_weeks),
        'recommended_habits': [
            'Write one page of notes in your own words after every study block.',
            'Map every cloud concept back to one repo or deployment you actually own.',
            'Use practice questions to find weak spots only after you can explain the concept without the answer choices.',
            'Keep renewal scope narrow: GCP first, AWS only as contrast material unless goals change.',
        ],
    }
