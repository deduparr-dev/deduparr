"""
Disk scan service for filesystem-based duplicate detection.
Independent of Plex/Radarr/Sonarr - scans directories directly.
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


VIDEO_EXTENSIONS = {
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
}


QUALITY_MARKERS = [
    r"\b1080p\b",
    r"\b720p\b",
    r"\b2160p\b",
    r"\b4k\b",
    r"\buhd\b",
    r"\bbluray\b",
    r"\bweb-dl\b",
    r"\bwebrip\b",
    r"\bweb\b",
    r"\bhdtv\b",
    r"\bdvd\b",
    r"\bx264\b",
    r"\bx265\b",
    r"\bh264\b",
    r"\bh265\b",
    r"\bhevc\b",
    r"\bavc\b",
    r"\b10bit\b",
    r"\b8bit\b",
    r"\bdts\b",
    r"\bdts-hd\b",
    r"\bhd\b",
    r"\batmos\b",
    r"\btruehd\b",
    r"\bma\b",
    r"\baac\b",
    r"\bac3\b",
    r"\bdd\b",
    r"\bnordic\b",
    r"\bswedish\b",
    r"\benglish\b",
    r"\beng\b",
    r"\bsdr\b",
    r"\bhdr\b",
    r"\bhdr10\b",
    r"\bdv\b",
    r"\bdolby\b",
]


RELEASE_GROUP_PATTERN = r"-[a-zA-Z0-9]+$"


class DiskFileInfo(TypedDict):
    """Information about a file found on disk"""

    path: str
    size: int
    is_hardlink: bool
    inode: int
    normalized_name: str


def is_sample_file(file_path: str) -> bool:
    """
    Check if a file path represents a sample file.

    Args:
        file_path: Full file path to check

    Returns:
        True if file appears to be a sample, False otherwise
    """
    if not file_path:
        return False

    file_path_lower = file_path.lower()

    sample_patterns = [
        "sample",
        "trailer",
        "preview",
        "rarbg.com",
        "etrg.mp4",
        "-sample.",
        "_sample.",
        ".sample.",
    ]

    return any(pattern in file_path_lower for pattern in sample_patterns)


class DiskScanService:
    """
    Filesystem-based duplicate detection service.
    Independent of Plex/Radarr/Sonarr - scans directories directly.
    """

    def find_duplicate_movies_on_disk(
        self, directory_paths: List[str]
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicate movies by scanning filesystem directly.

        Args:
            directory_paths: List of directories to scan

        Returns:
            Dict mapping normalized movie name to list of duplicate files
        """
        logger.info(f"Scanning {len(directory_paths)} directories for duplicate movies")

        all_files: List[str] = []
        for directory in directory_paths:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist: {directory}")
                continue

            files = self._scan_directory(directory, recursive=True)
            all_files.extend(files)

        logger.info(f"Found {len(all_files)} video files")

        grouped = self._group_by_normalized_name(all_files, is_movie=True)

        duplicates = self._filter_hardlinks(grouped)

        logger.info(
            f"Found {len(duplicates)} duplicate movie groups (after hardlink filtering)"
        )

        return duplicates

    def find_duplicate_episodes_on_disk(
        self, directory_paths: List[str]
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicate episodes by scanning filesystem directly.

        Args:
            directory_paths: List of directories to scan

        Returns:
            Dict mapping show+episode identifier to list of duplicate files
        """
        logger.info(
            f"Scanning {len(directory_paths)} directories for duplicate episodes"
        )

        all_files: List[str] = []
        for directory in directory_paths:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist: {directory}")
                continue

            files = self._scan_directory(directory, recursive=True)
            all_files.extend(files)

        logger.info(f"Found {len(all_files)} video files")

        grouped = self._group_by_normalized_name(all_files, is_movie=False)

        duplicates = self._filter_hardlinks(grouped)

        logger.info(
            f"Found {len(duplicates)} duplicate episode groups (after hardlink filtering)"
        )

        return duplicates

    def _scan_directory(self, directory: str, recursive: bool = True) -> List[str]:
        """
        Scan a directory for video files.

        Args:
            directory: Directory path to scan
            recursive: Whether to scan subdirectories

        Returns:
            List of video file paths
        """
        video_files: List[str] = []

        try:
            if recursive:
                for root, _, files in os.walk(directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if self._is_video_file(file_path) and not is_sample_file(
                            file_path
                        ):
                            video_files.append(file_path)
            else:
                for item in os.listdir(directory):
                    file_path = os.path.join(directory, item)
                    if os.path.isfile(file_path) and self._is_video_file(file_path):
                        if not is_sample_file(file_path):
                            video_files.append(file_path)
        except PermissionError as e:
            logger.warning(f"Permission denied scanning directory {directory}: {e}")
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")

        return video_files

    def _is_video_file(self, file_path: str) -> bool:
        """
        Check if a file is a video file based on extension.

        Args:
            file_path: File path to check

        Returns:
            True if file is a video file
        """
        return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS

    def _normalize_filename(self, filename: str) -> str:
        """
        Normalize a filename for comparison.

        Removes quality markers, release groups, special characters, etc.

        Args:
            filename: Filename to normalize

        Returns:
            Normalized filename
        """
        name = Path(filename).stem

        name = name.lower()

        for pattern in QUALITY_MARKERS:
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)

        name = re.sub(r"[\.\-_]+", " ", name)

        name = re.sub(RELEASE_GROUP_PATTERN, "", name)

        name = re.sub(r"\s+", " ", name).strip()

        return name

    def _extract_year(self, filename: str) -> Optional[str]:
        """
        Extract year from filename.

        Args:
            filename: Filename to extract year from

        Returns:
            Year as string, or None if not found
        """
        match = re.search(r"\b(19\d{2}|20\d{2})\b", filename)
        return match.group(1) if match else None

    def _extract_episode_info(self, filename: str) -> Optional[str]:
        """
        Extract episode information from filename (S01E01 format).

        Args:
            filename: Filename to extract episode info from

        Returns:
            Episode info in S00E00 format, or None if not found
        """
        patterns = [
            r"[sS](\d{1,2})[eE](\d{1,2})",
            r"(\d{1,2})x(\d{1,2})",
            r"[sS]eason[\s\.]?(\d{1,2})[\s\.]?[eE]pisode[\s\.]?(\d{1,2})",
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2))
                return f"S{season:02d}E{episode:02d}"

        return None

    def _are_hardlinks(self, file1: str, file2: str) -> bool:
        """
        Check if two files are hardlinks (same inode).

        Args:
            file1: First file path
            file2: Second file path

        Returns:
            True if files are hardlinks
        """
        try:
            stat1 = os.stat(file1)
            stat2 = os.stat(file2)

            return stat1.st_ino == stat2.st_ino and stat1.st_dev == stat2.st_dev
        except OSError as e:
            logger.warning(f"Failed to check hardlink status: {e}")
            return False

    def _group_by_normalized_name(
        self, files: List[str], is_movie: bool = True
    ) -> Dict[str, List[str]]:
        """
        Group files by normalized name.

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping normalized name to list of file paths
        """
        groups: Dict[str, List[str]] = {}

        for file_path in files:
            filename = os.path.basename(file_path)

            if is_movie:
                normalized = self._normalize_filename(filename)
                year = self._extract_year(filename)

                key = f"{normalized}|{year}" if year else normalized
            else:
                episode_info = self._extract_episode_info(filename)

                if not episode_info:
                    logger.debug(
                        f"Could not extract episode info from: {filename}, skipping"
                    )
                    continue

                parent_dir = os.path.basename(os.path.dirname(file_path))
                normalized = self._normalize_filename(parent_dir)

                key = f"{normalized}|{episode_info}"

            if key not in groups:
                groups[key] = []
            groups[key].append(file_path)

        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}

        logger.debug(
            f"Grouped {len(files)} files into {len(duplicate_groups)} potential duplicate groups"
        )

        return duplicate_groups

    def _filter_hardlinks(
        self, groups: Dict[str, List[str]]
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Filter out hardlinks from duplicate groups.

        Args:
            groups: Dict mapping key to list of file paths

        Returns:
            Dict mapping key to list of DiskFileInfo (excluding hardlink groups)
        """
        result: Dict[str, List[DiskFileInfo]] = {}

        for key, file_paths in groups.items():
            file_infos: List[DiskFileInfo] = []
            seen_inodes: Dict[int, str] = {}

            for file_path in file_paths:
                try:
                    stat_info = os.stat(file_path)
                    inode = stat_info.st_ino

                    if inode in seen_inodes:
                        original_path = seen_inodes[inode]
                        logger.debug(
                            f"Hardlink detected: {file_path} -> {original_path}"
                        )
                        continue

                    seen_inodes[inode] = file_path

                    is_hardlink = stat_info.st_nlink > 1

                    file_infos.append(
                        {
                            "path": file_path,
                            "size": stat_info.st_size,
                            "is_hardlink": is_hardlink,
                            "inode": inode,
                            "normalized_name": key,
                        }
                    )
                except OSError as e:
                    logger.warning(f"Failed to stat file {file_path}: {e}")
                    continue

            if len(file_infos) > 1:
                result[key] = file_infos
                logger.debug(
                    f"Found {len(file_infos)} true duplicates for '{key}' (after hardlink filtering)"
                )

        return result
