# Back Office DX Overhaul

**Date:** 2026-03-22
**Status:** Approved
**Scope:** Refactor Python scripts into a unified package, consolidate config, add structured logging, define error handling strategy, abstract storage provider

## Problem

The Back Office project has three developer experience pain points:

1. **Bash+Python mix** — `sync-dashboard.sh` and `quick-sync.sh` embed inline Python in bash, making them hard to debug and maintain.
2. **Three config systems** — `targets.yaml`, `qa-config.yaml`, and `agent-runner.env` serve overlapping purposes with different formats, creating confusion about where settings live.
3. **Inconsistent error handling and logging** — Scripts mix `print()` and `echo`, use stdout and stderr inconsistently, and have no structured logging or defined error recovery behavior.

## Constraints

- No backward compatibility required — interfaces can change freely.
- The storage/deploy layer must be provider-agnostic (not locked to AWS).
- No new dependencies for logging (stdlib `logging` module).
- Agent shell scripts (`agents/*.sh`) and prompts are untouched — they work well as-is.
- Makefile targets keep the same names; only their implementations change.

## Approach

Consolidate all Python scripts into a `backoffice/` package with clean module boundaries, a single config file, provider-agnostic storage, and structured logging. Migrate in three phases so nothing breaks mid-transition.

---

## 1. Package Structure

```
backoffice/
  __init__.py
  __main__.py         — Unified entry point: python -m backoffice <command>
  config.py           — Unified config loader, exposes typed Config dataclass
  log_config.py       — Structured logging setup (named to avoid shadowing stdlib logging)
  sync/
    __init__.py
    engine.py          — Orchestrates sync: gate -> aggregate -> upload -> invalidate
    providers/
      __init__.py
      base.py          — Abstract StorageProvider and CDNProvider interfaces
      aws.py           — S3 + CloudFront implementation (boto3)
  aggregate.py         — Rewrite of aggregate-results.py
  delivery.py          — Rewrite of generate-delivery-data.py
  tasks.py             — Rewrite of task-queue.py
  regression.py        — Rewrite of regression-runner.py
  setup.py             — Rewrite of backoffice_setup.py
  server.py            — Rewrite of dashboard-server.py (local dev server)
  api_server.py        — Rewrite of api-server.py (production scan trigger API)
  cli.py               — Rewrite of backoffice-cli.py (delegates subcommands)
  workflow.py           — Rewrite of local_audit_workflow.py
  scaffolding.py       — Rewrite of scaffold-github-workflows.py
```

### Entry Points

All modules are invoked through a single entry point: `python -m backoffice <command>`. The `__main__.py` dispatches to the appropriate module based on the subcommand. Examples:

```
python -m backoffice sync              # full dashboard sync
python -m backoffice sync --dept qa    # quick-sync for one department (skips test gate)
python -m backoffice config show       # dump resolved config
python -m backoffice config shell-export  # output shell vars for agent scripts
python -m backoffice audit ...         # run audit
python -m backoffice tasks list        # task queue operations
python -m backoffice regression        # run regression suite
python -m backoffice scaffold ...      # scaffold GitHub Actions workflows
python -m backoffice serve             # local dev dashboard server
python -m backoffice api-server        # production API server
```

Quick-sync behavior: `python -m backoffice sync --dept qa` skips the pre-deploy test gate and aggregation step — it uploads only that department's data file and invalidates the CDN. This matches current `quick-sync.sh` behavior.

### Scripts That Stay as Shell

- `scripts/run-agent.sh` — reads runner config via `eval $(python -m backoffice config shell-export)`. Note: this introduces a Python dependency where there was none (previously just `source agent-runner.env`). `scripts/setup.sh` must run first to install the package.
- `scripts/job-status.sh` — lightweight job status helper used by Makefile audit targets
- `scripts/sync-dashboard.sh` — becomes 3-line wrapper: `python -m backoffice sync "$@"`
- `scripts/quick-sync.sh` — becomes 3-line wrapper: `python -m backoffice sync --dept "$@"`
- `scripts/setup.sh` — initial bootstrap (installs Python deps, etc.)

