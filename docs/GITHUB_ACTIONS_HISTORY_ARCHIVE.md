# GitHub Actions History Archive

## What this is

This archives historical GitHub Actions metadata into Back Office so old workflow activity is available locally even after the repos move to Forgejo.

## Important boundary

- Git history moves into Forgejo by pushing branches and tags.
- GitHub Actions run history does not move into Forgejo automatically.
- Forgejo will show future local workflow runs.
- Old GitHub workflow runs need a separate archive if you want to keep them.

## Current local command

Run:

```bash
/home/merm/projects/back-office/scripts/archive-github-actions-history.sh
```

The script uses `gh api` and writes local JSON archives under:

```text
/home/merm/projects/back-office/results/github-actions-history/
```

Per repo it stores:

- `repo.json`
- `workflows.json`
- `runs.json`
- `runners.json`

It also writes:

- `summary.json`

## What gets preserved

- repo metadata from GitHub
- workflow definitions known to GitHub
- workflow run metadata
- runner metadata currently visible through the GitHub API

## What does not automatically get preserved

- full run logs
- full artifact payloads
- annotations rendered exactly like the GitHub web UI
- checks that were already expired on GitHub

If log retention matters, add a second pass that downloads logs while they still exist.

## Recommended use

1. Backfill git history into Forgejo.
2. Archive historical GitHub Actions metadata with this script.
3. Keep future private CI/CD in Forgejo.
4. Use Back Office as the long-term deploy and audit dashboard.
