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
  config.py          — Unified config loader
  logging.py         — Structured logging setup
  sync/
    __init__.py
    engine.py         — Orchestrates sync: gate -> aggregate -> upload -> invalidate
    providers/
      __init__.py
      base.py         — Abstract StorageProvider and CDNProvider interfaces
      aws.py          — S3 + CloudFront implementation (boto3)
  aggregate.py        — Rewrite of aggregate-results.py
  delivery.py         — Rewrite of generate-delivery-data.py
  tasks.py            — Rewrite of task-queue.py
  regression.py       — Rewrite of regression-runner.py
  setup.py            — Rewrite of backoffice_setup.py
  server.py           — Rewrite of dashboard-server.py
  cli.py              — Rewrite of backoffice-cli.py
  workflow.py         — Rewrite of local_audit_workflow.py
```

Agent shell scripts in `agents/` are untouched. `scripts/run-agent.sh` stays as a shell script but reads config via `eval $(python -m backoffice.config shell-export)`. `scripts/sync-dashboard.sh` and `scripts/quick-sync.sh` become 3-line wrappers calling into the package.

Makefile targets keep the same interface:
```makefile
# Before
dashboard: scripts/sync-dashboard.sh
# After
dashboard: python -m backoffice.sync
```

## 2. Unified Config

Three config files merge into one: `config/backoffice.yaml`.

```yaml
# Agent runner
runner:
  command: claude
  mode: claude-print

# Storage & CDN provider
deploy:
  provider: aws
  aws:
    region: us-east-1
    dashboard_targets:
      - bucket: my-bucket
        distribution_id: EXXXXX
        subdomain: admin.example.com
        filter_repo: null

# Scan & fix settings
scan:
  max_findings: 50
  severity_threshold: medium
fix:
  auto_deploy: false
  require_tests: true

# Audit targets
targets:
  back-office:
    path: /home/merm/projects/back-office
    language: python
    default_departments: [qa, seo, ada]
    test_command: make test
    coverage_command: make test-coverage
  bible-app:
    path: /home/merm/projects/bible-app
    # ...
```

`backoffice/config.py` loads this once and exposes a typed config object. All modules import from there — no more `os.environ` lookups scattered through the codebase.

The `BACK_OFFICE_ROOT` env var is still respected as an override for the root path. Agent shell scripts access runner config via `eval $(python -m backoffice.config shell-export)` which outputs shell variable assignments.

**Files removed:** `config/qa-config.yaml`, `config/agent-runner.env`.

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
# backoffice/logging.py

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
- Pre-deploy gate fails (tests don't pass): Abort entire sync, log which tests failed, exit 2. No uploads happen.
- Aggregation fails (malformed findings JSON): Skip that department, log warning with file path and parse error, continue. Dashboard shows stale data for that department.
- Upload fails mid-batch: Retry each file up to 3 times with exponential backoff (1s, 2s, 4s). If still failing, log error, continue uploading the rest. Exit 1 at the end.
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
- Update Makefile targets to call `python -m backoffice.<module>` directly.
- Update CI to run tests against the package.
- Agent shell scripts get the `eval $(python -m backoffice.config shell-export)` helper.

### Phase 3 — Delete old scripts
- Remove: `scripts/aggregate-results.py`, `scripts/generate-delivery-data.py`, `scripts/task-queue.py`, `scripts/regression-runner.py`, `scripts/backoffice_setup.py`, `scripts/dashboard-server.py`, `scripts/backoffice-cli.py`, `scripts/local_audit_workflow.py`.
- Remove: `config/qa-config.yaml`, `config/agent-runner.env`.
- Keep: `scripts/run-agent.sh` (reads config differently), `scripts/sync-dashboard.sh` (3-line wrapper), `scripts/quick-sync.sh` (3-line wrapper).

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
