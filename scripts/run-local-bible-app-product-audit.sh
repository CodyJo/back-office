#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
TARGET_REPO="/home/merm/projects/bible-app"
REPO_NAME="bible-app"
RESULTS_DIR="$QA_ROOT/results/$REPO_NAME"
LOG_DIR="$RESULTS_DIR/logs"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/product-audit-$TIMESTAMP.log"
SUMMARY_FILE="$RESULTS_DIR/latest-local-audit-summary.md"

mkdir -p "$LOG_DIR"

run_audit() {
  echo "Back Office local product audit"
  echo "Target: $TARGET_REPO"
  echo "Results: $RESULTS_DIR"
  echo "Log: $LOG_FILE"
  echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo

  bash "$QA_ROOT/scripts/job-status.sh" init "$TARGET_REPO" "product"
  bash "$QA_ROOT/agents/product-audit.sh" "$TARGET_REPO"
  python3 "$QA_ROOT/scripts/aggregate-results.py" "$QA_ROOT/results" "$QA_ROOT/dashboard/data.json"
}

run_audit 2>&1 | tee "$LOG_FILE"
PIPE_EXIT=${PIPESTATUS[0]}

if [ "$PIPE_EXIT" -ne 0 ]; then
  echo "Product audit failed. See $LOG_FILE" >&2
  exit "$PIPE_EXIT"
fi

python3 - "$RESULTS_DIR" "$SUMMARY_FILE" "$LOG_FILE" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

results_dir, summary_file, log_file = sys.argv[1:4]
findings_path = os.path.join(results_dir, "product-findings.json")
roadmap_path = os.path.join(results_dir, "product-roadmap.md")

with open(findings_path) as f:
    data = json.load(f)

summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
findings = data.get("findings", [])
top = findings[:5]

lines = [
    "# Bible App Local Product Audit",
    "",
    f"- Generated: {datetime.now(timezone.utc).isoformat()}",
    f"- Results dir: `{results_dir}`",
    f"- Log file: `{log_file}`",
    f"- Dashboard: `http://localhost:8070/product.html`",
    f"- Roadmap: `{roadmap_path}`",
    "",
    "## Score",
    "",
    f"- Product readiness: {summary.get('product_readiness_score', 'n/a')}",
    f"- Total findings: {summary.get('total', len(findings))}",
    f"- Critical: {summary.get('critical', 0)}",
    f"- High: {summary.get('high', 0)}",
    f"- Medium: {summary.get('medium', 0)}",
    f"- Low: {summary.get('low', 0)}",
    f"- Info: {summary.get('info', 0)}",
    "",
    "## Top Findings",
    "",
]

if not top:
    lines.append("- No findings generated.")
else:
    for item in top:
        lines.append(
            f"- [{item.get('severity', 'info')}] {item.get('title', 'Untitled')} "
            f"({item.get('category', 'uncategorized')})"
        )

with open(summary_file, "w") as f:
    f.write("\n".join(lines) + "\n")
PY

echo
echo "Local audit complete."
echo "Dashboard: http://localhost:8070/product.html"
echo "Job log:   $QA_ROOT/dashboard/.jobs-history.json"
echo "Run log:   $LOG_FILE"
echo "Summary:   $SUMMARY_FILE"
