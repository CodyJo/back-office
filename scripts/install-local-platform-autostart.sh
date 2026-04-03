#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/merm/projects/back-office"
UNIT_SOURCE_DIR="${ROOT_DIR}/systemd-user"
UNIT_TARGET_DIR="${HOME}/.config/systemd/user"

mkdir -p "${UNIT_TARGET_DIR}"

install -m 0644 "${UNIT_SOURCE_DIR}/forgejo-local.service" "${UNIT_TARGET_DIR}/forgejo-local.service"
install -m 0644 "${UNIT_SOURCE_DIR}/back-office-forgejo.service" "${UNIT_TARGET_DIR}/back-office-forgejo.service"

/usr/bin/systemctl --user daemon-reload
/usr/bin/systemctl --user enable --now forgejo-local.service
/usr/bin/systemctl --user enable --now back-office-forgejo.service

cat <<'EOF'
Installed and enabled:
- forgejo-local.service
- back-office-forgejo.service

These user services now start with your login session.

Optional for boot-without-login:
  sudo loginctl enable-linger "$USER"
EOF
