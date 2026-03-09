#!/usr/bin/env bash
# Sync all department dashboards and data to S3
# Usage: ./scripts/sync-dashboard.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG="$QA_ROOT/config/qa-config.yaml"

if [ ! -f "$CONFIG" ]; then
  echo "No config at $CONFIG — copy from qa-config.example.yaml" >&2
  exit 1
fi

# ── Aggregate all results into department-specific dashboard payloads ─────────

echo "Aggregating results..."
python3 "$SCRIPT_DIR/aggregate-results.py" "$QA_ROOT/results" "$QA_ROOT/dashboard/data.json"

# ── Dashboard files to deploy ────────────────────────────────────────────────

DASHBOARD_FILES=(
  "index.html"
  "backoffice.html"
  "seo.html"
  "ada.html"
  "compliance.html"
)

DATA_FILES=(
  "data.json:qa-data.json"
  "seo-data.json:seo-data.json"
  "ada-data.json:ada-data.json"
  "compliance-data.json:compliance-data.json"
)

# ── Deploy to S3 ─────────────────────────────────────────────────────────────

python3 -c "
import yaml, subprocess, sys, os

with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)

targets = cfg.get('dashboard_targets', [])
if not targets:
    print('No dashboard_targets in config', file=sys.stderr)
    sys.exit(0)

dashboard_dir = '$QA_ROOT/dashboard'
dashboard_files = ['index.html', 'backoffice.html', 'seo.html', 'ada.html', 'compliance.html']
data_files = [
    ('data.json', 'qa-data.json'),
    ('seo-data.json', 'seo-data.json'),
    ('ada-data.json', 'ada-data.json'),
    ('compliance-data.json', 'compliance-data.json'),
]

invalidation_paths = []

for t in targets:
    bucket = t['bucket']
    base_path = t.get('base_path', '')
    cf_id = t.get('cloudfront_id', '')

    prefix = f'{base_path}/' if base_path else ''

    # Upload all dashboard HTML files
    for html_file in dashboard_files:
        local_path = os.path.join(dashboard_dir, html_file)
        if not os.path.exists(local_path):
            print(f'  Skipping {html_file} (not found)')
            continue
        s3_key = f'{prefix}{html_file}'
        print(f'  Deploying {html_file} to s3://{bucket}/{s3_key}')
        subprocess.run([
            'aws', 's3', 'cp', local_path,
            f's3://{bucket}/{s3_key}',
            '--content-type', 'text/html',
            '--cache-control', 'no-cache, no-store, must-revalidate'
        ], check=True)
        invalidation_paths.append(f'/{s3_key}')

    # Upload all data JSON files
    for local_name, s3_name in data_files:
        local_path = os.path.join(dashboard_dir, local_name)
        if not os.path.exists(local_path):
            print(f'  Skipping {local_name} (not found)')
            continue
        s3_key = f'{prefix}{s3_name}'
        print(f'  Deploying {s3_name} to s3://{bucket}/{s3_key}')
        subprocess.run([
            'aws', 's3', 'cp', local_path,
            f's3://{bucket}/{s3_key}',
            '--content-type', 'application/json',
            '--cache-control', 'no-cache, no-store, must-revalidate'
        ], check=True)
        invalidation_paths.append(f'/{s3_key}')

    # Invalidate CloudFront cache
    if cf_id and invalidation_paths:
        print(f'  Invalidating CloudFront {cf_id} ({len(invalidation_paths)} paths)')
        subprocess.run([
            'aws', 'cloudfront', 'create-invalidation',
            '--distribution-id', cf_id,
            '--paths', *invalidation_paths
        ], check=True)

print('Dashboard sync complete.')
"
