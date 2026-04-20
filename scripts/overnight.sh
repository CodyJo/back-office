#!/usr/bin/env bash
# Back Office — Overnight Autonomous Loop
# Usage: ./scripts/overnight.sh [--interval 120] [--dry-run] [--targets "a,b"]
#
# Runs a continuous 9-phase cycle:
#   1. SNAPSHOT  — git tag each repo for rollback
#   2. AUDIT     — run audit-all-parallel per target, refresh dashboard
#   3. DECIDE    — Product Owner agent outputs a prioritized work plan
#   4. FIX       — fix agent on each planned fix (policy-gated)
#   5. BUILD     — feature-dev agent on each feature (policy-gated, branch-based)
#   6. VERIFY    — final test run on all modified repos
#   7. DEPLOY    — deploy if policy allows (disabled by default)
#   8. REPORT    — refresh dashboards, write cycle summary, append history
#   9. SLEEP     — wait for next cycle
#
# Designed to run overnight in tmux or via nohup.
#
# Safety features:
#   - Per-target autonomy policy from targets.yaml
#   - Dirty worktree detection (skip repos with uncommitted work)
#   - Plan schema validation (fail closed on invalid plan)
#   - Default branch detection (no main/master assumption)
#   - Graceful stop checks between every phase
#   - Repeated failure suppression (skip items that failed last 2 cycles)
#   - Coverage non-regression gate
#   - Rollback to snapshot tag on any test/coverage failure
#   - Cycle summary artifact for auditability

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$ROOT_DIR/results"
DASHBOARD_DIR="$ROOT_DIR/dashboard"
HISTORY_FILE="$RESULTS_DIR/overnight-history.json"
SUMMARY_FILE="$RESULTS_DIR/overnight-summary.json"
PLAN_FILE="$RESULTS_DIR/overnight-plan.json"
STOP_FILE="$RESULTS_DIR/.overnight-stop"
CONFIG_FILE="$ROOT_DIR/config/targets.yaml"
LEDGER_FILE="$RESULTS_DIR/overnight-ledger.jsonl"
QUARANTINE_OVERRIDES="$RESULTS_DIR/quarantine-clear.json"
QUARANTINE_THRESHOLD="${QUARANTINE_THRESHOLD:-3}"
FAILURE_WINDOW="${FAILURE_WINDOW:-2}"

# ── Args ─────────────────────────────────────────────────────────────────────

INTERVAL=45         # minutes between cycles
DRY_RUN=false
TARGET_FILTER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --interval)  INTERVAL="${2:?--interval requires a value (minutes)}"; shift 2 ;;
    --dry-run)   DRY_RUN=true; shift ;;
    --targets)   TARGET_FILTER="${2:?--targets requires a comma-separated list}"; shift 2 ;;
    -h|--help)
      echo "Usage: overnight.sh [--interval N] [--dry-run] [--targets \"a,b,c\"]"
      echo "  --interval N   Minutes between cycles (default: 120)"
      echo "  --dry-run      Audit + decide only, skip fix/build/deploy"
      echo "  --targets X    Comma-separated target names (default: all)"
      exit 0
      ;;
    *)  echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log_phase() {
  log "══════ $* ══════"
}

# Graceful stop check — call between EVERY phase.
# Accepts a phase name for the log message.
check_stop() {
  if [ -f "$STOP_FILE" ]; then
    log "Stop signal detected after phase: ${1:-unknown}. Exiting gracefully."
    rm -f "$STOP_FILE"
    exit 0
  fi
}

# Resolve targets from config/targets.yaml, filtering by --targets and validating paths.
# Output: one line per target, pipe-delimited:
#   name|path|test_command|deploy_command|coverage_command|language
get_valid_targets() {
  CONFIG_FILE="$CONFIG_FILE" TARGET_FILTER="$TARGET_FILTER" python3 - <<'PYEOF'
import yaml, os

config_path = os.environ['CONFIG_FILE']
filter_str = os.environ.get('TARGET_FILTER', '')
filter_list = [f.strip() for f in filter_str.split(',') if f.strip()] if filter_str else []

with open(config_path) as f:
    targets = yaml.safe_load(f).get('targets', [])

for t in targets:
    name = t.get('name', '')
    path = t.get('path', '')
    if not name or not path:
        continue
    if not os.path.isdir(path):
        continue
    if not os.path.isdir(os.path.join(path, '.git')):
        continue
    if filter_list and name not in filter_list:
        continue
    test_cmd = t.get('test_command', '')
    deploy_cmd = t.get('deploy_command', '')
    cov_cmd = t.get('coverage_command', '')
    lang = t.get('language', '')
    print(f'{name}|{path}|{test_cmd}|{deploy_cmd}|{cov_cmd}|{lang}')
PYEOF
}

# Get per-target autonomy policy field. Returns the value or the default.
# Usage: get_policy "target-name" "field_name" "default_value"
get_policy() {
  local target_name="$1" field="$2" default_val="$3"
  CONFIG_FILE="$CONFIG_FILE" TARGET_NAME="$target_name" FIELD="$field" DEFAULT="$default_val" python3 - <<'PYEOF'
import yaml, os

config_path = os.environ['CONFIG_FILE']
target_name = os.environ['TARGET_NAME']
field = os.environ['FIELD']
default = os.environ['DEFAULT']

with open(config_path) as f:
    targets = yaml.safe_load(f).get('targets', [])

for t in targets:
    if t.get('name') == target_name:
        autonomy = t.get('autonomy', {})
        if isinstance(autonomy, dict) and field in autonomy:
            val = autonomy[field]
            # Normalize booleans for shell consumption
            if isinstance(val, bool):
                print('true' if val else 'false')
            else:
                print(val)
            exit(0)
        break

print(default)
PYEOF
}

