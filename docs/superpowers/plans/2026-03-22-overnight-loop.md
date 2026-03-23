# Overnight Autonomous Loop Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous overnight loop that audits all repos, has an AI Product Owner prioritize work, fixes bugs, implements small/medium features, tests, deploys to production, and repeats every 2 hours.

**Architecture:** Shell script orchestrator (`overnight.sh`) drives a 9-phase cycle: snapshot → audit → decide → fix → build → verify → deploy → report → sleep. Two new Claude agents (Product Owner, Feature Dev) are added alongside existing audit/fix agents. Git tags provide rollback points.

**Tech Stack:** Bash (orchestrator), Claude CLI `--print` (agents), Python (backoffice CLI), JSON (data exchange), Git tags (rollback).

**Spec:** `docs/superpowers/specs/2026-03-22-overnight-loop-design.md`

---

## Chunk 1: Agent Prompts and Launchers

### Task 1: Product Owner Agent Prompt

**Files:**
- Create: `agents/prompts/product-owner.md`

- [ ] **Step 1: Write the Product Owner system prompt**

```markdown
# Product Owner Agent

You are the Back Office Product Owner. Your job is to review audit findings,
backlog data, and score trends, then output a prioritized work plan for
the overnight loop.

## Input

You will receive:
1. **Backlog summary** — top findings by severity × audit_count
2. **Score snapshot** — all repos × all departments with current scores
3. **Product findings** — feature recommendations from product audits
4. **Previous cycle results** — what was attempted last cycle (successes and failures)

## Decision Framework

Prioritize in this order:
1. Critical/high severity fixes where `fixable_by_agent` is true — always first
2. Chronic issues — findings with `audit_count >= 3` that keep reappearing
3. Low-hanging features — easy/moderate effort items from product roadmap
4. Score improvement — target repos with the lowest department scores

**Never attempt:**
- Hard effort items
- Items where `fixable_by_agent` is false
- Items that failed in the last 2 cycles (check previous cycle results)
- Repos with no test suite

**Limits per cycle:** Maximum 5 fixes + 2 features.

## Output Format

Return ONLY valid JSON matching this schema:

```json
{
  "cycle_id": "overnight-YYYYMMDD-HHMMSS",
  "decided_at": "ISO-8601 timestamp",
  "rationale": "1-2 sentence summary of priorities this cycle",
  "fixes": [
    {
      "repo": "repo-name",
      "finding_hash": "16-char hex hash",
      "title": "Finding title",
      "department": "department name",
      "severity": "critical|high|medium",
      "effort": "easy|moderate",
      "audit_count": 4,
      "reason": "Why this was prioritized"
    }
  ],
  "features": [
    {
      "repo": "repo-name",
      "title": "Feature title",
      "department": "department source",
      "effort": "easy|moderate",
      "description": "What to implement",
      "acceptance_criteria": ["criterion 1", "criterion 2"]
    }
  ],
  "skip": [
    {"repo": "repo-name", "reason": "Why skipped"}
  ]
}
```

Do not include any text before or after the JSON.
Do not wrap the JSON in markdown code fences.
```

- [ ] **Step 2: Commit**

```bash
git add agents/prompts/product-owner.md
git commit -m "feat(overnight): add Product Owner agent prompt"
```

---

### Task 2: Product Owner Launcher

**Files:**
- Create: `agents/product-owner.sh`

- [ ] **Step 1: Write the launcher script**

Follow the pattern from `agents/product-audit.sh`. The script:
1. Reads backlog.json, score-history.json, product-data.json, overnight-history.json
2. Builds a prompt with the data injected
3. Calls `run-agent.sh`
4. Validates the output is valid JSON
5. Writes to `results/overnight-plan.json`

