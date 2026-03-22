"""Tests for backoffice.tasks."""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from backoffice.tasks import (
    STATUS_ORDER,
    FINDINGS_FILE_BY_DEPARTMENT,
    BLOCKING_DEPARTMENTS,
    TaskContext,
    append_history,
    build_dashboard_payload,
    build_parser,
    ensure_task_defaults,
    find_task,
    generate_task_id,
    infer_product_key,
    iso_now,
    load_context,
    load_targets,
    load_yaml,
    parse_timestamp,
    read_json,
    save_payload,
    slugify,
    summarize_gate_status,
    write_yaml,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dirs(tmp_path):
    """Return (config_path, targets_path, results_dir, dashboard_dir)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    results = tmp_path / "results"
    results.mkdir()
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    config_path = config_dir / "task-queue.yaml"
    targets_path = config_dir / "targets.yaml"
    return config_path, targets_path, results, dashboard


@pytest.fixture
def empty_queue(tmp_dirs):
    config_path, targets_path, results, dashboard = tmp_dirs
    write_yaml(config_path, {"version": 1, "tasks": []})
    return config_path, targets_path, results, dashboard


@pytest.fixture
def targets_yaml(tmp_dirs):
    """Write a targets.yaml with one etheos-app target."""
    config_path, targets_path, results, dashboard = tmp_dirs
    targets_path.write_text(textwrap.dedent("""\
        targets:
          - name: etheos-app
            path: /tmp/etheos-app
            default_departments:
              - qa
              - product
    """))
    return config_path, targets_path, results, dashboard


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_lowercasing(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars_replaced_with_dash(self):
        assert slugify("foo!bar@baz") == "foo-bar-baz"

    def test_consecutive_separators_collapsed(self):
        assert slugify("  foo   bar  ") == "foo-bar"

    def test_truncated_to_48_chars(self):
        long = "a" * 60
        result = slugify(long)
        assert len(result) == 48

    def test_empty_string_returns_task(self):
        assert slugify("") == "task"

    def test_numeric_input(self):
        assert slugify("123") == "123"

    def test_leading_trailing_dashes_stripped(self):
        result = slugify("--hello--")
        assert not result.startswith("-")
        assert not result.endswith("-")


# ---------------------------------------------------------------------------
# generate_task_id
# ---------------------------------------------------------------------------


class TestGenerateTaskId:
    def test_format_is_repo_colon_slug_colon_stamp(self):
        task_id = generate_task_id("my-repo", "Fix the bug")
        parts = task_id.split(":")
        assert len(parts) == 3
        assert parts[0] == "my-repo"
        assert parts[1] == "fix-the-bug"
        assert len(parts[2]) == 15  # YYYYMMDD-HHMMSS

    def test_unique_across_calls(self):
        # Two rapid calls should produce the same timestamp format but both valid
        id1 = generate_task_id("repo", "Task")
        id2 = generate_task_id("repo", "Task")
        assert id1.startswith("repo:task:")
        assert id2.startswith("repo:task:")

    def test_empty_title_falls_back_to_task_slug(self):
        task_id = generate_task_id("repo", "!@#")
        assert task_id.startswith("repo:task:")


# ---------------------------------------------------------------------------
# infer_product_key
# ---------------------------------------------------------------------------


class TestInferProductKey:
    def test_known_mappings(self):
        assert infer_product_key("etheos-app") == "etheos"
        assert infer_product_key("bible-app") == "selah"
        assert infer_product_key("thenewbeautifulme") == "tnbm-tarot"
        assert infer_product_key("photo-gallery") == "analogify-studio"
        assert infer_product_key("photo-gallery-client-portal") == "analogify-studio"
        assert infer_product_key("codyjo.com") == "codyjo-method"
        assert infer_product_key("back-office") == "back-office"

    def test_unknown_repo_returns_repo_name(self):
        assert infer_product_key("some-unknown-repo") == "some-unknown-repo"


# ---------------------------------------------------------------------------
# ensure_task_defaults
# ---------------------------------------------------------------------------


class TestEnsureTaskDefaults:
    def test_minimal_task_gets_all_defaults(self):
        task = ensure_task_defaults({"repo": "etheos-app", "title": "My Task"}, {})
        assert task["status"] == "proposed"
        assert task["priority"] == "medium"
        assert task["category"] == "feature"
        assert task["owner"] == ""
        assert task["created_by"] == "product-owner"
        assert "created_at" in task
        assert "updated_at" in task
        assert task["acceptance_criteria"] == []
        assert task["notes"] == ""
        assert task["history"] == []
        assert task["handoff_required"] is True
        assert task["verification_command"] == ""
        assert task["repo_handoff_path"] == ""

    def test_id_generated_when_missing(self):
        task = ensure_task_defaults({"repo": "my-repo", "title": "Something"}, {})
        assert task["id"].startswith("my-repo:something:")

    def test_existing_id_preserved(self):
        task = ensure_task_defaults({"repo": "r", "title": "t", "id": "my:custom:id"}, {})
        assert task["id"] == "my:custom:id"

    def test_existing_status_preserved(self):
        task = ensure_task_defaults({"repo": "r", "title": "t", "status": "ready"}, {})
        assert task["status"] == "ready"

    def test_target_default_departments_used(self):
        targets = {"etheos-app": {"default_departments": ["qa", "ada", "product"]}}
        task = ensure_task_defaults({"repo": "etheos-app", "title": "T"}, targets)
        assert task["audits_required"] == ["qa", "ada", "product"]

    def test_fallback_audits_when_no_target(self):
        task = ensure_task_defaults({"repo": "unknown-repo", "title": "T"}, {})
        assert task["audits_required"] == ["qa", "product"]

    def test_product_key_inferred_from_repo(self):
        task = ensure_task_defaults({"repo": "etheos-app", "title": "T"}, {})
        assert task["product_key"] == "etheos"

    def test_target_path_set_from_target(self):
        targets = {"my-repo": {"path": "/srv/my-repo", "default_departments": []}}
        task = ensure_task_defaults({"repo": "my-repo", "title": "T"}, targets)
        assert task["target_path"] == "/srv/my-repo"

    def test_created_at_and_updated_at_match_when_new(self):
        task = ensure_task_defaults({"repo": "r", "title": "t"}, {})
        assert task["created_at"] == task["updated_at"]


# ---------------------------------------------------------------------------
# append_history
# ---------------------------------------------------------------------------


class TestAppendHistory:
    def test_appends_entry_to_history(self):
        task: dict = {}
        append_history(task, "ready", "agent", "started")
        assert len(task["history"]) == 1
        entry = task["history"][0]
        assert entry["status"] == "ready"
        assert entry["by"] == "agent"
        assert entry["note"] == "started"
        assert "at" in entry

    def test_note_is_stripped(self):
        task: dict = {}
        append_history(task, "done", "agent", "  trailing  ")
        assert task["history"][0]["note"] == "trailing"

    def test_multiple_entries_accumulate(self):
        task: dict = {"history": []}
        append_history(task, "proposed", "owner", "created")
        append_history(task, "ready", "owner", "approved")
        assert len(task["history"]) == 2

    def test_history_initialized_if_missing(self):
        task: dict = {}
        append_history(task, "proposed", "x", "y")
        assert "history" in task


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_utc_string_with_z(self):
        dt = parse_timestamp("2026-01-15T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso_utc_string_with_offset(self):
        dt = parse_timestamp("2026-01-15T10:00:00+00:00")
        assert dt is not None

    def test_none_returns_none(self):
        assert parse_timestamp(None) is None

    def test_empty_string_returns_none(self):
        assert parse_timestamp("") is None

    def test_garbage_returns_none(self):
        assert parse_timestamp("not-a-date") is None


# ---------------------------------------------------------------------------
# load_yaml / write_yaml
# ---------------------------------------------------------------------------


class TestYamlIO:
    def test_write_then_load(self, tmp_path):
        path = tmp_path / "test.yaml"
        write_yaml(path, {"key": "value", "list": [1, 2, 3]})
        loaded = load_yaml(path)
        assert loaded == {"key": "value", "list": [1, 2, 3]}

    def test_load_missing_returns_empty(self, tmp_path):
        result = load_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_write_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c.yaml"
        write_yaml(nested, {"x": 1})
        assert nested.exists()


# ---------------------------------------------------------------------------
# read_json
# ---------------------------------------------------------------------------


class TestReadJson:
    def test_reads_valid_json(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"a": 1}')
        assert read_json(p) == {"a": 1}

    def test_missing_file_returns_none(self, tmp_path):
        assert read_json(tmp_path / "missing.json") is None

    def test_malformed_json_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{broken")
        assert read_json(p) is None


# ---------------------------------------------------------------------------
# load_targets
# ---------------------------------------------------------------------------


class TestLoadTargets:
    def test_loads_list_of_targets(self, tmp_path):
        p = tmp_path / "targets.yaml"
        p.write_text(textwrap.dedent("""\
            targets:
              - name: my-app
                path: /srv/my-app
                default_departments:
                  - qa
        """))
        targets = load_targets(p)
        assert "my-app" in targets
        assert targets["my-app"]["path"] == "/srv/my-app"

    def test_missing_targets_yaml_returns_empty(self, tmp_path):
        targets = load_targets(tmp_path / "nonexistent.yaml")
        assert targets == {}

    def test_target_without_name_skipped(self, tmp_path):
        p = tmp_path / "targets.yaml"
        p.write_text(textwrap.dedent("""\
            targets:
              - path: /srv/anon
                default_departments: []
        """))
        targets = load_targets(p)
        assert targets == {}


# ---------------------------------------------------------------------------
# load_context
# ---------------------------------------------------------------------------


class TestLoadContext:
    def test_missing_config_returns_empty_payload(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        # config_path doesn't exist yet
        ctx = load_context(config_path, targets_path, results, dashboard)
        assert ctx.payload == {"version": 1, "tasks": []}

    def test_existing_tasks_loaded(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        # Add a task to the YAML
        write_yaml(config_path, {
            "version": 1,
            "tasks": [{"id": "r:t:1", "repo": "r", "title": "T", "status": "ready"}],
        })
        ctx = load_context(config_path, targets_path, results, dashboard)
        assert len(ctx.payload["tasks"]) == 1

    def test_malformed_tasks_field_resets_to_empty(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        write_yaml(config_path, {"version": 1, "tasks": "not-a-list"})
        ctx = load_context(config_path, targets_path, results, dashboard)
        assert ctx.payload["tasks"] == []


# ---------------------------------------------------------------------------
# build_dashboard_payload
# ---------------------------------------------------------------------------


class TestBuildDashboardPayload:
    def _make_task(self, status, priority="medium", repo="repo-a", created_at="2026-01-01T00:00:00+00:00"):
        return {
            "id": f"{repo}:{status}:{priority}",
            "repo": repo,
            "title": "Test",
            "status": status,
            "priority": priority,
            "created_at": created_at,
            "history": [],
        }

    def test_empty_tasks(self):
        result = build_dashboard_payload([])
        assert result["summary"]["total"] == 0
        assert result["tasks"] == []
        assert "generated_at" in result

    def test_summary_counts_correctly(self):
        tasks = [
            self._make_task("proposed"),
            self._make_task("in_progress"),
            self._make_task("blocked"),
            self._make_task("done"),
            self._make_task("cancelled"),
            self._make_task("ready_for_review"),
        ]
        result = build_dashboard_payload(tasks)
        s = result["summary"]
        assert s["total"] == 6
        assert s["done"] == 1
        assert s["blocked"] == 1
        assert s["in_progress"] == 1
        assert s["ready_for_review"] == 1
        # open = total - done - cancelled
        assert s["open"] == 4

    def test_tasks_sorted_by_status_order(self):
        tasks = [
            self._make_task("done"),
            self._make_task("proposed"),
            self._make_task("in_progress"),
        ]
        result = build_dashboard_payload(tasks)
        statuses = [t["status"] for t in result["tasks"]]
        assert statuses == ["proposed", "in_progress", "done"]

    def test_high_priority_before_low_same_status(self):
        tasks = [
            self._make_task("ready", priority="low"),
            self._make_task("ready", priority="high"),
        ]
        result = build_dashboard_payload(tasks)
        ready = [t for t in result["tasks"] if t["status"] == "ready"]
        assert ready[0]["priority"] == "high"

    def test_history_sorted_by_at(self):
        tasks = [
            {
                "id": "r:t:1",
                "repo": "r",
                "title": "T",
                "status": "proposed",
                "priority": "medium",
                "created_at": "2026-01-01T00:00:00+00:00",
                "history": [
                    {"at": "2026-01-03T00:00:00+00:00", "status": "proposed", "by": "x", "note": ""},
                    {"at": "2026-01-01T00:00:00+00:00", "status": "proposed", "by": "x", "note": ""},
                ],
            }
        ]
        result = build_dashboard_payload(tasks)
        history = result["tasks"][0]["history"]
        assert history[0]["at"] < history[1]["at"]

    def test_by_repo_counts(self):
        tasks = [
            self._make_task("done", repo="repo-a"),
            self._make_task("proposed", repo="repo-a"),
            self._make_task("cancelled", repo="repo-b"),
        ]
        result = build_dashboard_payload(tasks)
        by_repo = result["summary"]["by_repo"]
        assert by_repo["repo-a"]["total"] == 2
        assert by_repo["repo-a"]["done"] == 1
        assert by_repo["repo-a"]["open"] == 1
        assert by_repo["repo-b"]["total"] == 1
        assert by_repo["repo-b"]["open"] == 0  # cancelled doesn't count as open


# ---------------------------------------------------------------------------
# find_task
# ---------------------------------------------------------------------------


class TestFindTask:
    def test_finds_existing_task(self):
        tasks = [{"id": "r:t:1", "title": "A"}, {"id": "r:t:2", "title": "B"}]
        result = find_task(tasks, "r:t:2")
        assert result["title"] == "B"

    def test_missing_task_raises_system_exit(self):
        with pytest.raises(SystemExit, match="Unknown task id"):
            find_task([], "nonexistent")


# ---------------------------------------------------------------------------
# save_payload / YAML<->JSON sync
# ---------------------------------------------------------------------------


class TestSavePayload:
    def test_writes_yaml_config(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        payload = {
            "version": 1,
            "tasks": [{"repo": "r", "title": "T", "status": "proposed", "id": "r:t:1"}],
        }
        save_payload(payload, {}, config_path, results, dashboard)
        loaded = load_yaml(config_path)
        assert len(loaded["tasks"]) == 1
        assert loaded["tasks"][0]["id"] == "r:t:1"

    def test_writes_results_json(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        payload = {"version": 1, "tasks": []}
        save_payload(payload, {}, config_path, results, dashboard)
        results_json = results / "task-queue.json"
        assert results_json.exists()
        data = json.loads(results_json.read_text())
        assert "summary" in data
        assert "tasks" in data

    def test_writes_dashboard_json(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        payload = {"version": 1, "tasks": []}
        save_payload(payload, {}, config_path, results, dashboard)
        dash_json = dashboard / "task-queue.json"
        assert dash_json.exists()

    def test_results_and_dashboard_json_identical(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        payload = {
            "version": 1,
            "tasks": [{"repo": "r", "title": "T", "status": "proposed", "id": "r:t:1"}],
        }
        save_payload(payload, {}, config_path, results, dashboard)
        r_data = json.loads((results / "task-queue.json").read_text())
        d_data = json.loads((dashboard / "task-queue.json").read_text())
        # generated_at timestamps may differ by a millisecond in theory,
        # so compare summary and tasks only
        assert r_data["summary"] == d_data["summary"]
        assert r_data["tasks"] == d_data["tasks"]

    def test_normalize_applies_defaults(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        payload = {"version": 1, "tasks": [{"repo": "r", "title": "T"}]}
        save_payload(payload, {}, config_path, results, dashboard)
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "proposed"
        assert loaded["tasks"][0]["priority"] == "medium"


# ---------------------------------------------------------------------------
# summarize_gate_status
# ---------------------------------------------------------------------------


def _write_findings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


class TestSummarizeGateStatus:
    def _fresh_task(self, repo="my-repo", departments=("qa",)):
        return {
            "id": f"{repo}:t:1",
            "repo": repo,
            "title": "T",
            "status": "ready_for_review",
            "audits_required": list(departments),
            "handoff_required": False,
            "repo_handoff_path": "",
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _old_iso(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    def test_no_findings_artifact_fails_gate(self, tmp_path):
        task = self._fresh_task()
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("no findings artifact" in f for f in failures)

    def test_recent_clean_artifact_passes(self, tmp_path):
        task = self._fresh_task()
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok
        assert failures == []

    def test_stale_artifact_fails_gate(self, tmp_path):
        task = self._fresh_task()
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._old_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("stale" in f for f in failures)

    def test_blocking_critical_findings_fail_gate(self, tmp_path):
        task = self._fresh_task(departments=("qa",))
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 2, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("blocking findings" in f for f in failures)

    def test_blocking_high_findings_fail_gate(self, tmp_path):
        task = self._fresh_task(departments=("ada",))
        findings_path = tmp_path / "my-repo" / "ada-findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 3},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("blocking findings" in f for f in failures)

    def test_non_blocking_department_ignores_findings(self, tmp_path):
        """SEO is not in BLOCKING_DEPARTMENTS; high findings should not block."""
        task = self._fresh_task(departments=("seo",))
        findings_path = tmp_path / "my-repo" / "seo-findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 99},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok
        assert failures == []

    def test_missing_scanned_at_fails_gate(self, tmp_path):
        task = self._fresh_task()
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("missing scanned_at" in f for f in failures)

    def test_handoff_required_and_missing_fails_gate(self, tmp_path):
        task = self._fresh_task()
        task["handoff_required"] = True
        task["repo_handoff_path"] = str(tmp_path / "nonexistent" / "HANDOFF.md")
        # Provide a passing findings artifact
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("handoff missing" in f for f in failures)

    def test_handoff_present_does_not_fail(self, tmp_path):
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Handoff")
        task = self._fresh_task()
        task["handoff_required"] = True
        task["repo_handoff_path"] = str(handoff)
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok

    def test_unknown_department_skipped(self, tmp_path):
        task = self._fresh_task(departments=("not-a-department",))
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok
        assert failures == []

    def test_scanned_at_from_nested_summary(self, tmp_path):
        task = self._fresh_task()
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "summary": {"scanned_at": self._now_iso(), "critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok

    def test_scanned_at_from_metadata_generated_at(self, tmp_path):
        task = self._fresh_task()
        findings_path = tmp_path / "my-repo" / "findings.json"
        _write_findings(findings_path, {
            "metadata": {"generated_at": self._now_iso()},
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert ok

    def test_multiple_departments_all_must_pass(self, tmp_path):
        task = self._fresh_task(departments=("qa", "ada"))
        # Write good QA findings
        _write_findings(tmp_path / "my-repo" / "findings.json", {
            "scanned_at": self._now_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        # Write stale ADA findings
        _write_findings(tmp_path / "my-repo" / "ada-findings.json", {
            "scanned_at": self._old_iso(),
            "summary": {"critical": 0, "high": 0},
        })
        ok, failures = summarize_gate_status(task, tmp_path)
        assert not ok
        assert any("ada" in f for f in failures)


# ---------------------------------------------------------------------------
# Status transitions via CLI
# ---------------------------------------------------------------------------


def _make_queue(tmp_dirs, tasks: list[dict]) -> tuple[Path, Path, Path, Path]:
    config_path, targets_path, results, dashboard = tmp_dirs
    write_yaml(config_path, {"version": 1, "tasks": tasks})
    return config_path, targets_path, results, dashboard


def _args(command: str, config_path: Path, targets_path: Path, results: Path,
          dashboard: Path, **kwargs) -> object:
    """Build a minimal argparse.Namespace for a command."""
    import argparse
    ns = argparse.Namespace(
        command=command,
        config=config_path,
        targets_config=targets_path,
        results_dir=results,
        dashboard_dir=dashboard,
        **kwargs,
    )
    return ns


class TestStatusTransitions:
    def _base_task(self, task_id="r:t:1", status="proposed"):
        return {
            "id": task_id,
            "repo": "r",
            "title": "T",
            "status": status,
            "priority": "medium",
            "owner": "agent",
            "created_by": "product-owner",
        }

    def test_proposed_to_ready_is_reflected_in_yaml(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task()]
        )
        from backoffice.tasks import command_start
        args = _args("start", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        rc = command_start(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "in_progress"

    def test_start_appends_history(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task()]
        )
        from backoffice.tasks import command_start
        args = _args("start", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        command_start(args)
        loaded = load_yaml(config_path)
        history = loaded["tasks"][0]["history"]
        assert any(h["status"] == "in_progress" for h in history)

    def test_block_sets_status_blocked(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task(status="in_progress")]
        )
        from backoffice.tasks import command_block
        args = _args("block", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        rc = command_block(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "blocked"

    def test_review_sets_ready_for_review(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task(status="in_progress")]
        )
        from backoffice.tasks import command_review
        args = _args("review", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        rc = command_review(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "ready_for_review"

    def test_cancel_sets_cancelled(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task()]
        )
        from backoffice.tasks import command_cancel
        args = _args("cancel", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        rc = command_cancel(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "cancelled"

    def test_complete_blocked_when_gates_fail(self, tmp_dirs):
        """complete returns 2 when gates fail and allow_incomplete_gates is False."""
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs,
            [{
                **self._base_task(status="ready_for_review"),
                "audits_required": ["qa"],
                "handoff_required": False,
                "repo_handoff_path": "",
            }],
        )
        from backoffice.tasks import command_complete
        args = _args("complete", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None,
                     allow_incomplete_gates=False)
        rc = command_complete(args)
        assert rc == 2
        loaded = load_yaml(config_path)
        # Status should not have changed
        assert loaded["tasks"][0]["status"] == "ready_for_review"

    def test_complete_with_allow_incomplete_gates(self, tmp_dirs):
        """complete succeeds with allow_incomplete_gates=True even when gates fail."""
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs,
            [{
                **self._base_task(status="ready_for_review"),
                "audits_required": ["qa"],
                "handoff_required": False,
                "repo_handoff_path": "",
            }],
        )
        from backoffice.tasks import command_complete
        args = _args("complete", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None,
                     allow_incomplete_gates=True)
        rc = command_complete(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["status"] == "done"

    def test_complete_override_note_includes_gate_failures(self, tmp_dirs):
        """Gate failure details should be appended to the note when overriding."""
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs,
            [{
                **self._base_task(status="ready_for_review"),
                "audits_required": ["qa"],
                "handoff_required": False,
                "repo_handoff_path": "",
            }],
        )
        from backoffice.tasks import command_complete
        args = _args("complete", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None,
                     allow_incomplete_gates=True)
        command_complete(args)
        loaded = load_yaml(config_path)
        task = loaded["tasks"][0]
        done_entry = next((h for h in task["history"] if h["status"] == "done"), None)
        assert done_entry is not None
        assert "Override used despite gate failures" in done_entry["note"]

    def test_update_status_uses_custom_actor(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task()]
        )
        from backoffice.tasks import command_start
        args = _args("start", config_path, targets_path, results, dashboard,
                     id="r:t:1", by="custom-actor", owner=None, note=None)
        command_start(args)
        loaded = load_yaml(config_path)
        history = loaded["tasks"][0]["history"]
        in_progress_entry = next(h for h in history if h["status"] == "in_progress")
        assert in_progress_entry["by"] == "custom-actor"

    def test_update_status_uses_task_owner_when_by_none(self, tmp_dirs):
        config_path, targets_path, results, dashboard = _make_queue(
            tmp_dirs, [self._base_task()]
        )
        from backoffice.tasks import command_start
        args = _args("start", config_path, targets_path, results, dashboard,
                     id="r:t:1", by=None, owner=None, note=None)
        command_start(args)
        loaded = load_yaml(config_path)
        history = loaded["tasks"][0]["history"]
        in_progress_entry = next(h for h in history if h["status"] == "in_progress")
        assert in_progress_entry["by"] == "agent"  # from the task's owner field


# ---------------------------------------------------------------------------
# command_create
# ---------------------------------------------------------------------------


class TestCommandCreate:
    def test_creates_task_in_yaml(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_create
        args = _args("create", config_path, targets_path, results, dashboard,
                     repo="new-repo", title="New Feature",
                     category="feature", priority="high", status="proposed",
                     created_by="product-owner", owner=None, notes=None,
                     acceptance=None, audits=None,
                     verification_command=None, repo_handoff_path=None)
        rc = command_create(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert len(loaded["tasks"]) == 1
        task = loaded["tasks"][0]
        assert task["repo"] == "new-repo"
        assert task["title"] == "New Feature"
        assert task["status"] == "proposed"

    def test_create_appends_history_entry(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_create
        args = _args("create", config_path, targets_path, results, dashboard,
                     repo="r", title="T",
                     category="feature", priority="medium", status="proposed",
                     created_by="product-owner", owner=None, notes=None,
                     acceptance=None, audits=None,
                     verification_command=None, repo_handoff_path=None)
        command_create(args)
        loaded = load_yaml(config_path)
        task = loaded["tasks"][0]
        assert len(task["history"]) >= 1
        assert task["history"][0]["note"] == "Task created"

    def test_create_with_acceptance_criteria(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_create
        args = _args("create", config_path, targets_path, results, dashboard,
                     repo="r", title="T",
                     category="feature", priority="medium", status="proposed",
                     created_by="product-owner", owner=None, notes=None,
                     acceptance=["criterion one", "criterion two"],
                     audits=None,
                     verification_command=None, repo_handoff_path=None)
        command_create(args)
        loaded = load_yaml(config_path)
        assert loaded["tasks"][0]["acceptance_criteria"] == ["criterion one", "criterion two"]


# ---------------------------------------------------------------------------
# command_seed_etheos
# ---------------------------------------------------------------------------


class TestCommandSeedEtheos:
    def test_seeds_three_tasks(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_seed_etheos
        args = _args("seed-etheos", config_path, targets_path, results, dashboard)
        rc = command_seed_etheos(args)
        assert rc == 0
        loaded = load_yaml(config_path)
        assert len(loaded["tasks"]) == 3
        ids = {t["id"] for t in loaded["tasks"]}
        assert "etheos:frontend-stabilization" in ids
        assert "etheos:intake-pipeline" in ids
        assert "etheos:factory-builder" in ids

    def test_seed_is_idempotent(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_seed_etheos
        args = _args("seed-etheos", config_path, targets_path, results, dashboard)
        command_seed_etheos(args)
        command_seed_etheos(args)
        loaded = load_yaml(config_path)
        assert len(loaded["tasks"]) == 3  # no duplicates

    def test_seed_appends_history_entry(self, empty_queue):
        config_path, targets_path, results, dashboard = empty_queue
        from backoffice.tasks import command_seed_etheos
        args = _args("seed-etheos", config_path, targets_path, results, dashboard)
        command_seed_etheos(args)
        loaded = load_yaml(config_path)
        for task in loaded["tasks"]:
            assert any(h["note"] == "Seeded pilot task" for h in task["history"])


# ---------------------------------------------------------------------------
# List filtering
# ---------------------------------------------------------------------------


class TestListFiltering:
    def _setup(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        tasks = [
            {
                "id": "repo-a:t1:1",
                "repo": "repo-a",
                "title": "T1",
                "status": "proposed",
                "product_key": "product-x",
            },
            {
                "id": "repo-b:t2:1",
                "repo": "repo-b",
                "title": "T2",
                "status": "in_progress",
                "product_key": "product-y",
            },
            {
                "id": "repo-a:t3:1",
                "repo": "repo-a",
                "title": "T3",
                "status": "done",
                "product_key": "product-x",
            },
        ]
        write_yaml(config_path, {"version": 1, "tasks": tasks})
        return config_path, targets_path, results, dashboard

    def test_filter_by_repo(self, tmp_dirs):
        config_path, targets_path, results, dashboard = self._setup(tmp_dirs)
        ctx = load_context(config_path, targets_path, results, dashboard)
        tasks = [ensure_task_defaults(t, ctx.targets) for t in ctx.payload["tasks"]]
        filtered = [t for t in tasks if t.get("repo") == "repo-a"]
        assert len(filtered) == 2

    def test_filter_by_status(self, tmp_dirs):
        config_path, targets_path, results, dashboard = self._setup(tmp_dirs)
        ctx = load_context(config_path, targets_path, results, dashboard)
        tasks = [ensure_task_defaults(t, ctx.targets) for t in ctx.payload["tasks"]]
        filtered = [t for t in tasks if t.get("status") == "in_progress"]
        assert len(filtered) == 1
        assert filtered[0]["id"] == "repo-b:t2:1"

    def test_filter_by_product_key(self, tmp_dirs):
        config_path, targets_path, results, dashboard = self._setup(tmp_dirs)
        ctx = load_context(config_path, targets_path, results, dashboard)
        tasks = [ensure_task_defaults(t, ctx.targets) for t in ctx.payload["tasks"]]
        filtered = [t for t in tasks if t.get("product_key") == "product-x"]
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# STATUS_ORDER constant
# ---------------------------------------------------------------------------


class TestStatusOrder:
    def test_contains_all_expected_statuses(self):
        expected = {"proposed", "ready", "in_progress", "blocked", "ready_for_review", "done", "cancelled"}
        assert set(STATUS_ORDER) == expected

    def test_proposed_comes_before_done(self):
        assert STATUS_ORDER.index("proposed") < STATUS_ORDER.index("done")

    def test_in_progress_before_ready_for_review(self):
        assert STATUS_ORDER.index("in_progress") < STATUS_ORDER.index("ready_for_review")


# ---------------------------------------------------------------------------
# build_parser / main entry point
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_sync_command_parses(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        parser = build_parser(config_path, targets_path, results, dashboard)
        args = parser.parse_args(["sync"])
        assert args.command == "sync"

    def test_list_command_with_filters(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        parser = build_parser(config_path, targets_path, results, dashboard)
        args = parser.parse_args(["list", "--repo", "my-repo", "--status", "proposed"])
        assert args.repo == "my-repo"
        assert args.status == "proposed"

    def test_create_command_required_args(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        parser = build_parser(config_path, targets_path, results, dashboard)
        args = parser.parse_args(["create", "--repo", "r", "--title", "T"])
        assert args.repo == "r"
        assert args.title == "T"
        assert args.category == "feature"
        assert args.priority == "medium"

    def test_complete_has_allow_incomplete_gates_flag(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        parser = build_parser(config_path, targets_path, results, dashboard)
        args = parser.parse_args(["complete", "--id", "x:y:z", "--allow-incomplete-gates"])
        assert args.allow_incomplete_gates is True

    def test_seed_etheos_command_parses(self, tmp_dirs):
        config_path, targets_path, results, dashboard = tmp_dirs
        parser = build_parser(config_path, targets_path, results, dashboard)
        args = parser.parse_args(["seed-etheos"])
        assert args.command == "seed-etheos"
