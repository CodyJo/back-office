#!/usr/bin/env bash
# Quick sync — Upload a single department's data to all dashboard targets
#
# Usage: ./scripts/quick-sync.sh <department> <repo-name>
#   department: qa|seo|ada|compliance|privacy|monetization|product|all
#   repo-name:  e.g., "codyjo.com" or "thenewbeautifulme"
#
# This is much faster than the full sync-dashboard.sh because it:
#   1. Skips re-aggregation
#   2. Only uploads the changed data file(s)
#   3. Invalidates only the specific path(s)
#
# When department is "all", uploads all department data files for the given repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG="$QA_ROOT/config/qa-config.yaml"

if [ ! -f "$CONFIG" ]; then
  echo "No config at $CONFIG" >&2
  exit 1
fi

DEPT="${1:-all}"
REPO="${2:-}"

# Maps department -> raw findings filename, dashboard data filename
declare -A DEPT_MAP=(
  [qa]="findings.json:qa-data.json"
  [seo]="seo-findings.json:seo-data.json"
  [ada]="ada-findings.json:ada-data.json"
  [compliance]="compliance-findings.json:compliance-data.json"
  [privacy]="privacy-findings.json:privacy-data.json"
  [monetization]="monetization-findings.json:monetization-data.json"
  [product]="product-findings.json:product-data.json"
  [self-audit]="findings.json:self-audit-data.json"
)

upload_dept() {
  local dept="$1"
  local bucket="$2"
  local cf_id="$3"
  local repo="$4"
  local prefix="$5"

  local mapping="${DEPT_MAP[$dept]}"
  local raw_file="${mapping%%:*}"
  local s3_name="${mapping##*:}"
  local raw_path="$QA_ROOT/results/$repo/$raw_file"

  if [ ! -f "$raw_path" ]; then
    echo "  [$dept] No data: $raw_path"
    return 1
  fi

  local s3_key="${prefix}${s3_name}"
  echo "  [$dept] Uploading $raw_file -> s3://$bucket/$s3_key"
  aws s3 cp "$raw_path" "s3://$bucket/$s3_key" \
    --content-type "application/json" \
    --cache-control "no-cache, no-store, must-revalidate" \
    --quiet

  # Invalidate just this file
  if [ -n "$cf_id" ]; then
    echo "  [$dept] Invalidating /$s3_key"
    aws cloudfront create-invalidation \
      --distribution-id "$cf_id" \
      --paths "/$s3_key" \
      --output text --query 'Invalidation.Id' 2>/dev/null || true
  fi
}

