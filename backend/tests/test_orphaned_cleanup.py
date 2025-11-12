"""
Tests for orphaned database entry cleanup via *arr refresh commands
"""

import pytest
from unittest.mock import MagicMock

from app.services.arr_helpers import refresh_media_item


@pytest.mark.asyncio
async def test_refresh_media_item_movie():
    """Test refresh_media_item helper for movies"""
    mock_client = MagicMock()
    mock_client.post_command.return_value = {"id": 123, "status": "queued"}
    mock_logger = MagicMock()

    result = await refresh_media_item(
        client=mock_client,
        media_id=456,
        media_type="movie",
        logger_instance=mock_logger,
    )

    assert result is True
    mock_client.post_command.assert_called_once_with("RefreshMovie", movieId=456)


@pytest.mark.asyncio
async def test_refresh_media_item_series():
    """Test refresh_media_item helper for series"""
    mock_client = MagicMock()
    mock_client.post_command.return_value = {"id": 789, "status": "queued"}
    mock_logger = MagicMock()

    result = await refresh_media_item(
        client=mock_client,
        media_id=101,
        media_type="series",
        logger_instance=mock_logger,
    )

    assert result is True
    mock_client.post_command.assert_called_once_with("RefreshSeries", seriesId=101)


@pytest.mark.asyncio
async def test_refresh_media_item_invalid_type():
    """Test refresh_media_item with invalid media type"""
    mock_client = MagicMock()
    mock_logger = MagicMock()

    # Should raise ValueError for invalid media type
    with pytest.raises(ValueError, match="Unknown media type"):
        await refresh_media_item(
            client=mock_client,
            media_id=999,
            media_type="invalid",
            logger_instance=mock_logger,
        )


@pytest.mark.asyncio
async def test_refresh_media_item_error_handling():
    """Test error handling in refresh_media_item helper"""
    mock_client = MagicMock()
    mock_client.post_command.side_effect = Exception("API error")
    mock_logger = MagicMock()

    # Should raise exception on failure
    with pytest.raises(Exception, match="API error"):
        await refresh_media_item(
            client=mock_client,
            media_id=999,
            media_type="movie",
            logger_instance=mock_logger,
        )
