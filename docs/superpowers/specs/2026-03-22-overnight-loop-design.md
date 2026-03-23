# Overnight Autonomous Loop — Design Spec

**Date:** 2026-03-22
**Status:** Draft
**Scope:** An autonomous overnight development loop that audits, prioritizes, fixes bugs, implements features, tests, and deploys across all Back Office targets.

---

## Problem

Running audits and fixes manually is time-consuming. The user wants the system to work autonomously overnight: audit all repos, have an AI Product Owner decide what to fix and build, execute those changes safely, test, deploy to production, and repeat.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Loop mechanism | Shell script with sleep | Simple, debuggable, runs in tmux/nohup |
| Product Owner | Claude agent via `--print` | Reads backlog + findings, outputs JSON work plan |
| Rollback | Git tags before each cycle | `git reset --hard overnight-before-TAG` to undo |
| Deploy gate | Tests pass + coverage not decreased | Safe to ship if quality is maintained |
| Feature scope | Small + medium, AI-fixable only | `fixable_by_agent: true` or effort in [easy, moderate] |
| Cycle interval | 2 hours | Enough time for full audit + fix + feature + deploy |

---

## 1. Architecture

### Entry Point

```bash
bash scripts/overnight.sh [--interval 120] [--dry-run] [--targets "codyjo.com,analogify"]
```

Options:
- `--interval N` — minutes between cycles (default: 120)
- `--dry-run` — audit and decide only, no fixes/features/deploys
- `--targets "a,b"` — comma-separated subset of targets (default: all valid targets from targets.yaml)

Run in tmux or nohup:
```bash
tmux new-session -d -s overnight 'bash scripts/overnight.sh 2>&1 | tee -a results/overnight.log'
```

### File Layout

```
scripts/
  overnight.sh              — Main loop orchestrator
agents/
  prompts/product-owner.md  — Product Owner agent prompt
  product-owner.sh          — Product Owner agent launcher
  feature-dev.sh            — Feature development agent launcher
  prompts/feature-dev.md    — Feature development agent prompt
results/
  overnight.log             — Append-only log of all cycles
  overnight-plan.json       — Latest Product Owner work plan
  overnight-history.json    — History of all cycles (last 50)
```

---

## 2. Cycle Phases

### Phase 1: SNAPSHOT

Before touching any repo, create a rollback point:

```bash
for each target repo:
    cd $repo
    git tag "overnight-before-$(date +%Y%m%d-%H%M%S)" HEAD
```

Tags are lightweight and don't affect the working tree. They provide an instant rollback target.

### Phase 2: AUDIT

Run all 6 department audits on all targets in parallel:

```bash
for each target:
    make audit-all-parallel TARGET=$target &
done
wait
python3 -m backoffice refresh  # aggregate + backlog merge + score history
```

This reuses the existing audit infrastructure. After completion, `backlog.json`, all `-data.json` files, and `score-history.json` are up to date.

### Phase 3: DECIDE (Product Owner Agent)

Launch the Product Owner agent:

```bash
bash agents/product-owner.sh
```

The agent receives:
- `backlog.json` — all findings with recurrence counts
- `product-data.json` — product roadmap findings
- `score-history.json` — score trends
- Previous cycle's `overnight-history.json` — what was already attempted
- Each target's test/deploy commands from `targets.yaml`

The agent outputs `results/overnight-plan.json`:

```json
{
  "cycle_id": "overnight-20260322-230000",
  "decided_at": "2026-03-22T23:00:30Z",
  "rationale": "Focus on portis-app SEO (score: 1) and analogify monetization (score: 48)",
  "fixes": [
    {
      "repo": "portis-app",
      "finding_hash": "a1b2c3d4e5f6g7h8",
      "title": "No meta description or OG tags",
      "department": "seo",
      "severity": "critical",
      "effort": "easy",
      "audit_count": 4,
      "reason": "Critical SEO issue, seen in 4 audits, easy fix"
    }
  ],
  "features": [
    {
      "repo": "portis-app",
      "title": "Add comprehensive meta tags and OG social cards",
      "department": "seo",
      "effort": "moderate",
      "description": "Add meta descriptions, OG tags, Twitter cards, and structured data to all pages",
      "acceptance_criteria": [
        "Every page has a unique meta description",
        "OG image, title, description on all pages",
        "Twitter card meta tags present",
        "SEO score improves by at least 20 points"
      ]
    }
  ],
  "skip": [
    {"repo": "pe-bootstrap", "reason": "Terraform project, no actionable AI-fixable items"}
  ]
}
```

