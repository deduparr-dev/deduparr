"""
Base HTTP client for Radarr/Sonarr API interactions.
Direct httpx implementation to replace PyArr dependency.

API Version Strategy:
- RadarrClient: Uses v3 API (backward compatible with v4+)
- SonarrClient: Uses v5 API (current standard, v3 is deprecated)

Both clients inherit from ArrClient base class and share common HTTP logic.
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Union

import httpx

logger = logging.getLogger(__name__)

MediaType = Literal["movie", "series"]


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


class ArrClient:
    """
    Base HTTP client for Radarr/Sonarr APIs (v3/v5).

    Implements the minimal API endpoints needed for Deduparr:
    - Movie/Series listing and retrieval
    - File deletion
    - Manual import
    - Command execution (scans, refreshes)
    - System status

    Subclasses specify their API version (RadarrClient uses v3, SonarrClient uses v5).
    """

    def __init__(self, base_url: str, api_key: str):
        """
        Initialize *arr client

        Args:
            base_url: Base URL of Radarr/Sonarr instance (e.g., http://localhost:7878)
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_version = "v3"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx async client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/{self.api_version}",
                headers={
                    "X-Api-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
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
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Make HTTP request to *arr API

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without /api/v3 prefix)
            params: Query parameters
            json_data: JSON body data

        Returns:
            JSON response data

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

    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status"""
        result = await self._request("GET", "/system/status")
        if isinstance(result, list):
            raise ArrClientError("Expected dict but got list from system/status")
        return result

    async def get_root_folder(self) -> List[Dict[str, Any]]:
        """Get root folders"""
        result = await self._request("GET", "/rootfolder")
        if isinstance(result, dict):
            return [result]
        return result

    async def post_command(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Execute a command

        Args:
            name: Command name (e.g., "DownloadedMoviesScan", "RefreshMovie")
            **kwargs: Command parameters

        Returns:
            Command result with ID
        """
        data = {"name": name, **kwargs}
        result = await self._request("POST", "/command", json_data=data)
        if isinstance(result, list):
            raise ArrClientError("Expected dict but got list from command")
        return result


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

    async def get_movie(
        self, movie_id: Optional[int] = None
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Get movie(s)

        Args:
            movie_id: Optional movie ID. If None, returns all movies.

        Returns:
            Single movie dict if movie_id provided, list of movies otherwise
        """
        if movie_id is not None:
            return await self._request("GET", f"/movie/{movie_id}")
        return await self._request("GET", "/movie")

    async def upd_movie(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update movie (legacy method name for backward compatibility)

        Args:
            data: Movie data dictionary (must include 'id')

        Returns:
            Updated movie data
        """
        return await self.update_movie(data)

    async def update_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update movie

        Args:
            movie_data: Movie data dictionary (must include 'id')

        Returns:
            Updated movie data
        """
        movie_id = movie_data.get("id")
        if not movie_id:
            raise ValueError("Movie data must include 'id' field")
        result = await self._request("PUT", f"/movie/{movie_id}", json_data=movie_data)
        if isinstance(result, list):
            raise ArrClientError("Expected dict but got list from movie update")
        return result

    async def del_movie_file(self, movie_file_id: int) -> Dict[str, Any]:
        """
        Delete movie file (legacy method name for backward compatibility)

        Args:
            movie_file_id: Movie file ID to delete

        Returns:
            Empty dict on success
        """
        return await self.delete_movie_file(movie_file_id)

    async def delete_movie_file(self, movie_file_id: int) -> Dict[str, Any]:
        """
        Delete movie file

        Args:
            movie_file_id: Movie file ID to delete

        Returns:
            Empty dict on success
        """
        result = await self._request("DELETE", f"/moviefile/{movie_file_id}")
        if isinstance(result, list):
            return {}
        return result

    async def get_manual_import(
        self,
        folder: str,
        download_id: str = "",
        movie_id: Optional[int] = None,
        filter_existing_files: bool = True,
    ) -> List[Dict[str, Any]]:
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
        params: Dict[str, Any] = {
            "folder": folder,
            "filterExistingFiles": filter_existing_files,
        }
        if download_id:
            params["downloadId"] = download_id
        if movie_id is not None:
            params["movieId"] = movie_id

        result = await self._request("GET", "/manualimport", params=params)
        if isinstance(result, dict):
            return [result]
        return result


class SonarrClient(ArrClient):
    """
    Sonarr-specific API client for TV series management.
    Implements series-specific endpoints on top of the base client.
    Uses API v5 (current standard, v3 is deprecated).
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
        self.api_version = "v5"

    async def get_series(
        self, series_id: Optional[int] = None
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Get series

        Args:
            series_id: Optional series ID. If None, returns all series.

        Returns:
            Single series dict if series_id provided, list of series otherwise
        """
        if series_id is not None:
            return await self._request("GET", f"/series/{series_id}")
        return await self._request("GET", "/series")

    async def upd_series(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update series (legacy method name for backward compatibility)

        Args:
            data: Series data dictionary (must include 'id')

        Returns:
            Updated series data
        """
        return await self.update_series(data)

    async def update_series(self, series_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update series

        Args:
            series_data: Series data dictionary (must include 'id')

        Returns:
            Updated series data
        """
        series_id = series_data.get("id")
        if not series_id:
            raise ValueError("Series data must include 'id' field")
        result = await self._request(
            "PUT", f"/series/{series_id}", json_data=series_data
        )
        if isinstance(result, list):
            raise ArrClientError("Expected dict but got list from series update")
        return result

    async def get_episode_files_by_series_id(
        self, series_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get episode files for a series

        Args:
            series_id: Series ID

        Returns:
            List of episode files
        """
        params = {"seriesId": series_id}
        result = await self._request("GET", "/episodefile", params=params)
        if isinstance(result, dict):
            return [result]
        return result

    async def get_episode(
        self, episode_id: int
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Get episode by ID

        Args:
            episode_id: Episode ID

        Returns:
            Episode data (may be dict or list depending on Sonarr version)
        """
        return await self._request("GET", f"/episode/{episode_id}")

    async def del_episode_file(self, episode_file_id: int) -> Dict[str, Any]:
        """
        Delete episode file (legacy method name for backward compatibility)

        Args:
            episode_file_id: Episode file ID to delete

        Returns:
            Empty dict on success
        """
        return await self.delete_episode_file(episode_file_id)

    async def delete_episode_file(self, episode_file_id: int) -> Dict[str, Any]:
        """
        Delete episode file

        Args:
            episode_file_id: Episode file ID to delete

        Returns:
            Empty dict on success
        """
        result = await self._request("DELETE", f"/episodefile/{episode_file_id}")
        if isinstance(result, list):
            return {}
        return result

    async def get_manual_import(
        self,
        folder: str,
        download_id: str = "",
        series_id: Optional[int] = None,
        filter_existing_files: bool = True,
    ) -> List[Dict[str, Any]]:
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
        params: Dict[str, Any] = {
            "folder": folder,
            "filterExistingFiles": filter_existing_files,
        }
        if download_id:
            params["downloadId"] = download_id
        if series_id is not None:
            params["seriesId"] = series_id

        result = await self._request("GET", "/manualimport", params=params)
        if isinstance(result, dict):
            return [result]
        return result
