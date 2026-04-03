# Open Claude Resume Handoff

Last updated: April 2, 2026

## Objective

Continue the local-first platform migration so private development, review, CI/CD, and deploy control run through Forgejo + Back Office, with Bunny.net as the runtime target and GitHub as an optional public mirror only.

## Required Reading Order

1. [CLAUDE.md](/home/merm/projects/back-office/CLAUDE.md)
2. [MASTER-PROMPT.md](/home/merm/projects/back-office/MASTER-PROMPT.md)
3. [HANDOFF.md](/home/merm/projects/back-office/docs/HANDOFF.md)
4. [LOCAL_PLATFORM_ARCHITECTURE.md](/home/merm/projects/back-office/docs/LOCAL_PLATFORM_ARCHITECTURE.md)
5. [LOCAL_REVIEW_WORKFLOW.md](/home/merm/projects/back-office/docs/LOCAL_REVIEW_WORKFLOW.md)

## Current State

- Back Office already has a deploy dashboard MVP.
- That dashboard now supports either `github` or `forgejo` as the source-control provider.
- Provider selection is automatic:
  - if `BACK_OFFICE_SOURCE_CONTROL=forgejo`, use Forgejo
  - if `BACK_OFFICE_SOURCE_CONTROL=github`, use GitHub
  - otherwise use Forgejo when `FORGEJO_BASE_URL` and `FORGEJO_TOKEN` are present, else GitHub
- Public GitHub should remain mirror-only for selected repos/branches/tags.

Update as of April 1, 2026 end of session:

- Forgejo is now live at `http://localhost:3300`
- Forgejo SSH is live at `ssh://git@localhost:2223/...`
- local stack containers:
  - `forgejo-local`
  - `forgejo-postgres`
  - `forgejo-runner`
- admin user exists: `CodyJo`
- local secrets and bootstrap credentials are stored in ignored files:
  - [ops/forgejo-local/back-office.env](/home/merm/projects/back-office/ops/forgejo-local/back-office.env)
  - [ops/forgejo-local/admin-credentials.txt](/home/merm/projects/back-office/ops/forgejo-local/admin-credentials.txt)
- all top-level git repos under `/home/merm/projects` were backfilled into Forgejo under `CodyJo/*`
- verified live Forgejo repo inventory count: `18`
- local `origin` remotes were repointed to Forgejo for the imported repos
- selective GitHub remotes were preserved as `github-public`
- `selah` was pushed successfully to Forgejo `origin/main`
- Forgejo runner is registered as `codyjo-local-runner`
- Back Office payload verification with Forgejo env now reports provider `forgejo`
- first Forgejo Actions run exists for `CodyJo/selah` run `1` on `deploy.yml`, final status `failure`
- historical GitHub Actions run history is still separate from git history and requires a local archive step if you want to keep it outside GitHub
- archive tooling now exists:
  - [scripts/backfill-forgejo-history.sh](/home/merm/projects/back-office/scripts/backfill-forgejo-history.sh)
  - [scripts/archive-github-actions-history.sh](/home/merm/projects/back-office/scripts/archive-github-actions-history.sh)
  - [docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md](/home/merm/projects/back-office/docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md)
- archive visibility is now a real Back Office page:
  - [dashboard/actions-history.html](/home/merm/projects/back-office/dashboard/actions-history.html)
  - [backoffice/github_actions_history.py](/home/merm/projects/back-office/backoffice/github_actions_history.py)
  - [backoffice/server.py](/home/merm/projects/back-office/backoffice/server.py) routes:
    - `GET /api/github-actions/history`
    - `POST /api/github-actions/archive`
- HQ now exposes Forgejo status directly through `GET /api/ops/status`
- [dashboard/index.html](/home/merm/projects/back-office/dashboard/index.html) now includes:
  - a Forgejo topbar link
  - a Forgejo score card driven by the `ops/status` payload