### Decision Criteria

The Product Owner prioritizes by:

1. **Critical/high severity fixes** with `fixable_by_agent: true` — always first
2. **Chronic issues** — findings with `audit_count >= 3` (keep appearing, never fixed)
3. **Low-hanging fruit** — easy/moderate effort features from the product roadmap
4. **Score improvement potential** — target repos with the lowest scores first
5. **Never attempt**: hard effort items, non-AI-fixable items, items attempted and failed in previous cycles

Maximum per cycle: **5 fixes + 2 features** (to keep cycles under 2 hours).

### Phase 4: FIX

For each fix in the work plan:

```bash
for each fix:
    # Record pre-fix state
    cd $repo
    pre_coverage=$(get_coverage)

    # Run the existing fix agent (uses git worktrees for isolation)
    bash agents/fix-bugs.sh $repo_path

    # Verify
    run_tests $repo
    post_coverage=$(get_coverage)

    if tests_fail OR coverage_decreased:
        git reset --hard  # discard the fix
        log "FIX FAILED: $finding_id — tests failed or coverage decreased"
    else:
        log "FIX OK: $finding_id — tests pass, coverage $pre → $post"
    fi
done
```

This reuses the existing `fix-bugs.sh` which already handles worktree isolation, linting, and test verification.

### Phase 5: BUILD (Feature Development)

For each feature in the work plan:

```bash
for each feature:
    cd $repo
    pre_coverage=$(get_coverage)

    # Create a feature branch
    git checkout -b "overnight/$(date +%Y%m%d)-${feature_title_slug}"

    # Launch feature dev agent
    bash agents/feature-dev.sh $repo_path "$feature_json"

    # Verify
    run_tests $repo
    post_coverage=$(get_coverage)

    if tests_fail OR coverage_decreased:
        git checkout main
        git branch -D "overnight/..."
        log "FEATURE FAILED: $title — tests failed or coverage decreased"
    else:
        git checkout main
        git merge "overnight/..." --no-ff -m "feat: $title (overnight loop)"
        log "FEATURE OK: $title — merged to main"
    fi
done
```

The feature dev agent receives:
- The feature description and acceptance criteria from the work plan
- The repo's CLAUDE.md for context
- The repo's test/lint commands
- Instructions to follow TDD: write test first, then implement

### Phase 6: VERIFY

Run full test suite on every repo that was modified:

```bash
for each modified repo:
    cd $repo
    run lint_command
    run test_command
    run coverage_command (if available)

    if any_fail:
        # Rollback this repo to the snapshot tag
        git reset --hard overnight-before-$TIMESTAMP
        log "VERIFY FAILED: $repo — rolled back to snapshot"
    fi
done
```

### Phase 7: DEPLOY

For each repo that passed verification:

```bash
for each verified repo:
    cd $repo
    run deploy_command

    if deploy_fails:
        log "DEPLOY FAILED: $repo — code is committed but not deployed"
    else:
        log "DEPLOY OK: $repo"
    fi
done
```

Deploy commands come from `targets.yaml` (e.g., `npm run build` for Next.js apps, `bash scripts/deploy.sh` for Python apps).

### Phase 8: REPORT

```bash
# Refresh dashboards with post-fix/feature data
python3 -m backoffice refresh

# Sync to S3
python3 -m backoffice sync

# Append to overnight history
python3 -c "append_cycle_to_history()"

# Log summary
echo "Cycle complete: X fixes applied, Y features built, Z deploys"
```

The overnight history (`results/overnight-history.json`) tracks:
```json
{
  "cycles": [
    {
      "cycle_id": "overnight-20260322-230000",
      "started_at": "2026-03-22T23:00:00Z",
      "finished_at": "2026-03-23T00:45:00Z",
      "fixes_attempted": 3,
      "fixes_succeeded": 2,
      "fixes_failed": 1,
      "features_attempted": 1,
      "features_succeeded": 1,
      "features_failed": 0,
      "deploys_succeeded": 3,
      "deploys_failed": 0,
      "repos_rolled_back": 0,
      "score_changes": {
        "portis-app": {"seo": {"before": 1, "after": 65}},
        "analogify": {"qa": {"before": 76, "after": 82}}
      }
    }
  ]
}
```

