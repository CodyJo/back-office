# Autostart

Last updated: April 2, 2026

## Goal

Start the local platform automatically with your user session:

- Forgejo local stack
- Back Office in Forgejo mode

## Install

Run once:

```bash
/home/merm/projects/back-office/scripts/install-local-platform-autostart.sh
```

This installs user services into:

```text
~/.config/systemd/user/
```

And enables:

- `forgejo-local.service`
- `back-office-forgejo.service`

## Current State

Autostart is already installed and enabled on this machine for user `merm`.

Verified active services:

- `forgejo-local.service`
- `back-office-forgejo.service`

The current ownership model is:

- Forgejo is started by the user service
- Back Office on port `8070` is started by the user service

Do not also keep a separate manual Back Office process running on `8070`, or the service will fail to bind the port.

## What starts automatically

- Forgejo local Docker stack from:
  - `/home/merm/projects/back-office/ops/forgejo-local/compose.yaml`
- Back Office from:
  - `/home/merm/projects/back-office/scripts/run-back-office-forgejo.sh`

## URLs

- Back Office HQ: `http://127.0.0.1:8070/index.html`
- Back Office Deploy: `http://127.0.0.1:8070/deploy.html`
- Back Office Actions Archive: `http://127.0.0.1:8070/actions-history.html`
- Back Office Migration: `http://127.0.0.1:8070/migration.html`
- Forgejo: `http://127.0.0.1:3300/`

## Check status

```bash
systemctl --user status forgejo-local.service
systemctl --user status back-office-forgejo.service
```

## Restart manually

```bash
systemctl --user restart forgejo-local.service
systemctl --user restart back-office-forgejo.service
```

## Stop manually

```bash
systemctl --user stop back-office-forgejo.service
systemctl --user stop forgejo-local.service
```

## Disable autostart

```bash
systemctl --user disable --now back-office-forgejo.service
systemctl --user disable --now forgejo-local.service
```

## Boot without login

By default these start with your user session login.

If you want them to keep running even before you log in, enable linger:

```bash
sudo loginctl enable-linger "$USER"
```

That is optional and not required for normal desktop use.
