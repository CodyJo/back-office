#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/merm/projects/back-office"
ENV_FILE="${ENV_FILE:-/home/merm/projects/back-office/ops/forgejo-local/back-office.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  echo "Copy /home/merm/projects/back-office/ops/forgejo-local/back-office.env.example to ${ENV_FILE} and fill in the token." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

: "${FORGEJO_BASE_URL:?FORGEJO_BASE_URL is required}"
: "${FORGEJO_TOKEN:?FORGEJO_TOKEN is required}"

cd "${ROOT_DIR}"

exec python3 -m backoffice serve --port "${BACK_OFFICE_PORT:-8070}"
