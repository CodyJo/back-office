#!/usr/bin/env python3
"""Thin wrapper — delegates to backoffice package. Will be removed in Phase 3."""
import sys
from backoffice.regression import main
sys.exit(main(sys.argv[1:]) or 0)
