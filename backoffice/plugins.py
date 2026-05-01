"""Experimental plugin loader.

Phase 12 introduces a tiny extension surface so adapters and similar
components can be added without modifying ``backoffice/`` itself. The
design is deliberately small:

* No automatic plugin discovery. Operators register plugins explicitly
  in ``config/backoffice.yaml`` under ``plugins:``.
* Loading failures **do not break core flows** — every load attempt is
  wrapped, errors are recorded on the result, and the rest of Back
  Office continues to function.
* Plugin operations that mutate state are audited like any other.

This API is **experimental**: the plugin contract may change between
phases. See ``docs/architecture/phased-roadmap.md`` Phase 12.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)


# Plugin extension points.
EXTENSION_POINTS = (
    "adapter",
    "scanner",
    "department_check",
    "dashboard_card",
    "budget_reporter",
    "notification_sink",
)


@dataclass
class LoadedPlugin:
    name: str
    extension_point: str
    module_path: str
    cls_name: str = ""
    attribute: Any = None
    metadata: dict = field(default_factory=dict)


@dataclass
class LoadResult:
    loaded: list[LoadedPlugin] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def names(self) -> list[str]:
        return [p.name for p in self.loaded]


def _load_module(spec: dict) -> ModuleType:
    """Load a module by either dotted path or filesystem path.

    Two declaration shapes:

    * ``{"module": "my_package.my_module"}`` — imported normally.
    * ``{"path": "/abs/path/to/module.py"}`` — loaded from the
      filesystem (useful for in-repo example plugins).
    """
    module_name = spec.get("module")
    file_path = spec.get("path")
    if module_name and not file_path:
        return importlib.import_module(str(module_name))
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        # Use a stable but namespaced name so re-loading the same
        # plugin during tests doesn't collide with the real package.
        synthetic_name = "backoffice_plugin_" + path.stem
        spec_obj = importlib.util.spec_from_file_location(synthetic_name, path)
        if spec_obj is None or spec_obj.loader is None:
            raise ImportError(f"could not build spec for {path}")
        mod = importlib.util.module_from_spec(spec_obj)
        sys.modules[synthetic_name] = mod
        spec_obj.loader.exec_module(mod)
        return mod
    raise ValueError("plugin declaration requires 'module' or 'path'")


def load(declarations: list[dict] | None) -> LoadResult:
    """Load every plugin in *declarations*.

    Each declaration: ``{"name", "extension_point", "module"|"path",
    "attribute"?}``.

    The optional ``attribute`` is a dotted path inside the module —
    e.g. ``"plugin.MyAdapter"``. When omitted, the loaded plugin
    surfaces the whole module.
    """
    result = LoadResult()
    for decl in declarations or []:
        if not isinstance(decl, dict):
            result.errors.append({"error": "declaration is not a dict", "decl": str(decl)})
            continue
        name = str(decl.get("name") or "")
        ext = str(decl.get("extension_point") or "")
        if not name or not ext:
            result.errors.append({"name": name, "error": "missing name or extension_point"})
            continue
        if ext not in EXTENSION_POINTS:
            result.errors.append({"name": name, "error": f"unknown extension_point: {ext!r}"})
            continue

        try:
            module = _load_module(decl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plugin %s failed to load: %s", name, exc)
            result.errors.append({"name": name, "error": str(exc)})
            continue

        attribute = None
        cls_name = ""
        if decl.get("attribute"):
            cls_name = str(decl["attribute"])
            current: Any = module
            try:
                for part in cls_name.split("."):
                    current = getattr(current, part)
            except AttributeError as exc:
                result.errors.append({"name": name, "error": f"missing attribute: {exc}"})
                continue
            attribute = current
        else:
            attribute = module

        result.loaded.append(
            LoadedPlugin(
                name=name,
                extension_point=ext,
                module_path=getattr(module, "__name__", ""),
                cls_name=cls_name,
                attribute=attribute,
                metadata=dict(decl.get("metadata", {}) or {}),
            )
        )

        # If the plugin is an adapter, register it with the adapter
        # registry — this is the headline integration of Phase 12.
        if ext == "adapter" and hasattr(attribute, "name"):
            try:
                from backoffice.adapters import register as _register_adapter
                _register_adapter(getattr(attribute, "name"), attribute)
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to register adapter %s: %s", name, exc)

    return result


def safe_call(callable_: Any, *args, **kwargs) -> tuple[bool, Any]:
    """Run a plugin entry point without letting failures break callers.

    Returns ``(ok, value_or_exception_text)``.
    """
    try:
        return True, callable_(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("plugin call failed: %s", exc)
        return False, str(exc)
