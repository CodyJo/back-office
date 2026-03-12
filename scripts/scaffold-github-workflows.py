#!/usr/bin/env python3
"""Scaffold GitHub Actions workflow templates into a configured target repo."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS_PATH = REPO_ROOT / "config" / "targets.yaml"
TEMPLATES_DIR = REPO_ROOT / "templates" / "github-actions"

TEMPLATE_MAP = {
    "ci": ("product-ci.yml", "ci.yml"),
    "preview": ("product-preview.yml", "preview.yml"),
    "cd": ("product-cd.yml", "cd.yml"),
    "nightly": ("nightly-backoffice.yml", "nightly-backoffice.yml"),
}


def load_targets() -> list[dict]:
    with TARGETS_PATH.open() as handle:
        payload = yaml.safe_load(handle) or {}
    return payload.get("targets") or []


def resolve_target(name: str) -> dict:
    for target in load_targets():
        if target.get("name") == name:
            return target
    raise SystemExit(f"Unknown target: {name}")


def normalize_build_command(target: dict) -> str:
    return target.get("deploy_command") or target.get("test_command") or "echo 'set deploy command'"


def render_template(template_name: str, target: dict) -> str:
    template_path = TEMPLATES_DIR / template_name
    content = template_path.read_text()
    coverage_command = str(target.get("coverage_command", "")).strip()
    coverage_step = ""
    if coverage_command:
        coverage_step = textwrap.dedent(
            f"""\
                  - name: Coverage
                    run: {coverage_command}
            """
        )
    return (
        content
        .replace("__LINT_COMMAND__", target.get("lint_command", "echo 'set lint command'"))
        .replace("__TEST_COMMAND__", target.get("test_command", "echo 'set test command'"))
        .replace("__BUILD_COMMAND__", normalize_build_command(target))
        .replace("__COVERAGE_STEP__", coverage_step)
    )


def write_workflow(target: dict, key: str, force: bool) -> None:
    template_name, output_name = TEMPLATE_MAP[key]
    repo_path = Path(target["path"])
    workflows_dir = repo_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    output_path = workflows_dir / output_name
    if output_path.exists() and not force:
        print(f"skip {output_path} (exists)")
        return
    output_path.write_text(render_template(template_name, target))
    print(f"wrote {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, help="Target name from config/targets.yaml")
    parser.add_argument(
        "--workflows",
        default="ci,preview,cd,nightly",
        help="Comma-separated subset: ci,preview,cd,nightly",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing workflow files")
    args = parser.parse_args()

    target = resolve_target(args.target)
    keys = [item.strip() for item in args.workflows.split(",") if item.strip()]
    invalid = [item for item in keys if item not in TEMPLATE_MAP]
    if invalid:
      raise SystemExit(f"Unknown workflow types: {', '.join(invalid)}")

    for key in keys:
        write_workflow(target, key, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
