#!/usr/bin/env python3
"""Thin wrapper — delegates to backoffice package. Will be removed in Phase 3."""
import sys
from backoffice.aggregate import main
argv = sys.argv[1:]
sys.exit(main(*argv) or 0)