- [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html) has been moved onto the dark Back Office palette
- [dashboard/migration.html](/home/merm/projects/back-office/dashboard/migration.html) now includes Deploy, Actions Archive, and Forgejo nav links
- short operator routine doc:
  - [docs/DAILY_USE.md](/home/merm/projects/back-office/docs/DAILY_USE.md)
- autostart scaffolding:
  - [systemd-user/forgejo-local.service](/home/merm/projects/back-office/systemd-user/forgejo-local.service)
  - [systemd-user/back-office-forgejo.service](/home/merm/projects/back-office/systemd-user/back-office-forgejo.service)
  - [scripts/start-forgejo-local.sh](/home/merm/projects/back-office/scripts/start-forgejo-local.sh)
  - [scripts/install-local-platform-autostart.sh](/home/merm/projects/back-office/scripts/install-local-platform-autostart.sh)
  - [docs/AUTOSTART.md](/home/merm/projects/back-office/docs/AUTOSTART.md)
- autostart is already installed and enabled for the current desktop user on this machine
- the GitHub Actions metadata archive has already been executed once and stored under `/home/merm/projects/back-office/results/github-actions-history/`
- current notable archive counts:
  - `analogify` `144`
  - `back-office` `46`
  - `certstudy` `34`
  - `codyjo.com` `138`
  - `cordivent` `89`
  - `fuel` `90`
  - `openclaude` `200/280`
  - `pattern` `5`
  - `pe-bootstrap` `1`
  - `selah` `96`
  - `thenewbeautifulme` `188`

## Files Added Or Changed For This Thread

### Deploy control

- [backoffice/deploy_control.py](/home/merm/projects/back-office/backoffice/deploy_control.py)
- [dashboard/deploy.html](/home/merm/projects/back-office/dashboard/deploy.html)

### Local forge / review workflow

- [ops/forgejo-local/compose.yaml](/home/merm/projects/back-office/ops/forgejo-local/compose.yaml)
- [ops/forgejo-local/.env.example](/home/merm/projects/back-office/ops/forgejo-local/.env.example)
- [ops/forgejo-local/README.md](/home/merm/projects/back-office/ops/forgejo-local/README.md)
- [scripts/bootstrap-forgejo-repos.sh](/home/merm/projects/back-office/scripts/bootstrap-forgejo-repos.sh)
- [scripts/set-forgejo-remotes.sh](/home/merm/projects/back-office/scripts/set-forgejo-remotes.sh)
- [scripts/mirror-public-repo.sh](/home/merm/projects/back-office/scripts/mirror-public-repo.sh)
- [scripts/backfill-forgejo-history.sh](/home/merm/projects/back-office/scripts/backfill-forgejo-history.sh)
- [scripts/archive-github-actions-history.sh](/home/merm/projects/back-office/scripts/archive-github-actions-history.sh)
- [docs/LOCAL_PLATFORM_ARCHITECTURE.md](/home/merm/projects/back-office/docs/LOCAL_PLATFORM_ARCHITECTURE.md)
- [docs/LOCAL_REVIEW_WORKFLOW.md](/home/merm/projects/back-office/docs/LOCAL_REVIEW_WORKFLOW.md)
- [docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md](/home/merm/projects/back-office/docs/GITHUB_ACTIONS_HISTORY_ARCHIVE.md)
- [/home/merm/projects/codyjo-local-platform.code-workspace](/home/merm/projects/codyjo-local-platform.code-workspace)

## What Was Verified

- `python3 -m py_compile /home/merm/projects/back-office/backoffice/deploy_control.py /home/merm/projects/back-office/backoffice/server.py`
- `bash -n` passed for:
  - [bootstrap-forgejo-repos.sh](/home/merm/projects/back-office/scripts/bootstrap-forgejo-repos.sh)
  - [set-forgejo-remotes.sh](/home/merm/projects/back-office/scripts/set-forgejo-remotes.sh)
  - [mirror-public-repo.sh](/home/merm/projects/back-office/scripts/mirror-public-repo.sh)
