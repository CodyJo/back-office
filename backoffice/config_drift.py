"""Detect drift between the canonical backoffice.yaml and legacy
config/targets.yaml during the migration window.

Once overnight.sh switches fully to `python -m backoffice policy ...`, the
legacy file is no longer authoritative. While both exist we run
`detect_drift` during setup/refresh and surface:
  - targets present only in legacy (will silently be ignored after cutover)
  - targets present only in unified (benign; no action)
  - per-field autonomy conflicts (dangerous; unified value wins post-cutover)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from backoffice.config import Config


AUTONOMY_FIELDS = (
    "allow_fix",
    "allow_feature_dev",
    "allow_auto_commit",
    "allow_auto_merge",
    "allow_auto_deploy",
    "require_clean_worktree",
    "require_tests",
    "max_changes_per_cycle",
    "deploy_mode",
)


@dataclass
class DriftReport:
    conflicts: list[dict] = field(default_factory=list)
    extra_in_legacy: list[str] = field(default_factory=list)
    extra_in_unified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.conflicts or self.extra_in_legacy)


def load_legacy_targets(path: Path) -> dict[str, dict]:
    """Load config/targets.yaml (list-shaped) and return dict keyed by name.

    Returns an empty dict if the file is missing or malformed. This is a
    read-only migration-helper view; we do not normalize or validate here.
    """
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return {}
    items = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {}
    return {
        entry["name"]: entry
        for entry in items
        if isinstance(entry, dict) and entry.get("name")
    }


def detect_drift(config: Config, legacy_path: Path) -> DriftReport:
    legacy = load_legacy_targets(legacy_path)
    report = DriftReport()

    if not legacy:
        return report

    unified_names = set(config.targets.keys())
    legacy_names = set(legacy.keys())

    report.extra_in_legacy = sorted(legacy_names - unified_names)
    report.extra_in_unified = sorted(unified_names - legacy_names)

    for name in sorted(unified_names & legacy_names):
        unified_auton = config.targets[name].autonomy
        legacy_auton = legacy[name].get("autonomy") or {}
        if not isinstance(legacy_auton, dict):
            continue
        for fld in AUTONOMY_FIELDS:
            if fld not in legacy_auton:
                continue
            legacy_val = _coerce(legacy_auton[fld])
            unified_val = _coerce(getattr(unified_auton, fld))
            if legacy_val != unified_val:
                report.conflicts.append({
                    "target": name,
                    "field": fld,
                    "unified": unified_val,
                    "legacy": legacy_val,
                })

    return report


def _coerce(value: Any) -> Any:
    """Normalize values across YAML's bool/int/string representations."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if value is None:
        return None
    return str(value)
