#!/usr/bin/env bash
# Back Office — Watch Mode
# Usage: ./agents/watch.sh /path/to/target-repo [--interval 15] [--auto-fix] [--rescan]
#
# Monitors a results directory for new findings and triggers the fix agent.
# This is the "overnight mode" — set it up and let it run.
#
# Options:
#   --interval N   Check interval in minutes (default: 15)
#   --auto-fix     Automatically run fix agent when new findings appear
#   --sync         Sync dashboard after each cycle
#   --rescan       Run QA scan each cycle instead of only watching findings.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"

TARGET_REPO="${1:?Usage: watch.sh /path/to/target-repo [--interval 15] [--auto-fix] [--rescan]}"
INTERVAL=15
AUTO_FIX=false
SYNC=false
RESCAN=false

shift
while [ $# -gt 0 ]; do
  case "$1" in
    --interval)  INTERVAL="$2"; shift 2 ;;
    --auto-fix)  AUTO_FIX=true; shift ;;
    --sync)      SYNC=true; shift ;;
    --rescan)    RESCAN=true; shift ;;
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
echo "  Rescan:   $RESCAN"
echo ""
echo "Watching for changes... (Ctrl+C to stop)"
echo ""

run_scan_cycle() {
  local timestamp sync_flag findings total summary
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  sync_flag=""
  [ "$SYNC" = true ] && sync_flag="--sync"

  echo "[$timestamp] Running QA scan..."
  if ! bash "$SCRIPT_DIR/qa-scan.sh" "$TARGET_REPO" $sync_flag; then
    echo "[$timestamp] QA scan exited with error"
    return
  fi

  findings="$RESULTS_DIR/findings.json"
  if [ ! -f "$findings" ]; then
    echo "[$timestamp] No findings file produced"
    return
  fi

  total=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['summary']['total'])" "$findings" 2>/dev/null || echo "0")
  summary=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
s = d['summary']
print(f\"{s['total']} findings: {s['critical']} critical, {s['high']} high, {s['medium']} medium, {s['low']} low\")
" "$findings" 2>/dev/null || echo "scan complete")

  echo "[$timestamp] Scan summary: $summary"

  if [ "$AUTO_FIX" = true ] && [ "${total:-0}" != "0" ]; then
    echo "[$timestamp] Auto-fix enabled — launching fix agent..."
    if ! bash "$SCRIPT_DIR/fix-bugs.sh" "$TARGET_REPO" $sync_flag; then
      echo "[$timestamp] Fix agent exited with error"
      return
    fi

    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] Re-running QA scan to verify fixes..."
    bash "$SCRIPT_DIR/qa-scan.sh" "$TARGET_REPO" $sync_flag || echo "[$timestamp] Verification scan exited with error"
  fi
}

while true; do
  if [ "$RESCAN" = true ]; then
    run_scan_cycle
    sleep "${INTERVAL}m"
    continue
  fi

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
