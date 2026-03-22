#!/usr/bin/env python3
"""Thin wrapper — delegates to backoffice package. Will be removed in Phase 3."""
import sys
from backoffice.server import main

# Parse --port and --target from argv so the old CLI interface still works.
port = 8070
target = None
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--port" and i + 1 < len(args):
        port = int(args[i + 1])
        i += 2
    elif args[i] == "--target" and i + 1 < len(args):
        target = args[i + 1]
        i += 2
    else:
        target = args[i]
        i += 1

sys.exit(main(port=port, target=target) or 0)
