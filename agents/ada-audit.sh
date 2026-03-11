#!/usr/bin/env bash
# Back Office — ADA Compliance Audit Agent
# Usage: ./agents/ada-audit.sh /path/to/target-repo [--sync]
#
# Launches the configured agent runner to scan the target repository
# for ADA / WCAG 2.1 accessibility compliance issues.
#
# Options:
#   --sync    Sync results to S3 after scan completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/ada-audit.md"
CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: ada-audit.sh /path/to/target-repo [--sync]}"
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
echo "║  Back Office — ADA Compliance Audit: $REPO_NAME"
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
2. Read the project structure and understand the codebase, tech stack, and UI framework
3. Identify all files that produce user-facing HTML (templates, components, pages, layouts, styles)
4. Perform the full WCAG 2.1 audit — perceivable, operable, understandable, robust
5. Check ADA / Section 508 specific requirements
6. Run framework-specific accessibility checks
7. Calculate compliance score and WCAG level
8. Write all findings to: $RESULTS_DIR/ada-findings.json
9. Write a human-readable summary to: $RESULTS_DIR/ada-summary.md

Start the audit now."

# ── Launch agent runner ──────────────────────────────────────────────────────

echo "Launching ADA compliance audit agent..."
echo ""

job_start "ada"
bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$SCAN_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "ada" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Audit complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" ada "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
