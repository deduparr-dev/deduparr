"""
Shared helper functions for *arr services (Radarr/Sonarr)
Extracts common rescan and path management logic
"""

import logging
import os
import re
import shutil
from typing import Literal, Optional

logger = logging.getLogger(__name__)

MediaType = Literal["movie", "series"]


async def rescan_media_item(
    client,
    media_id: int,
    media_type: MediaType,
    kept_file_path: Optional[str],
    logger_instance: logging.Logger,
) -> bool:
    """
    Trigger a scan to find and import files for a specific movie or series

    This is used after deleting a duplicate file to make Radarr/Sonarr find and import
    the better quality file we kept. We use DownloadedMoviesScan/DownloadedEpisodesScan
    with the folder containing the kept file.

    Args:
        client: Radarr or Sonarr API client instance
        media_id: ID of the movie/series to scan for
        media_type: Type of media ("movie" or "series")
        kept_file_path: Path to the file we kept (if known)
        logger_instance: Logger instance to use

    Returns:
        True if command was successfully queued, False otherwise
    """
    try:
        scan_path = None

        if kept_file_path:
            scan_path = os.path.dirname(kept_file_path)
            logger_instance.info(f"Using kept file's directory for scan: {scan_path}")

            # Get media item and handle path issues
            if media_type == "movie":
                media_item = client.get_movie(media_id)
                update_method = client.upd_movie
                scan_command = "DownloadedMoviesScan"
            else:
                media_item = client.get_series(media_id)
                update_method = client.upd_series
                scan_command = "DownloadedEpisodesScan"

            if media_item:
                current_path = media_item.get("path", "")

                # Check if file is in library root (not in proper subfolder)
                root_folders = client.get_root_folder()
                is_library_root = any(
                    root.get("path") == scan_path for root in root_folders
                )

                if is_library_root:
                    # Move file into proper subfolder
                    new_folder = _create_media_subfolder(
                        media_item,
                        media_type,
                        scan_path,
                        kept_file_path,
                        logger_instance,
                    )
                    if not new_folder:
                        return False

                    # Update media path in *arr
                    media_item["path"] = new_folder
                    update_method(data=media_item)
                    logger_instance.info(
                        f"Updated {media_type} path in {media_type.capitalize()}arr to: {new_folder}"
                    )
                    scan_path = new_folder

                elif current_path and current_path != scan_path:
                    # File is in proper folder but path is different - update it
                    logger_instance.info(
                        f"{media_type.capitalize()} path mismatch detected. "
                        f"Current: {current_path}, Updating to: {scan_path}"
                    )
                    media_item["path"] = scan_path
                    update_method(data=media_item)
                    logger_instance.info(
                        f"Updated {media_type} path in {media_type.capitalize()}arr to: {scan_path}"
                    )
        else:
            # Fallback: Get the media item's configured path
            if media_type == "movie":
                media_item = client.get_movie(media_id)
                scan_command = "DownloadedMoviesScan"
            else:
                media_item = client.get_series(media_id)
                scan_command = "DownloadedEpisodesScan"

            if not media_item:
                logger_instance.error(
                    f"{media_type.capitalize()} {media_id} not found in {media_type.capitalize()}arr"
                )
                return False

            media_path = media_item.get("path", "")
            if not media_path:
                logger_instance.error(
                    f"Could not determine folder path for {media_type} {media_id}"
                )
                return False

            scan_path = media_path
            logger_instance.info(
                f"Using {media_type.capitalize()}arr's configured {media_type} path for scan: {scan_path}"
            )

        logger_instance.info(f"Triggering {scan_command} for folder: {scan_path}")
        client.post_command(scan_command, path=scan_path)
        logger_instance.info(
            f"Scan command queued for {media_type} {media_id} in folder {scan_path}"
        )
        return True

    except Exception as e:
        logger_instance.error(f"Error triggering scan for {media_type} {media_id}: {e}")
        raise


