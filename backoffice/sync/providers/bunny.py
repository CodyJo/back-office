"""Bunny.net Storage Zone + Pull Zone (CDN) provider implementation."""
from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import subprocess
import time
import urllib.error
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


UPLOAD_TIMEOUT = 300  # seconds per file upload
MAX_UPLOAD_SIZE = 500_000_000  # 500 MB


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

        file_size = Path(local_path).stat().st_size
        if file_size > MAX_UPLOAD_SIZE:
            raise ValueError(
                f"File too large ({file_size} bytes): {local_path}. "
                f"Maximum upload size is {MAX_UPLOAD_SIZE} bytes."
            )

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
            with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as resp:
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
        configured = dustbunny_bin or os.environ.get("DUSTBUNNY_BIN")
        if configured:
            self._bin = configured
            return

        path_candidate = shutil.which("dustbunny")
        if path_candidate:
            self._bin = path_candidate
            return

        local_bin = Path.home() / ".local" / "bin" / "dustbunny"
        if local_bin.exists():
            self._bin = str(local_bin)
            return

        self._bin = str(Path.home() / "projects" / "dustbunny" / "bin" / "dustbunny.mjs")

    def invalidate(self, distribution_id: str, paths: list[str]) -> None:
        """Purge the entire Pull Zone cache.

        Two strategies, in order:

        1. If ``BUNNY_API_KEY`` is in the environment, call Bunny's
           HTTP API directly (POST ``/pullzone/{id}/purgeCache``).
           This is the path CI takes — no Node tooling required.
        2. Otherwise fall back to the local ``dustbunny`` CLI.

        The distribution_id parameter is semantically a Pull Zone ID for
        Bunny targets.  The paths parameter is accepted for interface
        compatibility but ignored — Bunny purge is always zone-wide and free.
        """
        if not distribution_id:
            return
        pull_zone_id = distribution_id

        api_key = os.environ.get("BUNNY_API_KEY", "").strip()
        if api_key:
            self._invalidate_via_http_api(pull_zone_id, api_key)
            return

        cmd = [self._bin, "pz", "purge", pull_zone_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unknown error"
            raise RuntimeError(
                f"CDN cache purge failed for zone {pull_zone_id}: {stderr}"
            )
        logger.info("Purged CDN zone %s", pull_zone_id)

    @staticmethod
    def _invalidate_via_http_api(pull_zone_id: str, api_key: str) -> None:
        """Purge a Bunny Pull Zone via the account-level HTTP API.

        See https://docs.bunny.net/reference/pullzonepublic_purgecache.
        ``api_key`` is the Bunny.net account API key (My Account → API).
        """
        url = f"https://api.bunny.net/pullzone/{pull_zone_id}/purgeCache"
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={
                "AccessKey": api_key,
                "Accept": "application/json",
                "Content-Length": "0",
            },
            data=b"",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                logger.info(
                    "Purged Bunny Pull Zone %s via API (http=%d)",
                    pull_zone_id, resp.status,
                )
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"CDN cache purge failed for zone {pull_zone_id}: "
                f"HTTP {exc.code} {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"CDN cache purge failed for zone {pull_zone_id}: {exc.reason}"
            ) from exc
