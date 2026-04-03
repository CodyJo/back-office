#!/bin/bash
# Collects Claude Code session count, worktree count, and per-session uptime.
# Outputs JSON array. Exits 0 with zeros if nothing is running.
set -euo pipefail

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NOW_EPOCH=$(date +%s)

METRICS="["
FIRST=true

add_metric() {
    local metric="$1" labels="$2" value="$3"
    if [ "$FIRST" = true ]; then FIRST=false; else METRICS+=","; fi
    METRICS+=$(printf '\n  {"time":"%s","source":"claude","metric":"%s","labels":%s,"value":%s}' \
        "$NOW" "$metric" "$labels" "$value")
}

# Count claude processes and get per-session info
session_count=0
while IFS= read -r line; do
    [ -z "$line" ] && continue
    pid=$(echo "$line" | awk '{print $1}')
    start_epoch=$(echo "$line" | awk '{print $2}')
    uptime_sec=$((NOW_EPOCH - start_epoch))
    add_metric "claude_session_uptime_sec" "{\"session_id\":\"$pid\"}" "$uptime_sec"
    session_count=$((session_count + 1))
done < <(ps -eo pid,lstart --no-headers -C claude 2>/dev/null | while read -r pid rest; do
    # Convert lstart to epoch
    epoch=$(date -d "$rest" +%s 2>/dev/null || echo "$NOW_EPOCH")
    echo "$pid $epoch"
done)

add_metric "claude_active_sessions" "{}" "$session_count"

# Count active git worktrees across projects
worktree_count=0
PROJECTS_DIR="${PROJECTS_DIR:-/home/merm/projects}"
if [ -d "$PROJECTS_DIR" ]; then
    for repo in "$PROJECTS_DIR"/*/; do
        [ -d "${repo}.git" ] || continue
        wt=$(cd "$repo" && git worktree list 2>/dev/null | wc -l || echo 1)
        extra=$((wt - 1))
        worktree_count=$((worktree_count + extra))
    done
fi

add_metric "claude_worktrees_active" "{}" "$worktree_count"

METRICS+="\n]"
echo -e "$METRICS"