# Detect the default branch for a repo (don't assume main).
# Usage: get_default_branch /path/to/repo
get_default_branch() {
  local repo_path="$1"
  local branch
  # Try symbolic ref from remote HEAD
  branch=$(cd "$repo_path" && git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@') || true
  if [ -n "$branch" ]; then
    echo "$branch"
    return
  fi
  # Fall back: check if main exists, then master
  if (cd "$repo_path" && git rev-parse --verify main >/dev/null 2>&1); then
    echo "main"
  elif (cd "$repo_path" && git rev-parse --verify master >/dev/null 2>&1); then
    echo "master"
  else
    # Last resort: current branch
    (cd "$repo_path" && git rev-parse --abbrev-ref HEAD 2>/dev/null) || echo "main"
  fi
}

# Check if a repo's worktree is clean (no uncommitted changes).
# Returns 0 if clean, 1 if dirty.
is_worktree_clean() {
  local repo_path="$1"
  local status
  status=$(cd "$repo_path" && git status --porcelain 2>/dev/null) || return 1
  [ -z "$status" ]
}

# Run a target's test command. Returns the exit code.
run_tests() {
  local repo_path="$1" test_cmd="$2"
  if [ -z "$test_cmd" ]; then
    return 0
  fi
  (cd "$repo_path" && eval "$test_cmd") >/dev/null 2>&1
}

# Get coverage percentage by running the coverage command and parsing output.
# Handles pytest-cov (Python) and istanbul/c8 (Node) formats.
# Returns a numeric percentage or "0" on failure.
get_coverage_pct() {
  local repo_path="$1" cov_cmd="$2"
  if [ -z "$cov_cmd" ]; then
    echo "0"
    return
  fi
  local output
  output=$( (cd "$repo_path" && eval "$cov_cmd") 2>&1 ) || true
  COV_OUTPUT="$output" python3 - <<'PYEOF'
import os, re, sys

text = os.environ.get('COV_OUTPUT', '')
# Try multiple coverage output formats
patterns = [
    r'TOTAL\s+\d+\s+\d+\s+(\d+)%',                    # pytest-cov TOTAL line
    r'(\d+(?:\.\d+)?)%\s+total',                        # generic "N% total"
    r'Statements\s*:\s*(\d+(?:\.\d+)?)%',               # istanbul Statements
    r'All files\s*\|\s*(\d+(?:\.\d+)?)',                 # c8/istanbul table
    r'Lines\s*:\s*(\d+(?:\.\d+)?)%',                    # istanbul Lines
    r'(?:^|\n)\s*TOTAL\s+.*?(\d+(?:\.\d+)?)%',          # pytest-cov multiline
]
for pattern in patterns:
    m = re.search(pattern, text)
    if m:
        print(m.group(1))
        sys.exit(0)
print('0')
PYEOF
}

# Validate the plan JSON from the Product Owner.
# Returns 0 if valid, 1 if invalid. Prints error to stderr.
validate_plan() {
  local plan_path="$1"
  PLAN_PATH="$plan_path" python3 - <<'PYEOF'
import json, os, sys

plan_path = os.environ['PLAN_PATH']
try:
    with open(plan_path) as f:
        obj = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f'Plan validation failed: {e}', file=sys.stderr)
    sys.exit(1)

required_keys = {'fixes', 'features'}
missing = required_keys - set(obj.keys())
if missing:
    print(f'Plan missing required keys: {missing}', file=sys.stderr)
    sys.exit(1)

if not isinstance(obj.get('fixes'), list):
    print('Plan "fixes" is not an array', file=sys.stderr)
    sys.exit(1)

if not isinstance(obj.get('features'), list):
    print('Plan "features" is not an array', file=sys.stderr)
    sys.exit(1)

print(f'{len(obj["fixes"])} fixes, {len(obj["features"])} features')
sys.exit(0)
PYEOF
}

