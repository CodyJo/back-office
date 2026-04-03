# Local Review Workflow

Last updated: April 1, 2026

## Goal

Keep private code and private reviews local-first while still using familiar git and Actions patterns.

For the short operator routine, read [DAILY_USE.md](/home/merm/projects/back-office/docs/DAILY_USE.md).

## Working Model

1. Open [/home/merm/projects/codyjo-local-platform.code-workspace](/home/merm/projects/codyjo-local-platform.code-workspace) in VSCodium.
2. Run Claude Code and Codex in separate integrated terminals.
3. Make changes on short-lived branches in the local repo.
4. Push the branch to Forgejo `origin`.
5. Open and review the PR in Forgejo.
6. Let Forgejo Actions run validation and deploy workflows on your self-hosted runners.
7. Use Back Office to watch workflow state, Bunny state, and deploy readiness across the portfolio.
8. Mirror to GitHub only when a repo, branch, or tag should be public.

## Safety Boundary

- Forgejo PR review is the default approval boundary for meaningful AI-generated changes.
- Back Office is the portfolio-level operator view, not the only review surface.
- GitHub should not receive private code unless you intentionally mirror it.
- Production deploys should come from reviewed branches only.

## VSCodium Setup

- Use one integrated terminal for Claude Code.
- Use one integrated terminal for Codex.
- Use the task runner for:
  - Back Office dashboard
  - Forgejo up/down
  - Forgejo repo bootstrap
- Keep the Source Control panel focused on the repo you are actively reviewing.

## Repo Remote Convention

- `origin` -> Forgejo private remote
- `github-public` -> optional GitHub mirror

Do not reverse those roles.

## Scripts

- [bootstrap-forgejo-repos.sh](/home/merm/projects/back-office/scripts/bootstrap-forgejo-repos.sh) creates the portfolio repos in Forgejo and can optionally set `origin`.
- [set-forgejo-remotes.sh](/home/merm/projects/back-office/scripts/set-forgejo-remotes.sh) normalizes `origin` to the local forge for the known portfolio repos.
- [mirror-public-repo.sh](/home/merm/projects/back-office/scripts/mirror-public-repo.sh) pushes only the repo and ref you choose to public GitHub.

## Best Practices

- Keep private work private by default.
- Use PR review even when the only reviewer is you.
- Keep deploy workflows readable and branch-gated.
- Prefer immutable image tags and explicit rollback inputs.
- Treat Back Office as the release cockpit and Forgejo as the review system.
