"""
Base HTTP client for Radarr/Sonarr API interactions.
Direct httpx implementation to replace PyArr dependency.

API Version Strategy:
- RadarrClient: Uses v3 API (backward compatible with v4+)
- SonarrClient: Uses v5 API (current standard, v3 is deprecated)

Both clients inherit from ArrClient base class and share common HTTP logic.
The TypedDicts below describe the parts of each resource Deduparr reads; the
*arr sends more, and a resource sent back on update keeps all of it.
"""

import logging
from typing import List, Mapping, Optional, TypedDict, Union, cast, overload

import httpx

logger = logging.getLogger(__name__)

JsonObject = dict[str, object]
QueryParams = Mapping[str, Union[str, int, bool]]


class QualityRef(TypedDict, total=False):
    id: int
    name: str


class Revision(TypedDict, total=False):
    version: int
    real: int


class QualityModel(TypedDict, total=False):
    quality: QualityRef
    revision: Revision


class CustomFormatRef(TypedDict, total=False):
    id: int


class ArrFile(TypedDict, total=False):
    """A movie or episode file, tracked or offered for manual import"""

    id: int
    path: str
    quality: QualityModel
    customFormatScore: int
    customFormats: List[CustomFormatRef]
    seriesId: int
    seasonNumber: int
    episodeIds: List[int]


class MediaItem(TypedDict, total=False):
    """A Radarr movie or a Sonarr series; only a movie has a movieFile"""

    id: int
    title: str
    path: str
    qualityProfileId: int
    movieFile: ArrFile


class Episode(TypedDict, total=False):
    id: int
    seriesId: int
    seasonNumber: int
    episodeNumber: int
    title: str
    episodeFile: ArrFile


class ProfileItem(TypedDict, total=False):
    """A quality of a profile, or a group of qualities sharing one rank"""

    quality: QualityRef
    items: List["ProfileItem"]


class FormatItem(TypedDict, total=False):
    format: int
    score: int


class QualityProfile(TypedDict, total=False):
    items: List[ProfileItem]
    formatItems: List[FormatItem]


class RootFolder(TypedDict, total=False):
    path: str


class Command(TypedDict, total=False):
    id: int
    name: str
    status: str


class SystemStatus(TypedDict, total=False):
    version: str


class ArrClientError(Exception):
    """Base exception for *arr client errors"""

    pass


class ArrConnectionError(ArrClientError):
    """Connection to *arr service failed"""

    pass


class ArrAuthError(ArrClientError):
    """Authentication with *arr service failed"""

    pass


class ArrNotFoundError(ArrClientError):
    """Resource not found in *arr service"""

    pass


def _as_object(result: object, endpoint: str) -> JsonObject:
    """A response that has to be one JSON object."""
    if not isinstance(result, dict):
        raise ArrClientError(f"Expected an object from {endpoint}")
    return result


def _as_list(result: object, endpoint: str) -> List[JsonObject]:
    """A response that has to be a list; a lone object counts as one item."""
    if isinstance(result, dict):
        return [result]
    if not isinstance(result, list):
        raise ArrClientError(f"Expected a list from {endpoint}")
    return result


