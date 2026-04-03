#!/usr/bin/env bash
set -euo pipefail

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

require_var FORGEJO_BASE_URL
require_var FORGEJO_TOKEN

FORGEJO_OWNER="${FORGEJO_OWNER:-CodyJo}"
FORGEJO_OWNER_KIND="${FORGEJO_OWNER_KIND:-user}"
FORGEJO_VISIBILITY="${FORGEJO_VISIBILITY:-private}"
FORGEJO_SET_ORIGIN="${FORGEJO_SET_ORIGIN:-0}"

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

api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -fsS \
      -X "$method" \
      -H "Authorization: token ${FORGEJO_TOKEN}" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      "${FORGEJO_BASE_URL%/}${path}" \
      -d "$data"
  else
    curl -fsS \
      -X "$method" \
      -H "Authorization: token ${FORGEJO_TOKEN}" \
      -H "Accept: application/json" \
      "${FORGEJO_BASE_URL%/}${path}"
  fi
}

repo_exists() {
  local name="$1"
  curl -fsS -o /dev/null \
    -H "Authorization: token ${FORGEJO_TOKEN}" \
    -H "Accept: application/json" \
    "${FORGEJO_BASE_URL%/}/api/v1/repos/${FORGEJO_OWNER}/${name}"
}

create_repo() {
  local name="$1"
  local payload
  payload="$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "private": sys.argv[2] == "private", "auto_init": False}))' "$name" "$FORGEJO_VISIBILITY")"
  if [[ "$FORGEJO_OWNER_KIND" == "org" ]]; then
    api POST "/api/v1/orgs/${FORGEJO_OWNER}/repos" "$payload" >/dev/null
  else
    api POST "/api/v1/user/repos" "$payload" >/dev/null
  fi
}

fetch_ssh_url() {
  local name="$1"
  api GET "/api/v1/repos/${FORGEJO_OWNER}/${name}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ssh_url",""))'
}

set_origin_remote() {
  local path="$1"
  local ssh_url="$2"
  if [[ ! -d "$path/.git" ]]; then
    echo "Skipping remote update for $path; not a git repo" >&2
    return
  fi
  if git -C "$path" remote get-url origin >/dev/null 2>&1; then
    git -C "$path" remote set-url origin "$ssh_url"
  else
    git -C "$path" remote add origin "$ssh_url"
  fi
}

echo "Bootstrapping Forgejo repos for ${FORGEJO_OWNER} (${FORGEJO_OWNER_KIND})"

for entry in "${PORTFOLIO_REPOS[@]}"; do
  name="${entry%%|*}"
  path="${entry#*|}"
  if repo_exists "$name"; then
    echo "exists   ${name}"
  else
    create_repo "$name"
    echo "created  ${name}"
  fi

  if [[ "$FORGEJO_SET_ORIGIN" == "1" ]]; then
    ssh_url="$(fetch_ssh_url "$name")"
    if [[ -n "$ssh_url" ]]; then
      set_origin_remote "$path" "$ssh_url"
      echo "remote   ${name} -> ${ssh_url}"
    fi
  fi
done

echo "Forgejo repo bootstrap complete."