- the workspace JSON parses
- `deploy_control.build_deploy_control_payload(...)` still returns a valid payload
- with Forgejo env exported, `deploy_control.build_deploy_control_payload(...)` reports provider `forgejo` and summary `{'total': 15, 'ready': 8, 'blocked': 7, 'bunny': 9, 'gcp': 2, 'deferred': 3}`
- local `selah` push to `origin/main` succeeded and now tracks Forgejo
- Forgejo API shows the private repo inventory and a live `selah` workflow run
- live Forgejo repo inventory count matches the top-level local git repo count: `18`

## Important Known Facts

- Bunny private registry already exists: `6323`
- Confirmed Bunny app IDs:
  - `auth-service`: `UD0svg5olkCq0tn`
  - `fuel`: `F8cKya950t3vhvH`
  - `selah`: `YgU9xD2yYez1bhz`
  - `cordivent`: `dLK8UyDiv1e4sHu`
  - `certstudy`: `tZ7v1Y9QeSxg0E4`
  - `pattern`: `uuow5uE05olUn52`
  - `search`: `j4oVIwXaqYKmr2i`
  - `thenewbeautifulme-v2`: `8NwgOJyUv5cq6qk`
- Pattern still has an unresolved GitHub slug from this checkout, but Forgejo planning assumes `CodyJo/pattern`.
- The Back Office repo is dirty with unrelated user work. Do not revert unrelated changes.

## Immediate Next Steps

1. Run [scripts/archive-github-actions-history.sh](/home/merm/projects/back-office/scripts/archive-github-actions-history.sh) to pull old GitHub workflow metadata into local ignored results.
2. Open the local Forgejo UI and confirm login works using the ignored credentials file.
3. Run Back Office in Forgejo mode with [run-back-office-forgejo.sh](/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh).
4. Inspect the new archive view at `http://localhost:8070/actions-history.html` and decide whether to add deeper run drill-down or log download support.
5. Inspect the running `selah` workflow in Forgejo and determine whether it is:
   - still executing
   - blocked on repo secrets
   - blocked on Bunny deploy script assumptions
   - stalled due runner/job incompatibility
6. Add Forgejo runner visibility to the Back Office deploy dashboard if possible.
7. Add PR visibility/state to the deploy dashboard.
8. Inspect why `CodyJo/selah` workflow run `1` failed.
9. Create one real private branch + PR flow in Forgejo and verify review ergonomics.
10. Once a workflow completes successfully, dispatch a deploy from Back Office and verify the Bunny update.

## Recommended Next Coding Tasks

- Add Forgejo runner visibility to the deploy dashboard if the API surface allows it.
- Add PR visibility/state to the deploy dashboard.
- Add rollback controls:
  - previous successful image tag
  - manual tag override
  - redeploy last-known-good
- Add a stronger Back Office nav route for deploy control if it is becoming a core product surface.
- Add a Forgejo-specific bootstrap/env doc for runner registration if the current README is not enough during live setup.

## Constraints And Preferences

- Prefer boring, explicit, agent-readable automation.
- Keep Bunny as the runtime.
- Keep GitHub as mirror-only unless explicitly needed.
- Do not reintroduce AWS deployment coupling.
- Do not use Terraform as the main application deploy controller for Bunny rollouts.
- Keep review in Forgejo as the safety boundary for AI-authored changes.

## Suggested Resume Command Sequence

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep forgejo
/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh
```

Inspect workflow state:

```bash
curl -fsS -H "Authorization: token $(awk -F': ' '/API Token/ {print $2}' /home/merm/projects/back-office/ops/forgejo-local/admin-credentials.txt)" \
  'http://localhost:3300/api/v1/repos/CodyJo/selah/actions/runs?limit=20'
```

## Definition Of Good Resume Outcome

The next agent should leave the system with:

- a running Forgejo instance
- at least one registered runner
- Back Office reading Forgejo data instead of GitHub for deploy control
- at least one repo created in Forgejo and reachable as `origin`
- at least one validated private review -> workflow -> Bunny deploy path
