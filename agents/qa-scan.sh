#!/usr/bin/env bash
# Back Office — Scan Agent
# Usage: ./agents/qa-scan.sh /path/to/target-repo [--sync]
#
# Launches a Claude Code session that scans the target repository
# for bugs, security issues, and performance problems.
#
# Options:
#   --sync    Sync results to S3 after scan completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/qa-scan.md"
CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: qa-scan.sh /path/to/target-repo [--sync]}"
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
echo "║  Back Office — Scanning: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:  $TARGET_REPO"
echo "  Results: $RESULTS_DIR"
echo "  Time:    $(date -Iseconds)"
echo ""

# ── Read config for lint/test commands ────────────────────────────────────────

LINT_CMD=""
TEST_CMD=""
CONTEXT=""

if command -v python3 &>/dev/null && [ -f "$QA_ROOT/config/targets.yaml" ]; then
  mapfile -d '' -t _target_cfg < <(
    python3 "$QA_ROOT/scripts/parse-config.py" \
      "$QA_ROOT/config/targets.yaml" "$REPO_NAME" "$TARGET_REPO" \
      lint_command test_command context 2>/dev/null || true
  )
  LINT_CMD="${_target_cfg[0]:-}"
  TEST_CMD="${_target_cfg[1]:-}"
  CONTEXT="${_target_cfg[2]:-}"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

SCAN_PROMPT="$(cat "$PROMPT_FILE")

---

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME
- **Results directory:** $RESULTS_DIR

## Commands

- **Lint:** ${LINT_CMD:-"(auto-detect from project config)"}
- **Test:** ${TEST_CMD:-"(auto-detect from project config)"}

## Additional Context

${CONTEXT:-"No additional context provided. Read the project's README and CLAUDE.md for context."}

## Instructions

1. cd to $TARGET_REPO
2. Read the project structure and understand the codebase
3. Run linter and tests, capture output
4. Perform security audit, input validation check, performance review, and code quality review
5. Write all findings to: $RESULTS_DIR/findings.json
6. Write a human-readable summary to: $RESULTS_DIR/scan-summary.md
7. Generate dashboard data: $RESULTS_DIR/dashboard.json

Start the scan now."

# ── Launch Claude Code ───────────────────────────────────────────────────────

echo "Launching Claude Code scan agent..."
echo ""

job_start "qa"
unset CLAUDECODE 2>/dev/null || true
claude --print "$SCAN_PROMPT" \
  --allowedTools "Read,Glob,Grep,Bash,Write,Agent" \
  --add-dir "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "qa" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Scan complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
