#!/usr/bin/env bash
# Job status tracking library for Back Office agents
#
# Usage as library (source from agent scripts):
#   source "$QA_ROOT/scripts/job-status.sh"
#   job_start "seo"
#   claude --print ... && EXIT_CODE=0 || EXIT_CODE=$?
#   job_finish "seo" "$EXIT_CODE"
#
# Usage as CLI:
#   bash scripts/job-status.sh init /path/to/repo "qa seo ada compliance monetization product"
#   bash scripts/job-status.sh start seo
#   bash scripts/job-status.sh finish seo 0
#   bash scripts/job-status.sh finalize

_JOB_STATUS_DIR="${QA_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
_JOBS_FILE="$_JOB_STATUS_DIR/results/.jobs.json"
_JOBS_DASH_FILE="$_JOB_STATUS_DIR/dashboard/.jobs.json"
_JOBS_HISTORY_FILE="$_JOB_STATUS_DIR/results/.jobs-history.json"
_JOBS_DASH_HISTORY_FILE="$_JOB_STATUS_DIR/dashboard/.jobs-history.json"
_JOBS_LOCK="$_JOB_STATUS_DIR/results/.jobs.lock"

_write_jobs() {
  # Atomic write to both locations
  local tmp
  tmp=$(mktemp)
  cat > "$tmp"
  cp "$tmp" "$_JOBS_FILE"
  cp "$tmp" "$_JOBS_DASH_FILE"
  rm -f "$tmp"
}

_write_history() {
  # Atomic write history to both locations
  local tmp
  tmp=$(mktemp)
  cat > "$tmp"
  cp "$tmp" "$_JOBS_HISTORY_FILE"
  cp "$tmp" "$_JOBS_DASH_HISTORY_FILE"
  rm -f "$tmp"
}

job_init() {
  local target_repo="$1"
  local departments="$2"
  local repo_name
  repo_name="$(basename "$target_repo")"

  mkdir -p "$(dirname "$_JOBS_FILE")" "$(dirname "$_JOBS_DASH_FILE")"

  python3 -c "
import json, sys
from datetime import datetime, timezone

depts = '$departments'.split()
jobs = {}
for d in depts:
    jobs[d] = {
        'status': 'queued',
        'started_at': None,
        'finished_at': None,
        'elapsed_seconds': None,
        'findings_count': None,
        'score': None,
        'exit_code': None,
        'error': None
    }

data = {
    'run_id': 'audit-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'),
    'target': '$target_repo',
    'repo_name': '$repo_name',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'finished_at': None,
    'status': 'running',
    'jobs': jobs
}
print(json.dumps(data, indent=2))
" | _write_jobs
}

job_start() {
  local dept="$1"
  mkdir -p "$(dirname "$_JOBS_FILE")" "$(dirname "$_JOBS_DASH_FILE")"

  (
    flock -w 5 200 2>/dev/null || true

    python3 -c "
import json, sys, os
from datetime import datetime, timezone

path = '$_JOBS_FILE'
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
else:
    # No init was called — create a minimal jobs file
    data = {
        'run_id': 'single-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'),
        'target': os.environ.get('TARGET_REPO', ''),
        'repo_name': os.environ.get('REPO_NAME', ''),
        'started_at': datetime.now(timezone.utc).isoformat(),
        'finished_at': None,
        'status': 'running',
        'jobs': {}
    }

data['status'] = 'running'
data['jobs'].setdefault('$dept', {})
data['jobs']['$dept'].update({
    'status': 'running',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'finished_at': None,
    'elapsed_seconds': None,
    'findings_count': None,
    'score': None,
    'exit_code': None,
    'error': None
})
print(json.dumps(data, indent=2))
" | _write_jobs

  ) 200>"$_JOBS_LOCK"
}

job_finish() {
  local dept="$1"
  local exit_code="${2:-0}"

  (
    flock -w 5 200 2>/dev/null || true

    python3 -c "
import json, os
from datetime import datetime, timezone

path = '$_JOBS_FILE'
if not os.path.exists(path):
    exit(0)

with open(path) as f:
    data = json.load(f)

dept = '$dept'
code = int('$exit_code')
now = datetime.now(timezone.utc).isoformat()

if dept not in data['jobs']:
    data['jobs'][dept] = {}

job = data['jobs'][dept]
job['status'] = 'complete' if code == 0 else 'error'
job['finished_at'] = now
job['exit_code'] = code
if code == 0:
    job['error'] = None

# Calculate elapsed
if job.get('started_at'):
    start = datetime.fromisoformat(job['started_at'])
    end = datetime.fromisoformat(now)
    job['elapsed_seconds'] = round((end - start).total_seconds())

# Read findings count and score from results, stamp accurate scanned_at
repo = data.get('repo_name', '')
results_dir = '$_JOB_STATUS_DIR' + '/results/' + repo
findings_map = {
    'qa': 'findings.json',
    'seo': 'seo-findings.json',
    'ada': 'ada-findings.json',
    'compliance': 'compliance-findings.json',
    'monetization': 'monetization-findings.json',
    'product': 'product-findings.json',
}
score_map = {
    'seo': 'seo_score',
    'ada': 'compliance_score',
    'compliance': 'compliance_score',
    'monetization': 'monetization_readiness_score',
    'product': 'product_readiness_score',
}

fname = findings_map.get(dept)
if fname and code == 0:
    fpath = os.path.join(results_dir, fname)
    try:
        with open(fpath) as ff:
            findings = json.load(ff)
        summary = findings.get('summary', {})
        job['findings_count'] = summary.get('total', summary.get('total_findings', len(findings.get('findings', []))))

        # Get department-specific score
        score_key = score_map.get(dept)
        if score_key and score_key in summary:
            job['score'] = summary[score_key]
        elif dept == 'qa':
            # QA uses severity-based calculation
            c = summary.get('critical', 0)
            h = summary.get('high', 0)
            m = summary.get('medium', 0)
            l = summary.get('low', 0)
            job['score'] = max(0, 100 - c*15 - h*8 - m*3 - l*1)

        # Stamp accurate scanned_at time into findings JSON
        findings['scanned_at'] = now
        if isinstance(findings.get('summary'), dict):
            findings['summary']['scanned_at'] = now
        with open(fpath, 'w') as ff:
            json.dump(findings, ff, indent=2)
            ff.write('\n')
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

if code != 0:
    job['error'] = 'Agent exited with code ' + str(code)

# Check if all jobs are done
all_done = all(
    j.get('status') in ('complete', 'error')
    for j in data['jobs'].values()
)
if all_done:
    data['status'] = 'complete'
    data['finished_at'] = now
    # Check if any errors
    if any(j.get('status') == 'error' for j in data['jobs'].values()):
        data['status'] = 'error'

    # Append completed run to history
    history_path = '$_JOBS_HISTORY_FILE'
    try:
        with open(history_path) as hf:
            history = json.load(hf)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    # Replace if same run_id exists, otherwise append
    history = [h for h in history if h.get('run_id') != data.get('run_id')]
    history.append(data)
    history = history[-50:]  # Keep last 50 runs
    with open(history_path, 'w') as hf:
        json.dump(history, hf, indent=2)
        hf.write('\n')

print(json.dumps(data, indent=2))
" | _write_jobs

    # Copy history to dashboard dir if it exists
    if [ -f "$_JOBS_HISTORY_FILE" ]; then
      cp "$_JOBS_HISTORY_FILE" "$_JOBS_DASH_HISTORY_FILE" 2>/dev/null || true
    fi

  ) 200>"$_JOBS_LOCK"
}

