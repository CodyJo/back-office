#!/usr/bin/env bash
# Back Office — Feature Development Agent
# Usage: ./agents/feature-dev.sh /path/to/target-repo '<feature-json>'
#
# Launches the configured agent runner to implement a feature in the target
# repository using TDD: write tests first, verify fail, implement, verify pass,
# lint, commit.
#
# Arguments:
#   $1  — path to the target repository (must be a git repo)
#   $2  — feature JSON string (from overnight-plan.json .features[])

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/feature-dev.md"

# ── Args ──────────────────────────────────────────────────────────────────────

TARGET_REPO="${1:?Usage: feature-dev.sh /path/to/target-repo '<feature-json>'}"
FEATURE_JSON="${2:?Usage: feature-dev.sh /path/to/target-repo '<feature-json>'}"

# Validate target is a git repo
if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

# Validate feature JSON
if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$FEATURE_JSON" 2>/dev/null; then
  echo "Error: second argument is not valid JSON" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
mkdir -p "$RESULTS_DIR"

FEATURE_TITLE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('title','feature'))" "$FEATURE_JSON" 2>/dev/null || echo "feature")"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — Feature Dev: $REPO_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:  $TARGET_REPO"
echo "  Feature: $FEATURE_TITLE"
echo "  Results: $RESULTS_DIR"
echo "  Time:    $(date -Iseconds)"
echo ""

# ── Read config for target-specific settings ──────────────────────────────────

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

# ── Build the prompt ──────────────────────────────────────────────────────────

DEV_PROMPT="$(cat "$PROMPT_FILE")

---

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME
- **Results directory:** $RESULTS_DIR

## Feature Spec

\`\`\`json
$FEATURE_JSON
\`\`\`

## Commands

- **Lint:** ${LINT_CMD:-"(check project config — look for eslint, ruff, flake8, pylint)"}
- **Test:** ${TEST_CMD:-"(check project config — look for jest, pytest, vitest, npm test)"}

## Repository Context

${CONTEXT:-"No additional context provided. Read the project's README and CLAUDE.md if present."}

## Instructions

1. cd to $TARGET_REPO
2. Read the feature spec above and understand the acceptance criteria
3. Explore the codebase to understand existing patterns and structure
4. Follow the TDD process from the prompt: tests first, then implementation
5. Use lint command: ${LINT_CMD:-"auto-detect"}
6. Use test command: ${TEST_CMD:-"auto-detect"}
7. Write the status report JSON to: $RESULTS_DIR/feature-dev-result.json
8. Print the JSON report at the end of your output

Start the feature implementation now."

# ── Launch agent runner ───────────────────────────────────────────────────────

echo "Launching feature development agent..."
echo ""

job_start "feature-dev"
bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$DEV_PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Edit,Agent" \
  --repo "$TARGET_REPO" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "feature-dev" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

echo ""
echo "Feature development complete. Results in: $RESULTS_DIR/"
echo ""
echo "Done."