```bash
#!/usr/bin/env bash
# Back Office — Product Owner Agent
# Usage: ./agents/product-owner.sh
#
# Reads audit data and backlog, then outputs a prioritized work plan
# for the overnight loop.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$SCRIPT_DIR/prompts/product-owner.md"
DASHBOARD_DIR="$QA_ROOT/dashboard"
RESULTS_DIR="$QA_ROOT/results"
PLAN_FILE="$RESULTS_DIR/overnight-plan.json"

# ── Load data summaries ──────────────────────────────────────────────────────

BACKLOG_SUMMARY=""
if [ -f "$DASHBOARD_DIR/backlog.json" ]; then
  BACKLOG_SUMMARY=$(python3 -c "
import json, sys
data = json.load(open('$DASHBOARD_DIR/backlog.json'))
findings = sorted(data.get('findings', {}).values(),
                  key=lambda f: (
                    {'critical':0,'high':1,'medium':2,'low':3,'info':4}.get(f.get('severity','medium'), 5),
                    -f.get('audit_count', 1)
                  ))[:30]
for f in findings:
    print(f'{f.get(\"severity\",\"?\"):>8} | audit_count={f.get(\"audit_count\",1):>2} | fixable={f.get(\"fixable_by_agent\",False)} | {f.get(\"repo\",\"?\")} | {f.get(\"department\",\"?\")} | {f.get(\"title\",\"?\")[:80]}')
" 2>/dev/null || echo "(no backlog data)")
fi

SCORE_SNAPSHOT=""
if [ -f "$DASHBOARD_DIR/score-history.json" ]; then
  SCORE_SNAPSHOT=$(python3 -c "
import json
data = json.load(open('$DASHBOARD_DIR/score-history.json'))
if data.get('snapshots'):
    latest = data['snapshots'][-1]['scores']
    for repo, depts in sorted(latest.items()):
        scores = ' | '.join(f'{d}={s}' for d, s in sorted(depts.items()))
        print(f'  {repo}: {scores}')
" 2>/dev/null || echo "(no score data)")
fi

PRODUCT_SUMMARY=""
if [ -f "$DASHBOARD_DIR/product-data.json" ]; then
  PRODUCT_SUMMARY=$(python3 -c "
import json
data = json.load(open('$DASHBOARD_DIR/product-data.json'))
for repo in data.get('repos', []):
    findings = [f for f in repo.get('findings', [])
                if f.get('effort') in ('easy', 'moderate', 'small', 'tiny', 'medium')
                and f.get('fixable_by_agent', f.get('fixable', False))][:5]
    if findings:
        print(f'  {repo[\"name\"]}:')
        for f in findings:
            print(f'    - [{f.get(\"effort\",\"?\")}] {f.get(\"title\",\"?\")[:80]}')
" 2>/dev/null || echo "(no product data)")
fi

PREV_CYCLE=""
if [ -f "$RESULTS_DIR/overnight-history.json" ]; then
  PREV_CYCLE=$(python3 -c "
import json
data = json.load(open('$RESULTS_DIR/overnight-history.json'))
cycles = data.get('cycles', [])
if cycles:
    c = cycles[-1]
    print(f'Last cycle: {c.get(\"cycle_id\", \"?\")}')
    print(f'  Fixes: {c.get(\"fixes_succeeded\",0)} ok, {c.get(\"fixes_failed\",0)} failed')
    print(f'  Features: {c.get(\"features_succeeded\",0)} ok, {c.get(\"features_failed\",0)} failed')
    for item in c.get('failed_items', []):
        print(f'  FAILED: {item}')
" 2>/dev/null || echo "(first cycle)")
fi

# ── Build prompt ─────────────────────────────────────────────────────────────

PROMPT="$(cat "$PROMPT_FILE")

---

## Current Data

### Backlog (top 30 by severity × recurrence)
$BACKLOG_SUMMARY

### Score Snapshot
$SCORE_SNAPSHOT

### Product Roadmap Items (easy/moderate, AI-fixable)
$PRODUCT_SUMMARY

### Previous Cycle Results
$PREV_CYCLE

---

Generate the work plan now. Return only valid JSON."

# ── Launch agent ─────────────────────────────────────────────────────────────

echo "Launching Product Owner agent..."
AGENT_OUTPUT=$(bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$PROMPT" \
  --tools "Read,Glob,Grep,Bash" \
  --repo "$QA_ROOT" 2>&1) || true

# ── Extract and validate JSON ────────────────────────────────────────────────

# Try to extract JSON from output (agent may include extra text)
PLAN_JSON=$(echo "$AGENT_OUTPUT" | python3 -c "
import sys, json
text = sys.stdin.read()
# Try to find JSON object in the output
start = text.find('{')
if start == -1:
    print('{}', end='')
    sys.exit(0)
depth = 0
for i, c in enumerate(text[start:], start):
    if c == '{': depth += 1
    elif c == '}': depth -= 1
    if depth == 0:
        try:
            obj = json.loads(text[start:i+1])
            print(json.dumps(obj, indent=2), end='')
            sys.exit(0)
        except json.JSONDecodeError:
            pass
print('{}', end='')
" 2>/dev/null || echo '{}')

mkdir -p "$RESULTS_DIR"
echo "$PLAN_JSON" > "$PLAN_FILE"

# Validate
FIXES=$(echo "$PLAN_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('fixes',[])))" 2>/dev/null || echo 0)
FEATURES=$(echo "$PLAN_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('features',[])))" 2>/dev/null || echo 0)

echo ""
echo "Product Owner decided: $FIXES fixes, $FEATURES features"
echo "Plan written to: $PLAN_FILE"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x agents/product-owner.sh
```

- [ ] **Step 3: Test the launcher**

```bash
bash agents/product-owner.sh
cat results/overnight-plan.json | python3 -m json.tool | head -20
```

