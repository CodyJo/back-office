#!/usr/bin/env bash
set -euo pipefail

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

require_var FORGEJO_SSH_HOST

FORGEJO_OWNER="${FORGEJO_OWNER:-CodyJo}"
FORGEJO_SSH_PORT="${FORGEJO_SSH_PORT:-2222}"

declare -a PORTFOLIO_REPOS=(
  "auth-service|/home/merm/projects/auth-service"
  "certstudy|/home/merm/projects/certstudy"
  "codyjo.com|/home/merm/projects/codyjo.com"
  "cordivent|/home/merm/projects/cordivent"
  "fuel|/home/merm/projects/fuel"
  "pattern|/home/merm/projects/pattern"
  "selah|/home/merm/projects/selah"
  "thenewbeautifulme|/home/merm/projects/thenewbeautifulme"
  "analogify|/home/merm/projects/analogify"
  "continuum|/home/merm/projects/continuum"
  "back-office|/home/merm/projects/back-office"
  "pe-dashboards|/home/merm/projects/pe-dashboards"
  "pe-bootstrap|/home/merm/projects/pe-bootstrap"
)

for entry in "${PORTFOLIO_REPOS[@]}"; do
  name="${entry%%|*}"
  path="${entry#*|}"
  ssh_url="ssh://git@${FORGEJO_SSH_HOST}:${FORGEJO_SSH_PORT}/${FORGEJO_OWNER}/${name}.git"
  if [[ ! -d "$path/.git" ]]; then
    echo "skip     ${name} (not a git repo at ${path})"
    continue
  fi

  if git -C "$path" remote get-url origin >/dev/null 2>&1; then
    git -C "$path" remote set-url origin "$ssh_url"
  else
    git -C "$path" remote add origin "$ssh_url"
  fi
  echo "origin   ${name} -> ${ssh_url}"
done

echo "Forgejo remotes updated."
