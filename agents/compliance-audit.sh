#!/usr/bin/env bash
# Back Office — Regulatory Compliance Audit Agent
# Usage: ./agents/compliance-audit.sh /path/to/target-repo [--sync]
#
# Launches a Claude Code session that audits the target repository
# for GDPR, ISO 27001, and age verification compliance issues.
#
# Options:
#   --sync    Sync results to S3 after audit completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$SCRIPT_DIR/prompts/compliance-audit.md"
CONFIG_FILE="$QA_ROOT/config/qa-config.yaml"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: compliance-audit.sh /path/to/target-repo [--sync]}"
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
echo "║  Back Office — Regulatory Compliance Audit: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:     $TARGET_REPO"
echo "  Results:    $RESULTS_DIR"
echo "  Frameworks: GDPR, ISO 27001, Age Verification"
echo "  Time:       $(date -Iseconds)"
echo ""

# ── Read config for target-specific context ──────────────────────────────────

CONTEXT=""

if command -v python3 &>/dev/null && [ -f "$QA_ROOT/config/targets.yaml" ]; then
  # Extract target-specific config using python
  eval "$(python3 -c "
import yaml, sys
with open('$QA_ROOT/config/targets.yaml') as f:
    cfg = yaml.safe_load(f)
for t in cfg.get('targets', []):
    if t['name'] == '$REPO_NAME' or t.get('path','') == '$TARGET_REPO':
        print(f'CONTEXT={repr(t.get(\"context\",\"\"))}')
        break
" 2>/dev/null || true)"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

AUDIT_PROMPT="$(cat "$PROMPT_FILE")

---

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME
- **Results directory:** $RESULTS_DIR

## Additional Context

${CONTEXT:-"No additional context provided. Read the project's README and CLAUDE.md for context."}

## Instructions

1. cd to $TARGET_REPO
2. Read the project structure, README, CLAUDE.md, and understand the codebase
3. Identify the project type, target audience, and data processing activities
4. Perform the GDPR compliance audit — check every item listed in the prompt
5. Perform the ISO 27001 information security audit — check every control area
6. Perform the age verification audit — determine applicability, then check relevant laws
7. Calculate compliance scores for each framework and overall
8. Write all findings to: $RESULTS_DIR/compliance-findings.json
9. Write a human-readable summary to: $RESULTS_DIR/compliance-summary.md

Start the compliance audit now."

# ── Launch Claude Code ───────────────────────────────────────────────────────

echo "Launching Claude Code compliance audit agent..."
echo ""

unset CLAUDECODE 2>/dev/null || true
claude --print "$AUDIT_PROMPT" \
  --allowedTools "Read,Glob,Grep,Bash,Write,Agent" \
  --add-dir "$TARGET_REPO"

echo ""
echo "Compliance audit complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/sync-dashboard.sh" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
