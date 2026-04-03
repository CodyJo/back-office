# Local Platform Architecture

Last updated: April 2, 2026

## Goal

Run private development, code review, workflow execution, and deployment control locally without depending on the GitHub website for day-to-day work.

Public GitHub should become an optional mirror and publishing target, not the primary control plane.

## Current Implemented State

This is no longer just a target architecture. The following is already live on this machine:

- Forgejo local stack on `http://127.0.0.1:3300/`
- Back Office in Forgejo mode on `http://127.0.0.1:8070/`
- top-level git repos backfilled into Forgejo under `CodyJo/*`
- archived historical GitHub Actions metadata in Back Office
- user-session autostart via `systemd --user` for:
  - `forgejo-local.service`
  - `back-office-forgejo.service`

This means the local platform now starts with the desktop login session and the local bookmark URLs are stable for day-to-day use.

## Recommended Stack

- **Forgejo** as the private git server and local forge
- **Forgejo Actions** as the local workflow engine
- **self-hosted Forgejo runners** for all build/test/deploy execution
- **Back Office** as the portfolio dashboard and deploy controller
- **Bunny.net** as the production runtime target for app deployments
- **GCP** only for the repos that are intentionally GCP-first today
- **VSCodium** as the local editor and terminal front end
- **Claude Code / Codex** running in integrated terminals inside VSCodium

## Why This Stack

This keeps the pieces clean:

- Forgejo owns private git, PR review, issues, and workflow history.
- Back Office owns portfolio visibility, approval flow, deploy readiness, and release control.
- Runners own execution.
- Bunny owns runtime hosting.
- GitHub becomes an optional outward-facing distribution channel.

## Architecture

```text
VSCodium
  -> integrated terminal
  -> Claude Code / Codex
  -> local git repos in /home/merm/projects

Local Git / Forgejo
  -> private remotes
  -> PR review
  -> Actions workflows
  -> runner registration

Back Office
  -> portfolio dashboard
  -> deploy dashboard
  -> workflow visibility
  -> dispatch / rollback controls

Runners
  -> build
  -> test
  -> docker build/push
  -> Bunny deploy

Bunny.net
  -> Magic Containers
  -> Pull Zones
  -> Storage
  -> Database

Public GitHub
  -> optional mirror only
  -> public repos or selected branches/tags
```

## Source Of Truth

- **Private source of truth:** Forgejo
- **Portfolio operations source of truth:** Back Office
- **Runtime source of truth:** Bunny
- **Public distribution mirror:** GitHub

Do not invert that order.

## Workflow Model

### Private work

1. Work in local repos under `/home/merm/projects`.
2. Commit and push to Forgejo first.
3. Open PRs and review in Forgejo.
4. Run CI/CD in Forgejo Actions.
5. Use Back Office to monitor and dispatch deploys.
6. Mirror to GitHub only when a repo or branch should be public.

### Public release

1. Keep a repo private in Forgejo.
2. Approve release state in Back Office or Forgejo PR review.
3. Mirror selected branch/tag to GitHub.
4. Optionally publish images or release assets publicly.

## Best Practices

### Git

- Protect `main` in Forgejo for important repos.
- Require PR review for risky repos.
- Use short-lived branches for agent work.
- Keep one repo remote named `origin` for Forgejo once cutover is complete.
- Add a second remote like `github-public` only for repos you intentionally mirror.

### Actions

- Keep workflow files in `.github/workflows/` for portability.
- Let Forgejo read them unless you need `.forgejo/workflows/` divergence.
- Use immutable image tags such as `sha-<gitsha>`.
- Keep deploy workflows explicit and readable.

### Agents

- Run Claude Code and Codex in VSCodium terminals, not as hidden background systems.
- Use PR review in Forgejo as the safety boundary for meaningful changes.
- Use Back Office for portfolio-wide readiness and deployment visibility.

### Deploys

- Deploy from reviewed code in Forgejo.
- Keep Bunny app IDs and deploy secrets in the local forge, not in public GitHub.
- Keep rollback to a previous image tag as a first-class workflow.

## Implementation Phases

### Phase 1: Local forge

- Stand up Forgejo locally.
- Create your private org/user namespace.
- Add SSH keys.
- Add the initial private repos.

### Phase 2: Local workflows

- Register at least one Forgejo runner.
- Point the current CI/CD workflows at Forgejo Actions.
- Confirm local builds and Bunny deploys from Forgejo.

### Phase 3: Back Office integration

- Extend Back Office to read Forgejo workflow runs instead of only GitHub.
- Keep GitHub support as a second adapter, not the only one.
- Add deploy and rollback controls using Forgejo workflow dispatch.

### Phase 4: Public mirror policy

- Decide repo by repo whether to:
  - stay private in Forgejo only
  - mirror to GitHub
  - publish only selected tags/releases

## What Not To Do

- Do not make GitHub your main control plane if private local-first work is the goal.
- Do not keep AWS as a hidden deployment fallback.
- Do not split review across too many tools.
- Do not use Terraform as the main application deployment controller for Bunny app rollouts.

## VSCodium Role

Use a multi-root workspace so VSCodium becomes the operator cockpit:

- one window for the whole portfolio
- integrated terminals for Claude Code and Codex
- direct access to Back Office, product repos, and ops docs
- tasks to start Forgejo and Back Office locally

Use Forgejo PR review as the default safety boundary for AI-authored changes. Back Office should aggregate and control, but branch review still belongs in the forge.

## Next Steps

1. Debug the first failing Forgejo workflow and complete one full private CI/CD path.
2. Add deeper Forgejo visibility in Back Office:
   - runner counts
   - PR state
   - workflow detail
3. Add rollback controls from Back Office.
4. Decide whether to enable `linger` so the local platform keeps running before login.
