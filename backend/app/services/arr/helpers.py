"""
Shared helper functions for *arr services (Radarr/Sonarr)
Extracts common rescan and path management logic
"""

import logging
import os
from typing import Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config
from app.services.arr.client import (
    ArrFile,
    Episode,
    MediaItem,
    RadarrClient,
    SonarrClient,
)

logger = logging.getLogger(__name__)

# Whether Radarr/Sonarr may be pointed at the folder of the copy that is kept
# when it is not the one they track. On unless set to "false".
FOLLOW_KEPT_COPY_KEY = "arr_follow_kept_copy"


async def follow_kept_copy_enabled(db: AsyncSession) -> bool:
    """Whether a kept copy in another folder may take over the *arr's item"""
    result = await db.execute(
        select(Config.value).where(Config.key == FOLLOW_KEPT_COPY_KEY)
    )
    return (result.scalar_one_or_none() or "true").strip().lower() != "false"


def kept_file_is_in_item(item_path: str, kept_file_path: str) -> bool:
    """
    Whether the kept file sits in the folder the *arr keeps the item in, so a
    rescan imports it as it is. False means the item would have to be moved
    to the kept file's folder first.
    """
    return not item_path or _within(item_path, os.path.dirname(kept_file_path))


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
        ValueError: The kept file sits directly in a root folder, which the
            *arr refuses as a movie or series path, or in a folder that no
            path mapping covers and no root folder holds, so the *arr may not
            see it. The kept file is not moved behind the user's back.
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

    roots = await client.get_root_folder()
    # Root folders picked in the *arr's folder browser carry a trailing slash
    for root in roots:
        if root.get("path", "").rstrip("/") == folder.rstrip("/"):
            raise ValueError(
                f"{arr} cannot import {kept_file_path}: it sits directly in the "
                f"root folder {root['path']}. Move it into {current_path} and "
                f"refresh the {kind} in {arr}."
            )

    if current_path and not _within(current_path, folder):
        # A folder no mapping covers reaches the *arr as the media server sees
        # it, which is right only where both see the same path
        mapper = client.path_mapper
        if (
            mapper
            and not mapper.covers(folder)
            and not any(r.get("path") and _within(r["path"], folder) for r in roots)
        ):
            raise ValueError(
                f"{arr} cannot import {kept_file_path}: no path mapping covers "
                f"{folder}, and none of {arr}'s root folders holds it. Move it "
                f"into {current_path} and refresh the {kind} in {arr}."
            )
        new_path = _item_folder(client, roots, folder)
        logger_instance.info(
            f"{arr} keeps this {kind} in {current_path}; pointing it at {new_path}"
        )
        item["path"] = new_path
        await (
            client.update_movie(item)
            if isinstance(client, RadarrClient)
            else client.update_series(item)
        )

    await client.post_command(command, **{id_param: media_id})
    logger_instance.info(f"Asked {arr} to rescan {kind} {media_id} from disk")


def _item_folder(
    client: Union[RadarrClient, SonarrClient], roots: list, folder: str
) -> str:
    """
    The folder the item is pointed at for a kept file in ``folder``.

    A movie owns the folder its file is in. A series owns the folder under its
    root folder, with its season folders inside, so a kept episode points it at
    that one and not at its own season, which would leave the other seasons
    outside the series.
    """
    if isinstance(client, RadarrClient):
        return folder
    for root in roots:
        root_path = root.get("path", "").rstrip("/")
        if root_path and folder.startswith(root_path + "/"):
            return root_path + "/" + folder[len(root_path) + 1 :].split("/")[0]
    return folder


def _within(folder: str, path: str) -> bool:
    """Whether path is folder itself or inside it, as a season folder is."""
    folder = folder.rstrip("/")
    return path == folder or path.startswith(folder + "/")


async def find_movie_by_file_path(
    client: RadarrClient, file_path: str, logger_instance: logging.Logger
) -> Optional[MediaItem]:
    """The movie whose file Radarr keeps at exactly this path, if any"""
    try:
        for movie in await client.get_movie():
            if (movie.get("movieFile") or ArrFile()).get("path") == file_path:
                logger_instance.info(
                    f"Found movie '{movie.get('title')}' for file {file_path}"
                )
                return movie

        logger_instance.info(f"Movie not found in Radarr for file path: {file_path}")
        return None
    except Exception as e:
        logger_instance.error(f"Error finding movie for {file_path}: {e}")
        raise


async def find_episode_by_file_path(
    client: SonarrClient, file_path: str, logger_instance: logging.Logger
) -> Optional[Episode]:
    """
    The file Sonarr keeps at exactly this path, if any, inside an Episode that
    has only its series: Sonarr's episode files do not name their episodes.
    """
    try:
        for series in await client.get_series():
            series_id = series.get("id")
            if not series_id:
                continue
            for episode_file in await client.get_episode_files_by_series_id(series_id):
                if episode_file.get("path") == file_path:
                    logger_instance.info(
                        f"Found file {episode_file.get('id')} of series {series_id} "
                        f"for {file_path}"
                    )
                    return Episode(seriesId=series_id, episodeFile=episode_file)

        logger_instance.info(f"Episode not found in Sonarr for file path: {file_path}")
        return None
    except Exception as e:
        logger_instance.error(f"Error finding episode for {file_path}: {e}")
        raise