Expected: Valid JSON with fixes and/or features arrays.

- [ ] **Step 4: Commit**

```bash
git add agents/product-owner.sh
git commit -m "feat(overnight): add Product Owner agent launcher"
```

---

### Task 3: Feature Development Agent

**Files:**
- Create: `agents/prompts/feature-dev.md`
- Create: `agents/feature-dev.sh`

- [ ] **Step 1: Write the Feature Dev system prompt**

`agents/prompts/feature-dev.md`:

```markdown
# Feature Development Agent

You are the Back Office feature development agent. Your job is to implement
a specific feature in a target repository, following TDD practices.

## Process

1. **Read the feature spec** — understand what needs to be built
2. **Read the repo** — understand the codebase structure, existing patterns, CLAUDE.md
3. **Write tests first** — create tests that define the expected behavior
4. **Run tests** — verify they fail (TDD red phase)
5. **Implement** — write the minimal code to make tests pass
6. **Run tests** — verify they pass (TDD green phase)
7. **Run linter** — ensure code quality
8. **Commit** — commit with a descriptive message

## Constraints

- Work ONLY on the feature described — no unrelated refactoring
- Follow existing code patterns and conventions
- Do NOT modify CI/CD config, infrastructure, or deploy scripts
- Do NOT add new dependencies without a passing test
- Do NOT skip or bypass pre-commit hooks
- All commits must have descriptive messages referencing the feature

## Output

When done, write a summary to the results directory:
- What was implemented
- Tests added/modified
- Files changed
- Any concerns or limitations

## Commit Message Format

```
feat(<scope>): <description>

Overnight loop: <feature title>
```
```

- [ ] **Step 2: Write the Feature Dev launcher**

`agents/feature-dev.sh`:

```bash
#!/usr/bin/env bash
# Back Office — Feature Development Agent
# Usage: ./agents/feature-dev.sh /path/to/target-repo '{"title":"...","description":"...","acceptance_criteria":[...]}'
#
# Implements a feature in the target repo using TDD.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$SCRIPT_DIR/prompts/feature-dev.md"

TARGET_REPO="${1:?Usage: feature-dev.sh /path/to/target-repo '{feature_json}'}"
FEATURE_JSON="${2:?Usage: feature-dev.sh /path/to/target-repo '{feature_json}'}"

# Validate target
if [ ! -d "$TARGET_REPO/.git" ]; then
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
fi

REPO_NAME="$(basename "$TARGET_REPO")"

# ── Read config ──────────────────────────────────────────────────────────────

LINT_CMD=""
TEST_CMD=""
CONTEXT=""

if command -v python3 &>/dev/null && [ -f "$QA_ROOT/config/targets.yaml" ]; then
  mapfile -d '' -t _cfg < <(
    python3 "$QA_ROOT/scripts/parse-config.py" \
      "$QA_ROOT/config/targets.yaml" "$REPO_NAME" "$TARGET_REPO" \
      lint_command test_command context 2>/dev/null || true
  )
  LINT_CMD="${_cfg[0]:-}"
  TEST_CMD="${_cfg[1]:-}"
  CONTEXT="${_cfg[2]:-}"
fi

# ── Build prompt ─────────────────────────────────────────────────────────────

FEATURE_TITLE=$(echo "$FEATURE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('title','Feature'))" 2>/dev/null || echo "Feature")

PROMPT="$(cat "$PROMPT_FILE")

---

## Feature to Implement

$FEATURE_JSON

## Target Repository

- **Path:** $TARGET_REPO
- **Name:** $REPO_NAME

## Commands

- **Lint:** ${LINT_CMD:-"(auto-detect from project config)"}
- **Test:** ${TEST_CMD:-"(auto-detect from project config)"}

## Additional Context

${CONTEXT:-"Read the project's README and CLAUDE.md for context."}

## Instructions

1. cd to $TARGET_REPO
2. Read the project structure and understand the codebase
3. Implement the feature following TDD
4. Run linter and tests
5. Commit your changes with a clear message

Start now."

# ── Launch agent ─────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Feature Dev — $REPO_NAME: $FEATURE_TITLE"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

bash "$QA_ROOT/scripts/run-agent.sh" \
  --prompt "$PROMPT" \
  --tools "Read,Glob,Grep,Bash,Write,Edit,Agent" \
  --repo "$TARGET_REPO"

echo ""
echo "Feature development complete."
```

- [ ] **Step 3: Make executable and commit**

```bash
chmod +x agents/feature-dev.sh
git add agents/prompts/feature-dev.md agents/feature-dev.sh
git commit -m "feat(overnight): add Feature Development agent prompt and launcher"
```

---

## Chunk 2: Overnight Loop Orchestrator

### Task 4: Main Loop Script

