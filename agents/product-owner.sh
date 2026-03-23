#!/usr/bin/env bash
# Back Office — Product Owner Agent
# Usage: ./agents/product-owner.sh
#
# Reads audit data from dashboard/ and results/, asks the Product Owner
# agent to decide what to work on this cycle, and writes a work plan to
# results/overnight-plan.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
source "$QA_ROOT/scripts/job-status.sh"
PROMPT_FILE="$SCRIPT_DIR/prompts/product-owner.md"
DASHBOARD_DIR="$QA_ROOT/dashboard"
RESULTS_DIR="$QA_ROOT/results"
PLAN_FILE="$RESULTS_DIR/overnight-plan.json"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — Product Owner: Planning Cycle"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Dashboard: $DASHBOARD_DIR"
echo "  Results:   $RESULTS_DIR"
echo "  Plan:      $PLAN_FILE"
echo "  Time:      $(date -Iseconds)"
echo ""

# ── Validate input files ──────────────────────────────────────────────────────

BACKLOG_FILE="$DASHBOARD_DIR/backlog.json"
SCORE_FILE="$DASHBOARD_DIR/score-history.json"
PRODUCT_FILE="$DASHBOARD_DIR/product-data.json"
HISTORY_FILE="$RESULTS_DIR/overnight-history.json"

for f in "$BACKLOG_FILE" "$SCORE_FILE" "$PRODUCT_FILE"; do
  if [ ! -f "$f" ]; then
    echo "Error: required data file not found: $f" >&2
    echo "Run make audit-all first to generate dashboard data." >&2
    exit 1
  fi
done

# ── Extract data summaries via Python ─────────────────────────────────────────

echo "Extracting data summaries..."

# Top 30 backlog findings: critical/high fixable items first, then by audit_count desc
BACKLOG_SUMMARY="$(BACKLOG_FILE="$BACKLOG_FILE" python3 - <<'PYEOF'
import json, os

d = json.load(open(os.environ['BACKLOG_FILE']))
findings = d.get('findings', {})

items = []
for h, f in findings.items():
    items.append({
        'hash': h,
        'repo': f.get('repo', ''),
        'department': f.get('department', ''),
        'title': f.get('title', ''),
        'severity': f.get('severity', 'low'),
        'effort': f.get('current_finding', {}).get('effort', 'hard'),
        'fixable_by_agent': f.get('current_finding', {}).get('fixable_by_agent', False),
        'audit_count': f.get('audit_count', 1),
        'status': f.get('status', 'open'),
        'file': f.get('file', ''),
        'fix_suggestion': f.get('current_finding', {}).get('fix_suggestion', ''),
    })

SEV_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
items.sort(key=lambda x: (
    SEV_ORDER.get(x['severity'], 9),
    not x['fixable_by_agent'],
    -(x['audit_count']),
))

open_items = [i for i in items if i['status'] != 'fixed'][:30]
print(json.dumps(open_items, indent=2))
PYEOF
)"

# Score snapshot: latest scores per repo
SCORE_SUMMARY="$(SCORE_FILE="$SCORE_FILE" python3 - <<'PYEOF'
import json, os

d = json.load(open(os.environ['SCORE_FILE']))
snapshots = d.get('snapshots', [])
if not snapshots:
    print('{}')
    exit(0)

latest = snapshots[-1]
scores = latest.get('scores', {})

# Compute average score per repo
result = {}
for repo, dept_scores in scores.items():
    vals = [v for v in dept_scores.values() if isinstance(v, (int, float))]
    result[repo] = {
        'avg': round(sum(vals) / len(vals), 1) if vals else 0,
        'scores': dept_scores,
    }

# Sort by avg score ascending (lowest first = highest priority)
sorted_result = dict(sorted(result.items(), key=lambda x: x[1]['avg']))
print(json.dumps(sorted_result, indent=2))
PYEOF
)"

# Product roadmap items: easy/moderate fixable features
PRODUCT_SUMMARY="$(PRODUCT_FILE="$PRODUCT_FILE" python3 - <<'PYEOF'
import json, os

d = json.load(open(os.environ['PRODUCT_FILE']))
repos = d.get('repos', [])

items = []
for repo in repos:
    for f in repo.get('findings', []):
        if f.get('effort') in ('easy', 'moderate') and f.get('fixable_by_agent', False):
            items.append({
                'repo': repo['name'],
                'id': f.get('id', ''),
                'title': f.get('title', ''),
                'severity': f.get('severity', 'low'),
                'effort': f.get('effort', 'moderate'),
                'description': f.get('description', ''),
                'fix_suggestion': f.get('fix_suggestion', ''),
                'category': f.get('category', ''),
            })

