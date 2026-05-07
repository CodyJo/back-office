#!/usr/bin/env bash
# Back Office — QA Scan Agent (hybrid mode)
#
# Default flow:
#   1. Run free deterministic scanners (ruff/semgrep/bandit/pip-audit/npm-audit/gitleaks)
#      → writes results/<repo>/qa-deterministic-findings.json
#   2. Compute "changed files" since BASELINE_REF (default: origin/main)
#   3. Launch Claude with a *focused* prompt:
#         - Knows deterministic findings already exist (don't re-discover)
#         - Investigates only the changed files for novel/judgment issues
#         - Skipped entirely when no changed files exist
#   4. aggregate_qa merges both finding files automatically at refresh time
#
# Modes:
#   --deterministic-only   Skip Claude entirely. $0 spend. Use during budget freezes.
#   --ai-only              Skip deterministic scanner (legacy behavior).
#   --baseline REF         Override baseline git ref (default: origin/main).
#   --sync                 Sync results to S3 after scan completes.
#
# Usage:
#   ./agents/qa-scan.sh /path/to/target-repo [flags]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/qa-scan.md"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: qa-scan.sh /path/to/target-repo [flags]}"
shift
SYNC_TO_S3=false
MODE="hybrid"
BASELINE_REF="${BACK_OFFICE_BASELINE_REF:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --sync) SYNC_TO_S3=true ;;
    --deterministic-only) MODE="deterministic-only" ;;
    --ai-only) MODE="ai-only" ;;
    --baseline) BASELINE_REF="$2"; shift ;;
    --baseline=*) BASELINE_REF="${1#--baseline=}" ;;
  esac
  shift
done

if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
mkdir -p "$RESULTS_DIR"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — QA Scan: $REPO_NAME ($MODE)"
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

job_start "qa"
TRAP_EXIT_CODE=0

# ── Step 1: deterministic scanner ────────────────────────────────────────────

