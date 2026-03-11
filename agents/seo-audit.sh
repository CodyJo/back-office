#!/usr/bin/env bash
# Back Office — SEO & AI Engine Audit Agent
# Usage: ./agents/seo-audit.sh /path/to/target-repo [--sync]
#
# Launches the configured agent runner to audit the target repository
# for SEO issues, AI search engine optimization gaps, and content
# discoverability problems.
#
# Options:
#   --sync    Sync results to S3 after audit completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/seo-audit.md"
CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: seo-audit.sh /path/to/target-repo [--sync]}"
SYNC_TO_S3=false

for arg in "$@"; do
  case "$arg" in
    --sync) SYNC_TO_S3=true ;;
  esac
done

# Validate target
if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
mkdir -p "$RESULTS_DIR"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — SEO Audit: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:  $TARGET_REPO"
echo "  Results: $RESULTS_DIR"
echo "  Time:    $(date -Iseconds)"
echo ""

# ── Read config for target-specific settings ─────────────────────────────────

CONTEXT=""

if command -v python3 &>/dev/null && [ -f "$QA_ROOT/config/targets.yaml" ]; then
  mapfile -d '' -t _target_cfg < <(
    python3 "$QA_ROOT/scripts/parse-config.py" \
      "$QA_ROOT/config/targets.yaml" "$REPO_NAME" "$TARGET_REPO" \
      context 2>/dev/null || true
  )
  CONTEXT="${_target_cfg[0]:-}"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

SCAN_PROMPT="$(cat "$PROMPT_FILE")

---

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME
- **Results directory:** $RESULTS_DIR

## Additional Context

${CONTEXT:-"No additional context provided. Read the project's README and CLAUDE.md for context."}

## Instructions

1. cd to $TARGET_REPO
2. Read the project structure — identify the framework, rendering method (SSR/SSG/SPA), and existing SEO setup
3. Map all pages, routes, and content templates
4. Perform the full SEO audit: technical SEO, AI optimization, content SEO, performance SEO, and social meta
5. Calculate category scores and overall SEO score
6. Write all findings to: $RESULTS_DIR/seo-findings.json
7. Write a human-readable summary to: $RESULTS_DIR/seo-summary.md (include score breakdown, top issues, and quick wins)

Start the SEO audit now."

# ── Launch agent runner ──────────────────────────────────────────────────────

echo "Launching SEO audit agent..."
echo ""

job_start "seo"
bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$SCAN_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "seo" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "SEO audit complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" seo "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
