#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/merm/projects}"
FORGEJO_BASE_URL="${FORGEJO_BASE_URL:-http://localhost:3300}"
FORGEJO_TOKEN="${FORGEJO_TOKEN:?FORGEJO_TOKEN is required}"
FORGEJO_OWNER="${FORGEJO_OWNER:-CodyJo}"
FORGEJO_OWNER_KIND="${FORGEJO_OWNER_KIND:-user}"
FORGEJO_VISIBILITY="${FORGEJO_VISIBILITY:-private}"
FORGEJO_SSH_HOST="${FORGEJO_SSH_HOST:-localhost}"
FORGEJO_SSH_PORT="${FORGEJO_SSH_PORT:-2223}"
GITHUB_MIRROR_REMOTE="${GITHUB_MIRROR_REMOTE:-github-public}"
PUSH_TAGS="${PUSH_TAGS:-1}"

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
  local repo_name="$1"
  curl -fsS -o /dev/null \
    -H "Authorization: token ${FORGEJO_TOKEN}" \
    -H "Accept: application/json" \
    "${FORGEJO_BASE_URL%/}/api/v1/repos/${FORGEJO_OWNER}/${repo_name}"
}

create_repo() {
  local repo_name="$1"
  local payload
  payload="$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "private": sys.argv[2] == "private", "auto_init": False}))' "$repo_name" "$FORGEJO_VISIBILITY")"
  if [[ "$FORGEJO_OWNER_KIND" == "org" ]]; then
    api POST "/api/v1/orgs/${FORGEJO_OWNER}/repos" "$payload" >/dev/null
  else
    api POST "/api/v1/user/repos" "$payload" >/dev/null
  fi
}

forgejo_ssh_url() {
  local repo_name="$1"
  printf 'ssh://git@%s:%s/%s/%s.git' "$FORGEJO_SSH_HOST" "$FORGEJO_SSH_PORT" "$FORGEJO_OWNER" "$repo_name"
}

preserve_github_remote() {
  local repo_path="$1"
  local current_origin="$2"
  if [[ "$current_origin" == *github.com* ]]; then
    if git -C "$repo_path" remote get-url "$GITHUB_MIRROR_REMOTE" >/dev/null 2>&1; then
      git -C "$repo_path" remote set-url "$GITHUB_MIRROR_REMOTE" "$current_origin"
    else
      git -C "$repo_path" remote add "$GITHUB_MIRROR_REMOTE" "$current_origin"
    fi
  fi
}

backfill_repo() {
  local repo_path="$1"
  local repo_name
  repo_name="$(basename "$repo_path")"
  local target_url
  target_url="$(forgejo_ssh_url "$repo_name")"
  local current_origin=""

  if ! repo_exists "$repo_name"; then
    create_repo "$repo_name"
    echo "created repo ${repo_name}"
  fi

  if git -C "$repo_path" remote get-url origin >/dev/null 2>&1; then
    current_origin="$(git -C "$repo_path" remote get-url origin)"
    preserve_github_remote "$repo_path" "$current_origin"
    git -C "$repo_path" remote set-url origin "$target_url"
  else
    git -C "$repo_path" remote add origin "$target_url"
  fi

  echo "pushing branches ${repo_name}"
  GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' git -C "$repo_path" push --force --all origin

  if [[ "$PUSH_TAGS" == "1" ]]; then
    echo "pushing tags ${repo_name}"
    GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' git -C "$repo_path" push --force --tags origin
  fi
}

mapfile -t REPOS < <(find "$ROOT_DIR" -mindepth 1 -maxdepth 1 -type d -exec test -d '{}/.git' ';' -print | sort)

for repo_path in "${REPOS[@]}"; do
  echo "--- ${repo_path}"
  backfill_repo "$repo_path"
done

echo "Forgejo history backfill complete."