**Files:**
- Create: `scripts/overnight.sh`

- [ ] **Step 1: Write the overnight loop orchestrator**

This is the main script. It implements all 9 phases from the spec.

```bash
#!/usr/bin/env bash
# Back Office — Overnight Autonomous Loop
# Usage: ./scripts/overnight.sh [--interval 120] [--dry-run] [--targets "a,b"]
#
# Runs a continuous cycle: audit → decide → fix → build → verify → deploy → report
# Designed to run overnight in tmux or via nohup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$ROOT_DIR/results"
DASHBOARD_DIR="$ROOT_DIR/dashboard"
HISTORY_FILE="$RESULTS_DIR/overnight-history.json"
STOP_FILE="$RESULTS_DIR/.overnight-stop"

# ── Args ─────────────────────────────────────────────────────────────────────

INTERVAL=120
DRY_RUN=false
TARGET_FILTER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --interval)  INTERVAL="${2:?--interval requires a value}"; shift 2 ;;
    --dry-run)   DRY_RUN=true; shift ;;
    --targets)   TARGET_FILTER="${2:?--targets requires a value}"; shift 2 ;;
    *)           echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
log_phase() { log "══════ $* ══════"; }

get_valid_targets() {
  python3 -c "
import yaml
targets = yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets', [])
filter_list = '$TARGET_FILTER'.split(',') if '$TARGET_FILTER' else []
for t in targets:
    import os
    if not os.path.isdir(t['path']): continue
    if not os.path.isdir(os.path.join(t['path'], '.git')): continue
    if filter_list and t['name'] not in filter_list: continue
    print(t['name'] + '|' + t['path'] + '|' + t.get('test_command', '') + '|' + t.get('deploy_command', '') + '|' + t.get('coverage_command', ''))
" 2>/dev/null
}

run_tests() {
  local repo_path="$1" test_cmd="$2"
  if [ -z "$test_cmd" ]; then return 0; fi
  (cd "$repo_path" && eval "$test_cmd") >/dev/null 2>&1
}

get_coverage_pct() {
  local repo_path="$1" cov_cmd="$2"
  if [ -z "$cov_cmd" ]; then echo "0"; return; fi
  local output
  output=$( (cd "$repo_path" && eval "$cov_cmd") 2>&1 ) || true
  echo "$output" | python3 -c "
import sys, re
text = sys.stdin.read()
# Look for coverage percentage patterns
for pattern in [r'(\d+)%\s+total', r'TOTAL\s+\d+\s+\d+\s+(\d+)%', r'Statements\s*:\s*(\d+(?:\.\d+)?)%', r'All files\s*\|\s*(\d+(?:\.\d+)?)']:
    m = re.search(pattern, text)
    if m:
        print(m.group(1))
        sys.exit(0)
print('0')
" 2>/dev/null || echo "0"
}

append_history() {
  local cycle_json="$1"
  python3 -c "
import json, os
path = '$HISTORY_FILE'
if os.path.exists(path):
    try: data = json.load(open(path))
    except: data = {'cycles': []}
else:
    data = {'cycles': []}
data['cycles'].append(json.loads('''$cycle_json'''))
data['cycles'] = data['cycles'][-50:]
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
" 2>/dev/null || true
}

# ── Main Loop ────────────────────────────────────────────────────────────────

log "╔══════════════════════════════════════════════════════════╗"
log "║  Back Office — Overnight Autonomous Loop                ║"
log "║  Interval: ${INTERVAL}m | Dry run: $DRY_RUN             "
log "╚══════════════════════════════════════════════════════════╝"
log ""
log "Stop gracefully: touch $STOP_FILE"
log ""

rm -f "$STOP_FILE"

while true; do
  # Check for stop signal
  if [ -f "$STOP_FILE" ]; then
    log "Stop signal detected. Exiting."
    rm -f "$STOP_FILE"
    exit 0
  fi

  CYCLE_ID="overnight-$(date +%Y%m%d-%H%M%S)"
  CYCLE_START=$(date -Iseconds)
  FIXES_OK=0; FIXES_FAIL=0
  FEATURES_OK=0; FEATURES_FAIL=0
  DEPLOYS_OK=0; DEPLOYS_FAIL=0
  ROLLBACKS=0
  SCORE_CHANGES="{}"
  FAILED_ITEMS="[]"

  log_phase "CYCLE START: $CYCLE_ID"

  # ── Phase 1: SNAPSHOT ────────────────────────────────────────────────────

  log_phase "PHASE 1: SNAPSHOT"
  TAG_NAME="overnight-before-$(date +%Y%m%d-%H%M%S)"
  MODIFIED_REPOS=""

  while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd; do
    (cd "$path" && git tag "$TAG_NAME" HEAD 2>/dev/null) && \
      log "Tagged $name: $TAG_NAME" || \
      log "WARN: Could not tag $name"

    # Prune old overnight tags (older than 7 days)
    (cd "$path" && git tag | grep '^overnight-before-' | while read -r tag; do
      tag_date=$(echo "$tag" | sed 's/overnight-before-//' | cut -c1-8)
      cutoff=$(date -d '7 days ago' +%Y%m%d 2>/dev/null || date -v-7d +%Y%m%d 2>/dev/null || echo "00000000")
      if [ "$tag_date" \< "$cutoff" ]; then
        git tag -d "$tag" >/dev/null 2>&1 || true
      fi
    done) 2>/dev/null || true
  done < <(get_valid_targets)

  # ── Stop check helper ─────────────────────────────────────────────────
  check_stop() {
    if [ -f "$STOP_FILE" ]; then
      log "Stop signal detected after $1. Exiting gracefully."
      rm -f "$STOP_FILE"
      exit 0
    fi
  }

  # ── Phase 2: AUDIT ──────────────────────────────────────────────────────

  check_stop "SNAPSHOT"
  log_phase "PHASE 2: AUDIT"
  while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd; do
    log "Auditing $name..."
    (make -C "$ROOT_DIR" audit-all-parallel TARGET="$path" >/dev/null 2>&1) && \
      log "  $name: audit complete" || \
      log "  $name: audit had errors (continuing)"
  done < <(get_valid_targets)

  log "Refreshing dashboard data..."
  (cd "$ROOT_DIR" && python3 -m backoffice refresh) >/dev/null 2>&1 || \
    log "WARN: Dashboard refresh had errors"

  # ── Phase 3: DECIDE ─────────────────────────────────────────────────────

  check_stop "AUDIT"
  log_phase "PHASE 3: DECIDE (Product Owner)"
  bash "$ROOT_DIR/agents/product-owner.sh" 2>&1 | while read -r line; do log "  PO: $line"; done || true

  PLAN_FILE="$RESULTS_DIR/overnight-plan.json"
  if [ ! -f "$PLAN_FILE" ]; then
    log "No plan generated. Skipping fix/build phases."
  else
    NUM_FIXES=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('fixes',[])))" 2>/dev/null || echo 0)
    NUM_FEATURES=$(python3 -c "import json; print(len(json.load(open('$PLAN_FILE')).get('features',[])))" 2>/dev/null || echo 0)
    log "Plan: $NUM_FIXES fixes, $NUM_FEATURES features"

    if [ "$DRY_RUN" = true ]; then
      log "DRY RUN — skipping fix/build/deploy phases"
    else

      # ── Phase 4: FIX ──────────────────────────────────────────────────

      check_stop "DECIDE"
      log_phase "PHASE 4: FIX"
      python3 -c "
import json
plan = json.load(open('$PLAN_FILE'))
for i, fix in enumerate(plan.get('fixes', [])):
    print(f'{fix.get(\"repo\",\"?\")}\t{fix.get(\"title\",\"?\")}\t{fix.get(\"department\",\"?\")}\t{fix.get(\"severity\",\"?\")}')
" 2>/dev/null | while IFS=$'\t' read -r fix_repo fix_title fix_dept fix_sev; do
        # Find repo path
        FIX_PATH=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$fix_repo': print(t['path']); break
" 2>/dev/null || echo "")

        if [ -z "$FIX_PATH" ] || [ ! -d "$FIX_PATH" ]; then
          log "  SKIP: $fix_repo — path not found"
          FIXES_FAIL=$((FIXES_FAIL + 1))
          continue
        fi

        log "  FIX: $fix_repo — $fix_title"

        # Get pre-fix coverage
        FIX_TEST_CMD=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$fix_repo': print(t.get('test_command','')); break
" 2>/dev/null || echo "")
        FIX_COV_CMD=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$fix_repo': print(t.get('coverage_command','')); break
" 2>/dev/null || echo "")

        PRE_COV=$(get_coverage_pct "$FIX_PATH" "$FIX_COV_CMD")

        # Run fix agent
        (bash "$ROOT_DIR/agents/fix-bugs.sh" "$FIX_PATH") >/dev/null 2>&1 && FIX_EXIT=0 || FIX_EXIT=$?

        if [ "$FIX_EXIT" -ne 0 ]; then
          log "  FIX FAILED: $fix_repo — agent error"
          FIXES_FAIL=$((FIXES_FAIL + 1))
          continue
        fi

        # Verify tests still pass
        if run_tests "$FIX_PATH" "$FIX_TEST_CMD"; then
          POST_COV=$(get_coverage_pct "$FIX_PATH" "$FIX_COV_CMD")
          if [ "$POST_COV" -lt "$PRE_COV" ] 2>/dev/null; then
            log "  FIX ROLLED BACK: $fix_repo — coverage decreased ($PRE_COV% → $POST_COV%)"
            (cd "$FIX_PATH" && git reset --hard "$TAG_NAME") >/dev/null 2>&1
            FIXES_FAIL=$((FIXES_FAIL + 1))
            ROLLBACKS=$((ROLLBACKS + 1))
          else
            log "  FIX OK: $fix_repo — tests pass, coverage $PRE_COV% → $POST_COV%"
            FIXES_OK=$((FIXES_OK + 1))
            MODIFIED_REPOS="$MODIFIED_REPOS $fix_repo"
          fi
        else
          log "  FIX ROLLED BACK: $fix_repo — tests failed"
          (cd "$FIX_PATH" && git reset --hard "$TAG_NAME") >/dev/null 2>&1
          FIXES_FAIL=$((FIXES_FAIL + 1))
          ROLLBACKS=$((ROLLBACKS + 1))
        fi
      done

      # ── Phase 5: BUILD ─────────────────────────────────────────────────

      check_stop "FIX"
      log_phase "PHASE 5: BUILD (Features)"
      python3 -c "
import json
plan = json.load(open('$PLAN_FILE'))
for feat in plan.get('features', []):
    print(json.dumps(feat))
" 2>/dev/null | while read -r feat_json; do
        FEAT_REPO=$(echo "$feat_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('repo',''))" 2>/dev/null)
        FEAT_TITLE=$(echo "$feat_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('title','Feature'))" 2>/dev/null)

        FEAT_PATH=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$FEAT_REPO': print(t['path']); break
" 2>/dev/null || echo "")

        if [ -z "$FEAT_PATH" ] || [ ! -d "$FEAT_PATH" ]; then
          log "  SKIP: $FEAT_REPO — path not found"
          FEATURES_FAIL=$((FEATURES_FAIL + 1))
          continue
        fi

        FEAT_TEST_CMD=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$FEAT_REPO': print(t.get('test_command','')); break
" 2>/dev/null || echo "")
        FEAT_COV_CMD=$(python3 -c "
import yaml
for t in yaml.safe_load(open('$ROOT_DIR/config/targets.yaml')).get('targets',[]):
    if t['name'] == '$FEAT_REPO': print(t.get('coverage_command','')); break
" 2>/dev/null || echo "")

        log "  BUILD: $FEAT_REPO — $FEAT_TITLE"

        PRE_COV=$(get_coverage_pct "$FEAT_PATH" "$FEAT_COV_CMD")
        BRANCH_NAME="overnight/$(date +%Y%m%d)-$(echo "$FEAT_TITLE" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | head -c 40)"

        # Create feature branch
        (cd "$FEAT_PATH" && git checkout -b "$BRANCH_NAME") >/dev/null 2>&1 || {
          log "  BUILD FAILED: $FEAT_REPO — could not create branch"
          FEATURES_FAIL=$((FEATURES_FAIL + 1))
          continue
        }

        # Run feature dev agent
        (bash "$ROOT_DIR/agents/feature-dev.sh" "$FEAT_PATH" "$feat_json") >/dev/null 2>&1 && FEAT_EXIT=0 || FEAT_EXIT=$?

        # Verify
        if [ "$FEAT_EXIT" -eq 0 ] && run_tests "$FEAT_PATH" "$FEAT_TEST_CMD"; then
          POST_COV=$(get_coverage_pct "$FEAT_PATH" "$FEAT_COV_CMD")
          if [ "$POST_COV" -lt "$PRE_COV" ] 2>/dev/null; then
            log "  BUILD ROLLED BACK: $FEAT_REPO — coverage decreased ($PRE_COV% → $POST_COV%)"
            (cd "$FEAT_PATH" && git checkout main 2>/dev/null || git checkout master && git branch -D "$BRANCH_NAME") >/dev/null 2>&1
            FEATURES_FAIL=$((FEATURES_FAIL + 1))
          else
            # Merge feature branch
            (cd "$FEAT_PATH" && git checkout main 2>/dev/null || git checkout master
             git merge "$BRANCH_NAME" --no-ff -m "feat: $FEAT_TITLE (overnight loop)"
             git branch -d "$BRANCH_NAME") >/dev/null 2>&1 && {
              log "  BUILD OK: $FEAT_REPO — merged to main, coverage $PRE_COV% → $POST_COV%"
              FEATURES_OK=$((FEATURES_OK + 1))
              MODIFIED_REPOS="$MODIFIED_REPOS $FEAT_REPO"
            } || {
              log "  BUILD FAILED: $FEAT_REPO — merge conflict"
              (cd "$FEAT_PATH" && git merge --abort 2>/dev/null; git checkout main 2>/dev/null || git checkout master; git branch -D "$BRANCH_NAME" 2>/dev/null) || true
              FEATURES_FAIL=$((FEATURES_FAIL + 1))
            }
          fi
        else
          log "  BUILD ROLLED BACK: $FEAT_REPO — tests failed or agent error"
          (cd "$FEAT_PATH" && git checkout main 2>/dev/null || git checkout master
           git branch -D "$BRANCH_NAME" 2>/dev/null) || true
          FEATURES_FAIL=$((FEATURES_FAIL + 1))
        fi
      done

      # ── Phase 6: VERIFY ────────────────────────────────────────────────

      check_stop "BUILD"
      log_phase "PHASE 6: VERIFY"
      while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd; do
        echo "$MODIFIED_REPOS" | grep -qw "$name" || continue
        log "  Verifying $name..."
        if run_tests "$path" "$test_cmd"; then
          log "  $name: PASS"
        else
          log "  $name: FAIL — rolling back to $TAG_NAME"
          (cd "$path" && git reset --hard "$TAG_NAME") >/dev/null 2>&1
          ROLLBACKS=$((ROLLBACKS + 1))
          # Remove from modified list
          MODIFIED_REPOS=$(echo "$MODIFIED_REPOS" | sed "s/ $name / /g")
        fi
      done < <(get_valid_targets)

      # ── Phase 7: DEPLOY ────────────────────────────────────────────────

      check_stop "VERIFY"
      log_phase "PHASE 7: DEPLOY"
      while IFS='|' read -r name path test_cmd deploy_cmd cov_cmd; do
        echo "$MODIFIED_REPOS" | grep -qw "$name" || continue
        if [ -z "$deploy_cmd" ]; then
          log "  $name: no deploy command, skipping"
          continue
        fi
        log "  Deploying $name..."
        if (cd "$path" && eval "$deploy_cmd") >/dev/null 2>&1; then
          log "  $name: DEPLOY OK"
          DEPLOYS_OK=$((DEPLOYS_OK + 1))
        else
          log "  $name: DEPLOY FAILED (code is committed but not deployed)"
          DEPLOYS_FAIL=$((DEPLOYS_FAIL + 1))
        fi
      done < <(get_valid_targets)

    fi  # end of non-dry-run block
  fi    # end of plan-exists block

  # ── Phase 8: REPORT ──────────────────────────────────────────────────

  log_phase "PHASE 8: REPORT"
  (cd "$ROOT_DIR" && python3 -m backoffice refresh) >/dev/null 2>&1 || true
  (cd "$ROOT_DIR" && python3 -m backoffice sync) >/dev/null 2>&1 || \
    log "WARN: Dashboard sync failed"

  CYCLE_END=$(date -Iseconds)
  CYCLE_JSON="{
    \"cycle_id\": \"$CYCLE_ID\",
    \"started_at\": \"$CYCLE_START\",
    \"finished_at\": \"$CYCLE_END\",
    \"fixes_attempted\": $((FIXES_OK + FIXES_FAIL)),
    \"fixes_succeeded\": $FIXES_OK,
    \"fixes_failed\": $FIXES_FAIL,
    \"features_attempted\": $((FEATURES_OK + FEATURES_FAIL)),
    \"features_succeeded\": $FEATURES_OK,
    \"features_failed\": $FEATURES_FAIL,
    \"deploys_succeeded\": $DEPLOYS_OK,
    \"deploys_failed\": $DEPLOYS_FAIL,
    \"repos_rolled_back\": $ROLLBACKS,
    \"dry_run\": $DRY_RUN
  }"
  append_history "$CYCLE_JSON"

  log_phase "CYCLE END: $FIXES_OK fixes, $FEATURES_OK features, $DEPLOYS_OK deploys ($ROLLBACKS rollbacks)"

  # ── Phase 9: SLEEP ─────────────────────────────────────────────────

  log "Next cycle in $INTERVAL minutes"
  log ""

  # Check stop signal before sleeping
  if [ -f "$STOP_FILE" ]; then
    log "Stop signal detected. Exiting."
    rm -f "$STOP_FILE"
    exit 0
  fi

  sleep "${INTERVAL}m"
done
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/overnight.sh
```

