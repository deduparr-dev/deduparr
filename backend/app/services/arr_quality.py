"""
Rank duplicate files the way Radarr/Sonarr would, using the item's quality profile.

Mirrors the *arr upgrade logic (QualityModelComparer + custom format score):
1. Position of the quality in the profile (a quality group counts as one rank)
2. Revision (version, then real) - propers and repacks
3. Custom format score
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config
from app.models.duplicate import MediaType
from app.services.arr_client import ArrClientError, RadarrClient, SonarrClient
from app.services.radarr_service import RadarrService
from app.services.scoring_engine import MediaMetadata
from app.services.sonarr_service import SonarrService

logger = logging.getLogger(__name__)

PREFER_ARR_QUALITY_PROFILE_KEY = "prefer_arr_quality_profile"

RankedFile = Tuple[MediaMetadata, int, bool]


class ArrQualityUnavailable(Exception):
    """Raised when a duplicate set cannot be ranked by Radarr/Sonarr"""

    pass


@dataclass(frozen=True)
class ArrQuality:
    """How Radarr/Sonarr rates one file against the item's quality profile"""

    quality_name: str
    quality_rank: int
    revision: Tuple[int, int]
    custom_format_score: int

    @property
    def sort_key(self) -> Tuple[int, Tuple[int, int], int]:
        return (self.quality_rank, self.revision, self.custom_format_score)


def get_quality_rank(profile: dict, quality_id: int) -> int:
    """
    Get the rank of a quality in a quality profile (higher is better).

    Profile items are ordered from lowest to highest. Qualities inside a group
    share the group's rank, like QualityModelComparer without group order.
    Returns -1 if the quality is not part of the profile.
    """
    for index, item in enumerate(profile.get("items") or []):
        quality = item.get("quality")
        if quality and quality.get("id") == quality_id:
            return index
        for group_item in item.get("items") or []:
            group_quality = group_item.get("quality")
            if group_quality and group_quality.get("id") == quality_id:
                return index
    return -1


def build_arr_quality(resource: dict, profile: dict) -> Optional[ArrQuality]:
    """
    Build an ArrQuality from a moviefile, episodefile or manualimport resource.

    Returns None if the *arr could not determine the file's quality.
    """
    quality_model = resource.get("quality") or {}
    quality = quality_model.get("quality") or {}
    quality_id = quality.get("id")
    # Quality id 0 is "Unknown": the *arr could not parse the file
    if not quality_id:
        return None

    revision = quality_model.get("revision") or {}

    score = resource.get("customFormatScore")
    if score is None:
        format_ids = {cf.get("id") for cf in resource.get("customFormats") or []}
        score = sum(
            item.get("score", 0)
            for item in profile.get("formatItems") or []
            if item.get("format") in format_ids
        )

    return ArrQuality(
        quality_name=quality.get("name", str(quality_id)),
        quality_rank=get_quality_rank(profile, quality_id),
        revision=(revision.get("version", 1), revision.get("real", 0)),
        custom_format_score=score,
    )


def rank_by_arr_quality(
    ranked_files: List[RankedFile], arr_qualities: Dict[str, ArrQuality]
) -> List[RankedFile]:
    """
    Re-rank files by *arr quality, keeping Deduparr's score as tie-breaker.

    Args:
        ranked_files: Output of ScoringEngine.rank_duplicates
        arr_qualities: ArrQuality for every file path in ranked_files

    Returns:
        List of tuples (metadata, score, keep) with only the best file kept
    """
    ordered = sorted(
        ranked_files,
        key=lambda x: (
            arr_qualities[x[0].file_path].sort_key,
            x[1],
            x[0].file_size,
        ),
        reverse=True,
    )
    return [(metadata, score, i == 0) for i, (metadata, score, _) in enumerate(ordered)]


def _is_in_folder(file_path: str, folder: Optional[str]) -> bool:
    if not folder:
        return False
    return file_path.startswith(folder.rstrip("/") + "/")


