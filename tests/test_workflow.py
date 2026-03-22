"""Tests for backoffice.workflow."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from backoffice.workflow import (
    ALL_DEPARTMENTS,
    DEPARTMENT_SCRIPTS,
    FINDINGS_FILES,
    SCORE_FIELDS,
    build_parser,
    collect_target_snapshot,
    default_departments,
    extract_score,
    extract_scanned_at,
    handle_list_targets,
    handle_refresh,
    handle_run_all,
    handle_run_target,
    iso_now,
    load_targets,
    main,
    normalize_departments,
    qa_score_from_summary,
    read_json,
    refresh_dashboard_artifacts,
    resolve_target,
    summarize_department,
    with_run_lock,
    write_audit_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path, data):
    """Write a JSON fixture to *path*, creating parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _make_targets_yaml(path, targets):
    """Write a minimal targets.yaml file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump({"targets": targets}, f)


def _make_target(name="my-app", path="/tmp/my-app", departments=None, context=""):
    """Return a minimal target dict."""
    target = {"name": name, "path": path}
    if departments:
        target["default_departments"] = departments
    if context:
        target["context"] = context
    return target


# ---------------------------------------------------------------------------
# extract_scanned_at
# ---------------------------------------------------------------------------

class TestExtractScannedAt:
    def test_non_dict_returns_none(self):
        assert extract_scanned_at("not a dict") is None
        assert extract_scanned_at(None) is None

    def test_direct_scanned_at(self):
        assert extract_scanned_at({"scanned_at": "2026-01-01T00:00:00Z"}) == "2026-01-01T00:00:00Z"

    def test_direct_timestamp_fallback(self):
        assert extract_scanned_at({"timestamp": "2026-02-01T00:00:00Z"}) == "2026-02-01T00:00:00Z"

    def test_scanned_at_takes_precedence_over_timestamp(self):
        payload = {"scanned_at": "first", "timestamp": "second"}
        assert extract_scanned_at(payload) == "first"

    def test_metadata_audit_date(self):
        payload = {"metadata": {"auditDate": "2026-03-15"}}
        assert extract_scanned_at(payload) == "2026-03-15T00:00:00Z"

    def test_metadata_audit_date_snake_case(self):
        payload = {"metadata": {"audit_date": "2026-04-01"}}
        assert extract_scanned_at(payload) == "2026-04-01T00:00:00Z"

    def test_metadata_generated_at(self):
        payload = {"metadata": {"generated_at": "2026-05-01T12:00:00Z"}}
        assert extract_scanned_at(payload) == "2026-05-01T12:00:00Z"

    def test_metadata_generated_at_camel_case(self):
        payload = {"metadata": {"generatedAt": "2026-06-01T12:00:00Z"}}
        assert extract_scanned_at(payload) == "2026-06-01T12:00:00Z"

    def test_no_timestamp_returns_none(self):
        assert extract_scanned_at({"other": "data"}) is None

    def test_non_dict_metadata_ignored(self):
        payload = {"metadata": "not a dict"}
        assert extract_scanned_at(payload) is None

    def test_empty_audit_date_ignored(self):
        payload = {"metadata": {"auditDate": ""}}
        assert extract_scanned_at(payload) is None


# ---------------------------------------------------------------------------
# qa_score_from_summary
# ---------------------------------------------------------------------------

class TestQaScoreFromSummary:
    def test_non_dict_returns_none(self):
        assert qa_score_from_summary("not a dict") is None
        assert qa_score_from_summary(None) is None

    def test_perfect_score_no_findings(self):
        assert qa_score_from_summary({}) == 100

    def test_critical_deducts_15(self):
        assert qa_score_from_summary({"critical": 2}) == 100 - 30

    def test_high_deducts_8(self):
        assert qa_score_from_summary({"high": 3}) == 100 - 24

    def test_medium_deducts_3(self):
        assert qa_score_from_summary({"medium": 5}) == 100 - 15

    def test_low_deducts_1(self):
        assert qa_score_from_summary({"low": 10}) == 90

    def test_mixed_severities(self):
        summary = {"critical": 1, "high": 2, "medium": 3, "low": 4}
        expected = 100 - 15 - 16 - 9 - 4
        assert qa_score_from_summary(summary) == expected

    def test_floors_at_zero(self):
        assert qa_score_from_summary({"critical": 10}) == 0


# ---------------------------------------------------------------------------
# extract_score
# ---------------------------------------------------------------------------

class TestExtractScore:
    def test_qa_uses_qa_score_from_summary(self):
        payload = {}
        summary = {"critical": 1, "high": 0, "medium": 0, "low": 0}
        result = extract_score(payload, "qa", summary)
        assert result == 85  # 100 - 15

    def test_seo_from_summary_field(self):
        payload = {}
        summary = {"seo_score": 78}
        assert extract_score(payload, "seo", summary) == 78

    def test_ada_from_summary_compliance_score(self):
        payload = {}
        summary = {"compliance_score": 92}
        assert extract_score(payload, "ada", summary) == 92

    def test_monetization_from_summary(self):
        payload = {}
        summary = {"monetization_readiness_score": 65}
        assert extract_score(payload, "monetization", summary) == 65

    def test_product_from_summary(self):
        payload = {}
        summary = {"product_readiness_score": 70}
        assert extract_score(payload, "product", summary) == 70

    def test_fallback_to_metadata_fields(self):
        payload = {"metadata": {"seoScore": 88}}
        summary = {}
        assert extract_score(payload, "seo", summary) == 88

    def test_metadata_compliance_score(self):
        payload = {"metadata": {"complianceScore": 55}}
        summary = {}
        assert extract_score(payload, "compliance", summary) == 55

    def test_no_score_returns_none(self):
        assert extract_score({}, "seo", {}) is None

    def test_non_numeric_score_skipped(self):
        payload = {"metadata": {"seoScore": "high"}}
        assert extract_score(payload, "seo", {}) is None

    def test_summary_field_takes_precedence_over_metadata(self):
        payload = {"metadata": {"seoScore": 50}}
        summary = {"seo_score": 90}
        assert extract_score(payload, "seo", summary) == 90


# ---------------------------------------------------------------------------
# load_targets
# ---------------------------------------------------------------------------

class TestLoadTargets:
    def test_loads_from_yaml(self, tmp_path):
        config_path = str(tmp_path / "targets.yaml")
        targets = [{"name": "app", "path": "/tmp/app"}]
        _make_targets_yaml(config_path, targets)
        result = load_targets(config_path)
        assert len(result) == 1
        assert result[0]["name"] == "app"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_targets(str(tmp_path / "nonexistent.yaml"))

    def test_invalid_targets_type_raises(self, tmp_path):
        config_path = str(tmp_path / "targets.yaml")
        with open(config_path, "w") as f:
            yaml.safe_dump({"targets": "not a list"}, f)
        with pytest.raises(ValueError, match="must define a top-level"):
            load_targets(config_path)

    def test_empty_file_returns_empty(self, tmp_path):
        config_path = str(tmp_path / "targets.yaml")
        with open(config_path, "w") as f:
            f.write("")
        result = load_targets(config_path)
        assert result == []

    def test_loads_from_config_object(self):
        """When a Config with targets is passed, those are used directly."""
        from backoffice.config import Config, Target

        config = Config(
            targets={
                "my-repo": Target(
                    path="/home/user/my-repo",
                    language="python",
                    default_departments=["qa", "seo"],
                    context="A test repo",
                ),
            }
        )
        result = load_targets("/nonexistent/path", config=config)
        assert len(result) == 1
        assert result[0]["name"] == "my-repo"
        assert result[0]["path"] == "/home/user/my-repo"
        assert result[0]["default_departments"] == ["qa", "seo"]
        assert result[0]["context"] == "A test repo"

    def test_config_object_with_no_targets_falls_back_to_yaml(self, tmp_path):
        from backoffice.config import Config

        config = Config(targets={})
        config_path = str(tmp_path / "targets.yaml")
        _make_targets_yaml(config_path, [{"name": "fallback", "path": "/tmp/fb"}])
        result = load_targets(config_path, config=config)
        assert len(result) == 1
        assert result[0]["name"] == "fallback"


# ---------------------------------------------------------------------------
# normalize_departments
# ---------------------------------------------------------------------------

class TestNormalizeDepartments:
    def test_none_returns_all(self):
        result = normalize_departments(None)
        assert result == ALL_DEPARTMENTS

    def test_none_with_fallback(self):
        result = normalize_departments(None, ["qa", "seo"])
        assert result == ["qa", "seo"]

    def test_comma_separated_string(self):
        result = normalize_departments("qa, seo, ada")
        assert result == ["qa", "seo", "ada"]

    def test_list_input(self):
        result = normalize_departments(["qa", "product"])
        assert result == ["qa", "product"]

    def test_single_department_string(self):
        result = normalize_departments("qa")
        assert result == ["qa"]

    def test_unknown_department_raises(self):
        with pytest.raises(ValueError, match="Unknown departments"):
            normalize_departments("qa, invalid_dept")

    def test_empty_string_returns_empty(self):
        result = normalize_departments("")
        assert result == []

    def test_strips_whitespace(self):
        result = normalize_departments("  qa  ,  seo  ")
        assert result == ["qa", "seo"]


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------

class TestResolveTarget:
    def test_finds_target_by_name(self):
        targets = [_make_target("alpha"), _make_target("beta")]
        result = resolve_target(targets, "beta")
        assert result["name"] == "beta"

    def test_unknown_target_raises(self):
        targets = [_make_target("alpha")]
        with pytest.raises(ValueError, match="Unknown target: nope"):
            resolve_target(targets, "nope")

    def test_empty_targets_raises(self):
        with pytest.raises(ValueError, match="Unknown target"):
            resolve_target([], "anything")


# ---------------------------------------------------------------------------
# default_departments
# ---------------------------------------------------------------------------

class TestDefaultDepartments:
    def test_returns_target_departments(self):
        target = _make_target(departments=["qa", "seo"])
        assert default_departments(target) == ["qa", "seo"]

    def test_no_departments_returns_all(self):
        target = _make_target()
        assert default_departments(target) == ALL_DEPARTMENTS

    def test_string_departments_normalized(self):
        target = {"name": "x", "path": "/x", "default_departments": "qa,ada"}
        assert default_departments(target) == ["qa", "ada"]


# ---------------------------------------------------------------------------
# read_json
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_valid_file(self, tmp_path):
        p = str(tmp_path / "test.json")
        _write_json(p, {"key": "value"})
        assert read_json(p) == {"key": "value"}

    def test_missing_file_returns_none(self, tmp_path):
        assert read_json(str(tmp_path / "missing.json")) is None

    def test_malformed_json_returns_none(self, tmp_path):
        p = str(tmp_path / "bad.json")
        with open(p, "w") as f:
            f.write("{broken")
        assert read_json(p) is None


# ---------------------------------------------------------------------------
# iso_now
# ---------------------------------------------------------------------------

class TestIsoNow:
    def test_returns_iso_format(self):
        result = iso_now()
        assert "T" in result
        assert "+" in result or "Z" in result


# ---------------------------------------------------------------------------
# summarize_department
# ---------------------------------------------------------------------------

class TestSummarizeDepartment:
    def test_not_run_when_no_findings(self, tmp_path):
        repo_dir = str(tmp_path / "results" / "my-app")
        os.makedirs(repo_dir, exist_ok=True)
        result = summarize_department(repo_dir, "qa")
        assert result["status"] == "not-run"
        assert result["findings_total"] == 0
        assert result["score"] is None

    def test_complete_with_qa_findings(self, tmp_path):
        repo_dir = str(tmp_path / "results" / "my-app")
        os.makedirs(repo_dir, exist_ok=True)
        _write_json(
            os.path.join(repo_dir, "findings.json"),
            {
                "scanned_at": "2026-01-01T00:00:00Z",
                "summary": {"total": 2, "critical": 1, "high": 1, "medium": 0, "low": 0},
                "findings": [
                    {"id": "F1", "severity": "critical"},
                    {"id": "F2", "severity": "high"},
                ],
            },
        )
        result = summarize_department(repo_dir, "qa")
        assert result["status"] == "complete"
        assert result["findings_total"] == 2
        assert result["score"] == 100 - 15 - 8  # qa_score_from_summary
        assert result["scanned_at"] == "2026-01-01T00:00:00Z"

    def test_complete_with_seo_findings(self, tmp_path):
        repo_dir = str(tmp_path / "results" / "my-app")
        os.makedirs(repo_dir, exist_ok=True)
        _write_json(
            os.path.join(repo_dir, "seo-findings.json"),
            {
                "scanned_at": "2026-02-01T00:00:00Z",
                "summary": {"total": 3, "seo_score": 85},
                "findings": [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}],
            },
        )
        result = summarize_department(repo_dir, "seo")
        assert result["status"] == "complete"
        assert result["findings_total"] == 3
        assert result["score"] == 85

    def test_string_summary_handled(self, tmp_path):
        repo_dir = str(tmp_path / "results" / "my-app")
        os.makedirs(repo_dir, exist_ok=True)
        _write_json(
            os.path.join(repo_dir, "findings.json"),
            {
                "summary": "A textual summary",
                "findings": [{"id": "F1"}],
            },
        )
        result = summarize_department(repo_dir, "qa")
        assert result["status"] == "complete"
        assert result["summary_text"] == "A textual summary"
        assert result["findings_total"] == 1


# ---------------------------------------------------------------------------
# collect_target_snapshot
# ---------------------------------------------------------------------------

class TestCollectTargetSnapshot:
    def test_collects_all_departments(self, tmp_path):
        target = _make_target("my-app", departments=["qa", "seo"])
        results_dir = str(tmp_path / "results")
        repo_dir = os.path.join(results_dir, "my-app")
        os.makedirs(repo_dir, exist_ok=True)
        _write_json(
            os.path.join(repo_dir, "findings.json"),
            {"scanned_at": "2026-01-01T00:00:00Z", "summary": {"total": 1}, "findings": [{"id": "F1"}]},
        )
        snapshot = collect_target_snapshot(target, results_dir)
        assert snapshot["name"] == "my-app"
        assert len(snapshot["department_results"]) == 2
        assert snapshot["department_results"][0]["status"] == "complete"
        assert snapshot["department_results"][1]["status"] == "not-run"
        assert snapshot["latest_scan"] == "2026-01-01T00:00:00Z"

    def test_no_completed_departments(self, tmp_path):
        target = _make_target("empty-app", departments=["qa"])
        results_dir = str(tmp_path / "results")
        os.makedirs(os.path.join(results_dir, "empty-app"), exist_ok=True)
        snapshot = collect_target_snapshot(target, results_dir)
        assert snapshot["latest_scan"] is None

    def test_includes_context(self, tmp_path):
        target = _make_target("ctx-app", context="  Some context  ")
        results_dir = str(tmp_path / "results")
        os.makedirs(os.path.join(results_dir, "ctx-app"), exist_ok=True)
        snapshot = collect_target_snapshot(target, results_dir)
        assert snapshot["context"] == "Some context"


# ---------------------------------------------------------------------------
# write_audit_log
# ---------------------------------------------------------------------------

class TestWriteAuditLog:
    def test_writes_json_and_md_files(self, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        repo_dir = os.path.join(results_dir, "test-app")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        targets = [_make_target("test-app", departments=["qa"])]
        _write_json(
            os.path.join(repo_dir, "findings.json"),
            {"scanned_at": "2026-01-01T00:00:00Z", "summary": {"total": 1}, "findings": [{"id": "F1"}]},
        )

        write_audit_log(targets, results_dir, dashboard_dir)

        # Check JSON files
        json_path = os.path.join(results_dir, "local-audit-log.json")
        dash_json_path = os.path.join(dashboard_dir, "local-audit-log.json")
        assert os.path.exists(json_path)
        assert os.path.exists(dash_json_path)

        data = json.loads(open(json_path).read())
        assert "generated_at" in data
        assert len(data["targets"]) == 1
        assert data["targets"][0]["name"] == "test-app"

        # JSON files should be identical
        dash_data = json.loads(open(dash_json_path).read())
        assert data == dash_data

    def test_writes_md_files(self, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        repo_dir = os.path.join(results_dir, "test-app")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        targets = [_make_target("test-app", departments=["qa"])]
        _write_json(
            os.path.join(repo_dir, "findings.json"),
            {"scanned_at": "2026-01-01T00:00:00Z", "summary": {"total": 1}, "findings": [{"id": "F1"}]},
        )

        write_audit_log(targets, results_dir, dashboard_dir)

        md_path = os.path.join(results_dir, "local-audit-log.md")
        dash_md_path = os.path.join(dashboard_dir, "local-audit-log.md")
        assert os.path.exists(md_path)
        assert os.path.exists(dash_md_path)

        md_content = open(md_path).read()
        assert "# Local Audit Log" in md_content
        assert "## test-app" in md_content
        assert "status=`complete`" in md_content

        # MD files should be identical
        dash_md_content = open(dash_md_path).read()
        assert md_content == dash_md_content

    def test_includes_context_in_md(self, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        os.makedirs(os.path.join(results_dir, "ctx-app"), exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        targets = [_make_target("ctx-app", context="This is the context\nSecond line")]
        write_audit_log(targets, results_dir, dashboard_dir)

        md = open(os.path.join(results_dir, "local-audit-log.md")).read()
        assert "- Context: This is the context" in md
        # Only first line of context
        assert "Second line" not in md

    def test_recent_runs_from_history(self, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        history = [{"id": i, "status": "done"} for i in range(25)]
        _write_json(os.path.join(results_dir, ".jobs-history.json"), history)

        write_audit_log([], results_dir, dashboard_dir)

        data = json.loads(open(os.path.join(results_dir, "local-audit-log.json")).read())
        assert len(data["recent_runs"]) == 20  # last 20 only

    def test_score_text_in_md(self, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        repo_dir = os.path.join(results_dir, "scored-app")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        targets = [_make_target("scored-app", departments=["seo"])]
        _write_json(
            os.path.join(repo_dir, "seo-findings.json"),
            {"scanned_at": "2026-01-01T00:00:00Z", "summary": {"total": 0, "seo_score": 95}, "findings": []},
        )

        write_audit_log(targets, results_dir, dashboard_dir)

        md = open(os.path.join(results_dir, "local-audit-log.md")).read()
        assert "score=`95`" in md


# ---------------------------------------------------------------------------
# refresh_dashboard_artifacts
# ---------------------------------------------------------------------------

class TestRefreshDashboardArtifacts:
    @patch("backoffice.workflow.write_audit_log")
    @patch("backoffice.tasks.command_sync")
    @patch("backoffice.delivery.main")
    @patch("backoffice.aggregate.aggregate")
    def test_calls_all_three_modules(self, mock_aggregate, mock_delivery, mock_task_sync, mock_audit_log, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        targets = [_make_target("app")]

        with patch("backoffice.tasks._default_paths") as mock_paths:
            mock_paths.return_value = (
                Path(tmp_path / "config" / "task-queue.yaml"),
                Path(tmp_path / "config" / "targets.yaml"),
                Path(results_dir),
                Path(dashboard_dir),
            )
            refresh_dashboard_artifacts(targets, results_dir=results_dir, dashboard_dir=dashboard_dir)

        mock_aggregate.assert_called_once_with(
            results_dir, os.path.join(dashboard_dir, "data.json")
        )
        mock_delivery.assert_called_once_with(config=None)
        mock_task_sync.assert_called_once()
        mock_audit_log.assert_called_once_with(targets, results_dir, dashboard_dir)

    @patch("backoffice.workflow.write_audit_log")
    @patch("backoffice.tasks.command_sync")
    @patch("backoffice.delivery.main")
    @patch("backoffice.aggregate.aggregate")
    def test_passes_config_to_delivery(self, mock_aggregate, mock_delivery, mock_task_sync, mock_audit_log, tmp_path):
        results_dir = str(tmp_path / "results")
        dashboard_dir = str(tmp_path / "dashboard")
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(dashboard_dir, exist_ok=True)

        mock_config = MagicMock()
        targets = [_make_target("app")]

        with patch("backoffice.tasks._default_paths") as mock_paths:
            mock_paths.return_value = (
                Path(tmp_path / "config" / "task-queue.yaml"),
                Path(tmp_path / "config" / "targets.yaml"),
                Path(results_dir),
                Path(dashboard_dir),
            )
            refresh_dashboard_artifacts(targets, config=mock_config, results_dir=results_dir, dashboard_dir=dashboard_dir)

        mock_delivery.assert_called_once_with(config=mock_config)


# ---------------------------------------------------------------------------
# with_run_lock (file locking)
# ---------------------------------------------------------------------------

class TestWithRunLock:
    def test_acquires_lock_and_runs(self, tmp_path):
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)

        call_log = []

        @with_run_lock
        def test_fn(args, config=None):
            call_log.append("called")
            return 42

        args = argparse.Namespace(results_dir=results_dir)
        result = test_fn(args)
        assert result == 42
        assert call_log == ["called"]

    def test_lock_creates_results_dir(self, tmp_path):
        results_dir = str(tmp_path / "new_results")

        @with_run_lock
        def test_fn(args, config=None):
            return 0

        args = argparse.Namespace(results_dir=results_dir)
        test_fn(args)
        assert os.path.isdir(results_dir)

    def test_concurrent_lock_raises_value_error(self, tmp_path):
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)
        lock_path = os.path.join(results_dir, ".local-audit-run.lock")

        # Hold the lock externally
        with open(lock_path, "w") as held_lock:
            fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            @with_run_lock
            def test_fn(args, config=None):
                return 0

            args = argparse.Namespace(results_dir=results_dir)
            with pytest.raises(ValueError, match="Another local audit workflow"):
                test_fn(args)

    def test_passes_config_to_wrapped_function(self, tmp_path):
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)

        received_config = []

        @with_run_lock
        def test_fn(args, config=None):
            received_config.append(config)
            return 0

        args = argparse.Namespace(results_dir=results_dir)
        mock_cfg = MagicMock()
        test_fn(args, config=mock_cfg)
        assert received_config == [mock_cfg]


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_list_targets_command(self):
        parser = build_parser()
        args = parser.parse_args(["list-targets"])
        assert args.command == "list-targets"

    def test_refresh_command(self):
        parser = build_parser()
        args = parser.parse_args(["refresh"])
        assert args.command == "refresh"

    def test_run_target_command(self):
        parser = build_parser()
        args = parser.parse_args(["run-target", "--target", "my-app"])
        assert args.command == "run-target"
        assert args.target == "my-app"

    def test_run_target_with_departments(self):
        parser = build_parser()
        args = parser.parse_args(["run-target", "--target", "my-app", "--departments", "qa,seo"])
        assert args.departments == "qa,seo"

    def test_run_all_command(self):
        parser = build_parser()
        args = parser.parse_args(["run-all"])
        assert args.command == "run-all"

    def test_run_all_with_targets_and_departments(self):
        parser = build_parser()
        args = parser.parse_args(["run-all", "--targets", "a,b", "--departments", "qa"])
        assert args.targets == "a,b"
        assert args.departments == "qa"

    def test_custom_config_path(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "/custom/path.yaml", "list-targets"])
        assert args.config == "/custom/path.yaml"


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------

class TestMain:
    def test_list_targets_via_main(self, tmp_path):
        config_path = str(tmp_path / "targets.yaml")
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)
        _make_targets_yaml(config_path, [{"name": "app1", "path": "/tmp/app1"}])

        with patch("backoffice.workflow.RESULTS_DIR", results_dir):
            result = main(["--config", config_path, "list-targets"])
        assert result == 0

    def test_unknown_target_returns_1(self, tmp_path):
        config_path = str(tmp_path / "targets.yaml")
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)
        _make_targets_yaml(config_path, [{"name": "app1", "path": "/tmp/app1"}])

        with patch("backoffice.workflow.RESULTS_DIR", results_dir):
            result = main(["--config", config_path, "run-target", "--target", "nonexistent"])
        assert result == 1

    def test_missing_config_returns_1(self, tmp_path):
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)
        with patch("backoffice.workflow.RESULTS_DIR", results_dir):
            result = main(["--config", str(tmp_path / "no-such.yaml"), "list-targets"])
        assert result == 1

    def test_argv_defaults_to_none(self):
        """main() can be called with argv=None (uses sys.argv)."""
        with patch("sys.argv", ["workflow", "--config", "/dev/null", "list-targets"]):
            # /dev/null yields empty targets list; list-targets succeeds with 0
            result = main()
            assert result == 0

    def test_config_object_passed_through(self, tmp_path):
        """Config object is passed to handlers."""
        from backoffice.config import Config, Target

        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)

        config = Config(
            targets={
                "cfg-app": Target(path="/tmp/cfg-app", language="python"),
            }
        )

        with patch("backoffice.workflow.RESULTS_DIR", results_dir):
            result = main(["--config", "/dev/null", "list-targets"], config=config)
        assert result == 0


# ---------------------------------------------------------------------------
# handle_list_targets
# ---------------------------------------------------------------------------

class TestHandleListTargets:
    def test_lists_all_targets(self, tmp_path, caplog):
        config_path = str(tmp_path / "targets.yaml")
        results_dir = str(tmp_path / "results")
        os.makedirs(results_dir, exist_ok=True)
        _make_targets_yaml(config_path, [
            {"name": "alpha", "path": "/tmp/alpha"},
            {"name": "beta", "path": "/tmp/beta"},
        ])

        args = argparse.Namespace(config=config_path, results_dir=results_dir)
        import logging
        with caplog.at_level(logging.INFO, logger="backoffice.workflow"):
            result = handle_list_targets(args)

        assert result == 0
        messages = " ".join(r.message for r in caplog.records)
        assert "alpha" in messages
        assert "beta" in messages


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_all_departments_matches_scripts(self):
        assert ALL_DEPARTMENTS == list(DEPARTMENT_SCRIPTS.keys())

    def test_findings_files_cover_all_departments(self):
        assert set(FINDINGS_FILES.keys()) == set(ALL_DEPARTMENTS)

    def test_score_fields_subset_of_departments(self):
        # QA is handled separately, so SCORE_FIELDS should only cover non-QA
        assert "qa" not in SCORE_FIELDS
        for dept in SCORE_FIELDS:
            assert dept in ALL_DEPARTMENTS