### Phase 9: SLEEP

```bash
echo "Next cycle in $INTERVAL minutes"
sleep ${INTERVAL}m
```

---

## 3. Product Owner Agent

### Prompt Structure

The Product Owner agent is a Claude `--print` call that receives structured data and returns a JSON work plan.

**Input** (injected into prompt):
1. Current backlog summary (top 30 findings by severity × audit_count)
2. Score snapshot (all repos × all departments)
3. Product findings summary (top 20 by priority)
4. Previous cycle results (what was attempted, what succeeded/failed)
5. Constraints: max 5 fixes + 2 features per cycle, only AI-fixable, only easy/moderate effort

**Output**: The `overnight-plan.json` described in Phase 3.

**Decision rules encoded in the prompt:**
- Never re-attempt something that failed in the last 2 cycles
- Prioritize critical severity over everything
- Prioritize repos with the worst scores
- Prefer findings with high audit_count (chronic issues)
- Features must have clear acceptance criteria
- Skip repos with no test suite (cannot verify changes)

### Prompt File

`agents/prompts/product-owner.md` — contains the full system prompt with decision framework, input format, output schema, and examples.

### Launcher

`agents/product-owner.sh` — loads data, formats prompt, calls `run-agent.sh`, validates output JSON.

---

## 4. Feature Development Agent

### Prompt Structure

Receives:
- Feature description + acceptance criteria from work plan
- Repo path and CLAUDE.md context
- Lint/test/coverage commands
- Instruction to follow TDD (write test, verify fail, implement, verify pass)

### Safety Constraints

- Works on a feature branch (never commits directly to main)
- Must run tests before reporting success
- Cannot modify CI/CD config, infrastructure, or deploy scripts
- Cannot add new dependencies without a passing test
- Limited to files relevant to the feature (no sweeping refactors)

### Prompt File

`agents/prompts/feature-dev.md`

### Launcher

`agents/feature-dev.sh $repo_path "$feature_json"` — creates feature branch, launches agent, reports status.

---

## 5. Rollback Mechanism

### Automatic (per-repo)

During Phase 6 (VERIFY), if tests fail for a repo:
```bash
git reset --hard overnight-before-$TIMESTAMP
```
This instantly restores the repo to its pre-cycle state. No manual intervention.

### Manual (morning review)

If the user wakes up and doesn't like what happened:
```bash
# See what tags exist
git tag | grep overnight-before

# Roll back to before last night
cd /home/merm/projects/analogify
git reset --hard overnight-before-20260322-230000

# Or roll back all repos at once
for repo in analogify portis-app codyjo.com thenewbeautifulme; do
    cd /home/merm/projects/$repo
    git reset --hard $(git tag | grep overnight-before | sort | tail -1)
done
```

### Cleanup

Old overnight tags are pruned after 7 days:
```bash
# In the SNAPSHOT phase, clean tags older than 7 days
git tag | grep overnight-before | while read tag; do
    tag_date=$(echo $tag | sed 's/overnight-before-//')
    if older_than_7_days $tag_date; then
        git tag -d $tag
    fi
done
```

---

## 6. Safety Gates Summary

| Gate | When | Action on Failure |
|------|------|-------------------|
| Git tag snapshot | Before any changes | N/A — creates the safety net |
| Worktree isolation | During fixes | Discard worktree, main untouched |
| Test suite | After each fix/feature | Discard change, log failure |
| Coverage check | After each fix/feature | Discard change if coverage decreases |
| Lint check | After each fix/feature | Discard change if lint fails |
| Deploy gate | Before deploy | Skip deploy, code stays committed but undeployed |
| Cycle history | After each cycle | Never re-attempt recent failures |
| Tag pruning | Start of each cycle | Remove tags older than 7 days |

---

## 7. Logging

All output appends to `results/overnight.log`:

