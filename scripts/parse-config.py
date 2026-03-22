#!/usr/bin/env python3
"""Thin wrapper — agent scripts call this for target field lookups.
Delegates to backoffice.config.shell_export with null-delimited output.
"""
import sys

def main():
    if len(sys.argv) < 4:
        print("Usage: parse-config.py <config_path> <repo_name> <target_repo> <field1> [field2 ...]",
              file=sys.stderr)
        sys.exit(1)

    repo_name = sys.argv[2]
    target_repo = sys.argv[3]
    fields = sys.argv[4:] if len(sys.argv) > 4 else []
    if not fields:
        sys.exit(0)

    try:
        from backoffice.config import load_config, shell_export
        cfg = load_config()
    except Exception:
        sys.stdout.write("\0".join([""] * len(fields)))
        sys.exit(0)

    target_name = None
    for name, target in cfg.targets.items():
        if name == repo_name or target.path == target_repo:
            target_name = name
            break

    sys.stdout.write(shell_export(cfg, target_name=target_name, fields=fields))

if __name__ == "__main__":
    main()