# Append a cycle record to overnight-history.json.
# Input: JSON string for the cycle record.
append_history() {
  local cycle_json="$1"
  HISTORY_FILE="$HISTORY_FILE" CYCLE_JSON="$cycle_json" python3 - <<'PYEOF'
import json, os

history_path = os.environ['HISTORY_FILE']
cycle_str = os.environ['CYCLE_JSON']

try:
    cycle = json.loads(cycle_str)
except json.JSONDecodeError:
    exit(1)

if os.path.exists(history_path):
    try:
        with open(history_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        data = {'cycles': []}
else:
    data = {'cycles': []}

if not isinstance(data, dict) or 'cycles' not in data:
    data = {'cycles': []}

data['cycles'].append(cycle)
data['cycles'] = data['cycles'][-50:]  # Keep last 50 cycles

with open(history_path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYEOF
}

# Write cycle summary artifact for auditability.
write_summary() {
  local summary_json="$1"
  SUMMARY_FILE="$SUMMARY_FILE" SUMMARY_JSON="$summary_json" python3 - <<'PYEOF'
import json, os

summary_path = os.environ['SUMMARY_FILE']
summary_str = os.environ['SUMMARY_JSON']

try:
    obj = json.loads(summary_str)
except json.JSONDecodeError:
    exit(1)

with open(summary_path, 'w') as f:
    json.dump(obj, f, indent=2)
    f.write('\n')
PYEOF
}

# Get items that failed in the last 2 cycles (for repeated failure suppression).
# Returns a JSON array of {repo, title} objects.
get_recent_failures() {
  HISTORY_FILE="$HISTORY_FILE" python3 - <<'PYEOF'
import json, os

history_path = os.environ['HISTORY_FILE']
if not os.path.exists(history_path):
    print('[]')
    exit(0)

try:
    with open(history_path) as f:
        data = json.load(f)
except (json.JSONDecodeError, IOError):
    print('[]')
    exit(0)

cycles = data.get('cycles', [])[-2:]
failures = []
for c in cycles:
    for item in c.get('failed_items', []):
        if isinstance(item, dict):
            failures.append(item)
        elif isinstance(item, str):
            failures.append({'title': item})

print(json.dumps(failures))
PYEOF
}

# Append a decision to the execution ledger. Non-fatal if it fails.
# Usage: ledger <action> <target> <true|false> <reason_code> [detail_json]
ledger() {
  local action="$1" target="$2" allow="$3" reason="$4" detail="${5:-{\}}"
  (cd "$ROOT_DIR" && python3 -m backoffice state ledger-append \
      --path "$LEDGER_FILE" \
      --cycle "${CYCLE_ID:-unknown}" \
      --action "$action" \
      --target "$target" \
      --allow "$allow" \
      --reason "$reason" \
      --detail "$detail") 2>/dev/null || true
}

# Return JSON array of quarantined repos (empty array if none).
get_quarantined() {
  (cd "$ROOT_DIR" && python3 -m backoffice state quarantined \
      --history "$HISTORY_FILE" \
      --threshold "$QUARANTINE_THRESHOLD" \
      --overrides "$QUARANTINE_OVERRIDES") 2>/dev/null || echo "[]"
}

# Case-insensitive check: is "repo|title" in the recent-failure window?
is_recently_failed() {
  local repo="$1" title="$2"
  REPO="$repo" TITLE="$title" HISTORY_FILE="$HISTORY_FILE" \
  FAILURE_WINDOW="$FAILURE_WINDOW" python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.environ.get('ROOT_DIR', '.'))
from backoffice.overnight_state import FailureMemory
mem = FailureMemory(
    Path(os.environ['HISTORY_FILE']),
    window=int(os.environ.get('FAILURE_WINDOW', '2')),
)
sys.exit(0 if mem.should_skip(os.environ['REPO'], os.environ['TITLE']) else 1)
PYEOF
}

# Check if a repo is quarantined (exit 0 if yes, 1 if no).
is_quarantined() {
  local repo="$1"
  local flagged
  flagged=$(get_quarantined)
  REPO="$repo" FLAGGED="$flagged" python3 - <<'PYEOF'
import json, os, sys
try:
    names = json.loads(os.environ['FLAGGED'])
except json.JSONDecodeError:
    sys.exit(1)
sys.exit(0 if os.environ['REPO'] in names else 1)
PYEOF
}

# Export functions and variables for background subshells (parallel fix/feature phases)
export -f log log_phase check_stop get_policy is_worktree_clean run_tests get_coverage_pct get_default_branch get_valid_targets ledger is_recently_failed is_quarantined get_quarantined
export ROOT_DIR CONFIG_FILE RESULTS_DIR PLAN_FILE STOP_FILE DRY_RUN HISTORY_FILE SUMMARY_FILE LEDGER_FILE QUARANTINE_OVERRIDES QUARANTINE_THRESHOLD FAILURE_WINDOW

# ── Banner ───────────────────────────────────────────────────────────────────

log "╔══════════════════════════════════════════════════════════╗"
log "║  Back Office — Overnight Autonomous Loop                ║"
log "╠══════════════════════════════════════════════════════════╣"
log "║  Interval: ${INTERVAL}m  |  Dry run: $DRY_RUN"
if [ -n "$TARGET_FILTER" ]; then
  log "║  Targets:  $TARGET_FILTER"
fi
log "╚══════════════════════════════════════════════════════════╝"
log ""
log "Stop gracefully: touch $STOP_FILE"
log ""

# Clear any stale stop signal
rm -f "$STOP_FILE"

# Ensure results directory exists
mkdir -p "$RESULTS_DIR"

# ── Main Loop ────────────────────────────────────────────────────────────────

while true; do
  # Check for stop signal at loop boundary
  check_stop "LOOP_START"

  CYCLE_ID="overnight-$(date +%Y%m%d-%H%M%S)"
  CYCLE_START=$(date -Iseconds)

  # Cycle-level counters
  FIXES_OK=0
  FIXES_FAIL=0
  FEATURES_OK=0
  FEATURES_FAIL=0
  DEPLOYS_OK=0
  DEPLOYS_FAIL=0
  ROLLBACKS=0
  MODIFIED_REPOS=""
  SKIPPED_ITEMS=""
  FAILED_ITEMS_JSON="[]"
  CHANGED_REPOS_JSON="[]"
  DEPLOYED_REPOS_JSON="[]"
  ROLLBACK_REPOS_JSON="[]"

  log_phase "CYCLE START: $CYCLE_ID"

  # ── Phase 1: SNAPSHOT ──────────────────────────────────────────────────────

  log_phase "PHASE 1: SNAPSHOT"
  TAG_NAME="overnight-before-$(date +%Y%m%d-%H%M%S)"
  export TAG_NAME

  while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd lang; do
    [ -z "$name" ] && continue

    if (cd "$path" && git tag "$TAG_NAME" HEAD 2>/dev/null); then
      log "  Tagged $name: $TAG_NAME"
    else
      log "  WARN: Could not tag $name (tag may already exist)"
    fi

    # Prune overnight tags older than 7 days
    (cd "$path" && git tag -l 'overnight-before-*' | while read -r tag; do
      tag_date=$(echo "$tag" | sed 's/overnight-before-//' | cut -c1-8)
      cutoff=$(date -d '7 days ago' +%Y%m%d 2>/dev/null || date -v-7d +%Y%m%d 2>/dev/null || echo "00000000")
      if [ "$tag_date" \< "$cutoff" ]; then
        git tag -d "$tag" >/dev/null 2>&1 || true
      fi
    done) 2>/dev/null || true
  done < <(get_valid_targets)

  # ── Phase 2: AUDIT ────────────────────────────────────────────────────────

  check_stop "SNAPSHOT"
  log_phase "PHASE 2: AUDIT"

  # Launch ALL target audits in parallel (biggest speed win)
  declare -a AUDIT_PIDS=()
  declare -a AUDIT_NAMES=()
  while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd lang; do
    [ -z "$name" ] && continue
    log "  Auditing $name (parallel)..."
    (make -C "$ROOT_DIR" audit-all-parallel TARGET="$path" >/dev/null 2>&1) &
    AUDIT_PIDS+=($!)
    AUDIT_NAMES+=("$name")
  done < <(get_valid_targets)

  log "  Waiting for ${#AUDIT_PIDS[@]} parallel audits..."
  for i in "${!AUDIT_PIDS[@]}"; do
    if wait "${AUDIT_PIDS[$i]}" 2>/dev/null; then
      log "  ${AUDIT_NAMES[$i]}: audit complete"
    else
      log "  ${AUDIT_NAMES[$i]}: audit had errors (continuing)"
    fi
  done
  unset AUDIT_PIDS AUDIT_NAMES

  log "  Refreshing dashboard data..."
  (cd "$ROOT_DIR" && python3 -m backoffice refresh) >/dev/null 2>&1 || \
    log "  WARN: Dashboard refresh had errors"

  # ── Phase 3: DECIDE ───────────────────────────────────────────────────────

  check_stop "AUDIT"
  log_phase "PHASE 3: DECIDE (Product Owner)"

  # Pass recent failures to Product Owner so it can avoid repeating them
  RECENT_FAILURES=$(get_recent_failures)
  if [ "$RECENT_FAILURES" != "[]" ]; then
    log "  Recent failures to suppress: $RECENT_FAILURES"
  fi

  # Run the Product Owner agent
  if bash "$ROOT_DIR/agents/product-owner.sh" >/dev/null 2>&1; then
    log "  Product Owner agent completed"
  else
    log "  Product Owner agent exited with error"
  fi

  # Validate the plan
  PLAN_VALID=false
  if [ ! -f "$PLAN_FILE" ]; then
    log "  No plan file generated. Skipping fix/build phases."
  elif PLAN_VALIDATION=$(validate_plan "$PLAN_FILE" 2>&1); then
    PLAN_VALID=true
    log "  Plan validated: $PLAN_VALIDATION"

    NUM_FIXES=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('fixes',[])))" 2>/dev/null || echo 0)
    NUM_FEATURES=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('features',[])))" 2>/dev/null || echo 0)
    log "  Plan: $NUM_FIXES fixes, $NUM_FEATURES features"
  else
    log "  PLAN INVALID — fail closed, skipping fix/build phases."
    log "  Validation error: $PLAN_VALIDATION"
  fi

  if [ "$DRY_RUN" = true ]; then
    log "  DRY RUN — skipping fix/build/verify/deploy phases."
  elif [ "$PLAN_VALID" = true ]; then

    # ── Phase 4: FIX ───────────────────────────────────────────────────────

    check_stop "DECIDE"
    log_phase "PHASE 4: FIX"

    # Read fixes from plan
    FIX_COUNT=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('fixes',[])))" 2>/dev/null || echo 0)

    # Create temp dir for parallel fix results
    FIX_TMPDIR=$(mktemp -d)

    # Group fixes by repo: same-repo fixes run sequentially, cross-repo in parallel
    declare -A FIX_REPO_GROUPS
    for fix_idx in $(seq 0 $((FIX_COUNT - 1))); do
      _fr=$(PLAN_FILE="$PLAN_FILE" FIX_IDX="$fix_idx" python3 -c "
import json, os
plan = json.load(open(os.environ['PLAN_FILE']))
idx = int(os.environ['FIX_IDX'])
fixes = plan.get('fixes', [])
print(fixes[idx].get('repo', '') if idx < len(fixes) else '')
" 2>/dev/null) || continue
      [ -n "$_fr" ] && FIX_REPO_GROUPS[$_fr]+="$fix_idx "
    done

    log "  $FIX_COUNT fixes across ${#FIX_REPO_GROUPS[@]} repos (parallel across repos)"

    # Launch one background job per repo (sequential within each repo)
    for _group_repo in "${!FIX_REPO_GROUPS[@]}"; do
      (
        set +e  # Disable errexit in subshell — errors handled per-item
        for fix_idx in ${FIX_REPO_GROUPS[$_group_repo]}; do

          # Extract fix details via Python (safe JSON handling)
          FIX_INFO=$(PLAN_FILE="$PLAN_FILE" FIX_IDX="$fix_idx" python3 - <<'PYEOF'
import json, os

plan = json.load(open(os.environ['PLAN_FILE']))
idx = int(os.environ['FIX_IDX'])
fixes = plan.get('fixes', [])
if idx >= len(fixes):
    exit(1)
fix = fixes[idx]
# Output pipe-delimited: repo|title|department|severity
print(f'{fix.get("repo","")}\t{fix.get("title","")}\t{fix.get("department","")}\t{fix.get("severity","")}')
PYEOF
          ) || { echo "skip|$_group_repo||no-info" > "$FIX_TMPDIR/$fix_idx.result"; continue; }

          IFS=$'\t' read -r fix_repo fix_title fix_dept fix_sev <<< "$FIX_INFO"

          if [ -z "$fix_repo" ]; then
            echo "skip|unknown||no-repo" > "$FIX_TMPDIR/$fix_idx.result"
            continue
          fi

          # Resolve repo path
          FIX_PATH=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$fix_repo" python3 - <<'PYEOF'
import yaml, os
config_path = os.environ['CONFIG_FILE']
repo_name = os.environ['REPO_NAME']
with open(config_path) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == repo_name:
        print(t.get('path', ''))
        break
PYEOF
          ) || true

          if [ -z "$FIX_PATH" ] || [ ! -d "$FIX_PATH" ]; then
            echo "skip|$fix_repo|$fix_title|path-not-found" > "$FIX_TMPDIR/$fix_idx.result"
            ledger fix "$fix_repo" false "block:path-not-found" "{}"
            continue
          fi

          # Quarantine check — repos with persistent rollbacks are off-limits
          if is_quarantined "$fix_repo"; then
            echo "skip|$fix_repo|$fix_title|quarantined" > "$FIX_TMPDIR/$fix_idx.result"
            ledger fix "$fix_repo" false "block:quarantined" "{}"
            continue
          fi

          # Failure memory — same item failed in the recent window
          if is_recently_failed "$fix_repo" "$fix_title"; then
            echo "skip|$fix_repo|$fix_title|recently-failed" > "$FIX_TMPDIR/$fix_idx.result"
            ledger fix "$fix_repo" false "block:recently-failed" "{}"
            continue
          fi

          # Check autonomy policy: allow_fix
          ALLOW_FIX=$(get_policy "$fix_repo" "allow_fix" "true")
          if [ "$ALLOW_FIX" != "true" ]; then
            echo "skip|$fix_repo|$fix_title|policy-no-fix" > "$FIX_TMPDIR/$fix_idx.result"
            ledger fix "$fix_repo" false "block:allow_fix=false" "{}"
            continue
          fi

          # Check clean worktree
          REQUIRE_CLEAN=$(get_policy "$fix_repo" "require_clean_worktree" "true")
          if [ "$REQUIRE_CLEAN" = "true" ] && ! is_worktree_clean "$FIX_PATH"; then
            echo "skip|$fix_repo|$fix_title|dirty-worktree" > "$FIX_TMPDIR/$fix_idx.result"
            ledger fix "$fix_repo" false "block:worktree_dirty" "{}"
            continue
          fi

          ledger fix "$fix_repo" true "policy:allow_fix" "{}"

          log "  FIX: $fix_repo — [$fix_sev] $fix_title"

          # Get target-specific commands
          FIX_TEST_CMD=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$fix_repo" python3 -c "
import yaml, os
with open(os.environ['CONFIG_FILE']) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == os.environ['REPO_NAME']:
        print(t.get('test_command', '')); break
" 2>/dev/null) || true

          FIX_COV_CMD=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$fix_repo" python3 -c "
import yaml, os
with open(os.environ['CONFIG_FILE']) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == os.environ['REPO_NAME']:
        print(t.get('coverage_command', '')); break
" 2>/dev/null) || true

          # Get pre-fix coverage
          PRE_COV=$(get_coverage_pct "$FIX_PATH" "$FIX_COV_CMD")

          # Run fix agent
          if bash "$ROOT_DIR/agents/fix-bugs.sh" "$FIX_PATH" >/dev/null 2>&1; then
            FIX_EXIT=0
          else
            FIX_EXIT=$?
          fi

          if [ "$FIX_EXIT" -ne 0 ]; then
            log "  FIX FAILED: $fix_repo — agent error (exit $FIX_EXIT)"
            echo "fail|$fix_repo|$fix_title|agent_error" > "$FIX_TMPDIR/$fix_idx.result"
            continue
          fi

          # Check if tests required
          REQUIRE_TESTS=$(get_policy "$fix_repo" "require_tests" "true")

          # Verify tests pass after fix
          if [ "$REQUIRE_TESTS" = "true" ] && [ -n "$FIX_TEST_CMD" ]; then
            if run_tests "$FIX_PATH" "$FIX_TEST_CMD"; then
              # Check coverage non-regression
              POST_COV=$(get_coverage_pct "$FIX_PATH" "$FIX_COV_CMD")
              COV_REGRESSED="false"
              if [ -n "$PRE_COV" ] && [ -n "$POST_COV" ] && [ "$PRE_COV" != "0" ] && [ "$POST_COV" != "0" ]; then
                COV_REGRESSED=$(PRE="$PRE_COV" POST="$POST_COV" python3 -c "
import os
pre = float(os.environ['PRE'])
post = float(os.environ['POST'])
tolerance = 0.5  # Allow 0.5% variance for measurement noise
print('true' if post < pre - tolerance else 'false')
" 2>/dev/null) || COV_REGRESSED="false"
              fi

              if [ "$COV_REGRESSED" = "true" ]; then
                log "  FIX ROLLED BACK: $fix_repo — coverage decreased beyond 0.5% tolerance ($PRE_COV% -> $POST_COV%)"
                (cd "$FIX_PATH" && git reset --hard "$TAG_NAME") >/dev/null 2>&1 || true
                echo "rollback|$fix_repo|$fix_title|coverage_regression" > "$FIX_TMPDIR/$fix_idx.result"
                ledger rollback "$fix_repo" false "rollback:coverage_regression" "{}"
              else
                log "  FIX OK: $fix_repo — tests pass, coverage $PRE_COV% -> $POST_COV%"
                echo "ok|$fix_repo|$fix_title|" > "$FIX_TMPDIR/$fix_idx.result"
              fi
            else
              log "  FIX ROLLED BACK: $fix_repo — tests failed after fix"
              (cd "$FIX_PATH" && git reset --hard "$TAG_NAME") >/dev/null 2>&1 || true
              echo "rollback|$fix_repo|$fix_title|tests_failed" > "$FIX_TMPDIR/$fix_idx.result"
              ledger rollback "$fix_repo" false "rollback:tests_failed" "{}"
            fi
          else
            log "  FIX OK: $fix_repo — no test gate (policy: require_tests=$REQUIRE_TESTS)"
            echo "ok|$fix_repo|$fix_title|" > "$FIX_TMPDIR/$fix_idx.result"
          fi
        done
      ) &
    done
    wait

    # Aggregate fix results from temp files
    for fix_idx in $(seq 0 $((FIX_COUNT - 1))); do
      if [ -f "$FIX_TMPDIR/$fix_idx.result" ]; then
        IFS='|' read -r _fstatus _frepo _ftitle _freason < "$FIX_TMPDIR/$fix_idx.result"
        case "$_fstatus" in
          ok)
            FIXES_OK=$((FIXES_OK + 1))
            MODIFIED_REPOS="$MODIFIED_REPOS $_frepo"
            CHANGED_REPOS_JSON=$(CHANGED_REPOS_JSON="$CHANGED_REPOS_JSON" REPO="$_frepo" python3 -c "
import json, os
items = json.loads(os.environ['CHANGED_REPOS_JSON'])
if os.environ['REPO'] not in items: items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
            ;;
          fail)
            FIXES_FAIL=$((FIXES_FAIL + 1))
            FAILED_ITEMS_JSON=$(FAILED_ITEMS_JSON="$FAILED_ITEMS_JSON" REPO="$_frepo" TITLE="$_ftitle" TYPE="fix" python3 -c "
import json, os
items = json.loads(os.environ['FAILED_ITEMS_JSON'])
items.append({'repo': os.environ['REPO'], 'title': os.environ['TITLE'], 'type': os.environ['TYPE'], 'reason': '$_freason'})
print(json.dumps(items))
") || true
            ;;
          rollback)
            FIXES_FAIL=$((FIXES_FAIL + 1))
            ROLLBACKS=$((ROLLBACKS + 1))
            ROLLBACK_REPOS_JSON=$(ROLLBACK_REPOS_JSON="$ROLLBACK_REPOS_JSON" REPO="$_frepo" python3 -c "
import json, os
items = json.loads(os.environ['ROLLBACK_REPOS_JSON'])
items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
            FAILED_ITEMS_JSON=$(FAILED_ITEMS_JSON="$FAILED_ITEMS_JSON" REPO="$_frepo" TITLE="$_ftitle" TYPE="fix" python3 -c "
import json, os
items = json.loads(os.environ['FAILED_ITEMS_JSON'])
items.append({'repo': os.environ['REPO'], 'title': os.environ['TITLE'], 'type': os.environ['TYPE'], 'reason': '$_freason'})
print(json.dumps(items))
") || true
            ;;
          skip)
            SKIPPED_ITEMS="$SKIPPED_ITEMS $_frepo:$_freason"
            ;;
        esac
      fi
    done
    rm -rf "$FIX_TMPDIR"
    unset FIX_REPO_GROUPS

    # ── Phase 5: BUILD (Features) ────────────────────────────────────────

    check_stop "FIX"
    log_phase "PHASE 5: BUILD (Features)"

    FEAT_COUNT=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('features',[])))" 2>/dev/null || echo 0)

    # Create temp dir for parallel feature results
    FEAT_TMPDIR=$(mktemp -d)

    # Group features by repo for cross-repo parallelism
    declare -A FEAT_REPO_GROUPS
    for feat_idx in $(seq 0 $((FEAT_COUNT - 1))); do
      _featr=$(PLAN_FILE="$PLAN_FILE" FEAT_IDX="$feat_idx" python3 -c "
import json, os
plan = json.load(open(os.environ['PLAN_FILE']))
idx = int(os.environ['FEAT_IDX'])
features = plan.get('features', [])
print(features[idx].get('repo', '') if idx < len(features) else '')
" 2>/dev/null) || continue
      [ -n "$_featr" ] && FEAT_REPO_GROUPS[$_featr]+="$feat_idx "
    done

    log "  $FEAT_COUNT features across ${#FEAT_REPO_GROUPS[@]} repos (parallel across repos)"

    # Launch one background job per repo
    for _group_repo in "${!FEAT_REPO_GROUPS[@]}"; do
      (
        set +e  # Disable errexit in subshell — errors handled per-item
        for feat_idx in ${FEAT_REPO_GROUPS[$_group_repo]}; do

          # Extract feature JSON
          FEAT_JSON=$(PLAN_FILE="$PLAN_FILE" FEAT_IDX="$feat_idx" python3 - <<'PYEOF'
import json, os
plan = json.load(open(os.environ['PLAN_FILE']))
idx = int(os.environ['FEAT_IDX'])
features = plan.get('features', [])
if idx >= len(features):
    exit(1)
print(json.dumps(features[idx]))
PYEOF
          ) || { echo "skip|$_group_repo||no-info" > "$FEAT_TMPDIR/$feat_idx.result"; continue; }

          FEAT_REPO=$(echo "$FEAT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('repo',''))" 2>/dev/null) || true
          FEAT_TITLE=$(echo "$FEAT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('title','Feature'))" 2>/dev/null) || true

          if [ -z "$FEAT_REPO" ]; then
            echo "skip|unknown||no-repo" > "$FEAT_TMPDIR/$feat_idx.result"
            continue
          fi

          # Resolve repo path
          FEAT_PATH=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$FEAT_REPO" python3 - <<'PYEOF'
import yaml, os
config_path = os.environ['CONFIG_FILE']
repo_name = os.environ['REPO_NAME']
with open(config_path) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == repo_name:
        print(t.get('path', ''))
        break
PYEOF
          ) || true

          if [ -z "$FEAT_PATH" ] || [ ! -d "$FEAT_PATH" ]; then
            echo "skip|$FEAT_REPO|$FEAT_TITLE|path-not-found" > "$FEAT_TMPDIR/$feat_idx.result"
            ledger feature "$FEAT_REPO" false "block:path-not-found" "{}"
            continue
          fi

          # Quarantine check — repos with persistent rollbacks are off-limits
          if is_quarantined "$FEAT_REPO"; then
            echo "skip|$FEAT_REPO|$FEAT_TITLE|quarantined" > "$FEAT_TMPDIR/$feat_idx.result"
            ledger feature "$FEAT_REPO" false "block:quarantined" "{}"
            continue
          fi

          # Failure memory — same feature title failed in the recent window
          if is_recently_failed "$FEAT_REPO" "$FEAT_TITLE"; then
            echo "skip|$FEAT_REPO|$FEAT_TITLE|recently-failed" > "$FEAT_TMPDIR/$feat_idx.result"
            ledger feature "$FEAT_REPO" false "block:recently-failed" "{}"
            continue
          fi

          # Check autonomy policy: allow_feature_dev
          ALLOW_FEAT=$(get_policy "$FEAT_REPO" "allow_feature_dev" "false")
          if [ "$ALLOW_FEAT" != "true" ]; then
            echo "skip|$FEAT_REPO|$FEAT_TITLE|policy-no-feature" > "$FEAT_TMPDIR/$feat_idx.result"
            ledger feature "$FEAT_REPO" false "block:allow_feature_dev=false" "{}"
            continue
          fi

          # Check clean worktree
          REQUIRE_CLEAN=$(get_policy "$FEAT_REPO" "require_clean_worktree" "true")
          if [ "$REQUIRE_CLEAN" = "true" ] && ! is_worktree_clean "$FEAT_PATH"; then
            echo "skip|$FEAT_REPO|$FEAT_TITLE|dirty-worktree" > "$FEAT_TMPDIR/$feat_idx.result"
            ledger feature "$FEAT_REPO" false "block:worktree_dirty" "{}"
            continue
          fi

          ledger feature "$FEAT_REPO" true "policy:allow_feature_dev" "{}"

          log "  BUILD: $FEAT_REPO — $FEAT_TITLE"

          # Get the default branch for this repo
          DEFAULT_BRANCH=$(get_default_branch "$FEAT_PATH")

          # Get target-specific commands
          FEAT_TEST_CMD=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$FEAT_REPO" python3 -c "
import yaml, os
with open(os.environ['CONFIG_FILE']) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == os.environ['REPO_NAME']:
        print(t.get('test_command', '')); break
" 2>/dev/null) || true

          FEAT_COV_CMD=$(CONFIG_FILE="$CONFIG_FILE" REPO_NAME="$FEAT_REPO" python3 -c "
import yaml, os
with open(os.environ['CONFIG_FILE']) as f:
    targets = yaml.safe_load(f).get('targets', [])
for t in targets:
    if t.get('name') == os.environ['REPO_NAME']:
        print(t.get('coverage_command', '')); break
" 2>/dev/null) || true

          # Get pre-build coverage
          PRE_COV=$(get_coverage_pct "$FEAT_PATH" "$FEAT_COV_CMD")

          # Create feature branch (sanitize title for branch name)
          BRANCH_NAME="overnight/$(date +%Y%m%d)-$(echo "$FEAT_TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-' | head -c 40)"

          if ! (cd "$FEAT_PATH" && git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1); then
            echo "fail|$FEAT_REPO|$FEAT_TITLE|checkout_failed" > "$FEAT_TMPDIR/$feat_idx.result"
            continue
          fi

          if ! (cd "$FEAT_PATH" && git checkout -b "$BRANCH_NAME" >/dev/null 2>&1); then
            echo "fail|$FEAT_REPO|$FEAT_TITLE|branch_failed" > "$FEAT_TMPDIR/$feat_idx.result"
            continue
          fi

          # Run feature dev agent
          if bash "$ROOT_DIR/agents/feature-dev.sh" "$FEAT_PATH" "$FEAT_JSON" >/dev/null 2>&1; then
            FEAT_EXIT=0
          else
            FEAT_EXIT=$?
          fi

          # Verify: tests must pass + coverage non-regression
          REQUIRE_TESTS=$(get_policy "$FEAT_REPO" "require_tests" "true")
          FEAT_TESTS_OK=false

          if [ "$FEAT_EXIT" -eq 0 ]; then
            if [ "$REQUIRE_TESTS" = "true" ] && [ -n "$FEAT_TEST_CMD" ]; then
              if run_tests "$FEAT_PATH" "$FEAT_TEST_CMD"; then
                POST_COV=$(get_coverage_pct "$FEAT_PATH" "$FEAT_COV_CMD")
                COV_REGRESSED="false"
                if [ -n "$PRE_COV" ] && [ -n "$POST_COV" ] && [ "$PRE_COV" != "0" ] && [ "$POST_COV" != "0" ]; then
                  COV_REGRESSED=$(PRE="$PRE_COV" POST="$POST_COV" python3 -c "
import os
pre = float(os.environ['PRE'])
post = float(os.environ['POST'])
tolerance = 0.5  # Allow 0.5% variance for measurement noise
print('true' if post < pre - tolerance else 'false')
" 2>/dev/null) || COV_REGRESSED="false"
                fi

                if [ "$COV_REGRESSED" = "true" ]; then
                  log "  BUILD ROLLED BACK: $FEAT_REPO — coverage decreased beyond 0.5% tolerance ($PRE_COV% -> $POST_COV%)"
                else
                  FEAT_TESTS_OK=true
                  log "  Feature tests pass, coverage $PRE_COV% -> $POST_COV%"
                fi
              else
                log "  Feature tests failed"
              fi
            else
              FEAT_TESTS_OK=true
            fi
          else
            log "  Feature agent exited with error (exit $FEAT_EXIT)"
          fi

          if [ "$FEAT_TESTS_OK" = true ]; then
            ALLOW_MERGE=$(get_policy "$FEAT_REPO" "allow_auto_merge" "false")
            if [ "$ALLOW_MERGE" = "true" ]; then
              if (cd "$FEAT_PATH" && git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1 && \
                  git merge "$BRANCH_NAME" --no-ff -m "feat: $FEAT_TITLE (overnight loop)" >/dev/null 2>&1); then
                (cd "$FEAT_PATH" && git branch -d "$BRANCH_NAME" >/dev/null 2>&1) || true
                log "  BUILD OK: $FEAT_REPO — merged to $DEFAULT_BRANCH"
                echo "ok-merged|$FEAT_REPO|$FEAT_TITLE|" > "$FEAT_TMPDIR/$feat_idx.result"
              else
                log "  BUILD FAILED: $FEAT_REPO — merge conflict"
                (cd "$FEAT_PATH" && git merge --abort 2>/dev/null; git checkout "$DEFAULT_BRANCH" 2>/dev/null; git branch -D "$BRANCH_NAME" 2>/dev/null) || true
                echo "fail|$FEAT_REPO|$FEAT_TITLE|merge_conflict" > "$FEAT_TMPDIR/$feat_idx.result"
              fi
            else
              (cd "$FEAT_PATH" && git checkout "$DEFAULT_BRANCH" >/dev/null 2>&1) || true
              log "  BUILD OK: $FEAT_REPO — on branch $BRANCH_NAME (auto-merge disabled)"
              echo "ok-branch|$FEAT_REPO|$FEAT_TITLE|$BRANCH_NAME" > "$FEAT_TMPDIR/$feat_idx.result"
            fi
          else
            (cd "$FEAT_PATH" && git checkout "$DEFAULT_BRANCH" 2>/dev/null; git branch -D "$BRANCH_NAME" 2>/dev/null) || true
            echo "rollback|$FEAT_REPO|$FEAT_TITLE|tests_or_agent_failed" > "$FEAT_TMPDIR/$feat_idx.result"
          fi
        done
      ) &
    done
    wait

    # Aggregate feature results from temp files
    for feat_idx in $(seq 0 $((FEAT_COUNT - 1))); do
      if [ -f "$FEAT_TMPDIR/$feat_idx.result" ]; then
        IFS='|' read -r _bstatus _brepo _btitle _breason < "$FEAT_TMPDIR/$feat_idx.result"
        case "$_bstatus" in
          ok-merged)
            FEATURES_OK=$((FEATURES_OK + 1))
            MODIFIED_REPOS="$MODIFIED_REPOS $_brepo"
            CHANGED_REPOS_JSON=$(CHANGED_REPOS_JSON="$CHANGED_REPOS_JSON" REPO="$_brepo" python3 -c "
import json, os
items = json.loads(os.environ['CHANGED_REPOS_JSON'])
if os.environ['REPO'] not in items: items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
            ;;
          ok-branch)
            FEATURES_OK=$((FEATURES_OK + 1))
            ;;
          fail)
            FEATURES_FAIL=$((FEATURES_FAIL + 1))
            FAILED_ITEMS_JSON=$(FAILED_ITEMS_JSON="$FAILED_ITEMS_JSON" REPO="$_brepo" TITLE="$_btitle" TYPE="feature" python3 -c "
import json, os
items = json.loads(os.environ['FAILED_ITEMS_JSON'])
items.append({'repo': os.environ['REPO'], 'title': os.environ['TITLE'], 'type': os.environ['TYPE'], 'reason': '$_breason'})
print(json.dumps(items))
") || true
            ;;
          rollback)
            FEATURES_FAIL=$((FEATURES_FAIL + 1))
            ROLLBACKS=$((ROLLBACKS + 1))
            ROLLBACK_REPOS_JSON=$(ROLLBACK_REPOS_JSON="$ROLLBACK_REPOS_JSON" REPO="$_brepo" python3 -c "
import json, os
items = json.loads(os.environ['ROLLBACK_REPOS_JSON'])
items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
            FAILED_ITEMS_JSON=$(FAILED_ITEMS_JSON="$FAILED_ITEMS_JSON" REPO="$_brepo" TITLE="$_btitle" TYPE="feature" python3 -c "
import json, os
items = json.loads(os.environ['FAILED_ITEMS_JSON'])
items.append({'repo': os.environ['REPO'], 'title': os.environ['TITLE'], 'type': os.environ['TYPE'], 'reason': '$_breason'})
print(json.dumps(items))
") || true
            ;;
          skip)
            SKIPPED_ITEMS="$SKIPPED_ITEMS $_brepo:$_breason"
            ;;
        esac
      fi
    done
    rm -rf "$FEAT_TMPDIR"
    unset FEAT_REPO_GROUPS

    # ── Phase 6: VERIFY ──────────────────────────────────────────────────

    check_stop "BUILD"
    log_phase "PHASE 6: VERIFY"

    while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd lang; do
      [ -z "$name" ] && continue
      # Only verify repos that were modified in this cycle
      echo "$MODIFIED_REPOS" | grep -qw "$name" || continue

      log "  Verifying $name..."
      if [ -n "$test_cmd" ] && ! run_tests "$path" "$test_cmd"; then
        log "  $name: FAIL — rolling back to $TAG_NAME"
        (cd "$path" && git reset --hard "$TAG_NAME") >/dev/null 2>&1 || true
        ROLLBACKS=$((ROLLBACKS + 1))
        MODIFIED_REPOS=$(echo "$MODIFIED_REPOS" | sed "s/\b$name\b//g")
        ROLLBACK_REPOS_JSON=$(ROLLBACK_REPOS_JSON="$ROLLBACK_REPOS_JSON" REPO="$name" python3 -c "
import json, os
items = json.loads(os.environ['ROLLBACK_REPOS_JSON'])
items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
        ledger rollback "$name" false "rollback:verify_tests_failed" "{}"
      else
        log "  $name: PASS"
      fi
    done < <(get_valid_targets)

    # ── Phase 7: DEPLOY ──────────────────────────────────────────────────

    check_stop "VERIFY"
    log_phase "PHASE 7: DEPLOY"

    while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd lang; do
      [ -z "$name" ] && continue
      # Only deploy repos that were modified and survived verification
      echo "$MODIFIED_REPOS" | grep -qw "$name" || continue

      # Check deploy policy
      DEPLOY_MODE=$(get_policy "$name" "deploy_mode" "disabled")
      ALLOW_DEPLOY=$(get_policy "$name" "allow_auto_deploy" "false")

      if [ "$DEPLOY_MODE" = "disabled" ] || [ "$ALLOW_DEPLOY" != "true" ]; then
        log "  $name: deploy skipped (deploy_mode=$DEPLOY_MODE, allow_auto_deploy=$ALLOW_DEPLOY)"
        ledger deploy "$name" false "block:deploy_mode=$DEPLOY_MODE,allow_auto_deploy=$ALLOW_DEPLOY" "{}"
        continue
      fi

      if [ -z "$deploy_cmd" ]; then
        log "  $name: no deploy command configured, skipping"
        ledger deploy "$name" false "block:no_deploy_command" "{}"
        continue
      fi

      # Validate deploy command (no shell metacharacters beyond safe set)
      if [[ "$deploy_cmd" =~ [^a-zA-Z0-9\ _/.\-\&\|\;] ]]; then
        log "  $name: deploy command contains unsafe characters, skipping"
        ledger deploy "$name" false "block:unsafe_deploy_command" "{}"
        continue
      fi

      log "  Deploying $name..."
      if (cd "$path" && eval "$deploy_cmd") >/dev/null 2>&1; then
        log "  $name: DEPLOY OK"
        DEPLOYS_OK=$((DEPLOYS_OK + 1))
        DEPLOYED_REPOS_JSON=$(DEPLOYED_REPOS_JSON="$DEPLOYED_REPOS_JSON" REPO="$name" python3 -c "
import json, os
items = json.loads(os.environ['DEPLOYED_REPOS_JSON'])
items.append(os.environ['REPO'])
print(json.dumps(items))
") || true
        ledger deploy "$name" true "policy:deploy_mode=$DEPLOY_MODE" "{}"
      else
        log "  $name: DEPLOY FAILED (code is committed but not deployed)"
        DEPLOYS_FAIL=$((DEPLOYS_FAIL + 1))
        ledger deploy "$name" false "fail:deploy_command_exit_nonzero" "{}"
      fi
    done < <(get_valid_targets)

  fi  # end of non-dry-run + valid plan block

  # ── Phase 8: REPORT ────────────────────────────────────────────────────

  check_stop "DEPLOY"
  log_phase "PHASE 8: REPORT"

  # Refresh dashboards
  log "  Refreshing dashboard data..."
  (cd "$ROOT_DIR" && python3 -m backoffice refresh) >/dev/null 2>&1 || true
  (cd "$ROOT_DIR" && python3 -m backoffice sync) >/dev/null 2>&1 || \
    log "  WARN: Dashboard sync failed"

  CYCLE_END=$(date -Iseconds)

  # Build cycle JSON via Python for safe serialization
  CYCLE_JSON=$(CYCLE_ID="$CYCLE_ID" CYCLE_START="$CYCLE_START" CYCLE_END="$CYCLE_END" \
    FIXES_OK="$FIXES_OK" FIXES_FAIL="$FIXES_FAIL" \
    FEATURES_OK="$FEATURES_OK" FEATURES_FAIL="$FEATURES_FAIL" \
    DEPLOYS_OK="$DEPLOYS_OK" DEPLOYS_FAIL="$DEPLOYS_FAIL" \
    ROLLBACKS="$ROLLBACKS" DRY_RUN="$DRY_RUN" \
    FAILED_ITEMS_JSON="$FAILED_ITEMS_JSON" \
    CHANGED_REPOS_JSON="$CHANGED_REPOS_JSON" \
    DEPLOYED_REPOS_JSON="$DEPLOYED_REPOS_JSON" \
    ROLLBACK_REPOS_JSON="$ROLLBACK_REPOS_JSON" \
    SKIPPED_ITEMS="$SKIPPED_ITEMS" python3 - <<'PYEOF'
import json, os

cycle = {
    "cycle_id": os.environ["CYCLE_ID"],
    "started_at": os.environ["CYCLE_START"],
    "finished_at": os.environ["CYCLE_END"],
    "dry_run": os.environ["DRY_RUN"] == "true",
    "fixes_attempted": int(os.environ["FIXES_OK"]) + int(os.environ["FIXES_FAIL"]),
    "fixes_succeeded": int(os.environ["FIXES_OK"]),
    "fixes_failed": int(os.environ["FIXES_FAIL"]),
    "features_attempted": int(os.environ["FEATURES_OK"]) + int(os.environ["FEATURES_FAIL"]),
    "features_succeeded": int(os.environ["FEATURES_OK"]),
    "features_failed": int(os.environ["FEATURES_FAIL"]),
    "deploys_succeeded": int(os.environ["DEPLOYS_OK"]),
    "deploys_failed": int(os.environ["DEPLOYS_FAIL"]),
    "repos_rolled_back": int(os.environ["ROLLBACKS"]),
    "failed_items": json.loads(os.environ.get("FAILED_ITEMS_JSON", "[]")),
    "changed_repos": json.loads(os.environ.get("CHANGED_REPOS_JSON", "[]")),
    "deployed_repos": json.loads(os.environ.get("DEPLOYED_REPOS_JSON", "[]")),
    "rollback_repos": json.loads(os.environ.get("ROLLBACK_REPOS_JSON", "[]")),
    "skipped_items": [s for s in os.environ.get("SKIPPED_ITEMS", "").split() if s],
}
print(json.dumps(cycle))
PYEOF
  ) || CYCLE_JSON="{\"cycle_id\":\"$CYCLE_ID\",\"error\":\"serialization_failed\"}"

  # Append to history
  append_history "$CYCLE_JSON"

  # Write cycle summary artifact
  write_summary "$CYCLE_JSON"

  log "  Cycle summary written to: $SUMMARY_FILE"
  log_phase "CYCLE END: $FIXES_OK fixes, $FEATURES_OK features, $DEPLOYS_OK deploys ($ROLLBACKS rollbacks)"

  # ── Phase 9: SLEEP ─────────────────────────────────────────────────────

  check_stop "REPORT"

  log "Starting next cycle immediately. Stop with: touch $STOP_FILE"
  log ""
done
