#!/usr/bin/env bash
# Back Office — Watch Mode
# Usage: ./agents/watch.sh /path/to/target-repo [--interval 15] [--auto-fix]
#
# Monitors a results directory for new findings and triggers the fix agent.
# This is the "overnight mode" — set it up and let it run.
#
# Options:
#   --interval N   Check interval in minutes (default: 15)
#   --auto-fix     Automatically run fix agent when new findings appear
#   --sync         Sync dashboard after each cycle

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"

TARGET_REPO="${1:?Usage: watch.sh /path/to/target-repo [--interval 15] [--auto-fix]}"
INTERVAL=15
AUTO_FIX=false
SYNC=false

shift
while [ $# -gt 0 ]; do
  case "$1" in
    --interval)  INTERVAL="$2"; shift 2 ;;
    --auto-fix)  AUTO_FIX=true; shift ;;
    --sync)      SYNC=true; shift ;;
    *)           shift ;;
  esac
done

REPO_NAME="$(basename "$TARGET_REPO")"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
LAST_HASH=""

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — Watch Mode"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Target:   $REPO_NAME"
echo "  Interval: ${INTERVAL}m"
echo "  Auto-fix: $AUTO_FIX"
echo "  Sync:     $SYNC"
echo ""
echo "Watching for changes... (Ctrl+C to stop)"
echo ""

while true; do
  FINDINGS="$RESULTS_DIR/findings.json"

  if [ -f "$FINDINGS" ]; then
    CURRENT_HASH=$(md5sum "$FINDINGS" 2>/dev/null | cut -d' ' -f1 || echo "")

    if [ "$CURRENT_HASH" != "$LAST_HASH" ] && [ -n "$CURRENT_HASH" ]; then
      LAST_HASH="$CURRENT_HASH"
      TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

      # Parse summary — use safe file open via sys.argv
      SUMMARY=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
s = d['summary']
print(f\"{s['total']} findings: {s['critical']} critical, {s['high']} high, {s['medium']} medium, {s['low']} low\")
" "$FINDINGS" 2>/dev/null || echo "new findings detected")

      echo "[$TIMESTAMP] New findings: $SUMMARY"

      if [ "$AUTO_FIX" = true ]; then
        echo "[$TIMESTAMP] Auto-fix enabled — launching fix agent..."
        SYNC_FLAG=""
        [ "$SYNC" = true ] && SYNC_FLAG="--sync"
        bash "$SCRIPT_DIR/fix-bugs.sh" "$TARGET_REPO" $SYNC_FLAG || echo "Fix agent exited with error"
      fi

      # Sync dashboard
      if [ "$SYNC" = true ]; then
        bash "$QA_ROOT/scripts/quick-sync.sh" all "$REPO_NAME" 2>/dev/null || true
      fi
    fi
  fi

  sleep "${INTERVAL}m"
done
