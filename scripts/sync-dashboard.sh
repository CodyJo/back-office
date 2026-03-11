#!/usr/bin/env bash
# Sync all department dashboards and data to S3
# Usage: ./scripts/sync-dashboard.sh
#
# For each dashboard_target in config, this script:
#   1. Uploads all dashboard HTML files
#   2. If the target has a 'repo' field, deploys that repo's raw findings
#      as the department data files (so dashboards show only that site's data)
#   3. Falls back to aggregated data if no repo is specified

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG="$QA_ROOT/config/qa-config.yaml"

if [ ! -f "$CONFIG" ]; then
  echo "No config at $CONFIG — copy from qa-config.example.yaml" >&2
  exit 1
fi

# ── Run scoring tests as pre-deploy gate ─────────────────────────────────────

echo "Running scoring tests..."
if ! python3 "$SCRIPT_DIR/test-scoring.py"; then
  echo "ERROR: Scoring tests failed — deploy aborted." >&2
  exit 1
fi
echo "Scoring tests passed."
echo ""

# ── Aggregate all results into department-specific dashboard payloads ─────────

echo "Aggregating results..."
python3 "$SCRIPT_DIR/aggregate-results.py" "$QA_ROOT/results" "$QA_ROOT/dashboard/data.json"

# ── Deploy to S3 ─────────────────────────────────────────────────────────────

python3 -c "
import yaml, subprocess, sys, os, json, shutil

with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)

targets = cfg.get('dashboard_targets', [])
if not targets:
    print('No dashboard_targets in config', file=sys.stderr)
    sys.exit(0)

dashboard_dir = '$QA_ROOT/dashboard'
results_dir = '$QA_ROOT/results'

dashboard_files = [
    'index.html', 'qa.html', 'backoffice.html',
    'seo.html', 'ada.html', 'compliance.html', 'privacy.html', 'monetization.html', 'product.html',
    'jobs.html', 'faq.html', 'self-audit.html', 'admin.html',
    'selah.html', 'analogify.html', 'chromahaus.html', 'tnbm-tarot.html', 'back-office-hq.html',
    'site-branding.js', 'favicon.svg',
]

# Maps: raw findings filename -> dashboard data filename
dept_data_map = [
    ('findings.json', 'qa-data.json'),
    ('seo-findings.json', 'seo-data.json'),
    ('ada-findings.json', 'ada-data.json'),
    ('compliance-findings.json', 'compliance-data.json'),
    ('privacy-findings.json', 'privacy-data.json'),
    ('monetization-findings.json', 'monetization-data.json'),
    ('product-findings.json', 'product-data.json'),
]

# Job status files (from dashboard dir, not per-repo)
job_status_files = ['.jobs.json', '.jobs-history.json']

# Aggregated data files (used when no repo filter is specified)
agg_data_files = [
    ('data.json', 'qa-data.json'),
    ('seo-data.json', 'seo-data.json'),
    ('ada-data.json', 'ada-data.json'),
    ('compliance-data.json', 'compliance-data.json'),
    ('privacy-data.json', 'privacy-data.json'),
    ('monetization-data.json', 'monetization-data.json'),
    ('product-data.json', 'product-data.json'),
    ('org-data.json', 'org-data.json'),
    ('.jobs.json', '.jobs.json'),
    ('.jobs-history.json', '.jobs-history.json'),
    ('local-audit-log.json', 'local-audit-log.json'),
    ('local-audit-log.md', 'local-audit-log.md'),
]


def upload_file(local_path, bucket, s3_key, content_type):
    print(f'  Deploying {os.path.basename(local_path)} -> s3://{bucket}/{s3_key}')
    subprocess.run([
        'aws', 's3', 'cp', local_path,
        f's3://{bucket}/{s3_key}',
        '--content-type', content_type,
        '--cache-control', 'no-cache, no-store, must-revalidate'
    ], check=True)


for t in targets:
    bucket = t['bucket']
    base_path = t.get('base_path', '')
    cf_id = t.get('cloudfront_id', '')
    repo = t.get('repo', '')  # If set, deploy only this repo's data

    prefix = f'{base_path}/' if base_path else ''
    invalidation_paths = []

    print(f'\\nDeploying to {bucket}' + (f' (repo: {repo})' if repo else ' (all repos)'))

    # Upload all dashboard files (HTML + JS)
    for dash_file in dashboard_files:
        local_path = os.path.join(dashboard_dir, dash_file)
        if not os.path.exists(local_path):
            print(f'  Skipping {dash_file} (not found)')
            continue
        s3_key = f'{prefix}{dash_file}'
        if dash_file.endswith('.js'):
            content_type = 'application/javascript'
        elif dash_file.endswith('.svg'):
            content_type = 'image/svg+xml'
        else:
            content_type = 'text/html'
        upload_file(local_path, bucket, s3_key, content_type)
        invalidation_paths.append(f'/{s3_key}')

    # Upload data files — per-repo raw data or aggregated data
    if repo:
        # Deploy raw per-repo findings so dashboards show only this site's data
        repo_dir = os.path.join(results_dir, repo)
        if not os.path.isdir(repo_dir):
            print(f'  WARNING: No results directory for repo \"{repo}\"')
        else:
            for raw_file, s3_name in dept_data_map:
                raw_path = os.path.join(repo_dir, raw_file)
                if not os.path.exists(raw_path):
                    print(f'  Skipping {s3_name} (no {raw_file} for {repo})')
                    continue
                s3_key = f'{prefix}{s3_name}'
                upload_file(raw_path, bucket, s3_key, 'application/json')
                invalidation_paths.append(f'/{s3_key}')
        # Also deploy job status and history from dashboard dir
        for job_file in job_status_files:
            local_path = os.path.join(dashboard_dir, job_file)
            if os.path.exists(local_path):
                s3_key = f'{prefix}{job_file}'
                upload_file(local_path, bucket, s3_key, 'application/json')
                invalidation_paths.append(f'/{s3_key}')
    else:
        # Deploy aggregated data (all repos combined)
        for local_name, s3_name in agg_data_files:
            local_path = os.path.join(dashboard_dir, local_name)
            if not os.path.exists(local_path):
                print(f'  Skipping {local_name} (not found)')
                continue
            s3_key = f'{prefix}{s3_name}'
            content_type = 'text/markdown' if local_name.endswith('.md') else 'application/json'
            upload_file(local_path, bucket, s3_key, content_type)
            invalidation_paths.append(f'/{s3_key}')

    # Invalidate CloudFront cache
    if cf_id and invalidation_paths:
        print(f'  Invalidating CloudFront {cf_id} ({len(invalidation_paths)} paths)')
        subprocess.run([
            'aws', 'cloudfront', 'create-invalidation',
            '--distribution-id', cf_id,
            '--paths', *invalidation_paths
        ], check=True)

print('\\nDashboard sync complete.')
"
