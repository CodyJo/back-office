#!/usr/bin/env bash
# Back Office — Fix Agent
# Usage: ./agents/fix-bugs.sh /path/to/target-repo [--sync] [--deploy]
#
# Launches a Claude Code session that reads findings and fixes them
# using isolated git worktrees for safe parallel development.
#
# Options:
#   --sync     Sync results to S3 after fixes complete
#   --deploy   Run deploy command after successful fixes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$SCRIPT_DIR/prompts/fix-bugs.md"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: fix-bugs.sh /path/to/target-repo [--sync] [--deploy]}"
SYNC_TO_S3=false
RUN_DEPLOY=false

for arg in "$@"; do
  case "$arg" in
    --sync)   SYNC_TO_S3=true ;;
    --deploy) RUN_DEPLOY=true ;;
  esac
done

if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
FINDINGS_FILE="$RESULTS_DIR/findings.json"

if [ ! -f "$FINDINGS_FILE" ]; then
  echo "No findings file at $FINDINGS_FILE — run qa-scan.sh first" >&2
  exit 1
fi

# Count findings
TOTAL=$(python3 -c "import json; d=json.load(open('$FINDINGS_FILE')); print(d['summary']['total'])" 2>/dev/null || echo "?")
CRITICAL=$(python3 -c "import json; d=json.load(open('$FINDINGS_FILE')); print(d['summary']['critical'])" 2>/dev/null || echo "?")
HIGH=$(python3 -c "import json; d=json.load(open('$FINDINGS_FILE')); print(d['summary']['high'])" 2>/dev/null || echo "?")

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — Fixing: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:   $TARGET_REPO"
echo "  Findings: $TOTAL total ($CRITICAL critical, $HIGH high)"
echo "  Time:     $(date -Iseconds)"
echo ""

# ── Read deploy command from config ──────────────────────────────────────────

DEPLOY_CMD=""
LINT_CMD=""
TEST_CMD=""

if command -v python3 &>/dev/null && [ -f "$QA_ROOT/config/targets.yaml" ]; then
  eval "$(python3 -c "
import yaml
with open('$QA_ROOT/config/targets.yaml') as f:
    cfg = yaml.safe_load(f)
for t in cfg.get('targets', []):
    if t['name'] == '$REPO_NAME' or t.get('path','') == '$TARGET_REPO':
        print(f'DEPLOY_CMD={repr(t.get(\"deploy_command\",\"\"))}')
        print(f'LINT_CMD={repr(t.get(\"lint_command\",\"\"))}')
        print(f'TEST_CMD={repr(t.get(\"test_command\",\"\"))}')
        break
" 2>/dev/null || true)"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

FIX_PROMPT="$(cat "$PROMPT_FILE")

---

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME
- **Findings file:** $FINDINGS_FILE
- **Results directory:** $RESULTS_DIR

## Commands

- **Lint:** ${LINT_CMD:-"(check project config)"}
- **Test:** ${TEST_CMD:-"(check project config)"}

## Instructions

1. Read $FINDINGS_FILE
2. Filter to findings where fixable_by_agent is true
3. Sort by severity (critical first)
4. Group findings by file to minimize conflicts
5. For each group, use the Agent tool with isolation: worktree to:
   a. Apply fixes for all findings in the group
   b. Run linter: ${LINT_CMD:-"auto-detect"}
   c. Run tests: ${TEST_CMD:-"auto-detect"}
   d. Commit with message referencing finding IDs
6. Write fix results to: $RESULTS_DIR/fixes.json
7. Update: $RESULTS_DIR/dashboard.json with fix status

Start fixing now. Use parallel worktree agents where possible."

# ── Launch Claude Code ───────────────────────────────────────────────────────

echo "Launching Claude Code fix agent..."
echo ""

unset CLAUDECODE 2>/dev/null || true
claude --print "$FIX_PROMPT" \
  --allowedTools "Read,Glob,Grep,Bash,Write,Edit,Agent" \
  --add-dir "$TARGET_REPO"

echo ""
echo "Fixes complete. Results in: $RESULTS_DIR/"

# ── Deploy if requested ──────────────────────────────────────────────────────

if [ "$RUN_DEPLOY" = true ] && [ -n "$DEPLOY_CMD" ]; then
  echo "Running deploy: $DEPLOY_CMD"
  (cd "$TARGET_REPO" && eval "$DEPLOY_CMD")
fi

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/sync-dashboard.sh" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