SEV_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
items.sort(key=lambda x: SEV_ORDER.get(x['severity'], 9))
print(json.dumps(items[:20], indent=2))
PYEOF
)"

# Previous cycle results: last 2 entries from overnight-history.json
HISTORY_SUMMARY="$(HISTORY_FILE="$HISTORY_FILE" python3 - <<'PYEOF'
import json, os

path = os.environ['HISTORY_FILE']
if not os.path.exists(path):
    print('[]')
    exit(0)

d = json.load(open(path))
history = d if isinstance(d, list) else d.get('cycles', [])
print(json.dumps(history[-2:], indent=2))
PYEOF
)"

# ── Build the prompt ───────────────────────────────────────────────────────────

OWNER_PROMPT="$(cat "$PROMPT_FILE")

---

## Input Data

### Backlog (top 30 open findings, sorted by priority)

\`\`\`json
$BACKLOG_SUMMARY
\`\`\`

### Score Snapshot (repos sorted lowest avg score first)

\`\`\`json
$SCORE_SUMMARY
\`\`\`

### Product Roadmap Items (easy/moderate, agent-fixable)

\`\`\`json
$PRODUCT_SUMMARY
\`\`\`

### Previous Cycle Results (last 2 cycles)

\`\`\`json
$HISTORY_SUMMARY
\`\`\`

## Instructions

Apply the decision framework from the prompt above to the data provided.
Output valid JSON only matching the schema. No prose, no markdown fences — just the raw JSON object starting with { and ending with }.

Decide the work plan now."

# ── Launch agent runner ────────────────────────────────────────────────────────

echo "Launching Product Owner agent..."
echo ""

job_start "product-owner"
RAW_OUTPUT="$(
  bash "$QA_ROOT/scripts/run-agent.sh" \
    --prompt "$OWNER_PROMPT" \
    --tools "Read,Glob,Grep,Bash" \
    --repo "$QA_ROOT"
)" && _EXIT_CODE=0 || _EXIT_CODE=$?
job_finish "product-owner" "$_EXIT_CODE"
[ "$_EXIT_CODE" -ne 0 ] && exit "$_EXIT_CODE"

# ── Extract JSON from output ───────────────────────────────────────────────────
# Agent may include preamble text — find first { to its matching }

echo "Extracting JSON from agent output..."

JSON_OUTPUT="$(RAW_OUTPUT="$RAW_OUTPUT" python3 - <<'PYEOF'
import os, json

raw = os.environ['RAW_OUTPUT']

# Find the first { character
start = raw.find('{')
if start == -1:
    print('Error: no JSON object found in agent output', file=__import__('sys').stderr)
    exit(1)

# Walk forward counting braces to find matching }
depth = 0
end = -1
for i, ch in enumerate(raw[start:], start=start):
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0:
            end = i
            break

if end == -1:
    print('Error: unmatched braces in agent output', file=__import__('sys').stderr)
    exit(1)

candidate = raw[start:end+1]

# Validate it parses
try:
    obj = json.loads(candidate)
except json.JSONDecodeError as e:
    print(f'Error: JSON parse failed: {e}', file=__import__('sys').stderr)
    exit(1)

print(json.dumps(obj, indent=2))
PYEOF
)"

# ── Validate schema ────────────────────────────────────────────────────────────

JSON_OUTPUT="$JSON_OUTPUT" python3 - <<'PYEOF'
import os, json, sys

raw = os.environ['JSON_OUTPUT']
obj = json.loads(raw)

required_keys = {'cycle_id', 'decided_at', 'rationale', 'fixes', 'features', 'skip'}
missing = required_keys - set(obj.keys())
if missing:
    print(f'Error: plan JSON missing required keys: {missing}', file=sys.stderr)
    sys.exit(1)

if not isinstance(obj['fixes'], list):
    print('Error: fixes must be an array', file=sys.stderr)
    sys.exit(1)

if not isinstance(obj['features'], list):
    print('Error: features must be an array', file=sys.stderr)
    sys.exit(1)

print(f'Plan validated: {len(obj["fixes"])} fixes, {len(obj["features"])} features, {len(obj["skip"])} skips')
PYEOF

# ── Write plan ─────────────────────────────────────────────────────────────────

echo "$JSON_OUTPUT" > "$PLAN_FILE"
echo ""
echo "Work plan written to: $PLAN_FILE"
echo ""
echo "Done."