class ArrClient:
    """
    Base HTTP client for Radarr/Sonarr APIs (v3/v5).

    Implements the minimal API endpoints needed for Deduparr:
    - Movie/Series listing and retrieval
    - File deletion
    - Manual import candidates
    - Command execution (rescans)
    - System status

    Subclasses specify their API version (RadarrClient uses v3, SonarrClient uses v5).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        verify_ssl: bool = True,
    ):
        """
        Initialize *arr client

        Args:
            base_url: Base URL of Radarr/Sonarr instance (e.g., http://localhost:7878)
            api_key: API key for authentication
            timeout: Request timeout in seconds (float) or httpx.Timeout object. Defaults to 30.0
            verify_ssl: Whether to verify SSL certificates. Defaults to True
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_version = "v3"
        # store optional client configuration for use when creating httpx AsyncClient
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx async client"""
        if self._client is None:
            # determine timeout value (allow float or httpx.Timeout)
            timeout_val = (
                httpx.Timeout(self.timeout)
                if isinstance(self.timeout, (int, float))
                else self.timeout
            )
            if timeout_val is None:
                # default timeout
                timeout_val = httpx.Timeout(30.0)

            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/{self.api_version}",
                headers={
                    "X-Api-Key": self.api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "Deduparr (httpx)",
                },
                timeout=timeout_val,
                verify=self.verify_ssl,
            )
        return self._client

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[QueryParams] = None,
        json_data: Optional[Mapping[str, object]] = None,
    ) -> object:
        """
        Make HTTP request to *arr API

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without /api/v3 prefix)
            params: Query parameters
            json_data: JSON body data

        Returns:
            The decoded JSON response, {} for 204 No Content

        Raises:
            ArrConnectionError: Connection failed
            ArrAuthError: Authentication failed (401, 403)
            ArrNotFoundError: Resource not found (404)
            ArrClientError: Other API errors
        """
        client = await self._get_client()

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                params=params,
                json=json_data,
            )

            if response.status_code == 401:
                raise ArrAuthError("API key invalid or unauthorized")
            elif response.status_code == 403:
                raise ArrAuthError("Access forbidden")
            elif response.status_code == 404:
                raise ArrNotFoundError(f"Resource not found: {endpoint}")
            elif response.status_code >= 400:
                raise ArrClientError(
                    f"API request failed with status {response.status_code}: {response.text}"
                )

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.ConnectError as e:
            raise ArrConnectionError(f"Failed to connect to {self.base_url}: {e}")
        except httpx.TimeoutException as e:
            raise ArrConnectionError(f"Request timeout to {self.base_url}: {e}")
        except httpx.HTTPError as e:
            raise ArrClientError(f"HTTP error: {e}")

    async def get_system_status(self) -> SystemStatus:
        """Get system status"""
        endpoint = "/system/status"
        return cast(
            SystemStatus, _as_object(await self._request("GET", endpoint), endpoint)
        )

    async def get_root_folder(self) -> List[RootFolder]:
        """Get root folders"""
        endpoint = "/rootfolder"
        return cast(
            List[RootFolder], _as_list(await self._request("GET", endpoint), endpoint)
        )

    async def post_command(self, name: str, **kwargs: object) -> Command:
        """
        Execute a command on the *arr server.

        Args:
            name: Command name (e.g., "RescanMovie", "RescanSeries")
            **kwargs: Command-specific parameters, sent as the command's body

        Returns:
            The queued command with its ID and status

        Example:
            await client.post_command("RescanMovie", movieId=123)
        """
        data: JsonObject = {"name": name, **kwargs}
        endpoint = "/command"
        result = await self._request("POST", endpoint, json_data=data)
        return cast(Command, _as_object(result, endpoint))

    async def get_quality_profile(self, profile_id: int) -> QualityProfile:
        """
        Get a quality profile

        Args:
            profile_id: Quality profile ID

        Returns:
            Quality profile with its ordered quality items and custom format scores
        """
        endpoint = f"/qualityprofile/{profile_id}"
        return cast(
            QualityProfile, _as_object(await self._request("GET", endpoint), endpoint)
        )

    async def _get_manual_import(self, params: QueryParams) -> List[ArrFile]:
        """Manual import candidates, as Radarr or Sonarr narrows them"""
        endpoint = "/manualimport"
        result = await self._request("GET", endpoint, params=params)
        return cast(List[ArrFile], _as_list(result, endpoint))


class RadarrClient(ArrClient):
    """
    Radarr-specific API client for movie management.
    Implements movie-specific endpoints on top of the base client.
    Uses API v3 (backward compatible, also works with v4+).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        super().__init__(
            base_url=base_url, api_key=api_key, timeout=timeout, verify_ssl=verify_ssl
        )
        self.api_version = "v3"

    @overload
    async def get_movie(self, movie_id: None = None) -> List[MediaItem]: ...

    @overload
    async def get_movie(self, movie_id: int) -> MediaItem: ...

    async def get_movie(
        self, movie_id: Optional[int] = None
    ) -> Union[MediaItem, List[MediaItem]]:
        """One movie by ID, or every movie without one"""
        if movie_id is not None:
            endpoint = f"/movie/{movie_id}"
            result = await self._request("GET", endpoint)
            return cast(MediaItem, _as_object(result, endpoint))
        endpoint = "/movie"
        return cast(
            List[MediaItem], _as_list(await self._request("GET", endpoint), endpoint)
        )

    async def update_movie(self, movie_data: MediaItem) -> MediaItem:
        """
        Update movie

        Args:
            movie_data: The movie as Radarr returned it, with the changes made

        Returns:
            Updated movie data
        """
        movie_id = movie_data.get("id")
        if not movie_id:
            raise ValueError("Movie data must include 'id' field")
        endpoint = f"/movie/{movie_id}"
        result = await self._request("PUT", endpoint, json_data=movie_data)
        return cast(MediaItem, _as_object(result, endpoint))

    async def delete_movie_file(self, movie_file_id: int) -> None:
        """
        Delete movie file

        Args:
            movie_file_id: Movie file ID to delete
        """
        await self._request("DELETE", f"/moviefile/{movie_file_id}")

    async def get_movie_files(self, movie_id: int) -> List[ArrFile]:
        """
        Get movie files tracked for a movie

        Args:
            movie_id: Movie ID

        Returns:
            List of movie files
        """
        endpoint = "/moviefile"
        result = await self._request("GET", endpoint, params={"movieId": movie_id})
        return cast(List[ArrFile], _as_list(result, endpoint))

    async def get_manual_import(
        self,
        folder: str,
        download_id: str = "",
        movie_id: Optional[int] = None,
        filter_existing_files: bool = True,
    ) -> List[ArrFile]:
        """
        Get manual import candidates

        Args:
            folder: Folder path to scan
            download_id: Download ID (optional)
            movie_id: Movie ID to filter by
            filter_existing_files: Filter out already imported files

        Returns:
            List of importable files
        """
        params: dict[str, Union[str, int, bool]] = {
            "folder": folder,
            "filterExistingFiles": filter_existing_files,
        }
        if download_id:
            params["downloadId"] = download_id
        if movie_id is not None:
            params["movieId"] = movie_id
        return await self._get_manual_import(params)