```
[2026-03-22 23:00:00] ══════ CYCLE START: overnight-20260322-230000 ══════
[2026-03-22 23:00:01] SNAPSHOT: Tagged 5 repos
[2026-03-22 23:00:02] AUDIT: Starting 5 targets × 6 departments
[2026-03-22 23:35:00] AUDIT: Complete — 631 findings, 555 in backlog
[2026-03-22 23:35:05] DECIDE: Product Owner reviewing...
[2026-03-22 23:35:30] DECIDE: Plan — 3 fixes, 1 feature
[2026-03-22 23:35:31] FIX [1/3]: portis-app SEO-001 "No meta description"
[2026-03-22 23:38:00] FIX [1/3]: OK — tests pass, coverage 82% → 82%
[2026-03-22 23:38:01] FIX [2/3]: analogify ADA-005 "Missing form labels"
[2026-03-22 23:41:00] FIX [2/3]: OK — tests pass, coverage 78% → 79%
[2026-03-22 23:41:01] FIX [3/3]: codyjo.com QA-012 "Unused imports"
[2026-03-22 23:42:30] FIX [3/3]: FAILED — test regression, discarded
[2026-03-22 23:42:31] BUILD [1/1]: portis-app "Add OG social cards"
[2026-03-22 23:55:00] BUILD [1/1]: OK — tests pass, merged to main
[2026-03-22 23:55:01] VERIFY: 3 repos modified, all pass
[2026-03-22 23:55:30] DEPLOY: portis-app OK, analogify OK, codyjo.com SKIPPED (rolled back)
[2026-03-22 23:56:00] REPORT: Dashboards refreshed, synced to S3
[2026-03-22 23:56:01] ══════ CYCLE END: 2 fixes, 1 feature, 2 deploys ══════
[2026-03-22 23:56:02] Next cycle in 120 minutes
```

---

## 8. Implementation Files

### Files to Create

| File | Purpose |
|------|---------|
| `scripts/overnight.sh` | Main loop orchestrator (~200 lines) |
| `agents/product-owner.sh` | Product Owner agent launcher |
| `agents/prompts/product-owner.md` | Product Owner system prompt |
| `agents/feature-dev.sh` | Feature development agent launcher |
| `agents/prompts/feature-dev.md` | Feature dev system prompt |

### Files to Modify

| File | Change |
|------|--------|
| `Makefile` | Add `overnight` and `overnight-stop` targets |
| `results/.gitignore` | Add `overnight.log`, `overnight-plan.json`, `overnight-history.json` |

### No Changes to Existing Files

The loop reuses existing infrastructure:
- `agents/qa-scan.sh`, `seo-audit.sh`, etc. — unchanged
- `agents/fix-bugs.sh` — unchanged
- `scripts/run-agent.sh` — unchanged
- `backoffice refresh` / `backoffice sync` — unchanged

---

## 9. Usage

### Start

```bash
# In tmux (recommended)
tmux new-session -d -s overnight 'cd /home/merm/projects/back-office && make overnight'

# Or with nohup
nohup make overnight > /dev/null 2>&1 &
```

### Monitor

```bash
# Watch the log
tail -f results/overnight.log

# Check latest plan
cat results/overnight-plan.json | python3 -m json.tool

# Check history
python3 -c "import json; h=json.load(open('results/overnight-history.json')); c=h['cycles'][-1]; print(f'Last: {c[\"fixes_succeeded\"]} fixes, {c[\"features_succeeded\"]} features')"
```

### Stop

```bash
# Graceful (finishes current phase, then exits)
touch results/.overnight-stop

# Or kill the tmux session
tmux kill-session -t overnight
```

### Morning Review

```bash
# What happened overnight?
cat results/overnight.log | grep "CYCLE END"

# Score changes
python3 -c "
import json
h = json.load(open('results/overnight-history.json'))
for c in h['cycles']:
    for repo, depts in c.get('score_changes', {}).items():
        for dept, scores in depts.items():
            delta = scores['after'] - scores['before']
            if delta != 0:
                print(f'{repo}/{dept}: {scores[\"before\"]} → {scores[\"after\"]} ({delta:+d})')
"

# Rollback if needed
cd /home/merm/projects/analogify
git log --oneline -5  # see what was committed
git reset --hard overnight-before-20260322-230000  # undo if needed
```
