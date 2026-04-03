#!/bin/bash
# One-time setup for LAN remote access to borg.
# Configures: SSH (key-only, LAN-restricted), Samba (home + media), RDP (gnome-remote-desktop).
# Idempotent — safe to re-run.
# Requires: sudo
set -euo pipefail

echo "=== borg Remote Access Setup ==="
echo "This script configures SSH, Samba, and RDP for LAN access."
echo ""

# ── SSH ──────────────────────────────────────────────────────
echo "[1/3] Configuring SSH..."

if ! dpkg -l openssh-server &>/dev/null; then
    echo "  Installing openssh-server..."
    sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server
fi

# Backup original config
SSHD_CONFIG="/etc/ssh/sshd_config"
if [ ! -f "${SSHD_CONFIG}.bak.remote-access" ]; then
    sudo cp "$SSHD_CONFIG" "${SSHD_CONFIG}.bak.remote-access"
    echo "  Backed up $SSHD_CONFIG"
fi

# Create drop-in config for LAN access
sudo tee /etc/ssh/sshd_config.d/99-lan-access.conf > /dev/null << 'SSHEOF'
# LAN remote access config (managed by setup-remote-access.sh)
PasswordAuthentication no
PubkeyAuthentication yes
AllowUsers merm@10.0.0.0/24 merm@127.0.0.1
SSHEOF

sudo systemctl enable ssh
sudo systemctl restart ssh
echo "  SSH configured (key-only, LAN-restricted)"

# ── Samba ────────────────────────────────────────────────────
echo "[2/3] Configuring Samba..."

if ! dpkg -l samba &>/dev/null; then
    echo "  Installing samba..."
    sudo apt-get install -y -qq samba
fi

SMB_CONFIG="/etc/samba/smb.conf"
if [ ! -f "${SMB_CONFIG}.bak.remote-access" ]; then
    sudo cp "$SMB_CONFIG" "${SMB_CONFIG}.bak.remote-access"
    echo "  Backed up $SMB_CONFIG"
fi

# Check if our shares already exist
if ! grep -q '\[home\]' "$SMB_CONFIG" 2>/dev/null; then
    sudo tee -a "$SMB_CONFIG" > /dev/null << 'SMBEOF'

# ── LAN shares (managed by setup-remote-access.sh) ──
[home]
   comment = Home Directory
   path = /home/merm
   browseable = yes
   read only = no
   valid users = merm
   hosts allow = 10.0.0.0/24 127.0.0.1
   hosts deny = 0.0.0.0/0
   follow symlinks = yes
   wide links = yes

[media]
   comment = USB Drives
   path = /media/merm
   browseable = yes
   read only = no
   valid users = merm
   hosts allow = 10.0.0.0/24 127.0.0.1
   hosts deny = 0.0.0.0/0
   follow symlinks = yes
   wide links = yes
SMBEOF
    echo "  Samba shares added"
else
    echo "  Samba shares already configured"
fi

# Set Samba password for merm (prompts for password)
echo "  Setting Samba password for merm..."
sudo smbpasswd -a merm

sudo systemctl enable smbd
sudo systemctl restart smbd
echo "  Samba configured (home + media shares, LAN-restricted)"

# ── RDP (gnome-remote-desktop) ───────────────────────────────
echo "[3/3] Configuring RDP..."

# gnome-remote-desktop is already running on borg
if systemctl --user is-active gnome-remote-desktop.service &>/dev/null; then
    echo "  gnome-remote-desktop is already active"
    echo "  Configure RDP credentials via: Settings > Sharing > Remote Desktop"
    echo "  Or use: grdctl rdp set-credentials <username> <password>"
else
    echo "  gnome-remote-desktop not active. Start it via Settings > Sharing > Remote Desktop"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "From your laptop:"
echo "  SSH:    ssh merm@borg.local"
echo "  Files:  smb://borg.local/home"
echo "  USB:    smb://borg.local/media"
echo "  RDP:    borg.local:3389 (via Remmina)"
echo ""
echo "First: copy your laptop's SSH key to borg:"
echo "  ssh-copy-id merm@borg.local"
