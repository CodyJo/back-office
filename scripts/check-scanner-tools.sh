#!/usr/bin/env bash
# check-scanner-tools.sh — report which deterministic scanner binaries are installed.
#
# Missing tools don't block scans — backoffice/scanners emits an info-severity
# scanner-status finding per missing binary so coverage gaps surface in the
# dashboard. Run this before a fresh deployment to know what to install.

set -euo pipefail

TOOLS=(ruff bandit pip-audit semgrep gitleaks npm)

ok=0
missing=0
for tool in "${TOOLS[@]}"; do
  if command -v "$tool" &>/dev/null; then
    version=$("$tool" --version 2>&1 | head -1 || echo "?")
    printf "  OK  %-12s %s\n" "$tool" "$version"
    ok=$((ok + 1))
  else
    printf " MISS %-12s not in PATH\n" "$tool"
    missing=$((missing + 1))
  fi
done

echo ""
echo "Result: $ok installed, $missing missing"
if [ "$missing" -gt 0 ]; then
  echo "Install missing tools to maximize scanner coverage."
fi
