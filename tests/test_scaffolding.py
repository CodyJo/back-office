"""Tests for backoffice.scaffolding."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backoffice.scaffolding import (
    TEMPLATE_MAP,
    normalize_build_command,
    render_template,
    resolve_target,
    write_workflow,
    main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a minimal set of workflow templates in a temp directory."""
    tdir = tmp_path / "templates"
    tdir.mkdir()
    for template_name, _ in TEMPLATE_MAP.values():
        (tdir / template_name).write_text(
            "lint: __LINT_COMMAND__\n"
            "test: __TEST_COMMAND__\n"
            "build: __BUILD_COMMAND__\n"
            "__COVERAGE_STEP__"
        )
    return tdir


@pytest.fixture
def minimal_target(tmp_path: Path) -> dict:
    """Return a target dict pointing at a writable temp directory."""
    repo = tmp_path / "my-repo"
    repo.mkdir()
    return {
        "path": str(repo),
        "lint_command": "npm run lint",
        "test_command": "npm test",
        "coverage_command": "",
        "deploy_command": "npm run deploy",
    }


@pytest.fixture
def coverage_target(tmp_path: Path) -> dict:
    """Return a target dict with a coverage command set."""
    repo = tmp_path / "cov-repo"
    repo.mkdir()
    return {
        "path": str(repo),
        "lint_command": "npm run lint",
        "test_command": "npm test",
        "coverage_command": "npm run coverage",
        "deploy_command": "",
    }


@pytest.fixture
def config_with_targets(tmp_path: Path):
    """Return a Config whose targets dict contains two named entries."""
    from backoffice.config import Config, Target

    repo_a = tmp_path / "repo-a"
    repo_a.mkdir()
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()

    return Config(
        root=tmp_path,
        targets={
            "repo-a": Target(
                path=str(repo_a),
                lint_command="flake8 .",
                test_command="pytest",
                coverage_command="pytest --cov",
                deploy_command="",
            ),
            "repo-b": Target(
                path=str(repo_b),
                lint_command="",
                test_command="",
                coverage_command="",
                deploy_command="make deploy",
            ),
        },
    )


# ---------------------------------------------------------------------------
# normalize_build_command
# ---------------------------------------------------------------------------


def test_normalize_uses_deploy_command_first():
    target = {"deploy_command": "make deploy", "test_command": "make test"}
    assert normalize_build_command(target) == "make deploy"


def test_normalize_falls_back_to_test_command():
    target = {"deploy_command": "", "test_command": "pytest"}
    assert normalize_build_command(target) == "pytest"


def test_normalize_falls_back_to_default_when_both_empty():
    assert normalize_build_command({}) == "echo 'set deploy command'"


# ---------------------------------------------------------------------------
# render_template — placeholder replacement
# ---------------------------------------------------------------------------


def test_render_replaces_lint_command(templates_dir: Path, minimal_target: dict):
    content = render_template("product-ci.yml", minimal_target, templates_dir=templates_dir)
    assert "npm run lint" in content
    assert "__LINT_COMMAND__" not in content


def test_render_replaces_test_command(templates_dir: Path, minimal_target: dict):
    content = render_template("product-ci.yml", minimal_target, templates_dir=templates_dir)
    assert "npm test" in content
    assert "__TEST_COMMAND__" not in content


def test_render_replaces_build_command(templates_dir: Path, minimal_target: dict):
    content = render_template("product-ci.yml", minimal_target, templates_dir=templates_dir)
    assert "npm run deploy" in content
    assert "__BUILD_COMMAND__" not in content


def test_render_no_coverage_step_when_command_empty(templates_dir: Path, minimal_target: dict):
    content = render_template("product-ci.yml", minimal_target, templates_dir=templates_dir)
    assert "__COVERAGE_STEP__" not in content
    # The placeholder should be replaced with an empty string, not a step block.
    assert "- name: Coverage" not in content


def test_render_includes_coverage_step_when_command_set(templates_dir: Path, coverage_target: dict):
    content = render_template("product-ci.yml", coverage_target, templates_dir=templates_dir)
    assert "- name: Coverage" in content
    assert "npm run coverage" in content
    assert "__COVERAGE_STEP__" not in content


def test_render_default_lint_command_when_missing(templates_dir: Path):
    target = {"path": "/tmp/x", "test_command": "pytest", "deploy_command": ""}
    content = render_template("product-ci.yml", target, templates_dir=templates_dir)
    assert "echo 'set lint command'" in content


def test_render_default_test_command_when_missing(templates_dir: Path):
    target = {"path": "/tmp/x", "lint_command": "flake8"}
    content = render_template("product-ci.yml", target, templates_dir=templates_dir)
    assert "echo 'set test command'" in content


# ---------------------------------------------------------------------------
# write_workflow — skip vs force
# ---------------------------------------------------------------------------


def test_write_workflow_creates_file(templates_dir: Path, minimal_target: dict):
    write_workflow(minimal_target, "ci", force=False, templates_dir=templates_dir)
    output = Path(minimal_target["path"]) / ".github" / "workflows" / "ci.yml"
    assert output.exists()
    assert "npm run lint" in output.read_text()


def test_write_workflow_skips_existing_without_force(templates_dir: Path, minimal_target: dict):
    output = Path(minimal_target["path"]) / ".github" / "workflows" / "ci.yml"
    output.parent.mkdir(parents=True, exist_ok=True)
    original = "original content"
    output.write_text(original)

    write_workflow(minimal_target, "ci", force=False, templates_dir=templates_dir)

    assert output.read_text() == original


