#!/bin/bash
# Reverses LAN remote access setup.
# Restores SSH, Samba configs from backups, disables services.
# Requires: sudo
set -euo pipefail

echo "=== Undoing Remote Access Setup ==="

# ── SSH ──────────────────────────────────────────────────────
echo "[1/3] Reverting SSH..."
if [ -f /etc/ssh/sshd_config.d/99-lan-access.conf ]; then
    sudo rm /etc/ssh/sshd_config.d/99-lan-access.conf
    sudo systemctl restart ssh
    echo "  SSH LAN config removed"
else
    echo "  No LAN config found"
fi

# ── Samba ────────────────────────────────────────────────────
echo "[2/3] Reverting Samba..."
SMB_CONFIG="/etc/samba/smb.conf"
if [ -f "${SMB_CONFIG}.bak.remote-access" ]; then
    sudo cp "${SMB_CONFIG}.bak.remote-access" "$SMB_CONFIG"
    sudo systemctl restart smbd
    echo "  Samba config restored from backup"
else
    echo "  No Samba backup found"
fi

# ── RDP ──────────────────────────────────────────────────────
echo "[3/3] RDP..."
echo "  RDP is managed via GNOME Settings — disable manually if desired"

echo ""
echo "=== Undo Complete ==="
