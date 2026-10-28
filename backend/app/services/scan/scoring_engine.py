"""
Scoring engine for evaluating duplicate media file quality
"""

import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MediaMetadata:
    """Metadata extracted from media file"""

    file_path: str
    file_size: int
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bitrate: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    inode: Optional[int] = None
    is_hardlink: bool = False


class ScoringEngine:
    """Calculates quality scores for media files"""

    # Default scoring weights
    RESOLUTION_SCORES = {
        "4k": 20000,
        "2160p": 20000,
        "1080p": 10000,
        "1080": 10000,
        "720p": 5000,
        "720": 5000,
        "480p": 3000,
        "480": 3000,
        "sd": 1000,
    }

    VIDEO_CODEC_SCORES = {
        "hevc": 10000,
        "h265": 10000,
        "x265": 10000,
        "h264": 5000,
        "x264": 5000,
        "avc": 5000,
        "vc1": 3000,
        "vp9": 1000,
        "mpeg4": 500,
        "xvid": 500,
    }

    AUDIO_CODEC_SCORES = {
        "truehd": 4500,
        "atmos": 4500,
        "dts-hd ma": 4000,
        "dts-hd": 4000,
        "dca-ma": 4000,
        "flac": 2500,
        "pcm": 2500,
        "dts": 2000,
        "eac3": 1250,
        "e-ac-3": 1250,
        "ac3": 1000,
        "aac": 1000,
        "mp3": 1000,
        "mp2": 500,
    }

    FILENAME_PATTERN_SCORES = {
        r"remux": 20000,
        r"bluray.*1080p": 15000,
        r"bluray.*720p": 10000,
        r"web-?dl": 5000,
        r"webrip": 4000,
        r"proper": 1500,
        r"repack": 1500,
        r"hdtv": -1000,
        r"\.ts$": -1000,
        r"\.avi$": -1000,
        r"\.vob$": -5000,
        r"\.wmv$": -5000,
    }

    def __init__(self):
        """Initialize scoring engine"""
        pass

    def calculate_score(
        self, metadata: MediaMetadata, custom_rules: Optional[List[Dict]] = None
    ) -> int:
        """
        Calculate total quality score for a media file

        Args:
            metadata: Media file metadata
            custom_rules: Optional list of custom scoring rules

        Returns:
            Total score (higher is better quality)
        """
        score = 0

        # Resolution score
        score += self._score_resolution(metadata)

        # Video codec score
        score += self._score_video_codec(metadata)

        # Audio codec score
        score += self._score_audio_codec(metadata)

        # File size score (bigger is usually better for same resolution)
        score += self._score_file_size(metadata)

        # Filename pattern scores
        score += self._score_filename_patterns(metadata.file_path)

        # Apply custom rules if provided
        if custom_rules:
            score += self._apply_custom_rules(metadata, custom_rules)

        logger.debug(
            f"Calculated score {score} for {metadata.file_path} "
            f"(res:{metadata.resolution}, codec:{metadata.video_codec}, size:{metadata.file_size})"
        )

        return score

    def _score_resolution(self, metadata: MediaMetadata) -> int:
        """Score based on video resolution"""
        if not metadata.resolution:
            # Try to determine from dimensions
            if metadata.height:
                if metadata.height >= 2160:
                    return self.RESOLUTION_SCORES.get("4k", 0)
                elif metadata.height >= 1080:
                    return self.RESOLUTION_SCORES.get("1080p", 0)
                elif metadata.height >= 720:
                    return self.RESOLUTION_SCORES.get("720p", 0)
                elif metadata.height >= 480:
                    return self.RESOLUTION_SCORES.get("480p", 0)
            return 0

        resolution_lower = metadata.resolution.lower()
        for key, score in self.RESOLUTION_SCORES.items():
            if key in resolution_lower:
                return score
        return 0

    def _score_video_codec(self, metadata: MediaMetadata) -> int:
        """Score based on video codec"""
        if not metadata.video_codec:
            return 0

        codec_lower = metadata.video_codec.lower()
        for key, score in self.VIDEO_CODEC_SCORES.items():
            if key in codec_lower:
                return score
        return 0

    def _score_audio_codec(self, metadata: MediaMetadata) -> int:
        """Score based on audio codec"""
        if not metadata.audio_codec:
            return 0

        codec_lower = metadata.audio_codec.lower()
        for key, score in self.AUDIO_CODEC_SCORES.items():
            if key in codec_lower:
                return score
        return 0

    def _score_file_size(self, metadata: MediaMetadata) -> int:
        """
        Score based on file size
        Larger files generally indicate better quality (for same resolution)
        """
        # Convert bytes to GB and use as score component
        # Cap at reasonable values to prevent dominance
        size_gb = metadata.file_size / (1024**3)
        return min(int(size_gb * 100), 5000)

    def _score_filename_patterns(self, file_path: str) -> int:
        """Score based on filename patterns (source, quality indicators)"""
        score = 0
        file_path_lower = file_path.lower()

        for pattern, pattern_score in self.FILENAME_PATTERN_SCORES.items():
            if re.search(pattern, file_path_lower):
                score += pattern_score
                logger.debug(f"Pattern '{pattern}' matched, added {pattern_score}")

        return score

    def _apply_custom_rules(
        self, metadata: MediaMetadata, custom_rules: List[Dict]
    ) -> int:
        """
        Apply user-defined custom scoring rules

        Args:
            metadata: Media file metadata
            custom_rules: List of custom rules with pattern and score_modifier

        Returns:
            Additional score from custom rules
        """
        score = 0
        file_path_lower = metadata.file_path.lower()

        for rule in custom_rules:
            if not rule.get("enabled", True):
                continue

            pattern = rule.get("pattern", "")
            modifier = rule.get("score_modifier", 0)

            try:
                if re.search(pattern.lower(), file_path_lower):
                    score += modifier
                    logger.debug(f"Custom rule '{pattern}' matched, added {modifier}")
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")

        return score

    def rank_duplicates(
        self,
        files_metadata: List[MediaMetadata],
        custom_rules: Optional[List[Dict]] = None,
    ) -> List[tuple[MediaMetadata, int, bool]]:
        """
        Rank duplicate files by score and mark which to keep

        Args:
            files_metadata: List of metadata for duplicate files
            custom_rules: Optional custom scoring rules

        Returns:
            List of tuples (metadata, score, keep) sorted by score (highest first)
        """
        # Calculate scores
        scored_files = [
            (metadata, self.calculate_score(metadata, custom_rules))
            for metadata in files_metadata
        ]

        # Sort by score (highest first), then by file size (largest first as tie-breaker)
        # This ensures deterministic selection when scores are identical
        scored_files.sort(key=lambda x: (x[1], x[0].file_size), reverse=True)

        # Mark the highest scored file to keep
        results = []
        for i, (metadata, score) in enumerate(scored_files):
            keep = i == 0  # Keep only the first (highest scored, largest if tied)
            results.append((metadata, score, keep))

        return results
