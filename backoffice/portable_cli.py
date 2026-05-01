"""``python -m backoffice {export,import} ...`` CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from backoffice.config import load_config
from backoffice.portable import (
    ExportSelection,
    apply_payload,
    export_json,
    export_payload,
    validate_payload,
)
from backoffice.store import FileStore


def export_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backoffice export")
    parser.add_argument("--out", default="-", help="Output path or '-' for stdout")
    parser.add_argument("--no-agents", action="store_true")
    parser.add_argument("--no-routines", action="store_true")
    parser.add_argument("--no-budgets", action="store_true")
    parser.add_argument("--no-dashboard-targets", action="store_true")
    parser.add_argument("--no-autonomy", action="store_true")
    args = parser.parse_args(argv)

    config = load_config()
    store = FileStore(root=config.root)

    # Re-read the raw YAML so the export sees the literal config (incl
    # the budgets/agents/routines blocks the operator wrote).
    config_path = config.root / "config" / "backoffice.yaml"
    raw_yaml: dict = {}
    if config_path.exists():
        try:
            raw_yaml = yaml.safe_load(config_path.read_text()) or {}
        except yaml.YAMLError:
            raw_yaml = {}

    selection = ExportSelection(
        include_agents=not args.no_agents,
        include_routines=not args.no_routines,
        include_budgets=not args.no_budgets,
        include_dashboard_targets=not args.no_dashboard_targets,
        include_autonomy=not args.no_autonomy,
    )
    payload = export_payload(store=store, config_payload=raw_yaml, selection=selection)
    text = export_json(payload)

    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text)
    return 0


def import_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backoffice import")
    parser.add_argument("path", help="Path to the export JSON")
    parser.add_argument("--apply", action="store_true",
                        help="Apply the import (default: dry-run only)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace existing records on conflict")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read import file: {exc}", file=sys.stderr)
        return 2

    errors = validate_payload(payload)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    config = load_config()
    store = FileStore(root=config.root)

    plan = apply_payload(
        payload,
        store=store,
        dry_run=not args.apply,
        overwrite=args.overwrite,
    )
    print(json.dumps(plan.to_dict(), indent=2))
    if plan.errors:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    if "--import" in sys.argv:
        sys.exit(import_main([a for a in sys.argv[1:] if a != "--import"]))
    sys.exit(export_main(sys.argv[1:]))
