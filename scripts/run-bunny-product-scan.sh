#!/usr/bin/env bash

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATUS_SCRIPT="$ROOT_DIR/scripts/update-scan-status.py"
LOG_FILE="$ROOT_DIR/results/bunny-product-scan.log"
STATE_FILE="$ROOT_DIR/results/bunny-product-scan.state"

TARGETS=(
  "codyjo.com"
  "thenewbeautifulme"
  "fuel"
  "selah"
  "cordivent"
  "certstudy"
  "pattern"
  "auth-service"
)

TARGETS_CSV="$(IFS=,; echo "${TARGETS[*]}")"
FAILED_TARGETS=()
STATUS_LOOP_PID=""

log() {
  local ts
  ts="$(date -Iseconds)"
  printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG_FILE"
}

refresh_status() {
  python3 "$STATUS_SCRIPT" --targets "$TARGETS_CSV" >/dev/null 2>&1 || true
}

start_status_loop() {
  (
    while [[ -f "$STATE_FILE" ]] && [[ "$(cat "$STATE_FILE" 2>/dev/null)" == "running" ]]; do
      refresh_status
      sleep 30
    done
  ) &
  STATUS_LOOP_PID="$!"
}

stop_status_loop() {
  if [[ -n "$STATUS_LOOP_PID" ]] && kill -0 "$STATUS_LOOP_PID" 2>/dev/null; then
    kill "$STATUS_LOOP_PID" 2>/dev/null || true
    wait "$STATUS_LOOP_PID" 2>/dev/null || true
  fi
}

run_audit() {
  local target="$1"
  shift

  log "START audit target=$target departments=${*:-default}"
  if python3 -m backoffice audit "$target" "$@"; then
    log "DONE audit target=$target"
  else
    local exit_code=$?
    FAILED_TARGETS+=("$target:$exit_code")
    log "FAIL audit target=$target exit_code=$exit_code"
  fi
  refresh_status
}

mkdir -p "$ROOT_DIR/results"
: >"$LOG_FILE"
printf 'running\n' >"$STATE_FILE"
trap stop_status_loop EXIT

cd "$ROOT_DIR" || exit 1

log "Bunny product scan runner started"
log "Targets: $TARGETS_CSV"
refresh_status
start_status_loop

# Resume Selah from the departments that did not finish before the interactive run was stopped.
run_audit "selah" --departments "ada,compliance,monetization,product,cloud-ops"

run_audit "codyjo.com"
run_audit "thenewbeautifulme"
run_audit "fuel"
run_audit "cordivent"
run_audit "certstudy"
run_audit "pattern"
run_audit "auth-service"

log "START refresh"
if python3 -m backoffice refresh; then
  log "DONE refresh"
else
  refresh_exit=$?
  FAILED_TARGETS+=("refresh:$refresh_exit")
  log "FAIL refresh exit_code=$refresh_exit"
fi

refresh_status

if [[ -n "${BACK_OFFICE_ENABLE_REMOTE_SYNC:-}" ]]; then
  log "START sync"
  if python3 -m backoffice sync; then
    log "DONE sync"
  else
    sync_exit=$?
    FAILED_TARGETS+=("sync:$sync_exit")
    log "FAIL sync exit_code=$sync_exit"
  fi
else
  log "SKIP sync because BACK_OFFICE_ENABLE_REMOTE_SYNC is not enabled"
fi

refresh_status

if ((${#FAILED_TARGETS[@]} > 0)); then
  printf 'completed-with-failures\n' >"$STATE_FILE"
  log "Completed with failures: ${FAILED_TARGETS[*]}"
  exit 1
fi

printf 'completed\n' >"$STATE_FILE"
log "Bunny product scan runner completed successfully"
