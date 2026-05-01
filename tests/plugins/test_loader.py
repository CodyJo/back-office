"""Tests for Phase 12 plugin loader."""
from __future__ import annotations

from pathlib import Path


from backoffice.plugins import load, safe_call


SAMPLE_PATH = str(Path(__file__).parent / "sample_plugin.py")


# ──────────────────────────────────────────────────────────────────────


def test_load_path_based_plugin():
    result = load(
        [
            {
                "name": "sample",
                "extension_point": "adapter",
                "path": SAMPLE_PATH,
                "attribute": "SampleAdapter",
            }
        ]
    )
    assert result.ok
    assert "sample" in result.names()
    plugin = result.loaded[0]
    assert plugin.cls_name == "SampleAdapter"
    assert plugin.attribute.__name__ == "SampleAdapter"


def test_loaded_adapter_registers_with_adapter_registry():
    """Loading an adapter plugin registers it under its ``.name``."""
    from backoffice.adapters import get as get_adapter

    load(
        [
            {
                "name": "sample-adapter",
                "extension_point": "adapter",
                "path": SAMPLE_PATH,
                "attribute": "SampleAdapter",
            }
        ]
    )
    assert get_adapter("sample_plugin") is not None


def test_load_module_attribute_is_optional():
    """When attribute is omitted, the module itself is the surface."""
    result = load(
        [
            {
                "name": "sample-mod",
                "extension_point": "scanner",  # not adapter; no auto-register
                "path": SAMPLE_PATH,
            }
        ]
    )
    assert result.ok
    plugin = result.loaded[0]
    assert plugin.attribute is not None
    # Module exposes a top-level callable.
    assert plugin.attribute.hello() == "hello from sample plugin"


def test_load_unknown_extension_point_records_error():
    result = load([{"name": "x", "extension_point": "not-a-thing", "path": SAMPLE_PATH}])
    assert not result.ok
    assert any("unknown extension_point" in e["error"] for e in result.errors)


def test_load_missing_attribute_records_error():
    result = load(
        [
            {
                "name": "x",
                "extension_point": "adapter",
                "path": SAMPLE_PATH,
                "attribute": "NoSuchClass",
            }
        ]
    )
    assert not result.ok
    assert any("missing attribute" in e["error"] for e in result.errors)


def test_load_missing_module_does_not_break_subsequent_plugins():
    """A failing plugin must not stop later good plugins from loading."""
    result = load(
        [
            {"name": "broken", "extension_point": "adapter", "path": "/nonexistent/x.py"},
            {
                "name": "good",
                "extension_point": "adapter",
                "path": SAMPLE_PATH,
                "attribute": "SampleAdapter",
            },
        ]
    )
    assert "good" in result.names()
    assert any(e["name"] == "broken" for e in result.errors)


def test_load_skips_garbage_declarations():
    result = load([{"x": 1}, "not-a-dict", {"name": "ok", "extension_point": "adapter", "path": SAMPLE_PATH, "attribute": "SampleAdapter"}])
    assert "ok" in result.names()
    assert any("missing name" in e.get("error", "") or "not a dict" in e.get("error", "") for e in result.errors)


def test_safe_call_returns_value_on_success():
    ok, value = safe_call(lambda x: x + 1, 41)
    assert ok
    assert value == 42


def test_safe_call_returns_error_on_failure():
    def boom():
        raise RuntimeError("kaboom")
    ok, value = safe_call(boom)
    assert not ok
    assert "kaboom" in value


def test_load_empty_declarations_is_safe():
    result = load(None)
    assert result.ok
    assert result.loaded == []


def test_load_emits_no_state_on_failure():
    """A bad plugin must not pollute the LoadResult.loaded list."""
    result = load([{"name": "bad", "extension_point": "adapter", "path": "/missing"}])
    assert result.loaded == []
    assert len(result.errors) == 1