### Scripts Removed (logic moves to package)

`scripts/parse-config.py` is replaced by `python -m backoffice config shell-export`. The null-delimited output and shell-safety validation move into `backoffice/config.py`.

Agent shell scripts in `agents/` are untouched.

Makefile targets keep the same interface:
```makefile
# Before
dashboard: scripts/sync-dashboard.sh
# After
dashboard: python -m backoffice sync
```

## 2. Unified Config

Five config files merge into one: `config/backoffice.yaml`.

| Old File | New Location | Notes |
|----------|-------------|-------|
| `config/targets.yaml` | `targets:` section | List format changes to dict-keyed by name |
| `config/qa-config.yaml` | `deploy:`, `scan:`, `fix:`, `notifications:` sections | Field renames noted below |
| `config/agent-runner.env` | `runner:` section | Shell env vars become YAML |
| `config/api-config.yaml` | `api:` section | Port, API key, CORS origins |
| `config/task-queue.yaml` | Stays separate | Operational state, not config — lives at `config/task-queue.yaml` unchanged |

### Field Name Mapping (qa-config.yaml -> backoffice.yaml)

| Old (`qa-config.yaml`) | New (`backoffice.yaml`) |
|------------------------|------------------------|
| `dashboard_targets[].cloudfront_id` | `deploy.aws.dashboard_targets[].distribution_id` |
| `dashboard_targets[].repo` | `deploy.aws.dashboard_targets[].filter_repo` (null = aggregated) |
| `dashboard_targets[].base_path` | `deploy.aws.dashboard_targets[].base_path` (kept) |
| `dashboard_targets[].allow_public_read` | `deploy.aws.dashboard_targets[].allow_public_read` (kept, default false) |

### Complete Config Schema

```yaml
# Agent runner (command may include arguments, e.g. "claude --model haiku")
runner:
  command: "claude --model haiku"
  mode: claude-print

# Production API server
api:
  port: 8070
  api_key: ""
  allowed_origins:
    - "https://admin.thenewbeautifulme.com"
    - "http://localhost:8070"

# Storage & CDN provider
deploy:
  provider: aws
  aws:
    region: us-west-2
    dashboard_targets:
      - bucket: admin-thenewbeautifulme-site
        base_path: ""
        distribution_id: E372ZR95FXKVT5
        subdomain: admin.thenewbeautifulme.com
        filter_repo: thenewbeautifulme
        allow_public_read: false

# Scan & fix settings
scan:
  run_linter: true
  run_tests: true
  security_audit: true
  performance_review: true
  code_quality: true
  min_severity: low
  max_findings: 200
  exclude_patterns:
    - "node_modules/**"
    - "venv/**"
    - ".git/**"
    - "*.min.js"

fix:
  auto_fix_severity: high
  run_tests_after_fix: true
  run_linter_after_fix: true
  max_parallel_fixes: 4
  auto_commit: true
  auto_push: false

notifications:
  sync_to_s3: true

# Audit targets (dict-keyed by name; replaces the old list format)
targets:
  back-office:
    path: /home/merm/projects/back-office
    language: python
    default_departments: [qa]
    lint_command: "python3 scripts/test-scoring.py"
    test_command: "make test"
    coverage_command: "make test-coverage"
    deploy_command: "python3 scripts/aggregate-results.py results dashboard/data.json"
    context: |
      This is the local Back Office control plane and dashboard suite.
  bible-app:
    path: /home/merm/projects/bible-app
    language: typescript
    default_departments: [qa, seo, ada, compliance, monetization, product]
    lint_command: "npm run lint"
    test_command: "npm test && npm run typecheck"
    coverage_command: "npm run test:coverage"
    deploy_command: "npm run build"
    context: |
      Selah is a mobile-first Bible study app deployed at selah.codyjo.com.
  # ... remaining targets follow the same schema
```

