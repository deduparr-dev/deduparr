"""
Media server access.

An instance can have Plex, Jellyfin, or both set up, and a scan covers every
one of them. A server counts as configured when its credentials are present,
so there is no separate "which server" setting to keep in step.

Work against the MediaServer protocol; nothing above this package should know
which server answered.
"""

import logging
from typing import Dict, List, Sequence, Type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config
from app.services.media_server.base import (
    ConnectionInfo,
    DuplicateGroup,
    LibraryInfo,
    MediaServer,
    MediaServerError,
    MediaServerType,
)
from app.services.media_server.file_probe import (
    DEFAULT_SAMPLE_PATTERNS,
    SERVER_SAMPLE_PATTERNS,
    FileProbe,
    is_sample_file,
    probe_file,
)
from app.services.media_server.jellyfin_adapter import JellyfinAdapter
from app.services.media_server.plex_adapter import PlexAdapter

logger = logging.getLogger(__name__)

# Credentials that have to be present for a server to be usable at all.
REQUIRED_CONFIG: Dict[MediaServerType, Sequence[str]] = {
    MediaServerType.PLEX: ("plex_auth_token",),
    MediaServerType.JELLYFIN: ("jellyfin_url", "jellyfin_api_key"),
}

_ADAPTERS: Dict[MediaServerType, Type] = {
    MediaServerType.PLEX: PlexAdapter,
    MediaServerType.JELLYFIN: JellyfinAdapter,
}


def libraries_config_key(server_type: MediaServerType) -> str:
    """
    The config key holding which of a server's libraries to scan.

    Named per server - plex_libraries, jellyfin_libraries - so the two never
    share a selection: a user running both may want only one of them scanned,
    and two servers can have libraries of the same name.
    """
    return f"{server_type.value}_libraries"


async def selected_libraries(
    db: AsyncSession, server_type: MediaServerType
) -> List[str]:
    """Library names the user chose for one server."""
    result = await db.execute(
        select(Config).where(Config.key == libraries_config_key(server_type))
    )
    config = result.scalar_one_or_none()
    if not config or not config.value:
        return []
    return [name.strip() for name in config.value.split(",") if name.strip()]


async def configured_types(db: AsyncSession) -> List[MediaServerType]:
    """Media servers this instance has credentials for, in a stable order."""
    result = await db.execute(select(Config.key, Config.value))
    present = {key for key, value in result.all() if value}

    return [
        server_type
        for server_type, keys in REQUIRED_CONFIG.items()
        if all(key in present for key in keys)
    ]


async def get_media_servers(db: AsyncSession) -> List[MediaServer]:
    """
    Every configured media server.

    Empty when setup has not been completed; callers decide whether that is an
    error worth reporting to the user.
    """
    return [_ADAPTERS[server_type](db) for server_type in await configured_types(db)]


async def get_media_server(
    db: AsyncSession, server_type: MediaServerType
) -> MediaServer:
    """One specific media server, for acting on an item it reported."""
    adapter = _ADAPTERS.get(server_type)
    if adapter is None:
        raise MediaServerError(f"{server_type.value} is not supported")
    return adapter(db)


__all__ = [
    "ConnectionInfo",
    "DEFAULT_SAMPLE_PATTERNS",
    "DuplicateGroup",
    "FileProbe",
    "LibraryInfo",
    "MediaServer",
    "MediaServerError",
    "MediaServerType",
    "JellyfinAdapter",
    "PlexAdapter",
    "REQUIRED_CONFIG",
    "SERVER_SAMPLE_PATTERNS",
    "configured_types",
    "get_media_server",
    "get_media_servers",
    "is_sample_file",
    "libraries_config_key",
    "probe_file",
    "selected_libraries",
]
