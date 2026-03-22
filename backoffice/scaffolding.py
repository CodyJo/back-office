"""Scaffold GitHub Actions workflow templates into a target repo.

Ports scripts/scaffold-github-workflows.py into the backoffice package.
Key changes from the original script:
- Uses Config.targets for target lookup when a Config is supplied.
- Accepts argv and config arguments in main() for testability.
- Uses structured logging instead of print().
- Template map and rendering logic are identical to the original.
"""
from __future__ import annotations

import argparse
import logging
import sys
import textwrap
from pathlib import Path

from backoffice.config import Config, Target

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = _REPO_ROOT / "templates" / "github-actions"

TEMPLATE_MAP: dict[str, tuple[str, str]] = {
    "ci": ("product-ci.yml", "ci.yml"),
    "preview": ("product-preview.yml", "preview.yml"),
    "cd": ("product-cd.yml", "cd.yml"),
    "nightly": ("nightly-backoffice.yml", "nightly-backoffice.yml"),
}


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def resolve_target(name: str, config: Config | None = None) -> dict:
    """Return a target dict for *name*.

    If *config* is supplied, look up the target from ``config.targets``
    (a ``dict[str, Target]``).  Otherwise fall back to loading the legacy
    ``config/targets.yaml`` file directly.

    Raises ``SystemExit`` if the target cannot be found.
    """
    if config is not None:
        target_obj: Target | None = config.targets.get(name)
        if target_obj is None:
            raise SystemExit(f"Unknown target: {name}")
        # Convert the frozen dataclass to a plain dict so the rest of the
        # module can treat it uniformly.
        return {
            "path": target_obj.path,
            "language": target_obj.language,
            "lint_command": target_obj.lint_command,
            "test_command": target_obj.test_command,
            "coverage_command": target_obj.coverage_command,
            "deploy_command": target_obj.deploy_command,
            "context": target_obj.context,
        }

    # Legacy path: read config/targets.yaml
    import yaml

    targets_path = _REPO_ROOT / "config" / "targets.yaml"
    try:
        with targets_path.open() as handle:
            payload = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        raise SystemExit(f"targets.yaml not found at {targets_path}")

    for target in payload.get("targets") or []:
        if target.get("name") == name:
            return target
    raise SystemExit(f"Unknown target: {name}")


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def normalize_build_command(target: dict) -> str:
    """Return the best available build command from *target*."""
    return (
        target.get("deploy_command")
        or target.get("test_command")
        or "echo 'set deploy command'"
    )


def render_template(template_name: str, target: dict, templates_dir: Path = TEMPLATES_DIR) -> str:
    """Read *template_name* from *templates_dir* and substitute placeholders."""
    template_path = templates_dir / template_name
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
        .replace("__LINT_COMMAND__", target.get("lint_command") or "echo 'set lint command'")
        .replace("__TEST_COMMAND__", target.get("test_command") or "echo 'set test command'")
        .replace("__BUILD_COMMAND__", normalize_build_command(target))
        .replace("__COVERAGE_STEP__", coverage_step)
    )


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


def write_workflow(
    target: dict,
    key: str,
    force: bool,
    templates_dir: Path = TEMPLATES_DIR,
) -> None:
    """Write a workflow file for *key* into the target repo.

    Skips the file if it already exists and *force* is ``False``.
    """
    template_name, output_name = TEMPLATE_MAP[key]
    repo_path = Path(target["path"])
    workflows_dir = repo_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    output_path = workflows_dir / output_name

    if output_path.exists() and not force:
        logger.info("skip %s (exists)", output_path)
        return

    output_path.write_text(render_template(template_name, target, templates_dir=templates_dir))
    logger.info("wrote %s", output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, config: Config | None = None) -> int:
    """Parse *argv* and scaffold workflow files into the resolved target repo."""
    parser = argparse.ArgumentParser(
        description="Scaffold GitHub Actions workflow templates into a target repo."
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target name from config/targets.yaml (or Config.targets)",
    )
    parser.add_argument(
        "--workflows",
        default="ci,preview,cd,nightly",
        help="Comma-separated subset: ci,preview,cd,nightly",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing workflow files",
    )
    args = parser.parse_args(argv)

    target = resolve_target(args.target, config=config)
    keys = [item.strip() for item in args.workflows.split(",") if item.strip()]
    invalid = [item for item in keys if item not in TEMPLATE_MAP]
    if invalid:
        raise SystemExit(f"Unknown workflow types: {', '.join(invalid)}")

    for key in keys:
        write_workflow(target, key, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
