#!/usr/bin/env python3
"""Regression tests for CLI dispatch, workflow scaffolding, and config parsing."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import yaml


def check(name, condition, detail=""):
    if condition:
        return True
    message = f"FAIL: {name}"
    if detail:
        message += f" ({detail})"
    raise AssertionError(message)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_parse_config_tests(repo_root: Path) -> None:
    script = repo_root / "scripts" / "parse-config.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        config_path = tmpdir / "targets.yaml"
        payload = {
            "targets": [
                {
                    "name": "bible-app",
                    "path": "/tmp/bible-app",
                    "context": "Safe context",
                    "lint_command": "npm run lint",
                    "test_command": "npm test",
                    "deploy_command": "npm run build && npm run deploy",
                }
            ]
        }
        config_path.write_text(yaml.safe_dump(payload, sort_keys=False))

        completed = subprocess.run(
            [
                "python3",
                str(script),
                str(config_path),
                "bible-app",
                "/tmp/bible-app",
                "context",
                "lint_command",
                "deploy_command",
            ],
            check=True,
            capture_output=True,
            text=False,
        )
        values = completed.stdout.decode().split("\0")
        check("parse_config_safe_context", values[0] == "Safe context", repr(values))
        check("parse_config_safe_lint", values[1] == "npm run lint", repr(values))
        check("parse_config_rejects_unsafe_deploy", values[2] == "", repr(values))
        check("parse_config_warns_on_rejection", b"rejected unsafe config value" in completed.stderr)

        missing = subprocess.run(
            [
                "python3",
                str(script),
                str(config_path.with_name("missing.yaml")),
                "bible-app",
                "/tmp/bible-app",
                "context",
            ],
            check=True,
            capture_output=True,
            text=False,
        )
        check("parse_config_missing_file_empty_output", missing.stdout.decode() == "")


def run_scaffolding_tests(repo_root: Path) -> None:
    module = load_module("scaffold_github_workflows", repo_root / "scripts" / "scaffold-github-workflows.py")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        target_repo = tmpdir / "bible-app"
        target_repo.mkdir()
        targets_path = tmpdir / "targets.yaml"
        targets_path.write_text(
            yaml.safe_dump(
                {
                    "targets": [
                        {
                            "name": "bible-app",
                            "path": str(target_repo),
                            "lint_command": "npm run lint",
                            "test_command": "npm test",
                            "deploy_command": "npm run build",
                        }
                    ]
                },
                sort_keys=False,
            )
        )

        with mock.patch.object(module, "TARGETS_PATH", targets_path):
            target = module.resolve_target("bible-app")
            rendered = module.render_template("product-ci.yml", target)
            check("scaffold_renders_lint", "npm run lint" in rendered)
            check("scaffold_renders_test", "npm test" in rendered)
            check("scaffold_renders_build", "npm run build" in rendered)

            module.write_workflow(target, "ci", force=False)
            workflow_path = target_repo / ".github" / "workflows" / "ci.yml"
            check("scaffold_writes_ci_file", workflow_path.exists())

            original = workflow_path.read_text()
            workflow_path.write_text("keep me\n")
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                module.write_workflow(target, "ci", force=False)
            check("scaffold_skip_existing", "skip" in capture.getvalue())
            check("scaffold_preserves_existing", workflow_path.read_text() == "keep me\n")

            module.write_workflow(target, "ci", force=True)
            check("scaffold_force_overwrites", workflow_path.read_text() == original)

            try:
                with mock.patch("sys.argv", ["scaffold-github-workflows.py", "--target", "bible-app", "--workflows", "ci,bad"]):
                    module.main()
            except SystemExit as exc:
                check("scaffold_rejects_invalid_workflow", "Unknown workflow types" in str(exc))
            else:
                raise AssertionError("FAIL: scaffold_rejects_invalid_workflow")


def run_cli_tests(repo_root: Path) -> None:
    module = load_module("backoffice_cli", repo_root / "scripts" / "backoffice-cli.py")

    commands: list[list[str]] = []

    def fake_run_commands(batch: list[list[str]]) -> int:
        commands.extend(batch)
        return 0

    with mock.patch.object(module, "run_commands", side_effect=fake_run_commands):
        check("cli_audit_all_deploy", module.main(["audit-all", "--targets", "bible-app", "--deploy"]) == 0)
        check(
            "cli_audit_all_batch",
            commands == [
                ["python3", "scripts/local_audit_workflow.py", "run-all", "--targets", "bible-app"],
                ["bash", "scripts/sync-dashboard.sh"],
            ],
            json.dumps(commands),
        )

    commands.clear()
    with mock.patch.object(module, "run_commands", side_effect=fake_run_commands):
        check("cli_audit_deploy", module.main(["audit", "--target", "bible-app", "--departments", "qa,product", "--deploy"]) == 0)
        check(
            "cli_audit_batch",
            commands == [
                ["python3", "scripts/local_audit_workflow.py", "run-target", "--target", "bible-app", "--departments", "qa,product"],
                ["bash", "scripts/sync-dashboard.sh"],
            ],
            json.dumps(commands),
        )


def run_setup_tests(repo_root: Path) -> None:
    module = load_module("backoffice_setup", repo_root / "scripts" / "backoffice_setup.py")

    with tempfile.TemporaryDirectory(dir=repo_root) as tmp:
        tmpdir = Path(tmp)
        runner_config = tmpdir / "agent-runner.env"

        with mock.patch.object(module, "RUNNER_CONFIG", runner_config), mock.patch("shutil.which", return_value="/usr/bin/codex"):
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                module.persist_runner_config("codex", "codex --profile default", None)
            written = runner_config.read_text()
            check("setup_persists_runner_command", 'BACK_OFFICE_AGENT_RUNNER="codex --profile default"' in written)
            check("setup_defaults_codex_mode", 'BACK_OFFICE_AGENT_MODE="stdin-text"' in written)
            loaded = module.load_runner_config_file()
            check("setup_loads_persisted_runner", loaded["BACK_OFFICE_AGENT_RUNNER"] == "codex --profile default", repr(loaded))
            check("setup_loads_persisted_mode", loaded["BACK_OFFICE_AGENT_MODE"] == "stdin-text", repr(loaded))


def main():
    repo_root = Path(__file__).resolve().parents[1]
    run_parse_config_tests(repo_root)
    run_scaffolding_tests(repo_root)
    run_cli_tests(repo_root)
    run_setup_tests(repo_root)
    print("cli/scaffolding tests passed")


if __name__ == "__main__":
    main()