def _create_media_subfolder(
    media_item: dict,
    media_type: MediaType,
    library_root: str,
    kept_file_path: str,
    logger_instance: logging.Logger,
) -> Optional[str]:
    """
    Create proper media subfolder and move file into it

    Args:
        media_item: Movie or series data from *arr API
        media_type: Type of media ("movie" or "series")
        library_root: Library root path where file currently is
        kept_file_path: Path to the file we kept
        logger_instance: Logger instance to use

    Returns:
        Path to the new subfolder if successful, None otherwise
    """
    # Generate folder name: "Title (Year)"
    title = media_item.get("title", media_type.capitalize())
    year = media_item.get("year", "")
    folder_name = f"{title} ({year})" if year else title

    # Sanitize folder name
    folder_name = re.sub(r'[<>:"/\\|?*]', "", folder_name)

    new_media_folder = os.path.join(library_root, folder_name)
    new_file_path = os.path.join(new_media_folder, os.path.basename(kept_file_path))

    logger_instance.warning(
        f"Kept file is loose in library root ({library_root}). "
        f"Creating proper {media_type} subfolder and moving file..."
    )

    try:
        os.makedirs(new_media_folder, exist_ok=True)
        logger_instance.info(f"Created {media_type} folder: {new_media_folder}")

        shutil.move(kept_file_path, new_file_path)
        logger_instance.info(f"Moved file to: {new_file_path}")

        return new_media_folder

    except Exception as e:
        logger_instance.error(
            f"Failed to move file into subfolder: {e}. "
            f"Manual action required: Move {kept_file_path} to {new_media_folder}/"
        )
        return None


async def manual_import_file(
    client,
    file_path: str,
    media_id: int,
    media_type: MediaType,
    logger_instance: logging.Logger,
    search_for_file: bool = True,
) -> Optional[bool]:
    """
    Manually import a specific file using *arr's manual import API

    This is more targeted than a full library scan and works exactly like the
    "Manual Import" feature in Radarr/Sonarr's UI.

    Args:
        client: Radarr or Sonarr API client instance
        file_path: Full path to the file to import (may be outdated if file was moved)
        media_id: ID of the movie/series this file belongs to
        media_type: Type of media ("movie" or "series")
        logger_instance: Logger instance to use
        search_for_file: If True, search for actual file location if original path not found

    Returns:
        True if import succeeded, False if failed, None if file not found
    """
    try:
        # Check if file exists at reported location
        actual_path = file_path
        if search_for_file and not os.path.exists(file_path):
            logger_instance.info(
                f"File not found at {file_path}, searching library for actual location"
            )
            # File might have been moved (e.g., from root to organized folder)
            # Search by filename in the library
            filename = os.path.basename(file_path)

            # Get media details to find the root path
            if media_type == "movie":
                media_item = client.get_movie(media_id)
            else:
                media_item = client.get_series(media_id)

            if media_item and "path" in media_item:
                media_folder = media_item["path"]
                # Search in media's folder and parent library
                library_root = os.path.dirname(media_folder)
                for root, dirs, files in os.walk(library_root):
                    if filename in files:
                        potential_path = os.path.join(root, filename)
                        if os.path.exists(potential_path):
                            logger_instance.info(
                                f"Found file at new location: {potential_path}"
                            )
                            actual_path = potential_path
                            break

        if not os.path.exists(actual_path):
            logger_instance.warning(f"File not found in library: {file_path}")
            return None

        folder_path = os.path.dirname(actual_path)

        # Scan folder to get importable files
        logger_instance.info(
            f"Manual import: scanning {folder_path} for {media_type} {media_id}"
        )

        # Build parameters based on media type
        if media_type == "movie":
            manual_import_items = client.get_manual_import(
                folder=folder_path,
                downloadId="",
                movieId=media_id,
                filterExistingFiles=True,
            )
        else:  # series
            manual_import_items = client.get_manual_import(
                folder=folder_path,
                downloadId="",
                seriesId=media_id,
                filterExistingFiles=True,
            )

        if not manual_import_items:
            logger_instance.warning(
                f"No importable files found in {folder_path} for {media_type} {media_id}"
            )
            return None

        # Find our specific file in the results
        matching_item = None
        for item in manual_import_items:
            if item.get("path") == actual_path:
                matching_item = item
                break

        if not matching_item:
            logger_instance.warning(
                f"File {actual_path} not found in manual import scan results"
            )
            return None

        # Import the file using ManualImport command
        logger_instance.info(f"Manually importing file: {actual_path}")

        # Build import payload based on media type
        if media_type == "movie":
            import_files = [
                {
                    "path": actual_path,
                    "movieId": media_id,
                    "quality": matching_item.get("quality"),
                    "languages": matching_item.get("languages", []),
                    "releaseGroup": matching_item.get("releaseGroup"),
                }
            ]
        else:  # series
            import_files = [
                {
                    "path": actual_path,
                    "seriesId": media_id,
                    "episodeIds": [e["id"] for e in matching_item.get("episodes", [])],
                    "quality": matching_item.get("quality"),
                    "languages": matching_item.get("languages", []),
                    "releaseGroup": matching_item.get("releaseGroup"),
                }
            ]

        response = client.post_command(
            "ManualImport",
            files=import_files,
            importMode="Move",
        )

        logger_instance.info(
            f"✅ Manual import queued for {actual_path} (command ID: {response.get('id')})"
        )
        return True

    except Exception as e:
        logger_instance.error(f"Manual import failed for {file_path}: {e}")
        return False