All target fields are preserved: `path`, `language`, `default_departments`, `lint_command`, `test_command`, `coverage_command`, `deploy_command`, `context`. Targets missing optional fields (e.g., `pe-bootstrap` has no `coverage_command`) use the dataclass defaults (empty string). The API server resolves its target paths from the same `targets:` section (the separate `targets` map in `api-config.yaml` is eliminated).

### Config Object

`backoffice/config.py` loads this once and exposes a **frozen dataclass hierarchy**:

```python
@dataclass(frozen=True)
class Target:
    path: str
    language: str
    default_departments: list[str]
    lint_command: str = ""
    test_command: str = ""
    coverage_command: str = ""
    deploy_command: str = ""
    context: str = ""

@dataclass(frozen=True)
class Config:
    runner: RunnerConfig
    api: ApiConfig
    deploy: DeployConfig
    scan: ScanConfig
    fix: FixConfig
    notifications: NotificationsConfig
    targets: dict[str, Target]
```

All modules import `Config` from here — no more `os.environ` lookups scattered through the codebase. The `BACK_OFFICE_ROOT` env var is still respected as an override for the root path.

Agent shell scripts access runner config and target fields via `eval $(python -m backoffice config shell-export)`. The shell-export subcommand replaces `scripts/parse-config.py` and includes the same null-delimited output mode and shell-safety validation.

**Files removed:** `config/targets.yaml`, `config/qa-config.yaml`, `config/api-config.yaml`, `config/agent-runner.env`.
**Files kept:** `config/task-queue.yaml` (operational state, not configuration).

## 3. Provider Abstraction

```python
# backoffice/sync/providers/base.py

class StorageProvider(ABC):
    @abstractmethod
    def upload_file(self, local_path: str, remote_key: str,
                    content_type: str, cache_control: str) -> None: ...

    @abstractmethod
    def upload_files(self, file_mappings: list[dict]) -> None: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]: ...


class CDNProvider(ABC):
    @abstractmethod
    def invalidate(self, paths: list[str]) -> None: ...
```

The AWS implementation in `aws.py` wraps boto3. Future providers (GCS, Azure, local filesystem) implement the same interfaces.

The sync engine depends only on the abstract interfaces:

```python
class SyncEngine:
    def __init__(self, storage: StorageProvider, cdn: CDNProvider, config: Config):
        ...

    def run(self, department: str | None = None):
        self.run_pre_deploy_gate()
        self.aggregate()
        self.upload()
        self.invalidate()
```

### Canonical File Manifest

The sync engine uses a single source of truth for which files to upload. This resolves the discrepancy between the current `sync-dashboard.sh` and `quick-sync.sh` file lists.

**Full sync** uploads all of these:

```python
# Dashboard HTML/JS/CSS files
DASHBOARD_FILES = [
    'index.html', 'qa.html', 'backoffice.html',
    'seo.html', 'ada.html', 'compliance.html', 'privacy.html',
    'monetization.html', 'product.html',
    'jobs.html', 'faq.html', 'self-audit.html', 'admin.html', 'regression.html',
    'selah.html', 'analogify.html', 'chromahaus.html', 'tnbm-tarot.html',
    'back-office-hq.html',
    'documentation.html', 'documentation-github.html',
    'documentation-cicd.html', 'documentation-cli.html',
    'site-branding.js', 'department-context.js', 'favicon.svg',
]

# Department findings -> dashboard data file mapping
DEPT_DATA_MAP = {
    'qa':            ('findings.json',            'qa-data.json'),
    'seo':           ('seo-findings.json',        'seo-data.json'),
    'ada':           ('ada-findings.json',        'ada-data.json'),
    'compliance':    ('compliance-findings.json',  'compliance-data.json'),
    'privacy':       ('privacy-findings.json',     'privacy-data.json'),
    'monetization':  ('monetization-findings.json','monetization-data.json'),
    'product':       ('product-findings.json',     'product-data.json'),
    'self-audit':    ('findings.json',             'self-audit-data.json'),
}

# Shared metadata files (uploaded for both repo-scoped and aggregated targets)
SHARED_META_FILES = [
    'automation-data.json', 'org-data.json',
    'local-audit-log.json', 'local-audit-log.md',
    'regression-data.json',
]

# Job status files
JOB_STATUS_FILES = ['.jobs.json', '.jobs-history.json']
```

