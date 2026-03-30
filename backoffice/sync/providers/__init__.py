"""Provider factory."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backoffice.config import Config

from backoffice.sync.providers.base import CDNProvider, StorageProvider


def get_providers(config: "Config") -> tuple[StorageProvider, CDNProvider]:
    """Create storage and CDN providers from config."""
    provider = config.deploy.provider
    if provider == "bunny":
        from backoffice.sync.providers.bunny import BunnyCDN, BunnyStorage
        bunny = config.deploy.bunny
        return (
            BunnyStorage(bunny.storage_zone, bunny.storage_region, bunny.storage_key),
            BunnyCDN(),
        )
    raise ValueError(f"Unknown deploy provider: {provider}")
