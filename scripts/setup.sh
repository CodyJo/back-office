#!/usr/bin/env bash
# Back Office — Initial Setup
# Usage: ./scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QA_ROOT="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Back Office — Setup                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────

echo "Checking prerequisites..."

missing=()
if [ -n "${BACK_OFFICE_AGENT_RUNNER:-}" ]; then
  agent_bin="${BACK_OFFICE_AGENT_RUNNER%% *}"
  command -v "$agent_bin" &>/dev/null || missing+=("$agent_bin (configured BACK_OFFICE_AGENT_RUNNER)")
else
  command -v claude &>/dev/null || missing+=("an agent CLI via BACK_OFFICE_AGENT_RUNNER or claude")
fi
command -v git      &>/dev/null || missing+=("git")
command -v python3  &>/dev/null || missing+=("python3")
command -v aws      &>/dev/null || missing+=("aws (AWS CLI)")

if [ ${#missing[@]} -gt 0 ]; then
  echo ""
  echo "Missing required tools:"
  for m in "${missing[@]}"; do
    echo "  - $m"
  done
  echo ""
  echo "Install these before continuing."
  exit 1
fi

echo "  All prerequisites found."
echo ""

# ── Create config from examples ──────────────────────────────────────────────

if [ ! -f "$QA_ROOT/config/qa-config.yaml" ]; then
  cp "$QA_ROOT/config/qa-config.example.yaml" "$QA_ROOT/config/qa-config.yaml"
  echo "Created config/qa-config.yaml — edit this with your AWS settings"
else
  echo "config/qa-config.yaml already exists"
fi

if [ ! -f "$QA_ROOT/config/targets.yaml" ]; then
  cp "$QA_ROOT/config/targets.example.yaml" "$QA_ROOT/config/targets.yaml"
  echo "Created config/targets.yaml — add your target repositories"
else
  echo "config/targets.yaml already exists"
fi

# ── Make scripts executable ──────────────────────────────────────────────────

chmod +x "$QA_ROOT/agents/"*.sh
chmod +x "$QA_ROOT/scripts/"*.sh 2>/dev/null || true
echo "Made scripts executable"

# ── Create results directory ─────────────────────────────────────────────────

mkdir -p "$QA_ROOT/results"
echo "Created results/ directory"

# ── Install Python deps ──────────────────────────────────────────────────────

if ! python3 -c "import yaml" 2>/dev/null; then
  echo ""
  echo "Installing PyYAML..."
  pip3 install --quiet pyyaml
fi

echo ""
echo "Setup complete! Next steps:"
echo ""
echo "  1. Edit config/qa-config.yaml with your AWS settings"
echo "  2. Edit config/targets.yaml with your target repositories"
echo "  3. Optionally set BACK_OFFICE_AGENT_RUNNER / BACK_OFFICE_AGENT_MODE"
echo "  4. Run: make qa TARGET=/path/to/repo"
echo "  5. Run: make fix TARGET=/path/to/repo"
echo ""
echo "For AWS dashboard deployment:"
echo "  cd terraform && terraform init && terraform apply"
echo "  make dashboard"
echo ""