DETERMINISTIC_SUMMARY=""
DETERMINISTIC_TOTAL=0
if [ "$MODE" != "ai-only" ]; then
  echo "→ Running deterministic scanners..."
  if python3 -m backoffice scan "$REPO_NAME" 2>&1 | tee "$RESULTS_DIR/.last-deterministic-run.log" | tail -3; then
    DET_FILE="$RESULTS_DIR/qa-deterministic-findings.json"
    if [ -f "$DET_FILE" ]; then
      DETERMINISTIC_TOTAL=$(python3 -c "import json; d=json.load(open('$DET_FILE')); print(d.get('summary',{}).get('total',0))" 2>/dev/null || echo 0)
      DETERMINISTIC_SUMMARY=$(python3 -c "
import json
d = json.load(open('$DET_FILE'))
s = d.get('summary', {})
tools_run = ', '.join(d.get('tools_run', [])) or 'none'
tools_unav = ', '.join(d.get('tools_unavailable', [])) or 'none'
print(f\"{s.get('total',0)} findings ({s.get('critical',0)} critical, {s.get('high',0)} high, {s.get('medium',0)} medium, {s.get('low',0)} low)\")
print(f\"Tools run: {tools_run}\")
print(f\"Tools unavailable: {tools_unav}\")
" 2>/dev/null || echo "(scanner output present but unparseable)")
    fi
  else
    echo "  WARN: deterministic scan failed; continuing to AI step." >&2
  fi
  echo ""
fi

# ── Short-circuit: deterministic-only mode ──────────────────────────────────

if [ "$MODE" = "deterministic-only" ]; then
  echo "Mode = deterministic-only; skipping Claude."
  job_finish "qa" 0
  echo ""
  echo "Done."
  if [ "$SYNC_TO_S3" = true ]; then
    bash "$QA_ROOT/scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || true
  fi
  exit 0
fi

# ── Budget gate ─────────────────────────────────────────────────────────────
# Falls back to deterministic-only when the AI-spend budget is exhausted, so
# the overnight loop keeps producing value instead of crashing on hard limits.

if python3 -m backoffice budget-check "$REPO_NAME" --department qa >/dev/null 2>&1; then
  : # allow / warn — proceed with AI
else
  echo "  Budget BLOCK for $REPO_NAME/qa — falling back to deterministic-only."
  job_finish "qa" 0
  if [ "$SYNC_TO_S3" = true ]; then
    bash "$QA_ROOT/scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || true
  fi
  echo ""
  echo "Done (budget-blocked)."
  exit 0
fi

# ── Step 2: changed-files baseline ──────────────────────────────────────────

if [ -z "$BASELINE_REF" ]; then
  if git -C "$TARGET_REPO" rev-parse --verify origin/main >/dev/null 2>&1; then
    BASELINE_REF="origin/main"
  elif git -C "$TARGET_REPO" rev-parse --verify origin/master >/dev/null 2>&1; then
    BASELINE_REF="origin/master"
  else
    BASELINE_REF="HEAD~10"
  fi
fi

CHANGED_FILES="$(git -C "$TARGET_REPO" diff --name-only "$BASELINE_REF...HEAD" 2>/dev/null | head -100 || true)"
CHANGED_COUNT=$(printf '%s\n' "$CHANGED_FILES" | grep -c . || true)

echo "→ Changed files since $BASELINE_REF: $CHANGED_COUNT"

# Skip Claude when nothing has changed AND we already have deterministic findings.
if [ "$MODE" = "hybrid" ] && [ "$CHANGED_COUNT" = "0" ] && [ "$DETERMINISTIC_TOTAL" -gt 0 ]; then
  echo "  No changed files; skipping AI scan (deterministic findings carry the result)."
  job_finish "qa" 0
  echo ""
  echo "Done."
  if [ "$SYNC_TO_S3" = true ]; then
    bash "$QA_ROOT/scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || true
  fi
  exit 0
fi

# ── Step 3: build the focused Claude prompt ─────────────────────────────────

CHANGED_FILES_BLOCK=""
if [ "$CHANGED_COUNT" -gt 0 ]; then
  CHANGED_FILES_BLOCK="$(printf '%s\n' "$CHANGED_FILES" | sed 's/^/  - /')"
fi

DETERMINISTIC_BLOCK=""
if [ -n "$DETERMINISTIC_SUMMARY" ]; then
  DETERMINISTIC_BLOCK="A deterministic scanner has already produced findings (semgrep/ruff/bandit/etc.) and they are persisted at:
  \`$RESULTS_DIR/qa-deterministic-findings.json\`

Deterministic scan summary:
$DETERMINISTIC_SUMMARY

These will be merged into the dashboard automatically. **Do not re-discover them.**"
else
  DETERMINISTIC_BLOCK="No deterministic scanner output available — perform a full repo scan as you would have before."
fi

FOCUS_BLOCK=""
if [ "$CHANGED_COUNT" -gt 0 ]; then
  FOCUS_BLOCK="Concentrate your read on the **$CHANGED_COUNT files changed since \`$BASELINE_REF\`**:

$CHANGED_FILES_BLOCK

For files outside this list, only investigate when a finding in a changed file points to them."
else
  FOCUS_BLOCK="No changed files detected since \`$BASELINE_REF\`. Investigate the highest-risk areas of the codebase for novel issues a deterministic scanner could not catch (architecture, logic bugs, race conditions, missing edge cases)."
fi

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

## Hybrid Scan Mode

$DETERMINISTIC_BLOCK

Your job is to find what deterministic tools cannot:
- Architectural / design issues
- Logic bugs (race conditions, off-by-one, missing edge cases)
- Performance issues (N+1, unbounded loops) that don't match a generic rule
- Security issues outside the deterministic tools' coverage
- Test gaps (missing assertions, untested branches)

## Focus

$FOCUS_BLOCK

Skip lint/style issues — those are the deterministic scanner's job.

## Instructions

1. cd to $TARGET_REPO
2. Read the focus files and any high-risk areas they touch
3. Run linter and tests, capture output (the deterministic scanner already ran ruff/etc., so this is for test execution and any agent-specific checks)
4. Identify novel / judgment-call issues that need a human reviewer
5. Write findings to: $RESULTS_DIR/findings.json (canonical schema — see system prompt)
6. Write a human-readable summary to: $RESULTS_DIR/scan-summary.md
7. Generate dashboard data: $RESULTS_DIR/dashboard.json

If you find nothing novel beyond the deterministic findings, write a findings.json with an empty findings list and a summary explaining that.

Start the focused scan now."

# ── Step 4: launch agent runner ──────────────────────────────────────────────

echo "→ Launching focused AI scan..."
echo ""

bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$SCAN_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?

job_finish "qa" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Scan complete. Results in: $RESULTS_DIR/"

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
