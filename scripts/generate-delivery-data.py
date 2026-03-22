#!/usr/bin/env python3
"""Thin wrapper — delegates to backoffice package. Will be removed in Phase 3."""
import sys
from backoffice.delivery import main
sys.exit(main() or 0)
