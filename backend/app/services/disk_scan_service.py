"""
Disk scan service for filesystem-based duplicate detection.
Scans directories directly using filename parsing and optional checksums.
Can be used standalone or integrated with Plex/Radarr/Sonarr via scan orchestrator.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# Default patterns - can be extended via configuration
DEFAULT_VIDEO_EXTENSIONS = {
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


DEFAULT_QUALITY_MARKERS = [
    # Resolution markers
    r"\b1080p\b",
    r"\b720p\b",
    r"\b2160p\b",
    r"\b4k\b",
    r"\buhd\b",
    r"\b480p\b",
    r"\b576p\b",
    r"\b540p\b",
    r"\b360p\b",
    # Source markers
    r"\bbluray\b",
    r"\bblu-ray\b",
    r"\bbrrip\b",
    r"\bbdrip\b",
    r"\bweb-dl\b",
    r"\bwebdl\b",
    r"\bwebrip\b",
    r"\bweb\b",
    r"\bhdtv\b",
    r"\bdvd\b",
    r"\bdvdrip\b",
    r"\bremux\b",
    r"\bhdcam\b",
    r"\bcam\b",
    r"\btelesync\b",
    r"\bts\b",
    r"\bworkprint\b",
    r"\bwp\b",
    r"\bpdtv\b",
    r"\bsdtv\b",
    # Codec markers
    r"\bx264\b",
    r"\bx265\b",
    r"\bh\.?264\b",
    r"\bh\.?265\b",
    r"\bhevc\b",
    r"\bavc\b",
    r"\bvc-?1\b",
    r"\bmpeg-?2\b",
    r"\bav1\b",
    # Bit depth
    r"\b10bit\b",
    r"\b8bit\b",
    r"\b12bit\b",
    # Audio markers
    r"\bdts\b",
    r"\bdts-hd\b",
    r"\bdts-x\b",
    r"\bhd\b",
    r"\batmos\b",
    r"\btruehd\b",
    r"\bma\b",
    r"\baac\b",
    r"\bac3\b",
    r"\bdd\b",
    r"\bdd\+\b",
    r"\beac3\b",
    r"\bflac\b",
    r"\blpcm\b",
    r"\bmp3\b",
    r"\bopus\b",
    r"\bvorbis\b",
    # Audio channels
    r"\b5\.1\b",
    r"\b7\.1\b",
    r"\b2\.0\b",
    r"\b1\.0\b",
    r"\bmono\b",
    r"\bstereo\b",
    r"\bsurround\b",
    # HDR formats
    r"\bhdr\b",
    r"\bhdr10\b",
    r"\bhdr10\+\b",
    r"\bdolby[\s\.]?vision\b",
    r"\bdv\b",
    r"\bsdr\b",
    # Language markers
    r"\bnordic\b",
    r"\bswedish\b",
    r"\benglish\b",
    r"\beng\b",
    r"\bmulti\b",
    r"\bdual[\s\.]?audio\b",
    r"\bfrench\b",
    r"\bgerman\b",
    r"\bspanish\b",
    r"\bitalian\b",
    r"\bjapanese\b",
    r"\bchinese\b",
    # Edition markers
    r"\bextended\b",
    r"\bunrated\b",
    r"\bdirector'?s?[\s\.]?cut\b",
    r"\btheatrical\b",
    r"\bultimate\b",
    r"\bremastered\b",
    r"\bimax\b",
    r"\bcriterion\b",
    r"\bspecial[\s\.]?edition\b",
    # Version markers
    r"\bproper\b",
    r"\brepack\b",
    r"\brerip\b",
    r"\breal\b",
    # Container/format
    r"\bmkv\b",
    r"\bmp4\b",
    r"\bavi\b",
    r"\bm4v\b",
    r"\bts\b",
]


DEFAULT_SAMPLE_PATTERNS = [
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
]


DEFAULT_RELEASE_GROUP_PATTERN = r"-[a-zA-Z0-9]+$"


class DuplicateDetectionStrategy(str, Enum):
    """Strategies for detecting duplicates"""

    NAME_ONLY = "name_only"  # Only normalized name matching
    NAME_AND_EXACT_SIZE = "name_and_exact_size"  # Name + exact size match
    NAME_AND_SIMILAR_SIZE = "name_and_similar_size"  # Name + size within threshold
    EXACT_SIZE = "exact_size"  # Only exact size (ignores name)
    CHECKSUM = "checksum"  # File content hash (slow but accurate)
    COMBINED = "combined"  # All strategies combined for maximum detection


class HardlinkHandling(str, Enum):
    """How to handle hardlinked files"""

    EXCLUDE = "exclude"  # Remove hardlinks from results completely
    INCLUDE = "include"  # Include hardlinks in results
    REPORT_SEPARATELY = "report_separately"  # Keep hardlinks but mark them


@dataclass
class DiskScanConfig:
    """Configuration for disk-based duplicate scanning"""

    # Detection strategy
    strategy: DuplicateDetectionStrategy = DuplicateDetectionStrategy.NAME_ONLY

    # Size comparison threshold (percentage, e.g., 5.0 = ±5%)
    size_threshold_percent: float = 5.0

    # Minimum file size to consider (bytes, 0 = no minimum)
    min_file_size: int = 0

    # Maximum file size to consider (bytes, 0 = no maximum)
    max_file_size: int = 0

    # How to handle hardlinks
    hardlink_handling: HardlinkHandling = HardlinkHandling.EXCLUDE

    # Enable checksum calculation (slow)
    enable_checksum: bool = False

    # Checksum chunk size for reading files
    checksum_chunk_size: int = 8192

    # Patterns and extensions (customizable)
    video_extensions: Set[str] = field(default_factory=lambda: DEFAULT_VIDEO_EXTENSIONS)
    quality_markers: List[str] = field(default_factory=lambda: DEFAULT_QUALITY_MARKERS)
    sample_patterns: List[str] = field(default_factory=lambda: DEFAULT_SAMPLE_PATTERNS)
    release_group_pattern: str = DEFAULT_RELEASE_GROUP_PATTERN

    # Scanning options
    recursive: bool = True
    follow_symlinks: bool = False


class DiskFileInfo(TypedDict):
    """Information about a file found on disk"""

    path: str
    size: int
    is_hardlink: bool
    inode: int
    normalized_name: str
    checksum: Optional[str]
    confidence_score: float  # 0.0 to 1.0, higher = more confident it's a duplicate
    detection_method: str  # "name", "size", "checksum", "name_and_size", "combined"


def is_sample_file(file_path: str, patterns: Optional[List[str]] = None) -> bool:
    """
    Check if a file path represents a sample file.

    Args:
        file_path: Full file path to check
        patterns: Custom sample patterns (uses defaults if None)

    Returns:
        True if file appears to be a sample, False otherwise
    """
    if not file_path:
        return False

    file_path_lower = file_path.lower()
    check_patterns = patterns or DEFAULT_SAMPLE_PATTERNS

    return any(pattern in file_path_lower for pattern in check_patterns)


class DiskScanService:
    """
    Filesystem-based duplicate detection service.
    Scans directories using filename parsing, size comparison, and optional checksums.

    Supports multiple detection strategies:
    - Name-based matching (fast, may have false positives)
    - Size-based matching (exact or fuzzy)
    - Checksum verification (slow but definitive)
    - Combined strategies for comprehensive detection
    """

    def __init__(self, config: Optional[DiskScanConfig] = None):
        """
        Initialize disk scan service with configuration.

        Args:
            config: Configuration for scanning behavior (uses defaults if None)
        """
        self.config = config or DiskScanConfig()
        logger.info(
            f"Initialized DiskScanService with strategy: {self.config.strategy}"
        )

    def find_duplicate_movies_on_disk(
        self, directory_paths: List[str]
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicate movies by scanning filesystem directly.

        Uses configured detection strategy for finding duplicates.

        Args:
            directory_paths: List of directories to scan

        Returns:
            Dict mapping identifier to list of duplicate files
        """
        logger.info(
            f"Scanning {len(directory_paths)} directories for duplicate movies "
            f"(strategy: {self.config.strategy})"
        )

        all_files = self._scan_all_directories(directory_paths)
        logger.info(f"Found {len(all_files)} video files")

        if not all_files:
            return {}

        # Apply detection strategy
        duplicates = self._detect_duplicates(all_files, is_movie=True)

        logger.info(f"Found {len(duplicates)} duplicate movie groups")

        return duplicates

    def find_duplicate_episodes_on_disk(
        self, directory_paths: List[str]
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicate episodes by scanning filesystem directly.

        Uses configured detection strategy for finding duplicates.

        Args:
            directory_paths: List of directories to scan

        Returns:
            Dict mapping show+episode identifier to list of duplicate files
        """
        logger.info(
            f"Scanning {len(directory_paths)} directories for duplicate episodes "
            f"(strategy: {self.config.strategy})"
        )

        all_files = self._scan_all_directories(directory_paths)
        logger.info(f"Found {len(all_files)} video files")

        if not all_files:
            return {}

        # Apply detection strategy
        duplicates = self._detect_duplicates(all_files, is_movie=False)

        logger.info(f"Found {len(duplicates)} duplicate episode groups")

        return duplicates

    def _scan_all_directories(self, directory_paths: List[str]) -> List[str]:
        """
        Scan all directories for video files.

        Args:
            directory_paths: List of directories to scan

        Returns:
            Combined list of all video file paths
        """
        all_files: List[str] = []

        for directory in directory_paths:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist: {directory}")
                continue

            files = self._scan_directory(directory, self.config.recursive)
            all_files.extend(files)

        return all_files

    def _detect_duplicates(
        self, files: List[str], is_movie: bool = True
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Detect duplicates using configured strategy.

        Args:
            files: List of file paths to analyze
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping identifier to list of duplicate file info
        """
        strategy = self.config.strategy

        if strategy == DuplicateDetectionStrategy.NAME_ONLY:
            return self._find_by_name(files, is_movie)

        elif strategy == DuplicateDetectionStrategy.EXACT_SIZE:
            return self._find_by_exact_size(files, is_movie)

        elif strategy == DuplicateDetectionStrategy.NAME_AND_EXACT_SIZE:
            return self._find_by_name_and_exact_size(files, is_movie)

        elif strategy == DuplicateDetectionStrategy.NAME_AND_SIMILAR_SIZE:
            return self._find_by_name_and_similar_size(files, is_movie)

        elif strategy == DuplicateDetectionStrategy.CHECKSUM:
            return self._find_by_checksum(files, is_movie)

        elif strategy == DuplicateDetectionStrategy.COMBINED:
            return self._find_by_combined_strategy(files, is_movie)

        else:
            logger.warning(f"Unknown strategy {strategy}, falling back to NAME_ONLY")
            return self._find_by_name(files, is_movie)

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
                for root, _, files in os.walk(
                    directory, followlinks=self.config.follow_symlinks
                ):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if self._is_valid_video_file(file_path):
                            video_files.append(file_path)
            else:
                for item in os.listdir(directory):
                    file_path = os.path.join(directory, item)
                    if os.path.isfile(file_path) and self._is_valid_video_file(
                        file_path
                    ):
                        video_files.append(file_path)
        except PermissionError as e:
            logger.warning(f"Permission denied scanning directory {directory}: {e}")
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")

        return video_files

    def _is_valid_video_file(self, file_path: str) -> bool:
        """
        Check if file is a valid video file (correct extension, not sample, within size limits).

        Args:
            file_path: File path to check

        Returns:
            True if file is a valid video file to process
        """
        # Check extension
        if not self._is_video_file(file_path):
            return False

        # Check sample patterns
        if is_sample_file(file_path, self.config.sample_patterns):
            logger.debug(f"Skipping sample file: {file_path}")
            return False

        # Check file size limits
        try:
            size = os.path.getsize(file_path)

            if self.config.min_file_size > 0 and size < self.config.min_file_size:
                logger.debug(
                    f"Skipping file below minimum size ({size} < {self.config.min_file_size}): {file_path}"
                )
                return False

            if self.config.max_file_size > 0 and size > self.config.max_file_size:
                logger.debug(
                    f"Skipping file above maximum size ({size} > {self.config.max_file_size}): {file_path}"
                )
                return False

        except OSError as e:
            logger.warning(f"Could not get size for {file_path}: {e}")
            return False

        return True

    def _is_video_file(self, file_path: str) -> bool:
        """
        Check if a file is a video file based on extension.

        Args:
            file_path: File path to check

        Returns:
            True if file is a video file
        """
        return Path(file_path).suffix.lower() in self.config.video_extensions

    def _normalize_articles(self, name: str) -> str:
        """
        Move leading articles (The, A, An) to the end for better matching.

        Based on Radarr's CleanTitle implementation:
        - "The Movie" -> "Movie, The"
        - "A Film" -> "Film, A"
        - "An Episode" -> "Episode, An"

        Args:
            name: Name to normalize

        Returns:
            Name with articles moved to end
        """
        name = name.strip()

        # Pattern to match leading articles with word boundary
        article_pattern = r"^(the|a|an)\s+"
        match = re.match(article_pattern, name, re.IGNORECASE)

        if match:
            article = match.group(1)
            rest = name[len(match.group(0)) :]
            # Move article to end with comma (lowercase for consistency)
            return f"{rest}, {article.lower()}"

        return name

    def _parse_with_fallback(
        self, file_path: str, is_movie: bool = True
    ) -> Optional[str]:
        """
        Parse filename with 3-level fallback chain (inspired by Radarr/Sonarr).

        Fallback levels:
        1. Filename only: "Movie.2020.1080p.BluRay.mkv"
        2. Directory + Filename: "Movies/Movie (2020)/Movie.2020.1080p.BluRay.mkv"
        3. Directory + Extension: "Movies/Movie (2020)/.mkv" (last resort for badly named files)

        Args:
            file_path: Full path to file
            is_movie: True for movies, False for episodes

        Returns:
            Normalized identifier for grouping, or None if unparseable
        """
        filename = os.path.basename(file_path)
        parent_dir = os.path.basename(os.path.dirname(file_path))

        # Level 1: Try filename only
        if is_movie:
            normalized = self._normalize_filename(filename)
            year = self._extract_year(filename)

            # Check if we got meaningful content (not just extension or empty)
            if normalized and len(normalized) > 2:
                key = f"{normalized}|{year}" if year else normalized
                return key

            # Level 2: Try directory + filename
            combined = f"{parent_dir} {filename}"
            normalized = self._normalize_filename(combined)
            year = self._extract_year(combined)

            if normalized and len(normalized) > 2:
                key = f"{normalized}|{year}" if year else normalized
                return key

            # Level 3: Try directory + extension (last resort)
            ext = os.path.splitext(filename)[1]
            combined = f"{parent_dir}{ext}"
            normalized = self._normalize_filename(combined)
            year = self._extract_year(parent_dir)

            if normalized and len(normalized) > 2:
                key = f"{normalized}|{year}" if year else normalized
                return key
        else:
            # For episodes, try filename first
            episode_info = self._extract_episode_info(filename)

            if episode_info:
                return episode_info

            # Level 2: Try directory + filename for episodes
            combined = f"{parent_dir} {filename}"
            episode_info = self._extract_episode_info(combined)

            if episode_info:
                return episode_info

            # Level 3: Try directory name only
            episode_info = self._extract_episode_info(parent_dir)

            if episode_info:
                return episode_info

        return None

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

        # Remove quality markers using configured patterns
        for pattern in self.config.quality_markers:
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)

        # Replace separators with spaces
        name = re.sub(r"[\.\-_]+", " ", name)

        # Remove release groups using configured pattern
        name = re.sub(self.config.release_group_pattern, "", name)

        # Normalize whitespace
        name = re.sub(r"\s+", " ", name).strip()

        # Normalize articles (The, A, An) - do this AFTER cleaning
        name = self._normalize_articles(name)

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

    def _calculate_checksum(self, file_path: str) -> Optional[str]:
        """
        Calculate MD5 checksum of file.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of MD5 hash, or None if error
        """
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(self.config.checksum_chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.warning(f"Could not calculate checksum for {file_path}: {e}")
            return None

    def _calculate_confidence_score(
        self,
        name_match: bool,
        exact_size_match: bool,
        similar_size_match: bool,
        checksum_match: bool,
    ) -> tuple[float, str]:
        """
        Calculate confidence score and detection method for duplicate detection.

        Args:
            name_match: Whether normalized names match
            exact_size_match: Whether file sizes are identical
            similar_size_match: Whether file sizes are within threshold
            checksum_match: Whether file checksums match

        Returns:
            Tuple of (confidence score from 0.0 to 1.0, detection method string)
        """
        # Checksum match is definitive
        if checksum_match:
            return (1.0, "checksum")

        # Name + exact size is very high confidence
        if name_match and exact_size_match:
            return (0.95, "name_and_exact_size")

        # Name + similar size is high confidence
        elif name_match and similar_size_match:
            return (0.85, "name_and_similar_size")

        # Exact size only (different names) is medium confidence
        elif exact_size_match and not name_match:
            return (0.70, "exact_size")

        # Name only is lower confidence
        elif name_match:
            return (0.60, "name")

        # Similar size only
        elif similar_size_match:
            return (0.50, "similar_size")

        return (0.0, "none")

    def _are_sizes_similar(self, size1: int, size2: int) -> bool:
        """
        Check if two file sizes are within configured threshold.

        Args:
            size1: First file size in bytes
            size2: Second file size in bytes

        Returns:
            True if sizes are within threshold percentage
        """
        if size1 == size2:
            return True

        max_size = max(size1, size2)
        if max_size == 0:
            return False

        diff_percent = abs(size1 - size2) / max_size * 100
        return diff_percent <= self.config.size_threshold_percent

    # ===== Detection Strategy Methods =====

    def _find_by_name(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates by normalized name only.

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping normalized name to list of duplicate files
        """
        grouped = self._group_by_normalized_name(files, is_movie)
        return self._process_groups(grouped, check_size=False, check_checksum=False)

    def _find_by_exact_size(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates by exact file size only (ignores name).

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping size to list of duplicate files
        """
        groups: Dict[str, List[str]] = {}

        for file_path in files:
            try:
                size = os.path.getsize(file_path)
                key = f"size_{size}"

                if key not in groups:
                    groups[key] = []
                groups[key].append(file_path)
            except OSError as e:
                logger.warning(f"Failed to get size for {file_path}: {e}")
                continue

        # Only keep groups with duplicates
        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}

        return self._process_groups(
            duplicate_groups, check_size=False, check_checksum=False
        )

    def _find_by_name_and_exact_size(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates by normalized name AND exact size match.

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping name to list of duplicate files
        """
        name_groups = self._group_by_normalized_name(files, is_movie)

        # Within each name group, sub-group by exact size
        result: Dict[str, List[str]] = {}

        for name_key, file_list in name_groups.items():
            size_subgroups: Dict[int, List[str]] = {}

            for file_path in file_list:
                try:
                    size = os.path.getsize(file_path)
                    if size not in size_subgroups:
                        size_subgroups[size] = []
                    size_subgroups[size].append(file_path)
                except OSError:
                    continue

            # Only keep size groups with duplicates
            for size, size_file_list in size_subgroups.items():
                if len(size_file_list) > 1:
                    key = f"{name_key}|size_{size}"
                    result[key] = size_file_list

        return self._process_groups(result, check_size=False, check_checksum=False)

    def _find_by_name_and_similar_size(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates by normalized name AND similar size (within threshold).

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping name to list of duplicate files
        """
        name_groups = self._group_by_normalized_name(files, is_movie)

        # Within each name group, find files with similar sizes
        result: Dict[str, List[str]] = {}

        for name_key, file_list in name_groups.items():
            if len(file_list) < 2:
                continue

            # Get file sizes
            file_sizes: List[tuple[str, int]] = []
            for file_path in file_list:
                try:
                    size = os.path.getsize(file_path)
                    file_sizes.append((file_path, size))
                except OSError:
                    continue

            # Group by similar sizes
            size_groups: Dict[str, List[str]] = {}

            for file_path, size in file_sizes:
                # Find which group this belongs to
                assigned = False

                for group_key, group_files in size_groups.items():
                    # Check if size is similar to any file in this group
                    for existing_path in group_files:
                        existing_size = next(
                            s for p, s in file_sizes if p == existing_path
                        )
                        if self._are_sizes_similar(size, existing_size):
                            size_groups[group_key].append(file_path)
                            assigned = True
                            break
                    if assigned:
                        break

                if not assigned:
                    # Create new size group
                    group_key = f"{name_key}|~{size // (1024 * 1024)}MB"
                    size_groups[group_key] = [file_path]

            # Add groups with duplicates
            for group_key, group_files in size_groups.items():
                if len(group_files) > 1:
                    result[group_key] = group_files

        return self._process_groups(result, check_size=True, check_checksum=False)

    def _find_by_checksum(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates by file checksum (slow but definitive).

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping checksum to list of duplicate files
        """
        logger.info(
            f"Calculating checksums for {len(files)} files (this may take a while)..."
        )

        checksum_groups: Dict[str, List[str]] = {}
        total = len(files)

        for i, file_path in enumerate(files, 1):
            if i % 10 == 0:
                logger.info(f"Hashing file {i}/{total}...")

            checksum = self._calculate_checksum(file_path)
            if checksum:
                if checksum not in checksum_groups:
                    checksum_groups[checksum] = []
                checksum_groups[checksum].append(file_path)

        # Only keep groups with duplicates
        duplicate_groups = {k: v for k, v in checksum_groups.items() if len(v) > 1}

        return self._process_groups(
            duplicate_groups, check_size=False, check_checksum=True
        )

    def _find_by_combined_strategy(
        self, files: List[str], is_movie: bool
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Find duplicates using all strategies combined for maximum detection.

        Combines:
        1. Name-based grouping
        2. Size similarity checks
        3. Optional checksum verification

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping identifier to list of duplicate files with confidence scores
        """
        # Start with name-based grouping (fastest)
        name_groups = self._group_by_normalized_name(files, is_movie)

        # Also check for exact size duplicates (catches different names, same content)
        size_groups = self._find_by_exact_size(files, is_movie)

        # Merge the groups
        all_groups: Dict[str, List[str]] = dict(name_groups)

        # Add size-only groups (these might have different names)
        for size_key, size_file_list in size_groups.items():
            # Convert from DiskFileInfo back to paths
            size_paths = [f["path"] for f in size_file_list]

            # Check if these files are already in a name group
            already_grouped = any(
                p in paths for paths in all_groups.values() for p in size_paths
            )

            if not already_grouped:
                all_groups[size_key] = size_paths

        # Process all groups with full analysis
        return self._process_groups(
            all_groups, check_size=True, check_checksum=self.config.enable_checksum
        )

    def _group_by_normalized_name(
        self, files: List[str], is_movie: bool = True
    ) -> Dict[str, List[str]]:
        """
        Group files by normalized name using 3-level fallback parsing.

        Args:
            files: List of file paths
            is_movie: True for movies, False for episodes

        Returns:
            Dict mapping normalized name to list of file paths
        """
        groups: Dict[str, List[str]] = {}

        for file_path in files:
            # Use fallback parsing chain (filename -> dir+file -> dir+ext)
            key = self._parse_with_fallback(file_path, is_movie)

            if not key:
                logger.debug(
                    f"Could not parse file with fallback: {file_path}, skipping"
                )
                continue

            if key not in groups:
                groups[key] = []
            groups[key].append(file_path)

        # Only keep groups with potential duplicates
        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}

        logger.debug(
            f"Grouped {len(files)} files into {len(duplicate_groups)} potential duplicate groups"
        )

        return duplicate_groups

    def _process_groups(
        self,
        groups: Dict[str, List[str]],
        check_size: bool = False,
        check_checksum: bool = False,
    ) -> Dict[str, List[DiskFileInfo]]:
        """
        Process groups of files to create DiskFileInfo objects with confidence scores.

        Handles hardlink filtering based on configuration.

        Args:
            groups: Dict mapping key to list of file paths
            check_size: Whether to check size similarity for confidence
            check_checksum: Whether to calculate checksums

        Returns:
            Dict mapping key to list of DiskFileInfo objects
        """
        result: Dict[str, List[DiskFileInfo]] = {}

        for key, file_paths in groups.items():
            file_infos: List[DiskFileInfo] = []
            seen_inodes: Dict[int, str] = {}
            hardlink_groups: List[DiskFileInfo] = []

            # Get all file stats first
            file_stats: List[tuple[str, int, int, bool]] = []
            for file_path in file_paths:
                try:
                    stat_info = os.stat(file_path)
                    size = stat_info.st_size
                    inode = stat_info.st_ino
                    is_hardlink = stat_info.st_nlink > 1
                    file_stats.append((file_path, size, inode, is_hardlink))
                except OSError as e:
                    logger.warning(f"Failed to stat file {file_path}: {e}")
                    continue

            # Calculate checksums if needed
            checksums: Dict[str, Optional[str]] = {}
            if check_checksum:
                for file_path, _, _, _ in file_stats:
                    checksums[file_path] = self._calculate_checksum(file_path)

            # Process each file
            for file_path, size, inode, is_hardlink in file_stats:
                # Handle hardlinks based on configuration
                if inode in seen_inodes:
                    original_path = seen_inodes[inode]
                    logger.debug(f"Hardlink detected: {file_path} -> {original_path}")

                    if self.config.hardlink_handling == HardlinkHandling.EXCLUDE:
                        continue  # Skip this file
                    elif (
                        self.config.hardlink_handling
                        == HardlinkHandling.REPORT_SEPARATELY
                    ):
                        # Mark but keep in separate list
                        pass

                seen_inodes[inode] = file_path

                # Calculate confidence score and detection method
                checksum = checksums.get(file_path) if check_checksum else None

                # For confidence, we need to compare with other files in group
                # Check if this file matches others by various criteria
                checksum_match = False
                exact_size_match = False
                similar_size_match = False
                name_match = True  # If in same group, name matched already

                if check_checksum and checksum:
                    # Check if any other file has same checksum
                    checksum_match = any(
                        cs == checksum and fp != file_path
                        for fp, cs in checksums.items()
                    )

                if check_size and len(file_stats) > 1:
                    # Check if size matches others
                    for other_path, other_size, _, _ in file_stats:
                        if other_path != file_path:
                            if size == other_size:
                                exact_size_match = True
                            elif self._are_sizes_similar(size, other_size):
                                similar_size_match = True

                confidence, detection_method = self._calculate_confidence_score(
                    name_match=name_match,
                    exact_size_match=exact_size_match,
                    similar_size_match=similar_size_match,
                    checksum_match=checksum_match,
                )

                file_info: DiskFileInfo = {
                    "path": file_path,
                    "size": size,
                    "is_hardlink": is_hardlink,
                    "inode": inode,
                    "normalized_name": key,
                    "checksum": checksum,
                    "confidence_score": confidence,
                    "detection_method": detection_method,
                }

                if (
                    is_hardlink
                    and self.config.hardlink_handling
                    == HardlinkHandling.REPORT_SEPARATELY
                ):
                    hardlink_groups.append(file_info)
                else:
                    file_infos.append(file_info)

            # Only include groups with duplicates
            if len(file_infos) > 1:
                result[key] = file_infos
                logger.debug(
                    f"Found {len(file_infos)} duplicates for '{key}' "
                    f"(avg confidence: {sum(f['confidence_score'] for f in file_infos) / len(file_infos):.2f})"
                )

            # Add hardlink group if separate reporting enabled
            if (
                hardlink_groups
                and self.config.hardlink_handling == HardlinkHandling.REPORT_SEPARATELY
            ):
                result[f"{key}|hardlinks"] = hardlink_groups

        return result
