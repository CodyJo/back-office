# Forgejo Local Stack

This is the starter stack for running a private local forge for the Cody Jo portfolio.

It is intended to support:

- private git hosting
- PR review
- Actions workflows
- runner registration
- optional later Back Office integration

## Layout

- `compose.yaml` — Forgejo + PostgreSQL starter stack
- `.env.example` — local environment values to copy and edit

## Bring Up The Stack

1. Copy `.env.example` to `.env`
2. Adjust the values
3. Create the data directories:

```bash
mkdir -p data/forgejo data/conf data/postgres
sudo chown -R 1000:1000 data/forgejo data/conf
sudo chown -R 999:999 data/postgres
```

4. Start:

```bash
docker compose up -d
```

5. Open:

```text
http://localhost:3300
```

6. Complete the initial Forgejo setup in the browser.

## Important Notes

- This starter uses the rootless Forgejo image and PostgreSQL.
- The Forgejo docs recommend not running the runner on the same machine as the main Forgejo instance for stronger isolation. For a local-first single-user setup, you can still start that way and split it later.
- Keep public GitHub as a mirror, not the primary remote.

## SSH

The stack exposes Forgejo SSH on local port `2223`.

Example remote pattern after setup:

```bash
git remote set-url origin ssh://git@localhost:2223/CodyJo/fuel.git
```

## Runner

After Forgejo is up:

1. Bootstrap the local runner:

```bash
/home/merm/projects/back-office/scripts/bootstrap-forgejo-runner.sh
```

2. Use labels that match your workflow expectations, for example:

```text
self-hosted
linux
docker
```

Adjust labels if the workflows need something more specific.

## Next Integration Step

Back Office should grow a Forgejo adapter so the deploy dashboard can read:

- workflow run history
- runner availability
- PR state
- deploy dispatch status

without forcing the GitHub website into the loop.

## Portfolio Bootstrap

Once the admin account and API token exist, use the Back Office helper scripts:

```bash
export FORGEJO_BASE_URL=http://localhost:3300
export FORGEJO_TOKEN=replace-me
export FORGEJO_OWNER=CodyJo
/home/merm/projects/back-office/scripts/bootstrap-forgejo-repos.sh
```

To run Back Office in Forgejo mode:

```bash
cp /home/merm/projects/back-office/ops/forgejo-local/back-office.env.example \
  /home/merm/projects/back-office/ops/forgejo-local/back-office.env

/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh
```

To repoint local repos so `origin` becomes Forgejo:

```bash
export FORGEJO_SSH_HOST=localhost
export FORGEJO_SSH_PORT=2223
/home/merm/projects/back-office/scripts/set-forgejo-remotes.sh
```

To mirror only selected work to GitHub:

```bash
/home/merm/projects/back-office/scripts/mirror-public-repo.sh /home/merm/projects/fuel CodyJo/fuel main
```
