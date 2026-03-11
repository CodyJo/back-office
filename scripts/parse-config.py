#!/usr/bin/env python3
"""Safe YAML config parser for agent scripts.

Reads targets.yaml and outputs null-delimited values for the requested
fields, validated to be shell-safe (no command injection).

Usage:
    python3 scripts/parse-config.py <config_path> <repo_name> <target_repo> <field1> [field2 ...]

Output:
    Null-delimited values for the requested fields, safe for use with
    bash `mapfile -d '' -t`.

Example:
    mapfile -d '' -t _cfg < <(
        python3 scripts/parse-config.py "$QA_ROOT/config/targets.yaml" \
            "$REPO_NAME" "$TARGET_REPO" context lint_command test_command
    )
"""

import os
import re
import sys


def is_shell_safe(value: str) -> bool:
    """Reject values containing shell metacharacters that could enable injection."""
    # Allow empty strings
    if not value:
        return True
    # Block dangerous shell metacharacters
    dangerous = re.compile(r'[;|&`$(){}!\\\n\r]')
    return not dangerous.search(value)


def sanitize_value(value: str) -> str:
    """Return the value if safe, empty string otherwise."""
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    if is_shell_safe(value):
        return value
    # Log rejection to stderr but don't fail the script
    print(f"Warning: rejected unsafe config value: {value!r}", file=sys.stderr)
    return ""


def main():
    if len(sys.argv) < 4:
        print("Usage: parse-config.py <config_path> <repo_name> <target_repo> <field1> [field2 ...]",
              file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    repo_name = sys.argv[2]
    target_repo = sys.argv[3]
    fields = sys.argv[4:] if len(sys.argv) > 4 else []

    if not fields:
        sys.exit(0)

    try:
        import yaml
    except ImportError:
        # No PyYAML — output empty values
        sys.stdout.write("\0".join([""] * len(fields)))
        sys.exit(0)

    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"Warning: could not read config {config_path}: {e}", file=sys.stderr)
        sys.stdout.write("\0".join([""] * len(fields)))
        sys.exit(0)

    values = [""] * len(fields)
    for t in cfg.get("targets", []):
        if t.get("name") == repo_name or t.get("path", "") == target_repo:
            for i, field in enumerate(fields):
                raw = t.get(field, "")
                values[i] = sanitize_value(raw)
            break

    sys.stdout.write("\0".join(values))


if __name__ == "__main__":
    main()