**Quick-sync** (`sync --dept qa`) uploads only: the department's data file from `DEPT_DATA_MAP`, plus `JOB_STATUS_FILES` and `SHARED_META_FILES`. No HTML files, no other departments.

Note: `dashboard/metrics.html` exists on disk but is intentionally local-only and not deployed.

Provider selection driven by `deploy.provider` in config:

```python
def get_providers(config) -> tuple[StorageProvider, CDNProvider]:
    if config.deploy.provider == "aws":
        return AWSStorage(config), AWSCloudFront(config)
    raise ValueError(f"Unknown provider: {config.deploy.provider}")
```

## 4. Structured Logging

Replace all `print()` calls and inconsistent output with Python's `logging` module configured once at startup.

```python
# backoffice/log_config.py

def setup_logging(verbose: bool = False, json_output: bool = False):
    """Call once at entry point."""
    level = logging.DEBUG if verbose else logging.INFO

    if json_output:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))

    root = logging.getLogger("backoffice")
    root.setLevel(level)
    root.addHandler(handler)
```

Key decisions:
- **All log output to stderr.** Stdout reserved for data output (JSON, shell-export) so pipes work cleanly.
- **Two modes:** human-readable (default) and JSON (`--json-log` flag).
- **`--verbose` flag** on all entry points for debug-level output.
- **Each module uses `logger = logging.getLogger(__name__)`** for clear message provenance.
- **Agent shell scripts** continue using `echo` to stderr with a consistent prefix: `[backoffice:agent] message`.
- **No new dependencies.** Stdlib `logging` only.

## 5. Error Handling Strategy

### General Principles

