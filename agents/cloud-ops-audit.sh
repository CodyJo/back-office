#!/usr/bin/env bash
# Back Office — Cloud Ops (Well-Architected Review) Agent
# Usage: ./agents/cloud-ops-audit.sh /path/to/target-repo [--sync]
#
# Launches the configured agent runner to perform an AWS Well-Architected
# Review by analyzing Terraform files for infrastructure issues across
# 6 WAR pillars: Cost, Security, Reliability, Performance, Ops, Sustainability.
#
# Options:
#   --sync    Sync results to S3 after audit completes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/cloud-ops-audit.md"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: cloud-ops-audit.sh /path/to/target-repo [--sync]}"
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
echo "║  Back Office — Cloud Ops Audit: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:  $TARGET_REPO"
echo "  Results: $RESULTS_DIR"
echo "  Time:    $(date -Iseconds)"
echo ""

# ── Check for Terraform directory ────────────────────────────────────────────

TF_FILES=$(find "$TARGET_REPO" -name "*.tf" -type f 2>/dev/null | head -1 || true)
if [ -z "$TF_FILES" ]; then
  echo "No .tf files found in $REPO_NAME — writing clean report."
  cat > "$RESULTS_DIR/cloud-ops-findings.json" <<NOOP
{
  "scan_id": "no-terraform",
  "repo_name": "$REPO_NAME",
  "repo_path": "$TARGET_REPO",
  "scanned_at": "$(date -Iseconds)",
  "scan_duration_seconds": 0,
  "summary": { "total": 1, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 1 },
  "pillar_scores": {
    "cost_optimization": 100, "security": 100, "reliability": 100,
    "performance_efficiency": 100, "operational_excellence": 100, "sustainability": 100
  },
  "pillar_weights": {
    "cost_optimization": 0.30, "security": 0.25, "reliability": 0.20,
    "performance_efficiency": 0.10, "operational_excellence": 0.10, "sustainability": 0.05
  },
  "cloud_ops_score": 100,
  "findings": [
    {
      "id": "COPS-000",
      "severity": "info",
      "pillar": "operational_excellence",
      "category": "missing-monitoring",
      "title": "No Terraform directory found",
      "description": "This repository does not contain a terraform/ directory. No infrastructure audit was performed.",
      "file": "",
      "line": null,
      "evidence": "",
      "impact": "No infrastructure to audit",
      "fix_suggestion": "No action needed unless this repo should have Terraform configuration.",
      "effort": "easy",
      "fixable_by_agent": false
    }
  ]
}
NOOP
  exit 0
fi

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
2. Discover all Terraform files and identify AWS services in use
3. Run the 6-pillar audit: Cost Optimization, Security, Reliability, Performance Efficiency, Operational Excellence, Sustainability
4. Calculate per-pillar scores and the weighted composite cloud_ops_score
5. Write all findings to: $RESULTS_DIR/cloud-ops-findings.json
6. Write a human-readable summary to: $RESULTS_DIR/cloud-ops-summary.md (include pillar score breakdown, top issues, and quick wins)

Start the Cloud Ops audit now."

# ── Launch agent runner ──────────────────────────────────────────────────────

echo "Launching Cloud Ops audit agent..."
echo ""

job_start "cloud-ops"
bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$SCAN_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "cloud-ops" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Cloud Ops audit complete. Results in: $RESULTS_DIR/"

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" cloud-ops "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
