#!/usr/bin/env python3
"""Thin wrapper — delegates to backoffice package. Will be removed in Phase 3."""
import subprocess
import sys
result = subprocess.run([sys.executable, "-m", "backoffice"] + sys.argv[1:])
sys.exit(result.returncode)
