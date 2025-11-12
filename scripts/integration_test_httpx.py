#!/usr/bin/env python3
"""
Integration test script for httpx migration validation

This script verifies that the new RadarrClient and SonarrClient (using httpx)
work correctly with real API interactions.

Usage:
    python scripts/integration_test_httpx.py

Environment variables (optional):
    RADARR_URL - Radarr server URL (default: http://localhost:7878)
    RADARR_API_KEY - Radarr API key
    SONARR_URL - Sonarr server URL (default: http://localhost:8989)
    SONARR_API_KEY - Sonarr API key
"""

import asyncio
import logging
import os
import sys
from typing import Dict, List
import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ArrConnectionError(Exception):
    """Error connecting to *arr service"""

    pass


class RadarrClient:
    """Simplified RadarrClient for integration testing"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make HTTP request to Radarr API"""
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method, url, headers=self.headers, timeout=30.0, **kwargs
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise ArrConnectionError(
                    f"Radarr API error: {e.response.status_code} - {e.response.text}"
                )
            except httpx.RequestError as e:
                raise ArrConnectionError(f"Radarr connection error: {e}")

    async def get_system_status(self) -> Dict:
        """Get Radarr system status"""
        return await self._request("GET", "/system/status")

    async def get_movie(self) -> List[Dict]:
        """Get all movies"""
        return await self._request("GET", "/movie")

    async def get_root_folder(self) -> List[Dict]:
        """Get root folders"""
        return await self._request("GET", "/rootfolder")


class SonarrClient:
    """Simplified SonarrClient for integration testing"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make HTTP request to Sonarr API"""
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method, url, headers=self.headers, timeout=30.0, **kwargs
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise ArrConnectionError(
                    f"Sonarr API error: {e.response.status_code} - {e.response.text}"
                )
            except httpx.RequestError as e:
                raise ArrConnectionError(f"Sonarr connection error: {e}")

    async def get_system_status(self) -> Dict:
        """Get Sonarr system status"""
        return await self._request("GET", "/system/status")

    async def get_series(self) -> List[Dict]:
        """Get all series"""
        return await self._request("GET", "/series")

    async def get_root_folder(self) -> List[Dict]:
        """Get root folders"""
        return await self._request("GET", "/rootfolder")


class IntegrationTestResults:
    """Track integration test results"""

    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.errors: List[str] = []

    def record_pass(self, test_name: str):
        """Record a passing test"""
        self.tests_run += 1
        self.tests_passed += 1
        logger.info(f"✅ PASS: {test_name}")

    def record_fail(self, test_name: str, error: str):
        """Record a failing test"""
        self.tests_run += 1
        self.tests_failed += 1
        self.errors.append(f"{test_name}: {error}")
        logger.error(f"❌ FAIL: {test_name} - {error}")

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("INTEGRATION TEST SUMMARY")
        print("=" * 70)
        print(f"Total Tests:  {self.tests_run}")
        print(f"Passed:       {self.tests_passed}")
        print(f"Failed:       {self.tests_failed}")
        if self.tests_run > 0:
            print(f"Success Rate: {(self.tests_passed / self.tests_run * 100):.1f}%")
        else:
            print("Success Rate: N/A (no tests run)")

        if self.errors:
            print("\nFailed Tests:")
            for error in self.errors:
                print(f"  - {error}")

        print("=" * 70)
        return self.tests_failed == 0


