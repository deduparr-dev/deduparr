"""
The contract a media server adapter fulfils.

Everything above this layer - scanning, scoring, deletion - works in these
terms and never touches a server SDK.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Protocol, TypedDict

from app.services.scan.scoring_engine import MediaMetadata


class MediaServerType(str, Enum):
    """Media servers Deduparr can scan."""

    PLEX = "plex"
    JELLYFIN = "jellyfin"


class MediaServerError(Exception):
    """A media server could not satisfy a request."""


class LibraryInfo(TypedDict):
    """One library as the server describes it."""

    key: str
    title: str
    type: str  # "movie" or "show"
    count: int


class ConnectionInfo(TypedDict, total=False):
    """Outcome of a connection test, rendered straight into the setup wizard."""

    success: bool
    error: str
    server_name: str
    version: str


@dataclass(frozen=True)
class DuplicateGroup:
    """
    Every file one movie or episode is stored as.

    The group is what the scan layer turns into a DuplicateSet: all but the
    highest scoring file become deletion candidates.
    """

    item_id: str
    title: str
    files: List[MediaMetadata]


class MediaServer(Protocol):
    """
    What Deduparr asks of a media server.

    Authentication is deliberately absent: Plex uses an OAuth PIN exchange and
    Jellyfin an API key, so each adapter owns its own credential flow and only
    the operations below are shared.
    """

    type: MediaServerType

    async def test_connection(self) -> ConnectionInfo:
        """Confirm the server is reachable and the credentials work."""
        ...

    async def get_libraries(
        self, library_type: Optional[str] = None
    ) -> List[LibraryInfo]:
        """List libraries, optionally narrowed to "movie" or "show"."""
        ...

    async def find_duplicate_movies(self, library_name: str) -> List[DuplicateGroup]:
        """Movies the server holds more than one file for."""
        ...

    async def find_duplicate_episodes(self, library_name: str) -> List[DuplicateGroup]:
        """Episodes the server holds more than one file for."""
        ...

    async def get_library_paths(self, library_name: str) -> List[str]:
        """Filesystem roots of a library, for the optional deep scan."""
        ...

    async def refresh_item(self, item_id: str) -> bool:
        """Re-read one item, so a deletion is reflected without a full scan."""
        ...

    async def refresh_library(self, library_name: str) -> bool:
        """Re-scan a whole library, used when a targeted refresh is not enough."""
        ...