- [ ] **Step 3: Test with dry-run**

```bash
bash scripts/overnight.sh --dry-run --interval 1 --targets "back-office" 2>&1 | head -50
```

Expected: Runs through phases 1-3 (snapshot, audit, decide), then skips 4-7 (dry run), runs phase 8 (report), then sleeps.

Press Ctrl+C after seeing the sleep message.

- [ ] **Step 4: Commit**

```bash
git add scripts/overnight.sh
git commit -m "feat(overnight): add main loop orchestrator with 9-phase cycle"
```

---

## Chunk 3: Makefile Targets and Cleanup

### Task 5: Makefile Integration

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add overnight targets to Makefile**

Add after the `grafana-logs` target:

```makefile
# ── Overnight Loop ───────────────────────────────────────────────────────────

overnight: ## Start overnight autonomous loop (make overnight [INTERVAL=120] [TARGETS=a,b])
	@echo "Starting overnight loop... Stop with: touch results/.overnight-stop"
	bash scripts/overnight.sh \
		$(if $(INTERVAL),--interval "$(INTERVAL)",) \
		$(if $(TARGETS),--targets "$(TARGETS)",) \
		2>&1 | tee -a results/overnight.log

overnight-dry: ## Dry-run overnight loop (audit + decide only, no changes)
	bash scripts/overnight.sh --dry-run \
		$(if $(INTERVAL),--interval "$(INTERVAL)",) \
		$(if $(TARGETS),--targets "$(TARGETS)",) \
		2>&1 | tee -a results/overnight.log

overnight-stop: ## Stop the overnight loop gracefully
	@touch results/.overnight-stop
	@echo "Stop signal sent. Loop will exit after current phase."

overnight-status: ## Show overnight loop status and history
	@echo "=== Latest Plan ==="
	@cat results/overnight-plan.json 2>/dev/null | python3 -m json.tool | head -30 || echo "(no plan)"
	@echo ""
	@echo "=== Last 3 Cycles ==="
	@python3 -c "\
	import json; \
	h = json.load(open('results/overnight-history.json')); \
	for c in h['cycles'][-3:]: \
	    print(f'{c[\"cycle_id\"]}: {c[\"fixes_succeeded\"]} fixes, {c[\"features_succeeded\"]} features, {c[\"deploys_succeeded\"]} deploys')" 2>/dev/null || echo "(no history)"

overnight-rollback: ## Roll back all repos to last overnight snapshot (make overnight-rollback)
	@echo "Rolling back all repos to latest overnight snapshot..."
	@python3 -c "\
	import yaml, subprocess, os; \
	targets = yaml.safe_load(open('config/targets.yaml')).get('targets', []); \
	for t in targets: \
	    p = t['path']; \
	    if not os.path.isdir(p): continue; \
	    result = subprocess.run(['git', 'tag', '-l', 'overnight-before-*'], capture_output=True, text=True, cwd=p); \
	    tags = sorted(result.stdout.strip().split('\n')); \
	    if tags and tags[-1]: \
	        tag = tags[-1]; \
	        subprocess.run(['git', 'reset', '--hard', tag], cwd=p); \
	        print(f'  {t[\"name\"]}: rolled back to {tag}'); \
	    else: \
	        print(f'  {t[\"name\"]}: no snapshot tag found')"
```

