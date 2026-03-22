"""Sync engine — replaces sync-dashboard.sh and quick-sync.sh.

Orchestrates uploading dashboard files, department data, shared
metadata, and job status to configured storage targets, then
invalidates CDN caches.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from backoffice.sync.manifest import (
    AGG_DATA_MAP,
    DASHBOARD_FILES,
    DEPT_DATA_MAP,
    JOB_STATUS_FILES,
    SHARED_META_FILES,
    content_type_for,
)

if TYPE_CHECKING:
    from backoffice.config import DashboardTarget
    from backoffice.sync.providers.base import CDNProvider, StorageProvider

logger = logging.getLogger(__name__)

CACHE_CONTROL = "no-cache, no-store, must-revalidate"


class SyncEngine:
    """Upload dashboard assets and data to storage targets.

    Modes:
        Full sync  — ``run()``                  gate + aggregate + all files + CDN + regression
        Quick sync — ``run(department="qa")``    single dept data + shared + jobs + CDN
        Dry run    — ``run(dry_run=True)``       log-only, no uploads
    """

    def __init__(
        self,
        *,
        storage: StorageProvider,
        cdn: CDNProvider,
        dashboard_dir: Path,
        results_dir: Path,
        dashboard_targets: list[DashboardTarget],
        skip_gate: bool = False,
    ) -> None:
        self.storage = storage
        self.cdn = cdn
        self.dashboard_dir = Path(dashboard_dir)
        self.results_dir = Path(results_dir)
        self.dashboard_targets = dashboard_targets
        self.skip_gate = skip_gate

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls) -> SyncEngine:
        """Build a SyncEngine from the project config file."""
        from backoffice.config import load_config
        from backoffice.sync.providers import get_providers

        config = load_config()
        storage, cdn = get_providers(config)
        return cls(
            storage=storage,
            cdn=cdn,
            dashboard_dir=config.root / "dashboard",
            results_dir=config.root / "results",
            dashboard_targets=config.deploy.aws.dashboard_targets,
            skip_gate=False,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, *, department: str | None = None, dry_run: bool = False) -> int:
        """Execute a sync cycle.

        Args:
            department: If set, perform a quick sync for only this department.
            dry_run: If True, log what would be uploaded without touching storage.

        Returns:
            0 on success, 1 on partial failure, 2 on fatal error.
        """
        quick = department is not None
        had_errors = False

        for target in self.dashboard_targets:
            if not self._passes_gate(target):
                continue

            try:
                self._sync_target(target, department=department, dry_run=dry_run, quick=quick)
            except Exception:
                logger.exception("Failed to sync target %s", target.bucket)
                had_errors = True

        return 1 if had_errors else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _passes_gate(self, target: DashboardTarget) -> bool:
        """Check whether a target should be synced.

        Admin targets (subdomain starts with ``admin.``) are always
        allowed.  Non-admin targets require ``allow_public_read: true``.
        """
        subdomain = target.subdomain or ""
        if subdomain.startswith("admin."):
            return True
        if target.allow_public_read:
            return True
        logger.info(
            "Skipping target %s — set allow_public_read: true to publish publicly.",
            subdomain,
        )
        return False

    def _sync_target(
        self,
        target: DashboardTarget,
        *,
        department: str | None,
        dry_run: bool,
        quick: bool,
    ) -> None:
        """Build the file list and upload for a single target."""
        prefix = f"{target.base_path}/" if target.base_path else ""
        per_repo = target.filter_repo is not None
        file_mappings: list[dict] = []

        if quick:
            # Quick sync: single department + shared + jobs
            file_mappings.extend(self._dept_data_mappings(target, department, prefix, per_repo))
            file_mappings.extend(self._shared_meta_mappings(prefix))
            file_mappings.extend(self._job_status_mappings(prefix))
        else:
            # Full sync: HTML + all data + shared + jobs
            file_mappings.extend(self._dashboard_file_mappings(prefix))
            if per_repo:
                # Per-repo: use raw findings for every department
                for dept in DEPT_DATA_MAP:
                    file_mappings.extend(
                        self._dept_data_mappings(target, dept, prefix, per_repo=True)
                    )
            else:
                # Aggregated: use dashboard/<agg>.json files
                file_mappings.extend(self._agg_data_mappings(prefix))
            file_mappings.extend(self._shared_meta_mappings(prefix))
            file_mappings.extend(self._job_status_mappings(prefix))

        # Filter to files that actually exist on disk
        file_mappings = [m for m in file_mappings if Path(m["local_path"]).exists()]

        if dry_run:
            for m in file_mappings:
                logger.info(
                    "[dry-run] Would upload %s -> s3://%s/%s",
                    m["local_path"],
                    target.bucket,
                    m["remote_key"],
                )
            return

        # Upload
        bucket = target.bucket
        for m in file_mappings:
            m["bucket"] = bucket
        self.storage.upload_files(file_mappings)

        # CDN invalidation
        if target.distribution_id:
            paths = [f"/{m['remote_key']}" for m in file_mappings]
            if paths:
                self.cdn.invalidate(target.distribution_id, paths)

        # Regression log sync (full sync only)
        if not quick:
            self._sync_regression_logs(target, prefix)

    # ------------------------------------------------------------------
    # File-list builders
    # ------------------------------------------------------------------

    def _dashboard_file_mappings(self, prefix: str) -> list[dict]:
        """Build mappings for dashboard HTML/JS/SVG files."""
        mappings = []
        for filename in DASHBOARD_FILES:
            local_path = self.dashboard_dir / filename
            mappings.append({
                "local_path": str(local_path),
                "remote_key": f"{prefix}{filename}",
                "content_type": content_type_for(filename),
                "cache_control": CACHE_CONTROL,
            })
        return mappings

    def _dept_data_mappings(
        self,
        target: DashboardTarget,
        department: str | None,
        prefix: str,
        per_repo: bool,
    ) -> list[dict]:
        """Build mappings for a single department's data file.

        For per-repo targets, the source is ``results/<repo>/<raw_file>``.
        For aggregated targets during quick sync, the source is
        ``dashboard/<agg_source>`` that maps to the department's dashboard
        data filename.
        """
        if department is None:
            return []

        dept_entry = DEPT_DATA_MAP.get(department)
        if dept_entry is None:
            logger.warning("Unknown department: %s", department)
            return []

        raw_file, dashboard_name = dept_entry

        if per_repo and target.filter_repo:
            local_path = self.results_dir / target.filter_repo / raw_file
        else:
            # For aggregated targets, find the AGG_DATA_MAP source that
            # maps to this department's dashboard name.
            agg_source = None
            for src, dest in AGG_DATA_MAP.items():
                if dest == dashboard_name:
                    agg_source = src
                    break
            if agg_source is None:
                agg_source = dashboard_name
            local_path = self.dashboard_dir / agg_source

        return [{
            "local_path": str(local_path),
            "remote_key": f"{prefix}{dashboard_name}",
            "content_type": "application/json",
            "cache_control": CACHE_CONTROL,
        }]

    def _agg_data_mappings(self, prefix: str) -> list[dict]:
        """Build mappings for all aggregated data files."""
        mappings = []
        for source_file, remote_name in AGG_DATA_MAP.items():
            local_path = self.dashboard_dir / source_file
            mappings.append({
                "local_path": str(local_path),
                "remote_key": f"{prefix}{remote_name}",
                "content_type": "application/json",
                "cache_control": CACHE_CONTROL,
            })
        return mappings

    def _shared_meta_mappings(self, prefix: str) -> list[dict]:
        """Build mappings for shared metadata files."""
        mappings = []
        for filename in SHARED_META_FILES:
            local_path = self.dashboard_dir / filename
            mappings.append({
                "local_path": str(local_path),
                "remote_key": f"{prefix}{filename}",
                "content_type": content_type_for(filename),
                "cache_control": CACHE_CONTROL,
            })
        return mappings

    def _job_status_mappings(self, prefix: str) -> list[dict]:
        """Build mappings for job status files."""
        mappings = []
        for filename in JOB_STATUS_FILES:
            local_path = self.dashboard_dir / filename
            mappings.append({
                "local_path": str(local_path),
                "remote_key": f"{prefix}{filename}",
                "content_type": "application/json",
                "cache_control": CACHE_CONTROL,
            })
        return mappings

    def _sync_regression_logs(self, target: DashboardTarget, prefix: str) -> None:
        """Sync the regression results directory to storage."""
        regression_dir = self.results_dir / "regression"
        if not regression_dir.is_dir():
            logger.debug("Skipping regression logs (results/regression not found)")
            return

        remote_prefix = f"{prefix}results/regression" if prefix else "results/regression"
        logger.info("Syncing regression logs -> s3://%s/%s", target.bucket, remote_prefix)
        self.storage.sync_directory(
            bucket=target.bucket,
            local_dir=str(regression_dir),
            remote_prefix=remote_prefix,
            delete=True,
        )