class SonarrClient(ArrClient):
    """
    Sonarr-specific API client for TV series management.
    Implements series-specific endpoints on top of the base client.

    Auto-detects API version: tries v5 first (current standard), falls back to v3 if not available.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        super().__init__(
            base_url=base_url, api_key=api_key, timeout=timeout, verify_ssl=verify_ssl
        )
        # Start with v5, will auto-detect and fall back to v3 if needed
        self.api_version = "v5"
        self._version_detected = False

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[QueryParams] = None,
        json_data: Optional[Mapping[str, object]] = None,
    ) -> object:
        """
        Make HTTP request with automatic API version detection.

        Tries v5 first, falls back to v3 if v5 returns 404.
        """
        try:
            return await super()._request(method, endpoint, params, json_data)
        except ArrNotFoundError:
            # If we get 404 and haven't detected version yet, try v3
            if not self._version_detected and self.api_version == "v5":
                logger.info("Sonarr v5 API not found, falling back to v3")
                self.api_version = "v3"
                self._version_detected = True
                # Close existing client to force recreation with new API version
                if self._client:
                    await self._client.aclose()
                    self._client = None
                # Retry with v3
                return await super()._request(method, endpoint, params, json_data)
            # If already using v3 or version already detected, re-raise
            raise

    @overload
    async def get_series(self, series_id: None = None) -> List[MediaItem]: ...

    @overload
    async def get_series(self, series_id: int) -> MediaItem: ...

    async def get_series(
        self, series_id: Optional[int] = None
    ) -> Union[MediaItem, List[MediaItem]]:
        """One series by ID, or every series without one"""
        if series_id is not None:
            endpoint = f"/series/{series_id}"
            result = await self._request("GET", endpoint)
            return cast(MediaItem, _as_object(result, endpoint))
        endpoint = "/series"
        return cast(
            List[MediaItem], _as_list(await self._request("GET", endpoint), endpoint)
        )

    async def update_series(self, series_data: MediaItem) -> MediaItem:
        """
        Update series

        Args:
            series_data: The series as Sonarr returned it, with the changes made

        Returns:
            Updated series data
        """
        series_id = series_data.get("id")
        if not series_id:
            raise ValueError("Series data must include 'id' field")
        endpoint = f"/series/{series_id}"
        result = await self._request("PUT", endpoint, json_data=series_data)
        return cast(MediaItem, _as_object(result, endpoint))

    async def get_episode_files_by_series_id(self, series_id: int) -> List[ArrFile]:
        """
        Get episode files for a series

        Args:
            series_id: Series ID

        Returns:
            List of episode files
        """
        endpoint = "/episodefile"
        result = await self._request("GET", endpoint, params={"seriesId": series_id})
        return cast(List[ArrFile], _as_list(result, endpoint))

    async def get_episode(self, episode_id: int) -> Episode:
        """
        Get episode by ID

        Some Sonarr versions answer with a list holding the one episode.
        """
        endpoint = f"/episode/{episode_id}"
        episodes = _as_list(await self._request("GET", endpoint), endpoint)
        if not episodes:
            raise ArrNotFoundError(f"Resource not found: {endpoint}")
        return cast(Episode, episodes[0])

    async def delete_episode_file(self, episode_file_id: int) -> None:
        """
        Delete episode file

        Args:
            episode_file_id: Episode file ID to delete
        """
        await self._request("DELETE", f"/episodefile/{episode_file_id}")

    async def get_manual_import(
        self,
        folder: str,
        download_id: str = "",
        series_id: Optional[int] = None,
        filter_existing_files: bool = True,
    ) -> List[ArrFile]:
        """
        Get manual import candidates

        Args:
            folder: Folder path to scan
            download_id: Download ID (optional)
            series_id: Series ID to filter by
            filter_existing_files: Filter out already imported files

        Returns:
            List of importable files
        """
        params: dict[str, Union[str, int, bool]] = {
            "folder": folder,
            "filterExistingFiles": filter_existing_files,
        }
        if download_id:
            params["downloadId"] = download_id
        if series_id is not None:
            params["seriesId"] = series_id
        return await self._get_manual_import(params)