- [ ] **Step 2: Add .phony declarations**

Update the existing `.PHONY` line at the top of the Makefile to include the new targets:

```makefile
.PHONY: overnight overnight-dry overnight-stop overnight-status overnight-rollback
```

- [ ] **Step 3: Test make targets**

```bash
make help | grep overnight
```

Expected: All 5 overnight targets listed.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat(overnight): add Makefile targets for overnight loop management"
```

---

### Task 6: Gitignore and Final Verification

**Files:**
- Modify: `results/.gitignore` (create if needed)

- [ ] **Step 1: Add overnight files to gitignore**

```bash
echo "overnight.log" >> results/.gitignore
echo "overnight-plan.json" >> results/.gitignore
echo "overnight-history.json" >> results/.gitignore
echo ".overnight-stop" >> results/.gitignore
```

- [ ] **Step 2: Full dry-run test**

```bash
make overnight-dry INTERVAL=1 TARGETS=back-office 2>&1 | head -60
```

Let it run through one full cycle, then Ctrl+C. Verify:
- Phase 1 (SNAPSHOT): tags created
- Phase 2 (AUDIT): audits run
- Phase 3 (DECIDE): Product Owner outputs a plan
- Phases 4-7: skipped (dry run)
- Phase 8 (REPORT): dashboard refreshed

- [ ] **Step 3: Verify status command**

```bash
make overnight-status
```

Expected: Shows the plan and cycle history.

- [ ] **Step 4: Verify rollback command**

```bash
make overnight-rollback
```

Expected: Shows rollback for each repo (or "no snapshot tag found" if tags were pruned).

- [ ] **Step 5: Commit**

```bash
git add results/.gitignore
git commit -m "chore(overnight): add gitignore for overnight loop artifacts"
```

---

## Usage Summary

```bash
# Start overnight loop (in tmux)
tmux new-session -d -s overnight 'cd /home/merm/projects/back-office && make overnight'

# Monitor
tail -f results/overnight.log
make overnight-status

# Stop gracefully
make overnight-stop

# Morning review
make overnight-status
cat results/overnight.log | grep "CYCLE END"

# Rollback if needed
make overnight-rollback
```
