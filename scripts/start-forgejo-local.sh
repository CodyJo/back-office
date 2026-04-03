#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/merm/projects/back-office/ops/forgejo-local"
TRIES="${TRIES:-30}"
SLEEP_SECONDS="${SLEEP_SECONDS:-2}"

cd "${ROOT_DIR}"

for ((i=1; i<=TRIES; i+=1)); do
  if /usr/bin/docker info >/dev/null 2>&1; then
    exec /usr/bin/docker compose up -d
  fi
  sleep "${SLEEP_SECONDS}"
done

echo "docker daemon did not become ready in time" >&2
exit 1
