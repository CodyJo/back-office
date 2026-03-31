"""Tests for backoffice.sync.manifest."""
from backoffice.sync.manifest import (
    DASHBOARD_FILES,
    DEPT_DATA_MAP,
    AGG_DATA_MAP,
    content_type_for,
)


def test_dashboard_files_contains_key_files():
    assert "index.html" in DASHBOARD_FILES
    assert "department-context.js" in DASHBOARD_FILES
    assert "favicon.svg" in DASHBOARD_FILES


def test_dept_data_map_has_all_departments():
    assert "qa" in DEPT_DATA_MAP
    assert "seo" in DEPT_DATA_MAP
    assert "self-audit" in DEPT_DATA_MAP
    # Every department must map to a (raw_file, dashboard_file) tuple
    for dept, (raw, dashboard) in DEPT_DATA_MAP.items():
        assert raw.endswith(".json"), f"{dept} raw file must be .json"
        assert dashboard.endswith("-data.json"), f"{dept} dashboard file must be *-data.json"


def test_content_type_for_html():
    assert content_type_for("index.html") == "text/html"


def test_content_type_for_js():
    assert content_type_for("site-branding.js") == "application/javascript"


def test_content_type_for_json():
    assert content_type_for("qa-data.json") == "application/json"


def test_content_type_for_svg():
    assert content_type_for("favicon.svg") == "image/svg+xml"


def test_content_type_for_markdown():
    assert content_type_for("local-audit-log.md") == "text/markdown"


def test_agg_data_map_has_departments():
    assert "data.json" in AGG_DATA_MAP
    assert AGG_DATA_MAP["data.json"] == "qa-data.json"
    # Every agg source must map to a known department dashboard file
    dept_dashboard_files = {v for _, v in DEPT_DATA_MAP.values()}
    for source, target in AGG_DATA_MAP.items():
        assert target in dept_dashboard_files, (
            f"AGG_DATA_MAP[{source!r}] -> {target!r} not in DEPT_DATA_MAP dashboard files"
        )
