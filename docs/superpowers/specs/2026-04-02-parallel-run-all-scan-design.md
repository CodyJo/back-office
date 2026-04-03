# Parallel Run-All Local Scan Design

**Date:** 2026-04-02
**Status:** Draft
**Scope:** Run all configured Back Office audit targets concurrently, using each target’s default departments, keeping results local to HQ only, with no auto-fix behavior.

## Problem

The current local workflow `backoffice/workflow.py:448` runs `run-all` sequentially. For a full portfolio scan this is slower than necessary and does not match the requested operating mode.

The requested behavior is:

- run all configured projects in Back Office
- include `pattern`
- use each target’s configured `default_departments`
- do not auto-fix
- report only to the local HQ dashboard
- run targets in parallel, not sequentially

## Current State

- `handle_run_all(...)` iterates through selected targets one at a time.
- `run_target(...)` already runs a target’s department scripts without any fix, sync, or deploy step.
- `refresh_dashboard_artifacts(...)` already writes local dashboard artifacts from `results/` into `dashboard/`.
- `config/targets.yaml` already includes `pattern`, so no target-config change is required to satisfy that part of the request.

## Constraints

- Keep the existing local-only workflow shape: scan into `results/`, then refresh the local dashboard.
- Do not change per-target department defaults unless `--departments` is explicitly passed.
- Do not add auto-fix, sync, push, deploy, or merge behavior.
- Keep the change minimal and limited to the local workflow path.
- Preserve the ability to run a subset via `--targets`.

## Approaches Considered

### 1. Leave workflow sequential and launch multiple CLI processes externally

This avoids touching Python orchestration, but it pushes concurrency management outside the product, makes dashboard refresh timing awkward, and is not the requested built-in behavior.

### 2. Add parallel target execution inside `handle_run_all(...)`

Run each selected target in its own worker, wait for all target runs to finish, then do one final `refresh_dashboard_artifacts(...)` call.

**Recommendation:** choose this approach. It is the smallest product-level change that matches the requested behavior and preserves the existing local data flow.

### 3. Parallelize departments within each target too

This would increase concurrency further, but it expands scope, creates more contention around shared job-status files, and is unnecessary for the current request.

## Approved Design

### 1. Execution model

`handle_run_all(...)` will:

1. load all configured targets
2. apply optional `--targets` filtering
3. resolve departments per target using `default_departments(target)` unless `--departments` overrides them
4. submit each target run to a thread pool
5. wait for all submitted target runs to complete
6. fail the command if any target run fails
7. refresh dashboard artifacts once at the end

This keeps concurrency at the target level only. Within each target, department scripts still run in their existing order.

### 2. Local-only reporting

The scan output path does not change:

- raw results stay in `results/<repo>/...`
- job status stays in `results/.jobs*.json` and mirrored dashboard copies
- refreshed HQ artifacts stay in `dashboard/*.json`

No upload, sync, or deployment step is added. The output remains visible only through the local HQ dashboard and local files.

### 3. Target inclusion

`run-all` already means all configured targets unless `--targets` is passed. Because `config/targets.yaml` already contains `pattern`, the parallel run-all path automatically includes it. No extra config migration is needed.

### 4. Error handling

Each target future returns success or raises its underlying exception.

Behavior:

- successful targets finish normally
- failed targets are logged with the target name
- after all futures complete, `handle_run_all(...)` raises a non-zero outcome if any target failed
- dashboard refresh runs only if the full scan phase completes without target failures

This keeps failure behavior conservative and easy to reason about.

### 5. Logging

The workflow logs one line before queueing each target and one line when each target completes or fails. Logging stays in Python’s existing logger path and does not add a new reporting surface.

### 6. Testing

Add focused tests around `backoffice/workflow.py` for:

1. `handle_run_all(...)` submits all selected targets instead of running them in a direct sequential loop
2. each target still receives the correct department list
3. `refresh_dashboard_artifacts(...)` runs once after successful completion
4. a failing target causes a non-zero outcome and prevents the final refresh
5. target filtering via `--targets` still works under the parallel path

Tests should mock `run_target(...)` and `refresh_dashboard_artifacts(...)` so the concurrency contract is verified without running real scans.

## Implementation Outline

1. Update `backoffice/workflow.py` imports to include a standard-library executor utility.
2. Add a small helper to run one target with its resolved departments and structured logging.
3. Replace the sequential `for target in selected_targets` block in `handle_run_all(...)` with target-level concurrent submission and result collection.
4. Keep the single final `refresh_dashboard_artifacts(targets, config=config)` call.
5. Add focused regression tests in `tests/test_workflow.py`.

## Non-Goals

- no department-level parallelism within a target
- no change to agent shell scripts
- no change to fix-agent behavior
- no remote sync or deploy
- no changes to target configuration format

## Verification Plan

Before claiming completion:

1. run the focused workflow tests that cover the new parallel `run-all` behavior
2. run the broader workflow test module if the focused tests pass
3. run the actual local `run-all` command only after code changes and tests are green, since it is the operational outcome requested

## Result

This design gives Back Office a built-in parallel portfolio scan path that matches the requested operating mode while staying minimal: target-level concurrency, existing per-target department defaults, local HQ refresh at the end, and no auto-fix or remote side effects.
