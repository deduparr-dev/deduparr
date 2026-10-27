#!/usr/bin/env python3
"""
Scoring Logic Demonstration

This script demonstrates exactly how Deduparr decides which duplicate file to keep
and which to delete. Run this to see the scoring engine in action with real examples.
"""

import sys
import os
import re
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

# Inline the scoring engine to avoid import issues
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
        """
        # Convert bytes to GB and use as score component
        size_gb = metadata.file_size / (1024**3)
        return min(int(size_gb * 100), 5000)

    def _score_filename_patterns(self, file_path: str) -> int:
        """Score based on filename patterns"""
        score = 0
        file_path_lower = file_path.lower()

        for pattern, pattern_score in self.FILENAME_PATTERN_SCORES.items():
            if re.search(pattern, file_path_lower):
                score += pattern_score

        return score

    def _apply_custom_rules(
        self, metadata: MediaMetadata, custom_rules: List[Dict]
    ) -> int:
        """Apply user-defined custom scoring rules"""
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
            except re.error:
                pass

        return score

    def rank_duplicates(
        self,
        files_metadata: List[MediaMetadata],
        custom_rules: Optional[List[Dict]] = None,
    ) -> List[tuple]:
        """
        Rank duplicate files by score and mark which to keep
        """
        # Calculate scores
        scored_files = [
            (metadata, self.calculate_score(metadata, custom_rules))
            for metadata in files_metadata
        ]

        # Sort by score (highest first)
        scored_files.sort(key=lambda x: x[1], reverse=True)

        # Mark the highest scored file to keep
        results = []
        for i, (metadata, score) in enumerate(scored_files):
            keep = i == 0  # Keep only the first (highest scored)
            results.append((metadata, score, keep))

        return results


def print_separator(title=""):
    """Print a nice separator"""
    if title:
        print(f"\n{'='*80}")
        print(f"  {title}")
        print("=" * 80)
    else:
        print("-" * 80)


def demonstrate_scoring():
    """Demonstrate the scoring logic with examples"""

    print_separator("DEDUPARR SCORING LOGIC DEMONSTRATION")

    print("""
This demonstrates how Deduparr decides which duplicate file to keep.
The file with the HIGHEST SCORE is kept, all others are marked for deletion.

SCORING FACTORS:
1. Resolution (4K > 1080p > 720p > 480p)
2. Video Codec (HEVC > H264 > VC1 > older codecs)
3. Audio Codec (TrueHD/Atmos > DTS-HD > DTS > AC3 > AAC)
4. File Size (larger = better quality for same resolution)
5. Filename Patterns (REMUX > BluRay > WEB-DL > WEBRip > HDTV)
6. Custom Rules (user-defined regex patterns)

