"""
Translate absolute paths between Radarr/Sonarr and the media server.

Radarr/Sonarr and the media server (Plex or Jellyfin) often run in separate
containers that mount the same library under different paths (e.g. /data/movies
for Radarr and /movies for Plex). Deduparr works with the paths the media server
reports, so the mappings translate every path exchanged with Radarr/Sonarr: from
the *arr's view to the media server's in responses, and back in requests.

Mappings are written one per line as `<path in the *arr>=<path in the media server>`.
"""

import logging
from typing import Callable, List, Optional, Tuple, TypeVar, cast

logger = logging.getLogger(__name__)

T = TypeVar("T")

# JSON keys of the Radarr/Sonarr API that hold an absolute path
PATH_KEYS = frozenset({"path", "folder", "rootFolderPath"})


def _normalize(path: str) -> str:
    """Strip surrounding whitespace and trailing slashes ("/" becomes "")"""
    return path.strip().rstrip("/")


def _replace_prefix(path: str, old: str, new: str) -> Optional[str]:
    """Replace a directory prefix, or return None if path is not under it"""
    if path == old or path.startswith(old + "/"):
        return (new + path[len(old) :]) or "/"
    return None


class PathMapper:
    """Translates paths between the *arr's view and the media server's view of the library"""

    def __init__(self, mappings: List[Tuple[str, str]]):
        """
        Args:
            mappings: List of (path in the *arr, path in the media server) directory pairs
        """
        normalized = [(_normalize(arr), _normalize(plex)) for arr, plex in mappings]
        # The most specific mapping wins
        self._arr_to_plex = sorted(normalized, key=lambda m: len(m[0]), reverse=True)
        self._plex_to_arr = sorted(
            [(plex, arr) for arr, plex in normalized],
            key=lambda m: len(m[0]),
            reverse=True,
        )

    @classmethod
    def from_text(cls, text: Optional[str]) -> "PathMapper":
        """Parse mappings written one per line as `<*arr path>=<media server path>`"""
        mappings = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            arr_path, separator, plex_path = line.partition("=")
            arr_path, plex_path = arr_path.strip(), plex_path.strip()
            if (
                not separator
                or not arr_path.startswith("/")
                or not plex_path.startswith("/")
            ):
                logger.warning(f"Ignoring invalid path mapping: {line!r}")
                continue
            mappings.append((arr_path, plex_path))
        return cls(mappings)

    @property
    def is_empty(self) -> bool:
        return not self._arr_to_plex

    @staticmethod
    def _convert(path: str, mappings: List[Tuple[str, str]]) -> str:
        for old, new in mappings:
            converted = _replace_prefix(path, old, new)
            if converted is not None:
                return converted
        return path

    def to_plex(self, path: str) -> str:
        """Convert a path as the *arr sees it into the path the media server sees"""
        return self._convert(path, self._arr_to_plex)

    def to_arr(self, path: str) -> str:
        """Convert a path as the media server sees it into the path the *arr sees"""
        return self._convert(path, self._plex_to_arr)

    def translate_to_plex(self, value: T) -> T:
        """Convert the paths of a decoded *arr API response"""
        return cast(T, self._translate(value, self.to_plex))

    def translate_to_arr(self, value: T) -> T:
        """Convert the paths of a request about to be sent to the *arr"""
        return cast(T, self._translate(value, self.to_arr))

    def _translate(self, value: object, convert: Callable[[str], str]) -> object:
        if isinstance(value, dict):
            return {
                key: (
                    convert(item)
                    if key in PATH_KEYS and isinstance(item, str)
                    else self._translate(item, convert)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._translate(item, convert) for item in value]
        return value
