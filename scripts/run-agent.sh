#!/usr/bin/env bash
# Back Office — Agent runner adapter
# Usage:
#   run-agent.sh --prompt "..." --tools "Read,Glob" --repo /path/to/repo
#
# Supports an AI-agnostic entry point so the dashboard and scripts do not need
# to hard-code a single vendor CLI.

set -euo pipefail

PROMPT=""
TOOLS=""
REPO_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prompt)
      PROMPT="${2:-}"
      shift 2
      ;;
    --tools)
      TOOLS="${2:-}"
      shift 2
      ;;
    --repo|--add-dir)
      REPO_DIR="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$PROMPT" ] || [ -z "$REPO_DIR" ]; then
  echo "Usage: run-agent.sh --prompt \"...\" --tools \"...\" --repo /path/to/repo" >&2
  exit 1
fi

RUNNER_MODE="${BACK_OFFICE_AGENT_MODE:-claude-print}"
RUNNER_CMD="${BACK_OFFICE_AGENT_RUNNER:-claude}"

run_claude_print() {
  local runner_parts runner_bin
  read -r -a runner_parts <<< "$RUNNER_CMD"
  runner_bin="${runner_parts[0]:-}"
  command -v "$runner_bin" >/dev/null 2>&1 || {
    echo "Back Office agent runner not found: $runner_bin" >&2
    exit 1
  }

  unset CLAUDECODE 2>/dev/null || true
  "${runner_parts[@]}" --print "$PROMPT" \
    --allowedTools "$TOOLS" \
    --add-dir "$REPO_DIR"
}

run_stdin_text() {
  local runner_bin
  runner_bin="${RUNNER_CMD%% *}"
  command -v "$runner_bin" >/dev/null 2>&1 || {
    echo "Back Office agent runner not found: $runner_bin" >&2
    exit 1
  }

  printf '%s' "$PROMPT" | bash -lc "$RUNNER_CMD"
}

case "$RUNNER_MODE" in
  claude-print)
    run_claude_print
    ;;
  stdin-text)
    run_stdin_text
    ;;
  *)
    echo "Unsupported BACK_OFFICE_AGENT_MODE: $RUNNER_MODE" >&2
    echo "Supported modes: claude-print, stdin-text" >&2
    exit 1
    ;;
esac