SUBTITLE HANDLING:
Currently, subtitles are NOT considered in scoring. This is a planned feature.
The scoring focuses on video/audio quality only.
    """)

    # Create scoring engine
    engine = ScoringEngine()

    # Example 1: Different resolutions
    print_separator("Example 1: Same Movie, Different Resolutions")

    files_example1 = [
        MediaMetadata(
            file_path="/movies/The.Matrix.1999.720p.BluRay.x264.mkv",
            file_size=2_147_483_648,  # 2 GB
            resolution="720p",
            video_codec="h264",
            audio_codec="ac3",
            bitrate=5000,
            width=1280,
            height=720,
        ),
        MediaMetadata(
            file_path="/movies/The.Matrix.1999.1080p.BluRay.x264.mkv",
            file_size=8_589_934_592,  # 8 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="dts",
            bitrate=10000,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/The.Matrix.1999.2160p.BluRay.HEVC.mkv",
            file_size=34_359_738_368,  # 32 GB
            resolution="2160p",
            video_codec="hevc",
            audio_codec="truehd",
            bitrate=25000,
            width=3840,
            height=2160,
        ),
    ]

    ranked = engine.rank_duplicates(files_example1)
    print_results(ranked)

    # Example 2: Same resolution, different sources
    print_separator("Example 2: Same Resolution, Different Sources")

    files_example2 = [
        MediaMetadata(
            file_path="/movies/Inception.2010.1080p.HDTV.x264.mkv",
            file_size=1_610_612_736,  # 1.5 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=4000,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/Inception.2010.1080p.WEB-DL.x264.mkv",
            file_size=4_294_967_296,  # 4 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="ac3",
            bitrate=8000,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/Inception.2010.1080p.BluRay.REMUX.mkv",
            file_size=26_843_545_600,  # 25 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="dts-hd ma",
            bitrate=20000,
            width=1920,
            height=1080,
        ),
    ]

    ranked = engine.rank_duplicates(files_example2)
    print_results(ranked)

    # Example 3: With custom rules
    print_separator("Example 3: Custom Rules (prefer Director's Cut)")

    files_example3 = [
        MediaMetadata(
            file_path="/movies/Blade.Runner.1982.1080p.BluRay.x264.mkv",
            file_size=8_589_934_592,  # 8 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="dts",
            bitrate=10000,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/Blade.Runner.1982.Directors.Cut.1080p.BluRay.x264.mkv",
            file_size=9_663_676_416,  # 9 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="dts",
            bitrate=10000,
            width=1920,
            height=1080,
        ),
    ]

    # Custom rule to prefer Director's Cut
    custom_rules = [
        {"pattern": r"director.?s?.?cut", "score_modifier": 10000, "enabled": True}
    ]

    print("\nWithout custom rules:")
    ranked_no_rules = engine.rank_duplicates(files_example3)
    print_results(ranked_no_rules)

    print("\nWith custom rule (boost Director's Cut by 10,000 points):")
    ranked_with_rules = engine.rank_duplicates(files_example3, custom_rules)
    print_results(ranked_with_rules)

    # Example 4: Real-world messy filenames
    print_separator("Example 4: Real-World Scenario")

    files_example4 = [
        MediaMetadata(
            file_path="/movies/Interstellar.2014.1080p.WEBRip.x264.AAC-[YTS.MX].mkv",
            file_size=2_361_393_152,  # 2.2 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=4500,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/Interstellar.2014.1080p.BluRay.x265.10bit-GalaxyRG.mkv",
            file_size=4_831_838_208,  # 4.5 GB
            resolution="1080p",
            video_codec="hevc",
            audio_codec="ac3",
            bitrate=7000,
            width=1920,
            height=1080,
        ),
        MediaMetadata(
            file_path="/movies/Interstellar.2014.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1.mkv",
            file_size=32_212_254_720,  # 30 GB
            resolution="1080p",
            video_codec="h264",
            audio_codec="dts-hd ma",
            bitrate=22000,
            width=1920,
            height=1080,
        ),
    ]

    ranked = engine.rank_duplicates(files_example4)
    print_results(ranked)

    # Show scoring breakdown for the winner
    print_separator("Detailed Score Breakdown for Best File")
    winner = ranked[0][0]
    winner_score = ranked[0][1]

    breakdown = get_score_breakdown(engine, winner)
    print(f"\nFile: {os.path.basename(winner.file_path)}")
    print(f"Total Score: {winner_score:,}\n")

    for component, score in breakdown.items():
        print(f"  {component:30s}: {score:+7,} points")

    print_separator("CONCLUSION")
    print("""
The scoring system prioritizes:
1. Video quality (resolution, codec, bitrate)
2. Audio quality (codec)
3. Source quality (REMUX > BluRay > WEB > HDTV)
4. File size (as a quality indicator)

WHAT ABOUT SUBTITLES?
Currently, subtitles are NOT factored into the scoring. This means:
- External subtitle files (.srt, .sub) are ignored
- Embedded subtitle tracks are not counted
- This is intentional for v1.0 to keep logic simple

FUTURE ENHANCEMENTS:
- Subtitle count (more languages = better)
- Subtitle format (PGS/VobSub vs SRT)
- Forced subtitle tracks
- Audio track count (more languages = better)
- HDR/Dolby Vision detection
- Custom scoring profiles per library

To add subtitle scoring, you would:
1. Extract subtitle metadata from Plex media.parts[0].streams
2. Add SUBTITLE_SCORES to ScoringEngine
3. Add _score_subtitles() method
4. Include in calculate_score()
    """)


def print_results(ranked_files):
    """Print ranked files in a nice table"""
    print(f"\n{'#':<3} {'Score':>8}  {'Keep?':<6}  {'File'}")
    print("-" * 80)

    for i, (metadata, score, keep) in enumerate(ranked_files, 1):
        keep_marker = "✓ KEEP" if keep else "✗ DELETE"
        filename = os.path.basename(metadata.file_path)

        # Truncate long filenames
        if len(filename) > 50:
            filename = filename[:47] + "..."

        print(f"{i:<3} {score:>8,}  {keep_marker:<6}  {filename}")

        # Show details for first file
        if i == 1:
            details = []
            if metadata.resolution:
                details.append(f"res={metadata.resolution}")
            if metadata.video_codec:
                details.append(f"video={metadata.video_codec}")
            if metadata.audio_codec:
                details.append(f"audio={metadata.audio_codec}")
            size_gb = metadata.file_size / (1024**3)
            details.append(f"size={size_gb:.1f}GB")

            print(f"    └─ {', '.join(details)}")


def get_score_breakdown(engine, metadata):
    """Get detailed score breakdown"""
    breakdown = {}

    breakdown["Resolution"] = engine._score_resolution(metadata)
    breakdown["Video Codec"] = engine._score_video_codec(metadata)
    breakdown["Audio Codec"] = engine._score_audio_codec(metadata)
    breakdown["File Size"] = engine._score_file_size(metadata)
    breakdown["Filename Patterns"] = engine._score_filename_patterns(metadata.file_path)

    return breakdown


if __name__ == "__main__":
    try:
        demonstrate_scoring()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
