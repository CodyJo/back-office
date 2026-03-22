# Back Office Handoff

Last updated: March 14, 2026

## Current Direction

Back Office is the portfolio control plane for local repo audits, dashboard aggregation, delegated task tracking, and workflow scaffolding. The near-term priority is reliability of the local orchestration path so audits, refreshes, and task-queue syncs can run reproducibly against alternate data roots without accidentally reading from or writing to the live repo outputs.

## Completed

- Fixed a regression in `scripts/local_audit_workflow.py` where `BACK_OFFICE_ROOT` incorrectly changed both data paths and script paths.
- Split local audit resolution into:
  - script/code root derived from the repo location
  - data root derived from `BACK_OFFICE_ROOT`
- Updated the workflow refresh path so:
  - aggregation still uses the selected results/dashboard directories
  - delivery metadata generation receives the selected config/results/dashboard env
  - task queue sync receives the same env and no longer falls back to the live repo paths during temp-root runs
- Updated `scripts/task-queue.py` to respect:
  - `BACK_OFFICE_ROOT`
  - `BACK_OFFICE_TARGETS_CONFIG`
  - `BACK_OFFICE_RESULTS_DIR`
  - `BACK_OFFICE_DASHBOARD_DIR`
- Expanded `scripts/test-local-audit-workflow.py` to verify that `task-queue.json` is generated under the temporary dashboard root during `refresh`.

## Pending

- Add dedicated regression coverage for `scripts/task-queue.py` itself, not just the workflow integration path.
- Decide whether more Back Office scripts should consistently distinguish script root vs data root the same way.
- Review the existing dirty worktree files before bundling Back Office dashboard/data updates into any future commit. This repo already contains pre-existing modified and untracked files outside this change.
- Consider promoting the task queue and gate model into the public docs/README more explicitly once the delegated-workflow path is stable.

## Key Decisions And Constraints

- Do not deploy or sync dashboard assets as part of this work.
- `BACK_OFFICE_ROOT` should relocate config/results/dashboard state, but it should not relocate the checked-in scripts or department agents.
- Task queue sync is part of refresh behavior and should be reproducible in test/temp roots.
- There were pre-existing local modifications in this repo, including tracked dashboard artifacts and an untracked `scripts/task-queue.py`; work was limited to the control-plane scripts and docs needed for this fix.

## Files To Read First

- `scripts/local_audit_workflow.py`
- `scripts/task-queue.py`
- `scripts/test-local-audit-workflow.py`
- `docs/WORKFLOW-ARCHITECTURE.md`
- `docs/CLI-REFERENCE.md`
- `README.md`

## Integration Points

- Target repo definitions: `config/targets.yaml`
- Dashboard aggregation: `scripts/aggregate-results.py`
- Delivery metadata: `scripts/generate-delivery-data.py`
- Delegated queue payloads: `config/task-queue.yaml`, `results/task-queue.json`, `dashboard/task-queue.json`
- Dashboard publishing: `scripts/sync-dashboard.sh`

## Recommended Next Steps

1. Add direct tests for `scripts/task-queue.py` create/show/complete flows under temp-root execution.
2. Audit other scripts for similar path-coupling assumptions whenever `BACK_OFFICE_ROOT` is set.
3. Once the dirty worktree is sorted, commit the control-plane root fix separately from dashboard-content changes.
4. Consider adding `docs/HANDOFF.md` to any published or GitHub-facing documentation index that should guide future operators.

## Verification

- `python3 scripts/test-local-audit-workflow.py`
- `python3 scripts/test-cli-and-scaffolding.py`
- `python3 scripts/test-scoring.py`
- `python3 scripts/test-servers-and-setup.py`
- `python3 -m py_compile scripts/local_audit_workflow.py scripts/task-queue.py scripts/backoffice-cli.py`