upload_jobs_data() {
  local bucket="$1"
  local cf_id="$2"
  local prefix="$3"

  local dashboard_dir="$QA_ROOT/dashboard"
  local job_files=(.jobs.json .jobs-history.json)
  local invalidation_paths=()

  for f in "${job_files[@]}"; do
    local local_path="$dashboard_dir/$f"
    [ -f "$local_path" ] || continue
    local s3_key="${prefix}${f}"
    echo "  [jobs] Uploading $f -> s3://$bucket/$s3_key"
    aws s3 cp "$local_path" "s3://$bucket/$s3_key" \
      --content-type "application/json" \
      --cache-control "no-cache, no-store, must-revalidate" \
      --quiet
    invalidation_paths+=("/$s3_key")
  done

  if [ -n "$cf_id" ] && [ ${#invalidation_paths[@]} -gt 0 ]; then
    aws cloudfront create-invalidation \
      --distribution-id "$cf_id" \
      --paths "${invalidation_paths[@]}" \
      --output text --query 'Invalidation.Id' 2>/dev/null || true
  fi
}

upload_shared_data() {
  local bucket="$1"
  local cf_id="$2"
  local prefix="$3"

  local dashboard_dir="$QA_ROOT/dashboard"
  local shared_files=(org-data.json local-audit-log.json local-audit-log.md)
  local invalidation_paths=()

  for f in "${shared_files[@]}"; do
    local local_path="$dashboard_dir/$f"
    [ -f "$local_path" ] || continue
    local content_type="application/json"
    [[ "$f" == *.md ]] && content_type="text/markdown"
    local s3_key="${prefix}${f}"
    echo "  [shared] Uploading $f -> s3://$bucket/$s3_key"
    aws s3 cp "$local_path" "s3://$bucket/$s3_key" \
      --content-type "$content_type" \
      --cache-control "no-cache, no-store, must-revalidate" \
      --quiet
    invalidation_paths+=("/$s3_key")
  done

  if [ -n "$cf_id" ] && [ ${#invalidation_paths[@]} -gt 0 ]; then
    aws cloudfront create-invalidation \
      --distribution-id "$cf_id" \
      --paths "${invalidation_paths[@]}" \
      --output text --query 'Invalidation.Id' 2>/dev/null || true
  fi
}

upload_html() {
  local bucket="$1"
  local cf_id="$2"
  local prefix="$3"

  local dashboard_dir="$QA_ROOT/dashboard"
  local html_files=(index.html qa.html seo.html ada.html compliance.html privacy.html monetization.html product.html jobs.html faq.html self-audit.html admin.html selah.html analogify.html chromahaus.html tnbm-tarot.html back-office-hq.html documentation.html documentation-github.html documentation-cicd.html documentation-cli.html site-branding.js favicon.svg)
  local invalidation_paths=()

  for f in "${html_files[@]}"; do
    local local_path="$dashboard_dir/$f"
    [ -f "$local_path" ] || continue
    local content_type="text/html"
    [[ "$f" == *.js ]] && content_type="application/javascript"
    [[ "$f" == *.svg ]] && content_type="image/svg+xml"
    local s3_key="${prefix}${f}"
    aws s3 cp "$local_path" "s3://$bucket/$s3_key" \
      --content-type "$content_type" \
      --cache-control "no-cache, no-store, must-revalidate" \
      --quiet
    invalidation_paths+=("/$s3_key")
  done

  if [ -n "$cf_id" ] && [ ${#invalidation_paths[@]} -gt 0 ]; then
    aws cloudfront create-invalidation \
      --distribution-id "$cf_id" \
      --paths "${invalidation_paths[@]}" \
      --output text --query 'Invalidation.Id' 2>/dev/null || true
  fi
}

# Parse config and process each matching target
python3 -c "
import yaml, json, sys

with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)

targets = cfg.get('dashboard_targets', [])
for t in targets:
    repo = t.get('repo', '')
    if '$REPO' and repo != '$REPO':
        continue
    subdomain = t.get('subdomain', '')
    allow_public_read = t.get('allow_public_read', False)
    if subdomain and not subdomain.startswith('admin.') and not allow_public_read:
        print(f'Skipping public target {subdomain} — set allow_public_read: true to publish dashboards publicly.', file=sys.stderr)
        continue
    print(json.dumps({
        'bucket': t['bucket'],
        'cf_id': t.get('cloudfront_id', ''),
        'repo': repo,
        'prefix': (t.get('base_path', '') + '/') if t.get('base_path') else '',
    }))
" | while IFS= read -r line; do
  bucket=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['bucket'])")
  cf_id=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['cf_id'])")
  repo=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['repo'])")
  prefix=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['prefix'])")

  echo ""
  echo "Target: $bucket (repo: $repo)"

  if [ "$DEPT" = "all" ]; then
    for d in qa seo ada compliance privacy monetization product; do
      upload_dept "$d" "$bucket" "$cf_id" "$repo" "$prefix" || true
    done
  else
    upload_dept "$DEPT" "$bucket" "$cf_id" "$repo" "$prefix" || true
  fi

  # Always upload job status and history files
  upload_jobs_data "$bucket" "$cf_id" "$prefix"
  upload_shared_data "$bucket" "$cf_id" "$prefix"
done

echo ""
echo "Quick sync complete."
