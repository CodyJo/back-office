"""Reusable cloud migration service mapping and cost comparison helpers."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "config" / "cloud-cost-comparison.yaml",
        root / "results" / "cloud-cost-comparison.json",
        root / "dashboard" / "cloud-cost-comparison.json",
    )


def _default_config() -> dict:
    return {
        "version": 1,
        "updated_at": "2026-03-26T23:59:00+00:00",
        "source": {
            "account_id": "229678440188",
            "period_start": "2026-03-01",
            "period_end": "2026-03-27",
            "currency": "USD",
            "basis": "month_to_date",
            "notes": (
                "Seeded from AWS Cost Explorer SERVICE breakdown plus a CloudFront "
                "USAGE_TYPE inspection for the current month."
            ),
        },
        "line_items": [
            {"service": "AWS App Runner", "amount": 0.1656633336, "class": "platform"},
            {"service": "AWS Backup", "amount": 0.0001094313, "class": "platform"},
            {"service": "AWS Cost Explorer", "amount": 1.82, "class": "tooling"},
            {"service": "AWS Key Management Service", "amount": 0.016129032, "class": "platform"},
            {"service": "AWS Lambda", "amount": 0.0000317677, "class": "platform"},
            {"service": "AWS Secrets Manager", "amount": 4.094236486, "class": "platform"},
            {"service": "AWS WAF", "amount": 17.0935563181, "class": "platform"},
            {"service": "Amazon API Gateway", "amount": 0.724703, "class": "platform"},
            {
                "service": "Amazon CloudFront",
                "amount": 1307.5532844591,
                "class": "platform",
                "usage_breakdown": [
                    {"usage_type": "Invalidations", "amount": 1307.55},
                    {"usage_type": "Other", "amount": 0.0032844591},
                ],
            },
            {"service": "Amazon DynamoDB", "amount": 0.68849702, "class": "data"},
            {"service": "Amazon Elastic Compute Cloud - Compute", "amount": 7.375168684, "class": "platform"},
            {"service": "EC2 - Other", "amount": 4.4095496317, "class": "platform"},
            {"service": "Amazon Registrar", "amount": 45.0, "class": "domain"},
            {"service": "Amazon Route 53", "amount": 3.0773320256, "class": "domain"},
            {"service": "Amazon Simple Storage Service", "amount": 4.2060754666, "class": "data"},
            {"service": "Amazon Virtual Private Cloud", "amount": 1.736237505, "class": "platform"},
            {"service": "AmazonCloudWatch", "amount": 1.7752302812, "class": "tooling"},
            {"service": "CodeBuild", "amount": 1.98, "class": "tooling"},
            {"service": "Tax", "amount": 1.8, "class": "tax"},
        ],
    }


def _mapping_catalog() -> list[dict]:
    return [
        {
            "aws_service": "Amazon CloudFront",
            "category": "Edge delivery",
            "gcp_service": "Cloud CDN + HTTPS Load Balancer",
            "vercel_service": "Vercel Edge Network",
            "netlify_service": "Netlify CDN",
            "notes": "Primary static and edge delivery layer. Current bill is dominated by invalidations, not transfer.",
        },
        {
            "aws_service": "AWS WAF",
            "category": "Security",
            "gcp_service": "Cloud Armor",
            "vercel_service": "Managed WAF / enterprise security controls",
            "netlify_service": "Third-party / limited native edge security",
            "notes": "A direct managed security control in AWS and GCP; weaker one-to-one mapping on frontend platforms.",
        },
        {
            "aws_service": "Amazon Route 53",
            "category": "DNS",
            "gcp_service": "Cloud DNS",
            "vercel_service": "Vercel DNS",
            "netlify_service": "Netlify DNS",
            "notes": "Straightforward DNS migration surface.",
        },
        {
            "aws_service": "Amazon Registrar",
            "category": "Domains",
            "gcp_service": "Cloud Domains or external registrar",
            "vercel_service": "External registrar",
            "netlify_service": "External registrar",
            "notes": "Registrar cost usually carries through regardless of hosting choice.",
        },
        {
            "aws_service": "AWS Secrets Manager",
            "category": "Secrets",
            "gcp_service": "Secret Manager",
            "vercel_service": "Project env vars / external secrets",
            "netlify_service": "Environment variables / external secrets",
            "notes": "Security posture differs even when monthly cost is lower on a frontend platform.",
        },
        {
            "aws_service": "AWS App Runner",
            "category": "App runtime",
            "gcp_service": "Cloud Run",
            "vercel_service": "Functions / Fluid Compute",
            "netlify_service": "Functions / Edge Functions",
            "notes": "Cloud Run is the closest operational analog for your portfolio.",
        },
        {
            "aws_service": "Amazon API Gateway",
            "category": "API ingress",
            "gcp_service": "API Gateway or Cloud Run ingress",
            "vercel_service": "Serverless route handlers",
            "netlify_service": "Functions routes",
            "notes": "Often collapses into app runtime routing on GCP or frontend platforms.",
        },
        {
            "aws_service": "AWS Lambda",
            "category": "Functions",
            "gcp_service": "Cloud Functions or Cloud Run",
            "vercel_service": "Functions",
            "netlify_service": "Functions",
            "notes": "Low current spend; this is not a major cost driver today.",
        },
        {
            "aws_service": "CodeBuild",
            "category": "CI/CD",
            "gcp_service": "Cloud Build",
            "vercel_service": "Built-in deploy pipeline",
            "netlify_service": "Built-in deploy pipeline",
            "notes": "Frontend platforms absorb most of this build cost into plan pricing.",
        },
        {
            "aws_service": "Amazon Simple Storage Service",
            "category": "Object storage",
            "gcp_service": "Cloud Storage",
            "vercel_service": "Static asset store / Blob / external object storage",
            "netlify_service": "Static asset store / external object storage",
            "notes": "For anything beyond static assets, GCP stays closer to the AWS shape.",
        },
        {
            "aws_service": "Amazon DynamoDB",
            "category": "Database",
            "gcp_service": "Firestore or Cloud SQL",
            "vercel_service": "External database",
            "netlify_service": "External database",
            "notes": "Frontend platforms usually do not replace your database choice directly.",
        },
        {
            "aws_service": "Amazon Elastic Compute Cloud - Compute",
            "category": "Compute",
            "gcp_service": "Cloud Run or Compute Engine",
            "vercel_service": "External runtime for non-frontend workloads",
            "netlify_service": "External runtime for non-frontend workloads",
            "notes": "Persistent or bespoke compute is where pure frontend platforms stop fitting cleanly.",
        },
    ]


SCENARIOS = {
    "aws_full": {
        "label": "Fully AWS",
        "description": "Stay on AWS and normalize the current bill after removing the CloudFront invalidation anomaly.",
        "platform": "aws",
        "base_low": 0.0,
        "base_high": 0.0,
        "factors": {},
        "confidence": "medium",
        "notes": [
            "Uses your current AWS bill as the closest baseline.",
            "Keeps registrar and DNS costs in the estimate.",
        ],
    },
    "gcp_full": {
        "label": "Fully GCP",
        "description": "Rebuild the operational stack on GCP primitives while carrying domains and data services.",
        "platform": "gcp",
        "base_low": 0.0,
        "base_high": 0.0,
        "confidence": "medium",
        "factors": {
            "AWS App Runner": (0.7, 1.0),
            "AWS Backup": (0.6, 1.0),
            "AWS Key Management Service": (0.6, 1.0),
            "AWS Lambda": (0.7, 1.0),
            "AWS Secrets Manager": (0.4, 0.8),
            "AWS WAF": (0.7, 1.1),
            "Amazon API Gateway": (0.5, 1.0),
            "Amazon CloudFront": (0.0, 0.1),
            "Amazon DynamoDB": (0.9, 1.3),
            "Amazon Elastic Compute Cloud - Compute": (0.7, 1.0),
            "EC2 - Other": (0.6, 1.0),
            "Amazon Registrar": (0.8, 1.0),
            "Amazon Route 53": (0.6, 1.0),
            "Amazon Simple Storage Service": (0.8, 1.1),
            "Amazon Virtual Private Cloud": (0.6, 1.0),
            "AmazonCloudWatch": (0.6, 1.0),
            "CodeBuild": (0.6, 1.0),
        },
        "notes": [
            "Cloud Run is the intended runtime analog for App Runner and smaller EC2 workloads.",
            "CloudFront invalidation charges are treated as anomalous and not carried over directly.",
        ],
    },
    "vercel_full": {
        "label": "Fully Vercel",
        "description": "Push the frontend-heavy estate into Vercel and externalize the non-frontend pieces that do not fit.",
        "platform": "vercel",
        "base_low": 20.0,
        "base_high": 60.0,
        "confidence": "low",
        "factors": {
            "AWS App Runner": (0.0, 0.5),
            "AWS Backup": (0.0, 0.2),
            "AWS Key Management Service": (0.0, 0.2),
            "AWS Lambda": (0.0, 0.5),
            "AWS Secrets Manager": (0.0, 0.3),
            "AWS WAF": (0.0, 0.3),
            "Amazon API Gateway": (0.0, 0.5),
            "Amazon CloudFront": (0.0, 0.0),
            "Amazon DynamoDB": (0.8, 1.3),
            "Amazon Elastic Compute Cloud - Compute": (0.0, 0.6),
            "EC2 - Other": (0.0, 0.4),
            "Amazon Registrar": (0.8, 1.0),
            "Amazon Route 53": (0.4, 0.8),
            "Amazon Simple Storage Service": (0.0, 0.5),
            "Amazon Virtual Private Cloud": (0.0, 0.2),
            "AmazonCloudWatch": (0.0, 0.2),
            "CodeBuild": (0.0, 0.2),
        },
        "notes": [
            "Assumes a small-team Pro baseline; public Vercel pricing currently shows Pro anchored at $20.",
            "Database and bespoke backend needs are still treated as external carry.",
            "Security and WAF parity may require enterprise features or tradeoffs.",
        ],
    },
    "netlify_full": {
        "label": "Fully Netlify",
        "description": "Use Netlify as the frontend platform competitor baseline with similar externalization assumptions.",
        "platform": "netlify",
        "base_low": 20.0,
        "base_high": 60.0,
        "confidence": "low",
        "factors": {
            "AWS App Runner": (0.0, 0.5),
            "AWS Backup": (0.0, 0.2),
            "AWS Key Management Service": (0.0, 0.2),
            "AWS Lambda": (0.0, 0.5),
            "AWS Secrets Manager": (0.0, 0.3),
            "AWS WAF": (0.0, 0.4),
            "Amazon API Gateway": (0.0, 0.5),
            "Amazon CloudFront": (0.0, 0.0),
            "Amazon DynamoDB": (0.8, 1.3),
            "Amazon Elastic Compute Cloud - Compute": (0.0, 0.6),
            "EC2 - Other": (0.0, 0.4),
            "Amazon Registrar": (0.8, 1.0),
            "Amazon Route 53": (0.4, 0.8),
            "Amazon Simple Storage Service": (0.0, 0.5),
            "Amazon Virtual Private Cloud": (0.0, 0.2),
            "AmazonCloudWatch": (0.0, 0.2),
            "CodeBuild": (0.0, 0.2),
        },
        "notes": [
            "Assumes a current public Netlify Pro-style team baseline; the pricing page currently shows Personal $9 and Pro $20 per member/month.",
            "As with Vercel, database and bespoke backend services remain external.",
        ],
    },
}


def _write_files(root: Path, config: dict, payload: dict) -> dict:
    cfg_path, results_path, dashboard_path = _paths(root)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False))
    rendered = json.dumps(payload, indent=2)
    results_path.write_text(rendered + "\n")
    dashboard_path.write_text(rendered + "\n")
    return payload


def _load_config(root: Path) -> dict:
    cfg_path, _, _ = _paths(root)
    if not cfg_path.exists():
        return _default_config()
    payload = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(payload, dict):
        return _default_config()
    return payload


def _find_line_item(config: dict, service: str) -> dict | None:
    for item in config.get("line_items", []):
        if item.get("service") == service:
            return item
    return None


def _detect_anomalies(config: dict) -> list[dict]:
    anomalies: list[dict] = []
    cloudfront = _find_line_item(config, "Amazon CloudFront")
    if cloudfront:
        breakdown = cloudfront.get("usage_breakdown") or []
        invalidations = 0.0
        total = float(cloudfront.get("amount") or 0.0)
        for entry in breakdown:
            if entry.get("usage_type") == "Invalidations":
                invalidations += float(entry.get("amount") or 0.0)
        if total and invalidations / total >= 0.95:
            anomalies.append(
                {
                    "service": "Amazon CloudFront",
                    "amount": round(invalidations, 2),
                    "type": "suspected_invalidation_anomaly",
                    "summary": (
                        "CloudFront spend is almost entirely invalidations instead of edge transfer "
                        "or request volume."
                    ),
                    "impact": "Scenario estimates treat this as non-recurring until proven otherwise.",
                }
            )
    return anomalies


def _basis_amount(config: dict, item: dict, anomalies: list[dict]) -> float:
    service = item.get("service")
    amount = float(item.get("amount") or 0.0)
    if service == "Tax":
        return 0.0
    if service == "AWS Cost Explorer":
        return 0.0
    for anomaly in anomalies:
        if anomaly.get("service") == service:
            return max(0.0, amount - float(anomaly.get("amount") or 0.0))
    return amount


def _baseline(config: dict) -> dict:
    anomalies = _detect_anomalies(config)
    total_actual = sum(float(item.get("amount") or 0.0) for item in config.get("line_items", []))
    total_excluding_tax = sum(
        float(item.get("amount") or 0.0)
        for item in config.get("line_items", [])
        if item.get("service") != "Tax"
    )
    normalized_basis = sum(_basis_amount(config, item, anomalies) for item in config.get("line_items", []))
    return {
        "period_start": config.get("source", {}).get("period_start"),
        "period_end": config.get("source", {}).get("period_end"),
        "total_actual_month_to_date": round(total_actual, 2),
        "total_excluding_tax": round(total_excluding_tax, 2),
        "normalized_basis_month_to_date": round(normalized_basis, 2),
        "anomalies": anomalies,
    }


def _scenario_breakdown(config: dict, scenario_id: str, anomalies: list[dict]) -> dict:
    scenario = SCENARIOS[scenario_id]
    low = float(scenario.get("base_low") or 0.0)
    high = float(scenario.get("base_high") or 0.0)
    lines = []
    for item in config.get("line_items", []):
        basis = _basis_amount(config, item, anomalies)
        if basis <= 0:
            continue
        factors = scenario.get("factors", {}).get(item.get("service"), (1.0, 1.0) if scenario_id == "aws_full" else (0.0, 0.0))
        line_low = round(basis * float(factors[0]), 2)
        line_high = round(basis * float(factors[1]), 2)
        low += line_low
        high += line_high
        lines.append(
            {
                "service": item.get("service"),
                "basis_amount": round(basis, 2),
                "estimate_low": line_low,
                "estimate_high": line_high,
                "class": item.get("class"),
            }
        )
    return {
        "id": scenario_id,
        "label": scenario.get("label"),
        "description": scenario.get("description"),
        "confidence": scenario.get("confidence"),
        "platform": scenario.get("platform"),
        "estimate_low": round(low, 2),
        "estimate_high": round(high, 2),
        "notes": scenario.get("notes", []),
        "line_items": lines,
    }


def _service_rows(config: dict) -> list[dict]:
    rows = []
    for mapping in _mapping_catalog():
        item = _find_line_item(config, mapping["aws_service"])
        row = deepcopy(mapping)
        row["current_month_to_date"] = round(float(item.get("amount") or 0.0), 2) if item else 0.0
        rows.append(row)
    rows.sort(key=lambda entry: entry["current_month_to_date"], reverse=True)
    return rows


def _build_payload(config: dict) -> dict:
    anomalies = _detect_anomalies(config)
    baseline = _baseline(config)
    scenarios = [_scenario_breakdown(config, scenario_id, anomalies) for scenario_id in ("aws_full", "gcp_full", "vercel_full", "netlify_full")]
    scenarios.sort(key=lambda entry: entry["estimate_low"])
    return {
        "version": int(config.get("version") or 1),
        "updated_at": iso_now(),
        "source": config.get("source", {}),
        "baseline": baseline,
        "scenarios": scenarios,
        "service_rows": _service_rows(config),
        "pricing_notes": [
            "Estimates are heuristic ranges built from your current AWS bill, not direct cloud-vendor quotes.",
            "Vercel pricing page currently exposes Hobby, Pro, Enterprise, Cron Jobs, Fluid Compute, Observability, and Web Analytics.",
            "Netlify pricing page currently exposes Personal $9/month and Pro $20 per member/month.",
            "Cloud Run pricing is request-based or instance-based with a free tier.",
            "CloudFront invalidation-heavy spend is treated as anomalous until investigated.",
        ],
        "sources": [
            "https://vercel.com/pricing",
            "https://vercel.com/docs/cron-jobs",
            "https://www.netlify.com/pricing/",
            "https://cloud.google.com/run/pricing",
            "https://cloud.google.com/secret-manager/pricing",
            "https://cloud.google.com/dns/pricing",
            "https://cloud.google.com/cdn/pricing",
        ],
    }


def load(root: Path) -> dict:
    config = _load_config(root)
    payload = _build_payload(config)
    return _write_files(root, config, payload)

