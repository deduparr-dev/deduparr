"""
Shared helper functions for *arr services (Radarr/Sonarr)
Extracts common rescan and path management logic
"""

import logging
import os
from typing import Literal, Optional, Union

from app.services.arr.client import RadarrClient, SonarrClient

logger = logging.getLogger(__name__)

MediaType = Literal["movie", "series"]


async def rescan_media_item(
    client: Union[RadarrClient, SonarrClient],
    media_id: Optional[int],
    kept_file_path: str,
    logger_instance: logging.Logger,
) -> None:
    """
    Have Radarr/Sonarr rescan a movie or series from disk, or every one of
    them when media_id is None.

    A rescan imports the files in the item's folder the *arr does not track
    yet - the kept file - and drops the ones gone from disk. A kept file in
    another folder gets the item pointed at that folder first.

    Raises:
        ValueError: The kept file sits directly in a root folder. The *arr
            refuses a root folder as a movie or series path, and the kept file
            is not moved behind the user's back.
    """
    if isinstance(client, RadarrClient):
        arr, kind, command, id_param = "Radarr", "movie", "RescanMovie", "movieId"
    else:
        arr, kind, command, id_param = "Sonarr", "series", "RescanSeries", "seriesId"

    if media_id is None:
        await client.post_command(command)
        logger_instance.info(f"Asked {arr} to rescan every {kind} from disk")
        return

    item = await (
        client.get_movie(media_id)
        if isinstance(client, RadarrClient)
        else client.get_series(media_id)
    )
    current_path = item.get("path", "")
    folder = os.path.dirname(kept_file_path)

    # Root folders picked in the *arr's folder browser carry a trailing slash
    for root in await client.get_root_folder():
        if root.get("path", "").rstrip("/") == folder.rstrip("/"):
            raise ValueError(
                f"{arr} cannot import {kept_file_path}: it sits directly in the "
                f"root folder {root['path']}. Move it into {current_path} and "
                f"refresh the {kind} in {arr}."
            )

    if current_path and not _within(current_path, folder):
        logger_instance.info(
            f"{arr} keeps this {kind} in {current_path}; pointing it at {folder}"
        )
        item["path"] = folder
        await (
            client.update_movie(item)
            if isinstance(client, RadarrClient)
            else client.update_series(item)
        )

    await client.post_command(command, **{id_param: media_id})
    logger_instance.info(f"Asked {arr} to rescan {kind} {media_id} from disk")


def _within(folder: str, path: str) -> bool:
    """Whether path is folder itself or inside it, as a season folder is."""
    folder = folder.rstrip("/")
    return path == folder or path.startswith(folder + "/")


async def find_media_by_file_path(
    client: Union[RadarrClient, SonarrClient],
    file_path: str,
    media_type: MediaType,
    logger_instance: logging.Logger,
) -> Optional[dict]:
    """
    Find movie or episode by file path with support for orphaned files

    Handles cases where *arr has the file tracked but no proper episode/movie linkage
    (orphaned files). This commonly happens with manual imports or after deletions.

    Args:
        client: Radarr or Sonarr API client instance
        file_path: Full path to the media file from Plex
        media_type: Type of media ("movie" or "series")
        logger_instance: Logger instance to use

    Returns:
        Media data dict if found, None otherwise. For orphaned files, returns minimal
        data with "_orphaned": True flag.
    """
    try:
        if media_type == "movie":
            # Radarr: Search through all movies
            movies = await client.get_movie()

            for movie in movies:
                if "movieFile" in movie and movie["movieFile"]:
                    radarr_path = movie["movieFile"].get("path")
                    if radarr_path and radarr_path == file_path:
                        logger_instance.info(
                            f"Found movie '{movie['title']}' for file {file_path}"
                        )
                        return movie

            logger_instance.warning(
                f"Movie not found in Radarr for file path: {file_path}"
            )
            return None

        elif media_type == "series":
            # Sonarr: Search through all episode files
            episode_files = []
            all_series = await client.get_series()

            for series in all_series:
                series_id = series.get("id")
                if series_id:
                    files = await client.get_episode_files_by_series_id(series_id)
                    if files:
                        episode_files.extend(files)

            for episode_file in episode_files:
                sonarr_path = episode_file.get("path")
                if sonarr_path and sonarr_path == file_path:
                    # Found matching file - check if it has episode linkage
                    episode_ids = episode_file.get("episodeIds", [])

                    if episode_ids:
                        # Normal case: file is properly linked to episode(s)
                        episodes = await client.get_episode(episode_ids[0])
                        if isinstance(episodes, list) and episodes:
                            episode = episodes[0]
                        else:
                            episode = episodes

                        episode["episodeFile"] = episode_file
                        episode_title = episode.get("title", "Unknown Episode")
                        logger_instance.info(
                            f"Found episode '{episode_title}' for file {file_path}"
                        )
                        return episode
                    else:
                        # Orphaned file: Sonarr has the file but no episode linkage
                        # This happens with manual imports or after episode deletion
                        logger_instance.warning(
                            f"Found orphaned episode file in Sonarr (no episodeIds): {file_path}"
                        )
                        logger_instance.info(
                            f"Episode file ID: {episode_file.get('id')}, "
                            f"Series ID: {episode_file.get('seriesId')}, "
                            f"Season: {episode_file.get('seasonNumber')}"
                        )
                        # Return minimal episode object with file data
                        # This allows deletion pipeline to still work
                        return {
                            "id": None,  # No episode ID available
                            "seriesId": episode_file.get("seriesId"),
                            "seasonNumber": episode_file.get("seasonNumber"),
                            "episodeFile": episode_file,
                            "title": f"Orphaned S{episode_file.get('seasonNumber', 0):02d} file",
                            "_orphaned": True,  # Flag for pipeline to handle specially
                        }

            logger_instance.warning(
                f"Episode not found in Sonarr for file path: {file_path}"
            )
            return None

        else:
            raise ValueError(f"Unknown media type: {media_type}")

    except Exception as e:
        logger_instance.error(f"Error finding {media_type} for {file_path}: {e}")
        raise
