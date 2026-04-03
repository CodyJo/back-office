#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <repo-path> <github-owner/repo> [ref]" >&2
  exit 1
fi

REPO_PATH="$1"
GITHUB_REPO="$2"
REF="${3:-}"
REMOTE_NAME="${REMOTE_NAME:-github-public}"

if [[ ! -d "$REPO_PATH/.git" ]]; then
  echo "Not a git repository: $REPO_PATH" >&2
  exit 1
fi

GITHUB_URL="git@github.com:${GITHUB_REPO}.git"
if git -C "$REPO_PATH" remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git -C "$REPO_PATH" remote set-url "$REMOTE_NAME" "$GITHUB_URL"
else
  git -C "$REPO_PATH" remote add "$REMOTE_NAME" "$GITHUB_URL"
fi

if [[ -z "$REF" ]]; then
  REF="$(git -C "$REPO_PATH" rev-parse --abbrev-ref HEAD)"
fi

git -C "$REPO_PATH" push "$REMOTE_NAME" "$REF"
echo "Mirrored ${REPO_PATH} ${REF} -> ${GITHUB_REPO}"
