#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/merm/projects}"
OUTPUT_DIR="${OUTPUT_DIR:-/home/merm/projects/back-office/results/github-actions-history}"
DEFAULT_OWNER="${DEFAULT_OWNER:-CodyJo}"
MAX_RUNS_PER_REPO="${MAX_RUNS_PER_REPO:-200}"

command -v gh >/dev/null 2>&1 || {
  echo "gh CLI is required." >&2
  exit 1
}

mkdir -p "${OUTPUT_DIR}"

repo_slug_from_remote() {
  local remote_url="$1"
  python3 - "$remote_url" <<'PY'
import re
import sys

remote = sys.argv[1].strip()
patterns = [
    r'github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$',
]
for pattern in patterns:
    match = re.search(pattern, remote)
    if match:
        print(f"{match.group('owner')}/{match.group('repo')}")
        raise SystemExit(0)
raise SystemExit(1)
PY
}

github_slug_for_repo() {
  local repo_path="$1"
  local remote_name
  for remote_name in github-public origin upstream; do
    if git -C "$repo_path" remote get-url "$remote_name" >/dev/null 2>&1; then
      local remote_url
      remote_url="$(git -C "$repo_path" remote get-url "$remote_name")"
      if [[ "$remote_url" == *github.com* ]]; then
        repo_slug_from_remote "$remote_url"
        return 0
      fi
    fi
  done
  printf '%s/%s\n' "$DEFAULT_OWNER" "$(basename "$repo_path")"
}

archive_repo() {
  local repo_path="$1"
  local repo_name
  repo_name="$(basename "$repo_path")"
  local repo_slug
  repo_slug="$(github_slug_for_repo "$repo_path")"
  local repo_dir="${OUTPUT_DIR}/${repo_name}"
  mkdir -p "$repo_dir"

  echo "archiving ${repo_slug}"

  gh api "repos/${repo_slug}" > "${repo_dir}/repo.json"
  gh api --paginate "repos/${repo_slug}/actions/workflows?per_page=100" > "${repo_dir}/workflows.json"
  gh api --paginate "repos/${repo_slug}/actions/runs?per_page=100" > "${repo_dir}/runs.raw.jsonl"

  python3 - "${repo_dir}/runs.raw.jsonl" "${repo_dir}/runs.json" "${MAX_RUNS_PER_REPO}" <<'PY'
import json
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
max_runs = int(sys.argv[3])
runs = []
total_count = None
decoder = json.JSONDecoder()
payloads = []
raw_text = raw_path.read_text()
index = 0

while index < len(raw_text):
    while index < len(raw_text) and raw_text[index].isspace():
        index += 1
    if index >= len(raw_text):
        break
    payload, next_index = decoder.raw_decode(raw_text, index)
    payloads.append(payload)
    index = next_index

for payload in payloads:
    if total_count is None:
        total_count = payload.get("total_count")
    runs.extend(payload.get("workflow_runs", []))

runs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
summary = {
    "total_count": total_count if total_count is not None else len(runs),
    "archived_count": min(len(runs), max_runs),
    "workflow_runs": runs[:max_runs],
}
out_path.write_text(json.dumps(summary, indent=2) + "\n")
raw_path.unlink(missing_ok=True)
PY

  gh api "repos/${repo_slug}/actions/runners" > "${repo_dir}/runners.json" || true
}

mapfile -t REPOS < <(find "${ROOT_DIR}" -mindepth 1 -maxdepth 1 -type d -exec test -d '{}/.git' ';' -print | sort)

for repo_path in "${REPOS[@]}"; do
  archive_repo "${repo_path}"
done

python3 - "${OUTPUT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
summary = []
for repo_dir in sorted(p for p in root.iterdir() if p.is_dir()):
    repo_payload = json.loads((repo_dir / "repo.json").read_text())
    runs_payload = json.loads((repo_dir / "runs.json").read_text())
    workflows_payload = json.loads((repo_dir / "workflows.json").read_text())
    summary.append({
        "repo": repo_payload["full_name"],
        "archived_runs": runs_payload["archived_count"],
        "total_runs": runs_payload["total_count"],
        "workflow_count": len(workflows_payload.get("workflows", [])),
        "html_url": repo_payload["html_url"],
    })

(root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
PY

echo "GitHub Actions history archive complete: ${OUTPUT_DIR}"