- **Fatal vs. non-fatal**: Config problems are fatal (can't proceed without valid config). Data problems are non-fatal (degrade gracefully, keep going).
- **Exit codes**: 0 = success, 1 = partial failure (warnings but work completed), 2 = fatal error.
- **All errors to stderr** via the structured logger. Stdout stays clean for data.
- **No silent swallowing**: Every `except` block logs something. No bare `except:` or `except Exception: pass`.

### Per-Module Behavior

**Sync Engine (`sync/engine.py`)**
- Pre-deploy gate fails (tests don't pass): Abort entire sync, log which tests failed, exit 2. No uploads happen. Note: quick-sync mode (`sync --dept`) skips this gate entirely, matching current behavior.
- Aggregation fails (malformed findings JSON): Skip that department, log warning with file path and parse error, continue. Dashboard shows stale data for that department.
- Upload fails mid-batch: Application-level retry — each file retried up to 3 times with exponential backoff (1s, 2s, 4s). This is on top of boto3's built-in retry (which handles transient HTTP errors). The application retry catches higher-level failures (permission denied, bucket not found after eventual consistency, etc.). If a file still fails after retries, log error, continue uploading the rest. Exit 1 at the end.
- CDN invalidation fails: Log warning, don't fail the run. Dashboard serves stale cache until next successful invalidation.

**Config (`config.py`)**
- Config file missing: Fatal error: `Config not found at config/backoffice.yaml — run 'python -m backoffice.setup' to create one`. Exit 2.
- Malformed YAML: Fatal error with parse error and line number. Exit 2.
- Missing required fields: Fatal error listing exactly which fields are missing. Exit 2.
- Target path doesn't exist: Warning at load time, error only when auditing that target.

**Aggregation (`aggregate.py`)**
- Findings file missing for a department: Skip silently — not every repo has every department scanned.
- Findings file is malformed JSON: Log warning with file path, skip, continue.
- Results directory doesn't exist: Warning, produce empty aggregated output.

**Task Queue (`tasks.py`)**
- task-queue.yaml missing or malformed: Fatal error with clear message. Exit 2.
- Gate check fails (audit artifacts missing): Task stays in current state, log which gate failed and what artifact is missing.

**Regression Runner (`regression.py`)**
- Target's test command fails: Capture exit code and stderr, record as failure in output. Continue to next target.
- Test command times out: Kill process, record as timeout, continue.
- Coverage data not found: Record coverage as `null`, log warning. Don't fabricate numbers.

## 6. Migration Plan

### Phase 1 — Package exists alongside scripts/
- Create `backoffice/` package with all modules.
- Old scripts in `scripts/` become thin wrappers that import from the package:
  ```python
  # scripts/aggregate-results.py (temporary wrapper)
  from backoffice.aggregate import main
  main()
  ```
- Everything works during transition without breaking Makefile or CI.

### Phase 2 — Makefile points to package
- Update Makefile targets to call `python -m backoffice <command>` directly.
- Update CI to run tests against the package.
- Agent shell scripts get the `eval $(python -m backoffice config shell-export)` helper.

### Phase 3 — Delete old scripts and configs
- **Remove scripts:** `scripts/aggregate-results.py`, `scripts/generate-delivery-data.py`, `scripts/task-queue.py`, `scripts/regression-runner.py`, `scripts/backoffice_setup.py`, `scripts/dashboard-server.py`, `scripts/api-server.py`, `scripts/backoffice-cli.py`, `scripts/local_audit_workflow.py`, `scripts/parse-config.py`, `scripts/scaffold-github-workflows.py`.
- **Remove configs:** `config/targets.yaml`, `config/qa-config.yaml`, `config/api-config.yaml`, `config/agent-runner.env`.
- **Keep scripts:** `scripts/run-agent.sh` (reads config via shell-export), `scripts/sync-dashboard.sh` (3-line wrapper), `scripts/quick-sync.sh` (3-line wrapper), `scripts/job-status.sh` (lightweight job status helper), `scripts/setup.sh` (initial bootstrap).
- **Keep configs:** `config/task-queue.yaml` (operational state), `config/backoffice.yaml` (new unified config).
- **Keep example files:** Update `config/*.example.yaml` to match new schema.

### Migration Verification

The sync engine rewrite is the highest-risk change (it touches live S3 deploys). To verify correctness:

1. **Dry-run mode**: `python -m backoffice sync --dry-run` logs every file that would be uploaded with its content-type, cache-control, and destination key — but does not upload. Compare this output against the current `sync-dashboard.sh` behavior on the same data.
2. **Diff test**: Run old sync script with `--dryrun` flag (aws cli) and new sync engine with `--dry-run`, diff the file manifests.
3. **Staged rollout**: Deploy to the lowest-traffic dashboard target first (admin.codyjo.com), verify manually, then expand to other targets.
4. **`allow_public_read` safety**: Unit test that the default is `false` and that the upload logic respects it. This is a safety-critical field.

### Tests
- Migrate `scripts/test-*.py` to `tests/` directory at project root.
- Rewrite to test package modules directly.
- Coverage target: maintain 55.8% as floor, aim for 80%+ on new package code.

## What's Untouched

- `agents/` — shell scripts and prompts
- `dashboard/` — HTML, JS, JSON files
- `lib/` — reference docs
- `terraform/` — infrastructure
- `docs/` — existing documentation
- `scripts/run-local-bible-app-product-audit.sh` — one-off convenience script
