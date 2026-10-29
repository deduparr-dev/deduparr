"""
Filesystem facts about a media file.

Both media server adapters and the disk scanner need to know whether a path is
a throwaway sample and what the filesystem says about it, so that lives here
once instead of in each of them.
"""

import os
from dataclasses import dataclass
from typing import Optional, Sequence

# The filesystem scanner walks release directories, so it also sees the extras
# a release group ships next to the feature.
DEFAULT_SAMPLE_PATTERNS: tuple[str, ...] = (
    "sample",
    "trailer",
    "preview",
    "rarbg.com",
    "etrg.mp4",
    "-sample.",
    "_sample.",
    ".sample.",
    "featurette",
    "deleted",
    "extra",
)

# A media server only ever lists what it has catalogued as part of the item, so
# matching "sample" alone is enough and avoids discarding a legitimate title
# that merely contains one of the broader words.
SERVER_SAMPLE_PATTERNS: tuple[str, ...] = ("sample",)

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".m2ts",
        ".ts",
        ".vob",
        ".ogv",
    }
)


def is_video_file(file_path: str) -> bool:
    """Whether a path has a video file extension."""
    return os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS


def is_sample_file(file_path: str, patterns: Optional[Sequence[str]] = None) -> bool:
    """Whether a path looks like a sample rather than the feature itself."""
    if not file_path:
        return False

    lowered = file_path.lower()
    return any(pattern in lowered for pattern in (patterns or DEFAULT_SAMPLE_PATTERNS))


@dataclass(frozen=True)
class FileProbe:
    """What the filesystem reports for one path."""

    exists: bool
    size: int
    inode: Optional[int]
    is_hardlink: bool


def probe_file(file_path: str) -> FileProbe:
    """
    Stat a path, treating any failure as "not there".

    A missing inode is how the scan layer recognises a file the media server
    still advertises but that no longer exists on disk.
    """
    if not file_path:
        return FileProbe(exists=False, size=0, inode=None, is_hardlink=False)

    try:
        stat_info = os.stat(file_path)
    except OSError:
        return FileProbe(exists=False, size=0, inode=None, is_hardlink=False)

    return FileProbe(
        exists=True,
        size=stat_info.st_size,
        inode=stat_info.st_ino,
        is_hardlink=stat_info.st_nlink > 1,
    )