def test_write_workflow_overwrites_with_force(templates_dir: Path, minimal_target: dict):
    output = Path(minimal_target["path"]) / ".github" / "workflows" / "ci.yml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("original content")

    write_workflow(minimal_target, "ci", force=True, templates_dir=templates_dir)

    assert output.read_text() != "original content"
    assert "npm run lint" in output.read_text()


def test_write_workflow_creates_workflows_dir(templates_dir: Path, minimal_target: dict):
    workflows_dir = Path(minimal_target["path"]) / ".github" / "workflows"
    assert not workflows_dir.exists()

    write_workflow(minimal_target, "nightly", force=False, templates_dir=templates_dir)

    assert workflows_dir.is_dir()


def test_write_workflow_logs_skip(templates_dir: Path, minimal_target: dict, caplog):
    import logging

    output = Path(minimal_target["path"]) / ".github" / "workflows" / "ci.yml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("exists")

    with caplog.at_level(logging.INFO, logger="backoffice.scaffolding"):
        write_workflow(minimal_target, "ci", force=False, templates_dir=templates_dir)

    assert any("skip" in r.message for r in caplog.records)


def test_write_workflow_logs_wrote(templates_dir: Path, minimal_target: dict, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="backoffice.scaffolding"):
        write_workflow(minimal_target, "ci", force=False, templates_dir=templates_dir)

    assert any("wrote" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# resolve_target — Config.targets path
# ---------------------------------------------------------------------------


def test_resolve_target_from_config(config_with_targets):
    target = resolve_target("repo-a", config=config_with_targets)
    assert target["lint_command"] == "flake8 ."
    assert target["test_command"] == "pytest"
    assert target["coverage_command"] == "pytest --cov"


def test_resolve_target_from_config_second_entry(config_with_targets):
    target = resolve_target("repo-b", config=config_with_targets)
    assert target["deploy_command"] == "make deploy"


def test_resolve_target_unknown_raises_system_exit(config_with_targets):
    with pytest.raises(SystemExit, match="Unknown target"):
        resolve_target("no-such-repo", config=config_with_targets)


def test_resolve_target_legacy_unknown_raises(tmp_path, monkeypatch):
    """When no config is passed and targets.yaml lacks the target, SystemExit is raised."""
    import yaml
    import backoffice.scaffolding as scaffolding

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    targets_yaml = config_dir / "targets.yaml"
    targets_yaml.write_text(yaml.dump({"targets": [{"name": "other", "path": "/tmp"}]}))
    monkeypatch.setattr(scaffolding, "_REPO_ROOT", tmp_path)

    with pytest.raises(SystemExit, match="Unknown target"):
        resolve_target("missing-target")


def test_resolve_target_legacy_found(tmp_path, monkeypatch):
    """When no config is passed and targets.yaml has the target, it is returned."""
    import yaml
    import backoffice.scaffolding as scaffolding

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    targets_yaml = config_dir / "targets.yaml"
    targets_yaml.write_text(
        yaml.dump({"targets": [{"name": "myrepo", "path": "/tmp/myrepo", "lint_command": "make lint"}]})
    )
    monkeypatch.setattr(scaffolding, "_REPO_ROOT", tmp_path)

    target = resolve_target("myrepo")
    assert target["path"] == "/tmp/myrepo"
    assert target["lint_command"] == "make lint"


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


def test_main_writes_ci_workflow(tmp_path, config_with_targets, templates_dir, monkeypatch):
    import backoffice.scaffolding as scaffolding

    monkeypatch.setattr(scaffolding, "TEMPLATES_DIR", templates_dir)

    ret = main(["--target", "repo-a", "--workflows", "ci"], config=config_with_targets)

    assert ret == 0
    output = Path(config_with_targets.targets["repo-a"].path) / ".github" / "workflows" / "ci.yml"
    assert output.exists()


def test_main_invalid_workflow_type_raises(config_with_targets):
    with pytest.raises(SystemExit, match="Unknown workflow types"):
        main(["--target", "repo-a", "--workflows", "invalid"], config=config_with_targets)


def test_main_force_flag_overwrites(tmp_path, config_with_targets, templates_dir, monkeypatch):
    import backoffice.scaffolding as scaffolding

    monkeypatch.setattr(scaffolding, "TEMPLATES_DIR", templates_dir)

    # First write without force
    main(["--target", "repo-a", "--workflows", "ci"], config=config_with_targets)
    output = Path(config_with_targets.targets["repo-a"].path) / ".github" / "workflows" / "ci.yml"
    output.write_text("stale content")

    # Second write with force should overwrite
    ret = main(["--target", "repo-a", "--workflows", "ci", "--force"], config=config_with_targets)
    assert ret == 0
    assert output.read_text() != "stale content"


def test_main_multiple_workflows(tmp_path, config_with_targets, templates_dir, monkeypatch):
    import backoffice.scaffolding as scaffolding

    monkeypatch.setattr(scaffolding, "TEMPLATES_DIR", templates_dir)

    ret = main(["--target", "repo-a", "--workflows", "ci,nightly"], config=config_with_targets)
    assert ret == 0

    workflows_dir = Path(config_with_targets.targets["repo-a"].path) / ".github" / "workflows"
    assert (workflows_dir / "ci.yml").exists()
    assert (workflows_dir / "nightly-backoffice.yml").exists()