# CLI mode
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    init)
      QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
      _JOB_STATUS_DIR="$QA_ROOT"
      _JOBS_FILE="$QA_ROOT/results/.jobs.json"
      _JOBS_DASH_FILE="$QA_ROOT/dashboard/.jobs.json"
      _JOBS_HISTORY_FILE="$QA_ROOT/results/.jobs-history.json"
      _JOBS_DASH_HISTORY_FILE="$QA_ROOT/dashboard/.jobs-history.json"
      _JOBS_LOCK="$QA_ROOT/results/.jobs.lock"
      job_init "${2:?Usage: job-status.sh init /path/to/repo \"dept1 dept2 ...\"}" "${3:-qa seo ada compliance monetization product}"
      ;;
    start)
      QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
      _JOB_STATUS_DIR="$QA_ROOT"
      _JOBS_FILE="$QA_ROOT/results/.jobs.json"
      _JOBS_DASH_FILE="$QA_ROOT/dashboard/.jobs.json"
      _JOBS_HISTORY_FILE="$QA_ROOT/results/.jobs-history.json"
      _JOBS_DASH_HISTORY_FILE="$QA_ROOT/dashboard/.jobs-history.json"
      _JOBS_LOCK="$QA_ROOT/results/.jobs.lock"
      job_start "${2:?Usage: job-status.sh start <department>}"
      ;;
    finish)
      QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
      _JOB_STATUS_DIR="$QA_ROOT"
      _JOBS_FILE="$QA_ROOT/results/.jobs.json"
      _JOBS_DASH_FILE="$QA_ROOT/dashboard/.jobs.json"
      _JOBS_HISTORY_FILE="$QA_ROOT/results/.jobs-history.json"
      _JOBS_DASH_HISTORY_FILE="$QA_ROOT/dashboard/.jobs-history.json"
      _JOBS_LOCK="$QA_ROOT/results/.jobs.lock"
      job_finish "${2:?Usage: job-status.sh finish <department> [exit_code]}" "${3:-0}"
      ;;
    finalize)
      QA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
      _JOB_STATUS_DIR="$QA_ROOT"
      _JOBS_FILE="$QA_ROOT/results/.jobs.json"
      _JOBS_DASH_FILE="$QA_ROOT/dashboard/.jobs.json"
      _JOBS_HISTORY_FILE="$QA_ROOT/results/.jobs-history.json"
      _JOBS_DASH_HISTORY_FILE="$QA_ROOT/dashboard/.jobs-history.json"
      _JOBS_LOCK="$QA_ROOT/results/.jobs.lock"
      # Mark overall as complete and save to history
      python3 -c "
import json
from datetime import datetime, timezone

with open('$_JOBS_FILE') as f:
    data = json.load(f)

data['finished_at'] = datetime.now(timezone.utc).isoformat()
has_err = any(j.get('status') == 'error' for j in data['jobs'].values())
data['status'] = 'error' if has_err else 'complete'

# Append to history
history_path = '$_JOBS_HISTORY_FILE'
try:
    with open(history_path) as hf:
        history = json.load(hf)
except (FileNotFoundError, json.JSONDecodeError):
    history = []
history = [h for h in history if h.get('run_id') != data.get('run_id')]
history.append(data)
history = history[-50:]
with open(history_path, 'w') as hf:
    json.dump(history, hf, indent=2)
    hf.write('\n')

print(json.dumps(data, indent=2))
" | _write_jobs
      # Copy history to dashboard dir
      if [ -f "$_JOBS_HISTORY_FILE" ]; then
        cp "$_JOBS_HISTORY_FILE" "$_JOBS_DASH_HISTORY_FILE" 2>/dev/null || true
      fi
      ;;
    *)
      echo "Usage: job-status.sh {init|start|finish|finalize} [args...]" >&2
      exit 1
      ;;
  esac
fi