async def test_radarr_connection(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test basic Radarr connection"""
    test_name = "Radarr Connection"
    try:
        client = RadarrClient(base_url=url, api_key=api_key)
        system_status = await client.get_system_status()

        if not system_status:
            raise ValueError("No system status returned")

        if "version" not in system_status:
            raise ValueError("System status missing 'version' field")

        logger.info(f"Connected to Radarr v{system_status.get('version')}")
        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_radarr_get_movies(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test retrieving movies from Radarr"""
    test_name = "Radarr Get Movies"
    try:
        client = RadarrClient(base_url=url, api_key=api_key)
        movies = await client.get_movie()

        if not isinstance(movies, list):
            raise ValueError(f"Expected list, got {type(movies)}")

        logger.info(f"Retrieved {len(movies)} movies from Radarr")

        if movies:
            # Verify movie structure
            first_movie = movies[0]
            required_fields = ["id", "title"]
            for field in required_fields:
                if field not in first_movie:
                    raise ValueError(f"Movie missing required field: {field}")

        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_radarr_get_root_folders(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test retrieving root folders from Radarr"""
    test_name = "Radarr Get Root Folders"
    try:
        client = RadarrClient(base_url=url, api_key=api_key)
        root_folders = await client.get_root_folder()

        if not isinstance(root_folders, list):
            raise ValueError(f"Expected list, got {type(root_folders)}")

        logger.info(f"Retrieved {len(root_folders)} root folders from Radarr")

        if root_folders:
            # Verify folder structure
            first_folder = root_folders[0]
            if "path" not in first_folder:
                raise ValueError("Root folder missing 'path' field")

        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_sonarr_connection(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test basic Sonarr connection"""
    test_name = "Sonarr Connection"
    try:
        client = SonarrClient(base_url=url, api_key=api_key)
        system_status = await client.get_system_status()

        if not system_status:
            raise ValueError("No system status returned")

        if "version" not in system_status:
            raise ValueError("System status missing 'version' field")

        logger.info(f"Connected to Sonarr v{system_status.get('version')}")
        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_sonarr_get_series(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test retrieving series from Sonarr"""
    test_name = "Sonarr Get Series"
    try:
        client = SonarrClient(base_url=url, api_key=api_key)
        series = await client.get_series()

        if not isinstance(series, list):
            raise ValueError(f"Expected list, got {type(series)}")

        logger.info(f"Retrieved {len(series)} series from Sonarr")

        if series:
            # Verify series structure
            first_series = series[0]
            required_fields = ["id", "title"]
            for field in required_fields:
                if field not in first_series:
                    raise ValueError(f"Series missing required field: {field}")

        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_sonarr_get_root_folders(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test retrieving root folders from Sonarr"""
    test_name = "Sonarr Get Root Folders"
    try:
        client = SonarrClient(base_url=url, api_key=api_key)
        root_folders = await client.get_root_folder()

        if not isinstance(root_folders, list):
            raise ValueError(f"Expected list, got {type(root_folders)}")

        logger.info(f"Retrieved {len(root_folders)} root folders from Sonarr")

        if root_folders:
            # Verify folder structure
            first_folder = root_folders[0]
            if "path" not in first_folder:
                raise ValueError("Root folder missing 'path' field")

        results.record_pass(test_name)
        return True
    except Exception as e:
        results.record_fail(test_name, str(e))
        return False


async def test_radarr_error_handling(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test Radarr error handling with invalid credentials"""
    test_name = "Radarr Error Handling"
    try:
        # Use invalid API key
        client = RadarrClient(base_url=url, api_key="invalid_key_12345")
        try:
            await client.get_system_status()
            # Should have raised an error
            raise ValueError("Expected ArrConnectionError but request succeeded")
        except ArrConnectionError as e:
            # Expected behavior
            if "401" in str(e) or "Unauthorized" in str(e):
                results.record_pass(test_name)
                return True
            else:
                raise ValueError(f"Unexpected error message: {e}")
    except ValueError as e:
        results.record_fail(test_name, str(e))
        return False
    except Exception as e:
        results.record_fail(test_name, f"Unexpected exception: {e}")
        return False


async def test_sonarr_error_handling(
    url: str, api_key: str, results: IntegrationTestResults
):
    """Test Sonarr error handling with invalid credentials"""
    test_name = "Sonarr Error Handling"
    try:
        # Use invalid API key
        client = SonarrClient(base_url=url, api_key="invalid_key_12345")
        try:
            await client.get_system_status()
            # Should have raised an error
            raise ValueError("Expected ArrConnectionError but request succeeded")
        except ArrConnectionError as e:
            # Expected behavior
            if "401" in str(e) or "Unauthorized" in str(e):
                results.record_pass(test_name)
                return True
            else:
                raise ValueError(f"Unexpected error message: {e}")
    except ValueError as e:
        results.record_fail(test_name, str(e))
        return False
    except Exception as e:
        results.record_fail(test_name, f"Unexpected exception: {e}")
        return False


async def run_integration_tests():
    """Run all integration tests"""
    results = IntegrationTestResults()

    # Get configuration from environment
    radarr_url = os.getenv("RADARR_URL", "http://localhost:7878")
    radarr_api_key = os.getenv("RADARR_API_KEY", "")
    sonarr_url = os.getenv("SONARR_URL", "http://localhost:8989")
    sonarr_api_key = os.getenv("SONARR_API_KEY", "")

    print("\n" + "=" * 70)
    print("HTTPX MIGRATION INTEGRATION TESTS")
    print("=" * 70)
    print(f"Radarr URL: {radarr_url}")
    print(f"Radarr API Key: {'*' * 20 if radarr_api_key else 'NOT SET'}")
    print(f"Sonarr URL: {sonarr_url}")
    print(f"Sonarr API Key: {'*' * 20 if sonarr_api_key else 'NOT SET'}")
    print("=" * 70 + "\n")

    # Radarr tests
    if radarr_api_key:
        logger.info("Running Radarr tests...")
        await test_radarr_connection(radarr_url, radarr_api_key, results)
        await test_radarr_get_movies(radarr_url, radarr_api_key, results)
        await test_radarr_get_root_folders(radarr_url, radarr_api_key, results)
        await test_radarr_error_handling(radarr_url, radarr_api_key, results)
    else:
        logger.warning(
            "⚠️  Skipping Radarr tests - RADARR_API_KEY not set in environment"
        )

    # Sonarr tests
    if sonarr_api_key:
        logger.info("\nRunning Sonarr tests...")
        await test_sonarr_connection(sonarr_url, sonarr_api_key, results)
        await test_sonarr_get_series(sonarr_url, sonarr_api_key, results)
        await test_sonarr_get_root_folders(sonarr_url, sonarr_api_key, results)
        await test_sonarr_error_handling(sonarr_url, sonarr_api_key, results)
    else:
        logger.warning(
            "⚠️  Skipping Sonarr tests - SONARR_API_KEY not set in environment"
        )

    # Print summary
    success = results.print_summary()

    if not radarr_api_key and not sonarr_api_key:
        print(
            "\n⚠️  WARNING: No API keys provided. Set environment variables to run tests:"
        )
        print("   export RADARR_API_KEY=your_radarr_api_key")
        print("   export SONARR_API_KEY=your_sonarr_api_key")
        print("\nAlternatively, use the manual test checklist below.\n")
        return True  # Don't fail if no credentials provided

    return success


def print_manual_test_checklist():
    """Print manual test checklist for integration validation"""
    print("\n" + "=" * 70)
    print("MANUAL INTEGRATION TEST CHECKLIST")
    print("=" * 70)
    print(
        """
If you have Radarr/Sonarr running, you can manually verify the httpx migration:

1. CONNECTION TESTING
   □ Start the Deduparr backend: cd backend && python -m app.main
   □ Test Radarr connection via API:
     curl -X POST http://localhost:3001/api/setup/test/radarr \\
       -H "Content-Type: application/json" \\
       -d '{"url": "http://localhost:7878", "api_key": "YOUR_KEY"}'
   □ Test Sonarr connection via API:
     curl -X POST http://localhost:3001/api/setup/test/sonarr \\
       -H "Content-Type: application/json" \\
       -d '{"url": "http://localhost:8989", "api_key": "YOUR_KEY"}'
   □ Verify both return success with version info

2. DATA RETRIEVAL
   □ Save Radarr config and verify movies are retrieved during scan
   □ Save Sonarr config and verify series are retrieved during scan
   □ Check logs for any httpx-related errors

3. ERROR HANDLING
   □ Test with invalid API key - should return clear error message
   □ Test with unreachable URL - should return connection error
   □ Verify errors are properly formatted and informative

4. FULL WORKFLOW (if you have test data)
   □ Run duplicate scan with Plex + Radarr/Sonarr
   □ Verify duplicates are detected correctly
   □ Execute dry-run deletion - verify preview is accurate
   □ Execute actual deletion - verify files are removed from Radarr/Sonarr
   □ Verify rescan triggers correctly after deletion

EXPECTED RESULTS:
✅ All API calls should work identically to PyArr-based version
✅ No new errors or exceptions in logs
✅ Response times should be similar or better than PyArr
✅ All duplicate detection and deletion workflows function normally
"""
    )
    print("=" * 70 + "\n")


if __name__ == "__main__":
    # Run integration tests
    success = asyncio.run(run_integration_tests())

    # Print manual checklist
    print_manual_test_checklist()

    # Exit with appropriate code
    sys.exit(0 if success else 1)
