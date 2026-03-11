#!/usr/bin/env bash
# Back Office — Product Roadmap & Backlog Audit Agent
# Usage: ./agents/product-audit.sh /path/to/target-repo [--sync]
#
# Launches a Claude Code session that audits the target repository
# for feature gaps, UX issues, technical debt, and growth
# opportunities, then produces a prioritized product roadmap.
#
# Options:
#   --sync    Sync results to S3 after audit completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/product-audit.md"
CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: product-audit.sh /path/to/target-repo [--sync]}"
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
echo "║  Back Office — Product Roadmap Audit: $REPO_NAME"
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
2. Read the project structure — understand the product, tech stack, and existing features
3. Map all features, pages, user flows, and integrations
4. Perform the full product audit: feature gaps, UX issues, technical debt, growth opportunities
5. Calculate category scores and overall product readiness score
6. Write all findings to: $RESULTS_DIR/product-findings.json
7. Write a human-readable roadmap to: $RESULTS_DIR/product-roadmap.md (organized by priority with effort estimates)

Start the product roadmap audit now."

# ── Launch Claude Code ───────────────────────────────────────────────────────

echo "Launching Claude Code product roadmap audit agent..."
echo ""

job_start "product"
unset CLAUDECODE 2>/dev/null || true
claude --print "$SCAN_PROMPT" \
  --allowedTools "Read,Glob,Grep,Bash,Write,Agent" \
  --add-dir "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "product" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Product roadmap audit complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" product "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
