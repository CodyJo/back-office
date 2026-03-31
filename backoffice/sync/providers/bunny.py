"""Bunny.net Storage Zone + Pull Zone (CDN) provider implementation."""
from __future__ import annotations

import logging
import mimetypes
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from backoffice.sync.providers.base import CDNProvider, StorageProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 1

def _storage_url(region: str, zone: str, path: str) -> str:
    """Build the Bunny Storage upload URL.

    The primary region (DE/Falkenstein) uses ``storage.bunnycdn.com``
    without a region prefix.  Replica regions use ``{region}.storage.bunnycdn.com``.
    """
    host = "storage.bunnycdn.com" if region.lower() in ("de", "") else f"{region}.storage.bunnycdn.com"
    return f"https://{host}/{zone}/{path}"


def _retry(fn, *args, **kwargs):
    """Retry fn up to MAX_RETRIES times with exponential backoff."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Retry %d/%d after %.1fs: %s",
                    attempt + 1, MAX_RETRIES, wait, exc,
                )
                time.sleep(wait)
    raise last_exc


class BunnyStorage(StorageProvider):
    """Upload files to a Bunny.net Storage Zone via HTTP PUT."""

    def __init__(self, storage_zone: str, storage_region: str,
                 access_key: str | None = None) -> None:
        self._zone = storage_zone
        self._region = storage_region
        key = access_key or os.environ.get("BUNNY_STORAGE_KEY")
        if not key:
            raise ValueError(
                "BunnyStorage requires an access key. "
                "Pass access_key= or set the BUNNY_STORAGE_KEY environment variable."
            )
        self._access_key = key

    # ------------------------------------------------------------------
    # StorageProvider interface
    # ------------------------------------------------------------------

    def upload_file(self, bucket: str, local_path: str, remote_key: str,
                    content_type: str, cache_control: str) -> None:
        """Upload a single file via HTTP PUT.

        The bucket parameter is accepted for interface compatibility but
        ignored — the storage zone is configured at construction time.
        """
        url = _storage_url(self._region, self._zone, remote_key.lstrip("/"))

        def _do_upload():
            data = Path(local_path).read_bytes()
            req = urllib.request.Request(
                url=url,
                data=data,
                method="PUT",
                headers={
                    "AccessKey": self._access_key,
                    "Content-Type": content_type,
                },
            )
            with urllib.request.urlopen(req) as resp:
                resp.read()

        _retry(_do_upload)
        logger.info(
            "Uploaded %s -> bunny://%s/%s",
            Path(local_path).name, self._zone, remote_key,
        )

    def upload_files(self, file_mappings: list[dict]) -> None:
        """Upload multiple files described by a list of mapping dicts."""
        for m in file_mappings:
            self.upload_file(
                m["bucket"], m["local_path"], m["remote_key"],
                m["content_type"], m["cache_control"],
            )

    def sync_directory(self, bucket: str, local_dir: str,
                       remote_prefix: str, delete: bool = False) -> None:
        """Recursively upload every file under local_dir to remote_prefix.

        The delete parameter is accepted for interface compatibility; Bunny
        does not support server-side delete-on-sync via this path, so it is
        currently a no-op.
        """
        base = Path(local_dir)
        for local_file in sorted(base.rglob("*")):
            if not local_file.is_file():
                continue
            relative = local_file.relative_to(base)
            prefix = remote_prefix.rstrip("/")
            remote_key = f"{prefix}/{relative}" if prefix else str(relative)
            content_type, _ = mimetypes.guess_type(str(local_file))
            content_type = content_type or "application/octet-stream"
            self.upload_file(bucket, str(local_file), remote_key, content_type, "no-cache")


class BunnyCDN(CDNProvider):
    """Purge Bunny Pull Zone cache via DustBunny CLI."""

    def __init__(self, dustbunny_bin: str | None = None) -> None:
        self._bin = dustbunny_bin or os.environ.get(
            "DUSTBUNNY_BIN",
            str(Path.home() / "projects" / "dustbunny" / "bin" / "dustbunny.mjs"),
        )

    def invalidate(self, distribution_id: str, paths: list[str]) -> None:
        """Purge the entire Pull Zone cache.

        The distribution_id parameter is semantically a Pull Zone ID for
        Bunny targets.  The paths parameter is accepted for interface
        compatibility but ignored — Bunny purge is always zone-wide and free.
        """
        if not distribution_id:
            return
        pull_zone_id = distribution_id
        cmd = [self._bin, "pz", "purge", pull_zone_id]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Purged Pull Zone %s", pull_zone_id)
        except Exception as exc:
            logger.warning("Pull Zone purge failed for %s: %s", pull_zone_id, exc)
