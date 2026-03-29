#!/usr/bin/env bash
# Back Office — OG Image Remediation
# Usage: ./agents/og-remediation.sh /path/to/target-repo [--sync]
#
# Scans a target repo for missing or outdated OG images, favicons, and
# social meta tags. Generates SVG sources, converts to PNG, and fixes
# meta tag configuration.
#
# Options:
#   --sync     Sync results to S3 after remediation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/og-remediation.md"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: og-remediation.sh /path/to/target-repo [--sync]}"
SYNC_TO_S3=false

for arg in "$@"; do
  case "$arg" in
    --sync) SYNC_TO_S3=true ;;
  esac
done

if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
mkdir -p "$RESULTS_DIR"

# ── Load prompt ──────────────────────────────────────────────────────────────

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Error: prompt file not found at $PROMPT_FILE" >&2
  exit 1
fi

SYSTEM_PROMPT="$(cat "$PROMPT_FILE")"

# ── Build dynamic prompt ─────────────────────────────────────────────────────

SCAN_PROMPT="$SYSTEM_PROMPT

---

## Target Repository

- Path: $TARGET_REPO
- Repo name: $REPO_NAME
- Results directory: $RESULTS_DIR

## Conversion Script

After generating SVG files, run the conversion script:
- OG images: node $QA_ROOT/scripts/svg-to-png.mjs <public-dir>
- Favicons: node $QA_ROOT/scripts/svg-to-png.mjs <public-dir> --favicon

## Output

Write remediation results to: $RESULTS_DIR/og-remediation.json
"

# ── Run agent ────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  OG Image Remediation — $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

job_start "og-remediation"

bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$SCAN_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Edit,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?

job_finish "og-remediation" "$_EXIT_CODE"

# ── Sync ─────────────────────────────────────────────────────────────────────

if $SYNC_TO_S3; then
  echo "Syncing results to S3..."
  python3 -m backoffice sync 2>/dev/null || echo "Sync skipped (backoffice sync not available)"
fi

echo ""
echo "OG remediation complete for $REPO_NAME"
echo "Results: $RESULTS_DIR/og-remediation.json"