async def trigger_full_library_scan(
    client, media_type: MediaType, logger_instance: logging.Logger
) -> bool:
    """
    Trigger a full library scan for all movies or series

    Args:
        client: Radarr or Sonarr API client instance
        media_type: Type of media ("movie" or "series")
        logger_instance: Logger instance to use

    Returns:
        True if command was successfully queued
    """
    try:
        scan_command = (
            "DownloadedMoviesScan"
            if media_type == "movie"
            else "DownloadedEpisodesScan"
        )

        root_folders = client.get_root_folder()
        for root in root_folders:
            path = root.get("path")
            if path:
                client.post_command(scan_command, path=path)
                logger_instance.info(
                    f"Queued full scan for {media_type.capitalize()}arr library: {path}"
                )
        return True

    except Exception as e:
        logger_instance.error(
            f"Error triggering full {media_type.capitalize()}arr library scan: {e}"
        )
        raise


async def refresh_media_item(
    client, media_id: int, media_type: MediaType, logger_instance: logging.Logger
) -> bool:
    """
    Refresh a movie or series metadata and clean up orphaned database entries

    This command will:
    - Update metadata from indexers (TMDB/TVDB)
    - Check if files still exist on disk
    - Remove orphaned database entries if files are missing

    Useful for cleaning up after external deletions (e.g., qBittorrent removed a file
    but *arr still has it in the database).

    Args:
        client: Radarr or Sonarr API client instance
        media_id: ID of the movie/series to refresh
        media_type: Type of media ("movie" or "series")
        logger_instance: Logger instance to use

    Returns:
        True if command was successfully queued
    """
    try:
        if media_type == "movie":
            command_name = "RefreshMovie"
            id_param = "movieId"
        elif media_type == "series":
            command_name = "RefreshSeries"
            id_param = "seriesId"
        else:
            raise ValueError(f"Unknown media type: {media_type}")

        result = client.post_command(command_name, **{id_param: media_id})
        logger_instance.info(
            f"Queued {media_type} refresh for ID {media_id}, "
            f"command ID: {result.get('id')} (will clean up orphaned DB entries)"
        )
        return True

    except Exception as e:
        logger_instance.error(f"Error refreshing {media_type} {media_id}: {e}")
        raise


def find_media_by_file_path(
    client,
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
            movies = client.get_movie()
            
            for movie in movies:
                if "movieFile" in movie and movie["movieFile"]:
                    radarr_path = movie["movieFile"].get("path")
                    if radarr_path and radarr_path == file_path:
                        logger_instance.info(
                            f"Found movie '{movie['title']}' for file {file_path}"
                        )
                        return movie
            
            logger_instance.warning(f"Movie not found in Radarr for file path: {file_path}")
            return None
            
        elif media_type == "series":
            # Sonarr: Search through all episode files
            episode_files = []
            all_series = client.get_series()
            
            for series in all_series:
                series_id = series.get("id")
                if series_id:
                    files = client.get_episode_files_by_series_id(series_id)
                    if files:
                        episode_files.extend(files)
            
            for episode_file in episode_files:
                sonarr_path = episode_file.get("path")
                if sonarr_path and sonarr_path == file_path:
                    # Found matching file - check if it has episode linkage
                    episode_ids = episode_file.get("episodeIds", [])
                    
                    if episode_ids:
                        # Normal case: file is properly linked to episode(s)
                        episodes = client.get_episode(episode_ids[0])
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
            
            logger_instance.warning(f"Episode not found in Sonarr for file path: {file_path}")
            return None
            
        else:
            raise ValueError(f"Unknown media type: {media_type}")
            
    except Exception as e:
        logger_instance.error(f"Error finding {media_type} for {file_path}: {e}")
        raise