class ArrQualityRanker:
    """Evaluates duplicate files through Radarr/Sonarr, caching lookups per scan"""

    def __init__(self, db: AsyncSession):
        self.radarr_service = RadarrService(db)
        self.sonarr_service = SonarrService(db)
        self._media_items: Dict[MediaType, List[dict]] = {}
        self._profiles: Dict[Tuple[MediaType, int], dict] = {}

    @classmethod
    async def from_config(cls, db: AsyncSession) -> Optional["ArrQualityRanker"]:
        """Create a ranker if 'Prefer *arr quality profile' is enabled"""
        result = await db.execute(
            select(Config).where(Config.key == PREFER_ARR_QUALITY_PROFILE_KEY)
        )
        config = result.scalar_one_or_none()
        if not config or config.value != "true":
            return None
        return cls(db)

    async def _get_client(self, media_type: MediaType) -> RadarrClient | SonarrClient:
        service = (
            self.radarr_service
            if media_type == MediaType.MOVIE
            else self.sonarr_service
        )
        try:
            return await service._get_client()
        except ValueError as e:
            raise ArrQualityUnavailable(str(e))

    async def _get_media_items(
        self, client: RadarrClient | SonarrClient, media_type: MediaType
    ) -> List[dict]:
        if media_type not in self._media_items:
            if media_type == MediaType.MOVIE:
                items = await client.get_movie()
            else:
                items = await client.get_series()
            self._media_items[media_type] = (
                items if isinstance(items, list) else [items]
            )
        return self._media_items[media_type]

    async def _get_profile(
        self,
        client: RadarrClient | SonarrClient,
        media_type: MediaType,
        profile_id: int,
    ) -> dict:
        key = (media_type, profile_id)
        if key not in self._profiles:
            self._profiles[key] = await client.get_quality_profile(profile_id)
        return self._profiles[key]

    def _find_media_item(
        self, media_items: List[dict], file_paths: List[str]
    ) -> Optional[dict]:
        paths = set(file_paths)
        for item in media_items:
            movie_file = item.get("movieFile") or {}
            if movie_file.get("path") in paths:
                return item
        for item in media_items:
            if any(_is_in_folder(path, item.get("path")) for path in file_paths):
                return item
        return None

    async def evaluate(
        self, media_type: MediaType, file_paths: List[str]
    ) -> Dict[str, ArrQuality]:
        """
        Evaluate every file of a duplicate set with Radarr (movies) or Sonarr (episodes).

        Raises:
            ArrQualityUnavailable: If any file cannot be evaluated
        """
        arr_name = "Radarr" if media_type == MediaType.MOVIE else "Sonarr"
        client = await self._get_client(media_type)

        try:
            media_items = await self._get_media_items(client, media_type)
            media_item = self._find_media_item(media_items, file_paths)
            if not media_item:
                raise ArrQualityUnavailable(f"no matching item in {arr_name}")

            media_id = media_item["id"]
            profile = await self._get_profile(
                client, media_type, media_item["qualityProfileId"]
            )

            if media_type == MediaType.MOVIE:
                tracked_files = await client.get_movie_files(media_id)
            else:
                tracked_files = await client.get_episode_files_by_series_id(media_id)
            resources = {f.get("path"): f for f in tracked_files}

            untracked_folders = {
                os.path.dirname(path) for path in file_paths if path not in resources
            }
            for folder in sorted(untracked_folders):
                if media_type == MediaType.MOVIE:
                    items = await client.get_manual_import(
                        folder=folder, movie_id=media_id
                    )
                else:
                    items = await client.get_manual_import(
                        folder=folder, series_id=media_id
                    )
                for item in items:
                    resources.setdefault(item.get("path"), item)
        except ArrClientError as e:
            raise ArrQualityUnavailable(f"{arr_name} request failed: {e}")
        finally:
            await client.close()

        qualities: Dict[str, ArrQuality] = {}
        for path in file_paths:
            resource = resources.get(path)
            if resource is None:
                raise ArrQualityUnavailable(f"{arr_name} does not know file {path}")
            quality = build_arr_quality(resource, profile)
            if quality is None:
                raise ArrQualityUnavailable(
                    f"{arr_name} could not parse the quality of {path}"
                )
            qualities[path] = quality

        return qualities
