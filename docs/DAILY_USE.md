# Daily Use

Last updated: April 2, 2026

## Core URLs

- Back Office HQ: `http://127.0.0.1:8070/index.html`
- Back Office Deploy: `http://127.0.0.1:8070/deploy.html`
- Back Office Actions Archive: `http://127.0.0.1:8070/actions-history.html`
- Back Office Migration: `http://127.0.0.1:8070/migration.html`
- Forgejo: `http://127.0.0.1:3300/`

Use `127.0.0.1` instead of `localhost`.
Use `http` for Forgejo, not `https`.

## Start The Local Platform

Autostart is already enabled on this machine, so after login these should normally already be running.

If you need to start them manually:

Start Forgejo:

```bash
cd /home/merm/projects/back-office/ops/forgejo-local
docker compose up -d
```

Start Back Office:

```bash
/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh
```

For automatic startup on login, read [AUTOSTART.md](/home/merm/projects/back-office/docs/AUTOSTART.md).

Check service status:

```bash
systemctl --user status forgejo-local.service
systemctl --user status back-office-forgejo.service
```

## Daily Loop

1. Open VSCodium on [/home/merm/projects/codyjo-local-platform.code-workspace](/home/merm/projects/codyjo-local-platform.code-workspace).
2. Open Forgejo and Back Office in the browser.
3. Work in a repo on a short-lived branch.
4. Commit locally.
5. Push to Forgejo `origin`.
6. Open or update the PR in Forgejo.
7. Review before merge.
8. Watch deploy readiness in Back Office.
9. Deploy from Back Office when the repo is ready.
10. Mirror to GitHub only if you want that code or ref public.

## Commit And Push

```bash
cd /home/merm/projects/<repo>
git checkout -b my-change
git add .
git commit -m "describe change"
git push origin HEAD
```

`origin` should point to local Forgejo.

## Review And Deploy

- Use Forgejo for branch review and PR review.
- Use Back Office HQ for portfolio visibility.
- Use Back Office Deploy for deploy status and dispatch.
- Use Back Office Actions Archive to compare current local workflows with old GitHub workflow history.

## If Something Is Down

Forgejo not loading:

```bash
cd /home/merm/projects/back-office/ops/forgejo-local
docker compose up -d
```

Back Office not loading:

```bash
systemctl --user restart back-office-forgejo.service
```

If you intentionally want to run Back Office by hand for debugging, stop the service first so port `8070` is free:

```bash
systemctl --user stop back-office-forgejo.service
```

Forgejo login details:

```bash
cat /home/merm/projects/back-office/ops/forgejo-local/admin-credentials.txt
```

## Working Rules

- Keep private work in Forgejo by default.
- Treat Forgejo PR review as the safety gate for AI-authored changes.
- Use Back Office as the operator cockpit.
- Keep GitHub mirror-only unless you intentionally want something public.
- Deploy from reviewed branches only.
