#!/usr/bin/env bash
# Back Office — Fix Agent
# Usage: ./agents/fix-bugs.sh /path/to/target-repo [--sync] [--deploy] [--preview]
#
# Launches the configured agent runner that reads findings and fixes them
# using isolated git worktrees for safe parallel development.
#
# Options:
#   --sync     Sync results to S3 after fixes complete
#   --deploy   Run deploy command after successful fixes
#   --preview  Land fixes on isolated back-office/preview/<job-id> branch,
#              emit a preview-<job-id>.json artifact, and DO NOT deploy.
#              Intended for the dashboard Review & Approve flow.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/fix-bugs.md"

# ── Args ─────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: fix-bugs.sh /path/to/target-repo [--sync] [--deploy] [--preview]}"
SYNC_TO_S3=false
RUN_DEPLOY=false
PREVIEW_MODE=false

for arg in "$@"; do
  case "$arg" in
    --sync)    SYNC_TO_S3=true ;;
    --deploy)  RUN_DEPLOY=true ;;
    --preview) PREVIEW_MODE=true ;;
  esac
done

if [ "$PREVIEW_MODE" = true ] && [ "$RUN_DEPLOY" = true ]; then
  echo "Error: --preview and --deploy are mutually exclusive" >&2
  exit 2
fi

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

# ── Preview mode: set up isolated branch ─────────────────────────────────────

JOB_ID=""
PREVIEW_BRANCH=""
PREVIEW_BASE_REF=""
if [ "$PREVIEW_MODE" = true ]; then
  JOB_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%06x' $((RANDOM*RANDOM)))"
  PREVIEW_BRANCH="back-office/preview/$JOB_ID"
  PREVIEW_BASE_REF="$(git -C "$TARGET_REPO" symbolic-ref --short HEAD 2>/dev/null || echo main)"

  if ! git -C "$TARGET_REPO" diff --quiet || ! git -C "$TARGET_REPO" diff --cached --quiet; then
    echo "Error: target repo has uncommitted changes — commit or stash before --preview" >&2
    exit 2
  fi

  echo "Preview mode: creating branch $PREVIEW_BRANCH from $PREVIEW_BASE_REF"
  git -C "$TARGET_REPO" checkout -b "$PREVIEW_BRANCH"
  mkdir -p "$RESULTS_DIR"
fi

# Count findings
TOTAL=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['summary']['total'])" "$FINDINGS_FILE" 2>/dev/null || echo "?")
CRITICAL=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['summary']['critical'])" "$FINDINGS_FILE" 2>/dev/null || echo "?")
HIGH=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['summary']['high'])" "$FINDINGS_FILE" 2>/dev/null || echo "?")

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
  mapfile -d '' -t _target_cfg < <(
    python3 "$QA_ROOT/scripts/parse-config.py" \
      "$QA_ROOT/config/targets.yaml" "$REPO_NAME" "$TARGET_REPO" \
      deploy_command lint_command test_command 2>/dev/null || true
  )
  DEPLOY_CMD="${_target_cfg[0]:-}"
  LINT_CMD="${_target_cfg[1]:-}"
  TEST_CMD="${_target_cfg[2]:-}"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

PREVIEW_DIRECTIVE=""
if [ "$PREVIEW_MODE" = true ]; then
  PREVIEW_DIRECTIVE="
## Preview Mode

This job is running in preview mode. Commit ALL fixes to the current branch
(\`$PREVIEW_BRANCH\`). DO NOT merge, push to main, or deploy. A human will
review the resulting diff in the dashboard Review & Approve panel.

Write the IDs of findings you addressed to \`$RESULTS_DIR/.fix-addressed-$JOB_ID.json\`
as a JSON array, each entry matching the canonical finding schema
(\`id\`, \`severity\`, \`title\`, \`file\`, \`line\`, \`trust_class\`).
"
fi

FIX_PROMPT="$(cat "$PROMPT_FILE")
$PREVIEW_DIRECTIVE

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

# ── Launch agent runner ──────────────────────────────────────────────────────

echo "Launching fix agent..."
echo ""

job_start "fix"
bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$FIX_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Edit,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "fix" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Fixes complete. Results in: $RESULTS_DIR/"

# ── Preview artifact generation ─────────────────────────────────────────────

if [ "$PREVIEW_MODE" = true ]; then
  PREVIEW_FINDINGS="$RESULTS_DIR/.fix-addressed-$JOB_ID.json"
  if [ ! -f "$PREVIEW_FINDINGS" ]; then
    echo "Warning: agent did not emit $PREVIEW_FINDINGS — writing empty checklist" >&2
    echo "[]" > "$PREVIEW_FINDINGS"
  fi

  PREVIEW_OUT="$RESULTS_DIR/preview-$JOB_ID.json"
  echo "Generating preview artifact -> $PREVIEW_OUT"
  python3 -m backoffice preview \
    --repo-path "$TARGET_REPO" \
    --repo-name "$REPO_NAME" \
    --job-id "$JOB_ID" \
    --branch "$PREVIEW_BRANCH" \
    --base-ref "$PREVIEW_BASE_REF" \
    --findings "$PREVIEW_FINDINGS" \
    --out "$PREVIEW_OUT"

  # Preview mode NEVER deploys — return to base branch and bail here.
  git -C "$TARGET_REPO" checkout "$PREVIEW_BASE_REF" >/dev/null 2>&1 || true
  if [ "$SYNC_TO_S3" = true ]; then
    echo "Syncing preview artifact..."
    BACK_OFFICE_ENABLE_REMOTE_SYNC="${BACK_OFFICE_ENABLE_REMOTE_SYNC:-1}" \
      python3 -m backoffice sync --dept qa || echo "Warning: preview sync failed"
  fi
  echo ""
  echo "Preview ready: branch=$PREVIEW_BRANCH artifact=$PREVIEW_OUT"
  exit 0
fi

# ── Deploy if requested ──────────────────────────────────────────────────────

if [ "$RUN_DEPLOY" = true ] && [ -n "$DEPLOY_CMD" ]; then
  # Validate deploy command — only allow simple command names (no shell metacharacters)
  if [[ "$DEPLOY_CMD" =~ [^a-zA-Z0-9\ _/.\-] ]]; then
    echo "Error: deploy_command contains unsafe characters, skipping: $DEPLOY_CMD" >&2
  else
    echo "Running deploy: $DEPLOY_CMD"
    # shellcheck disable=SC2086
    (cd "$TARGET_REPO" && $DEPLOY_CMD)
  fi
fi

# ── Sync to S3 if requested ─────────────────────────────────────────────────

if [ "$SYNC_TO_S3" = true ]; then
  echo "Syncing results to S3..."
  bash "$SCRIPT_DIR/../scripts/quick-sync.sh" qa "$REPO_NAME" 2>/dev/null || echo "Warning: S3 sync failed"
fi

echo ""
echo "Done."
