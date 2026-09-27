"""
Tests for ranking duplicate files by Radarr/Sonarr quality profile
"""

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.main import app
from app.models import Config, DuplicateSet
from app.models.duplicate import MediaType
from app.services.arr_client import (
    ArrConnectionError,
    RadarrClient,
    SonarrClient,
)
from app.services.arr_quality import (
    PREFER_ARR_QUALITY_PROFILE_KEY,
    ArrQuality,
    ArrQualityRanker,
    ArrQualityUnavailable,
    build_arr_quality,
    get_quality_rank,
    rank_by_arr_quality,
)
from app.services.scan_helpers import (
    create_duplicate_set,
    verify_and_update_existing_set,
)
from app.services.scoring_engine import MediaMetadata, ScoringEngine

# Profile items are ordered lowest to highest, like the *arr API returns them
PROFILE = {
    "id": 4,
    "items": [
        {"quality": {"id": 3, "name": "WEBDL-1080p"}, "items": [], "allowed": True},
        {
            "id": 1001,
            "name": "WEB 1080p",
            "quality": None,
            "items": [
                {"quality": {"id": 15, "name": "WEBRip-1080p"}},
                {"quality": {"id": 16, "name": "WEBDL-1080p v2"}},
            ],
            "allowed": True,
        },
        {"quality": {"id": 7, "name": "Bluray-1080p"}, "items": [], "allowed": True},
        {"quality": {"id": 30, "name": "Remux-1080p"}, "items": [], "allowed": True},
    ],
    "formatItems": [
        {"format": 1, "name": "HDR", "score": 500},
        {"format": 2, "name": "x265 (HD)", "score": -10000},
    ],
}


def resource(
    path: str,
    quality_id: int,
    quality_name: str,
    version: int = 1,
    real: int = 0,
    custom_format_score: int | None = 0,
) -> dict:
    item = {
        "path": path,
        "quality": {
            "quality": {"id": quality_id, "name": quality_name},
            "revision": {"version": version, "real": real, "isRepack": False},
        },
    }
    if custom_format_score is not None:
        item["customFormatScore"] = custom_format_score
    return item


def metadata(path: str, size: int = 1000, resolution: str = "1080p") -> MediaMetadata:
    return MediaMetadata(file_path=path, file_size=size, resolution=resolution)


def arr_quality(rank: int, revision=(1, 0), cf_score: int = 0) -> ArrQuality:
    return ArrQuality(
        quality_name=f"rank-{rank}",
        quality_rank=rank,
        revision=revision,
        custom_format_score=cf_score,
    )


# --- Quality profile order ---


def test_quality_rank_follows_profile_order():
    assert get_quality_rank(PROFILE, 3) == 0
    assert get_quality_rank(PROFILE, 7) == 2
    assert get_quality_rank(PROFILE, 30) == 3


def test_quality_rank_group_counts_as_one_rank():
    assert get_quality_rank(PROFILE, 15) == 1
    assert get_quality_rank(PROFILE, 16) == 1


def test_quality_rank_unknown_quality_is_lowest():
    assert get_quality_rank(PROFILE, 999) == -1


# --- Building ArrQuality from API resources ---


def test_build_arr_quality_uses_custom_format_score():
    quality = build_arr_quality(
        resource("/m/a.mkv", 7, "Bluray-1080p", version=2, custom_format_score=1750),
        PROFILE,
    )
    assert quality == ArrQuality(
        quality_name="Bluray-1080p",
        quality_rank=2,
        revision=(2, 0),
        custom_format_score=1750,
    )


def test_build_arr_quality_derives_score_from_custom_formats():
    item = resource("/m/a.mkv", 7, "Bluray-1080p", custom_format_score=None)
    item["customFormats"] = [{"id": 1, "name": "HDR"}, {"id": 2, "name": "x265"}]

    quality = build_arr_quality(item, PROFILE)

    assert quality.custom_format_score == 500 - 10000


def test_build_arr_quality_unknown_quality_returns_none():
    assert build_arr_quality(resource("/m/a.mkv", 0, "Unknown"), PROFILE) is None
    assert build_arr_quality({"path": "/m/a.mkv"}, PROFILE) is None


# --- Ranking ---


def test_rank_profile_order_beats_deduparr_score():
    remux = metadata("/m/remux.mkv")
    web = metadata("/m/web.mkv")
    # Deduparr prefers the WEB-DL, the profile prefers the Remux
    ranked = [(web, 40000, True), (remux, 20000, False)]
    qualities = {"/m/web.mkv": arr_quality(0), "/m/remux.mkv": arr_quality(3)}

    result = rank_by_arr_quality(ranked, qualities)

    assert [(m.file_path, s, k) for m, s, k in result] == [
        ("/m/remux.mkv", 20000, True),
        ("/m/web.mkv", 40000, False),
    ]


def test_rank_revision_breaks_quality_tie():
    original = metadata("/m/original.mkv")
    proper = metadata("/m/proper.mkv")
    ranked = [(original, 30000, True), (proper, 25000, False)]
    qualities = {
        "/m/original.mkv": arr_quality(2, revision=(1, 0)),
        "/m/proper.mkv": arr_quality(2, revision=(2, 0)),
    }

    result = rank_by_arr_quality(ranked, qualities)

    assert result[0][0] is proper and result[0][2] is True
    assert result[1][2] is False


def test_rank_real_revision_breaks_version_tie():
    a = metadata("/m/a.mkv")
    b = metadata("/m/b.mkv")
    qualities = {
        "/m/a.mkv": arr_quality(2, revision=(1, 0)),
        "/m/b.mkv": arr_quality(2, revision=(1, 1)),
    }

    result = rank_by_arr_quality([(a, 10, True), (b, 5, False)], qualities)

    assert result[0][0] is b


def test_rank_custom_format_score_breaks_revision_tie():
    hdr = metadata("/m/hdr.mkv")
    x265 = metadata("/m/x265.mkv")
    ranked = [(x265, 35000, True), (hdr, 30000, False)]
    qualities = {
        "/m/x265.mkv": arr_quality(2, cf_score=-10000),
        "/m/hdr.mkv": arr_quality(2, cf_score=500),
    }

    result = rank_by_arr_quality(ranked, qualities)

    assert result[0][0] is hdr and result[0][2] is True


def test_rank_full_arr_tie_falls_back_to_deduparr_score():
    a = metadata("/m/a.mkv")
    b = metadata("/m/b.mkv")
    qualities = {"/m/a.mkv": arr_quality(2), "/m/b.mkv": arr_quality(2)}

    result = rank_by_arr_quality([(a, 100, False), (b, 200, True)], qualities)

    assert result[0][0] is b
    assert sum(1 for _, _, keep in result if keep) == 1


# --- Setting ---


@pytest.mark.asyncio
async def test_ranker_disabled_by_default(test_db):
    assert await ArrQualityRanker.from_config(test_db) is None


@pytest.mark.asyncio
async def test_ranker_enabled_by_config(test_db):
    test_db.add(Config(key=PREFER_ARR_QUALITY_PROFILE_KEY, value="true"))
    await test_db.commit()

    assert isinstance(await ArrQualityRanker.from_config(test_db), ArrQualityRanker)


@pytest.mark.asyncio
async def test_arr_quality_profile_setting_endpoint(test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/arr-quality-profile")
        assert response.status_code == 200
        assert response.json() == {"enabled": False}

        response = await client.put(
            "/api/config/arr-quality-profile", json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json() == {"enabled": True}

        response = await client.get("/api/config/arr-quality-profile")
        assert response.json() == {"enabled": True}

    result = await test_db.execute(
        select(Config).where(Config.key == PREFER_ARR_QUALITY_PROFILE_KEY)
    )
    assert result.scalar_one().value == "true"


# --- Evaluating files through Radarr/Sonarr (mocked clients) ---


def radarr_client_mock() -> AsyncMock:
    client = AsyncMock(spec=RadarrClient)
    client.get_movie.return_value = [
        {"id": 9, "path": "/movies/Other (2001)", "qualityProfileId": 1},
        {
            "id": 42,
            "path": "/movies/Film (2020)",
            "qualityProfileId": 4,
            "movieFile": {"path": "/movies/Film (2020)/Film.WEBDL-1080p.mkv"},
        },
    ]
    client.get_quality_profile.return_value = PROFILE
    client.get_movie_files.return_value = [
        resource("/movies/Film (2020)/Film.WEBDL-1080p.mkv", 3, "WEBDL-1080p")
    ]
    client.get_manual_import.return_value = [
        resource(
            "/downloads/Film.2020.Remux-1080p.mkv",
            30,
            "Remux-1080p",
            custom_format_score=500,
        )
    ]
    return client


@pytest.mark.asyncio
async def test_evaluate_radarr_tracked_and_untracked_files(test_db):
    client = radarr_client_mock()
    ranker = ArrQualityRanker(test_db)
    tracked = "/movies/Film (2020)/Film.WEBDL-1080p.mkv"
    untracked = "/downloads/Film.2020.Remux-1080p.mkv"

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        qualities = await ranker.evaluate(MediaType.MOVIE, [tracked, untracked])

    assert qualities[tracked].quality_rank == 0
    assert qualities[untracked].quality_rank == 3
    assert qualities[untracked].custom_format_score == 500
    client.get_quality_profile.assert_awaited_once_with(4)
    client.get_movie_files.assert_awaited_once_with(42)
    client.get_manual_import.assert_awaited_once_with(folder="/downloads", movie_id=42)
    client.close.assert_awaited()


@pytest.mark.asyncio
async def test_evaluate_radarr_matches_movie_by_folder(test_db):
    client = radarr_client_mock()
    client.get_movie.return_value[1].pop("movieFile")
    client.get_movie_files.return_value = []
    client.get_manual_import.return_value = [
        resource("/movies/Film (2020)/a.mkv", 7, "Bluray-1080p"),
        resource("/movies/Film (2020)/b.mkv", 3, "WEBDL-1080p"),
    ]
    ranker = ArrQualityRanker(test_db)

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        qualities = await ranker.evaluate(
            MediaType.MOVIE, ["/movies/Film (2020)/a.mkv", "/movies/Film (2020)/b.mkv"]
        )

    assert qualities["/movies/Film (2020)/a.mkv"].quality_rank == 2
    client.get_manual_import.assert_awaited_once_with(
        folder="/movies/Film (2020)", movie_id=42
    )


@pytest.mark.asyncio
async def test_evaluate_caches_media_items_and_profiles(test_db):
    client = radarr_client_mock()
    ranker = ArrQualityRanker(test_db)
    paths = ["/movies/Film (2020)/Film.WEBDL-1080p.mkv"]

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        await ranker.evaluate(MediaType.MOVIE, paths)
        await ranker.evaluate(MediaType.MOVIE, paths)

    client.get_movie.assert_awaited_once()
    client.get_quality_profile.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_sonarr_uses_series_folder(test_db):
    client = AsyncMock(spec=SonarrClient)
    client.get_series.return_value = [
        {"id": 7, "path": "/tv/Show", "qualityProfileId": 4}
    ]
    client.get_quality_profile.return_value = PROFILE
    client.get_episode_files_by_series_id.return_value = [
        resource("/tv/Show/Season 01/Show.S01E01.WEBRip.mkv", 15, "WEBRip-1080p")
    ]
    client.get_manual_import.return_value = [
        resource("/tv/Show/Season 01/Show.S01E01.Bluray.mkv", 7, "Bluray-1080p")
    ]
    ranker = ArrQualityRanker(test_db)
    tracked = "/tv/Show/Season 01/Show.S01E01.WEBRip.mkv"
    untracked = "/tv/Show/Season 01/Show.S01E01.Bluray.mkv"

    with patch.object(ranker.sonarr_service, "_get_client", return_value=client):
        qualities = await ranker.evaluate(MediaType.EPISODE, [tracked, untracked])

    assert qualities[tracked].quality_rank == 1
    assert qualities[untracked].quality_rank == 2
    client.get_episode_files_by_series_id.assert_awaited_once_with(7)
    client.get_manual_import.assert_awaited_once_with(
        folder="/tv/Show/Season 01", series_id=7
    )


@pytest.mark.asyncio
async def test_evaluate_unavailable_when_media_not_matched(test_db):
    client = radarr_client_mock()
    ranker = ArrQualityRanker(test_db)

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        with pytest.raises(ArrQualityUnavailable, match="no matching item in Radarr"):
            await ranker.evaluate(MediaType.MOVIE, ["/elsewhere/x.mkv"])


@pytest.mark.asyncio
async def test_evaluate_unavailable_when_file_unknown(test_db):
    client = radarr_client_mock()
    client.get_manual_import.return_value = []
    ranker = ArrQualityRanker(test_db)

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        with pytest.raises(ArrQualityUnavailable, match="does not know file"):
            await ranker.evaluate(
                MediaType.MOVIE,
                [
                    "/movies/Film (2020)/Film.WEBDL-1080p.mkv",
                    "/downloads/Film.2020.Remux-1080p.mkv",
                ],
            )


@pytest.mark.asyncio
async def test_evaluate_unavailable_when_quality_unparsed(test_db):
    client = radarr_client_mock()
    client.get_manual_import.return_value = [
        resource("/downloads/Film.2020.Remux-1080p.mkv", 0, "Unknown")
    ]
    ranker = ArrQualityRanker(test_db)

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        with pytest.raises(ArrQualityUnavailable, match="could not parse"):
            await ranker.evaluate(
                MediaType.MOVIE,
                [
                    "/movies/Film (2020)/Film.WEBDL-1080p.mkv",
                    "/downloads/Film.2020.Remux-1080p.mkv",
                ],
            )


@pytest.mark.asyncio
async def test_evaluate_unavailable_when_arr_unreachable(test_db):
    client = radarr_client_mock()
    client.get_movie.side_effect = ArrConnectionError("connection refused")
    ranker = ArrQualityRanker(test_db)

    with patch.object(ranker.radarr_service, "_get_client", return_value=client):
        with pytest.raises(ArrQualityUnavailable, match="Radarr request failed"):
            await ranker.evaluate(MediaType.MOVIE, ["/movies/Film (2020)/a.mkv"])

    client.close.assert_awaited()


@pytest.mark.asyncio
async def test_evaluate_unavailable_when_arr_not_configured(test_db):
    ranker = ArrQualityRanker(test_db)

    with pytest.raises(ArrQualityUnavailable, match="Sonarr configuration not found"):
        await ranker.evaluate(MediaType.EPISODE, ["/tv/Show/a.mkv"])


# --- Duplicate set creation ---


async def _create_set(test_db, arr_ranker, caplog) -> DuplicateSet:
    files = [
        metadata("/movies/Film (2020)/Film.2020.1080p.WEB-DL.x265.mkv", size=4 * 2**30),
        metadata("/movies/Film (2020)/Film.2020.1080p.BluRay.x264.mkv", size=2**30),
    ]
    with caplog.at_level(logging.INFO):
        await create_duplicate_set(
            test_db,
            "plex-1",
            "Film",
            MediaType.MOVIE,
            files,
            ScoringEngine(),
            [],
            logging.getLogger("test"),
            arr_ranker,
        )
    await test_db.commit()
    result = await test_db.execute(
        select(DuplicateSet).options(selectinload(DuplicateSet.files))
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_create_set_keeps_arr_preferred_file(test_db, caplog):
    ranker = AsyncMock(spec=ArrQualityRanker)
    ranker.evaluate.return_value = {
        "/movies/Film (2020)/Film.2020.1080p.WEB-DL.x265.mkv": arr_quality(
            0, cf_score=-10000
        ),
        "/movies/Film (2020)/Film.2020.1080p.BluRay.x264.mkv": arr_quality(2),
    }

    dup_set = await _create_set(test_db, ranker, caplog)

    kept = [f for f in dup_set.files if f.keep]
    assert [f.file_path for f in kept] == [
        "/movies/Film (2020)/Film.2020.1080p.BluRay.x264.mkv"
    ]
    # Deduparr alone would keep the larger x265 WEB-DL
    web = next(f for f in dup_set.files if "WEB-DL" in f.file_path)
    assert web.score > kept[0].score
    assert dup_set.space_to_reclaim == web.file_size
    assert json.loads(kept[0].file_metadata)["arr_quality"] == "rank-2"
    assert json.loads(web.file_metadata)["arr_custom_format_score"] == -10000


@pytest.mark.asyncio
async def test_create_set_falls_back_to_deduparr_score(test_db, caplog):
    ranker = AsyncMock(spec=ArrQualityRanker)
    ranker.evaluate.side_effect = ArrQualityUnavailable("no matching item in Radarr")

    dup_set = await _create_set(test_db, ranker, caplog)

    kept = [f for f in dup_set.files if f.keep]
    assert [f.file_path for f in kept] == [
        "/movies/Film (2020)/Film.2020.1080p.WEB-DL.x265.mkv"
    ]
    assert "arr_quality" not in json.loads(kept[0].file_metadata)
    assert "no matching item in Radarr" in caplog.text
    assert "using Deduparr score" in caplog.text


@pytest.mark.asyncio
async def test_create_set_without_ranker_uses_deduparr_score(test_db, caplog):
    dup_set = await _create_set(test_db, None, caplog)

    kept = [f for f in dup_set.files if f.keep]
    assert [f.file_path for f in kept] == [
        "/movies/Film (2020)/Film.2020.1080p.WEB-DL.x265.mkv"
    ]


# --- Client calls ---


@pytest.mark.asyncio
async def test_radarr_client_get_movie_files():
    client = RadarrClient(base_url="http://radarr:7878", api_key="key")
    with patch.object(client, "_request", AsyncMock(return_value=[{"id": 1}])) as req:
        assert await client.get_movie_files(42) == [{"id": 1}]
    req.assert_awaited_once_with("GET", "/moviefile", params={"movieId": 42})


@pytest.mark.asyncio
async def test_client_get_quality_profile():
    client = SonarrClient(base_url="http://sonarr:8989", api_key="key")
    with patch.object(client, "_request", AsyncMock(return_value=PROFILE)) as req:
        assert await client.get_quality_profile(4) == PROFILE
    req.assert_awaited_once_with("GET", "/qualityprofile/4")


@pytest.mark.asyncio
async def test_existing_set_rerank_uses_arr_ranker(test_db):
    web = metadata("/movies/Film (2020)/Film.2020.1080p.WEB-DL.x265.mkv", 4 * 2**30)
    bluray = metadata("/movies/Film (2020)/Film.2020.1080p.BluRay.x264.mkv", 2**30)
    gone = metadata("/movies/Film (2020)/Film.2020.720p.HDTV.mkv", 2**29)
    await create_duplicate_set(
        test_db,
        "plex-1",
        "Film",
        MediaType.MOVIE,
        [web, bluray, gone],
        ScoringEngine(),
        [],
        logging.getLogger("test"),
    )
    await test_db.commit()
    result = await test_db.execute(
        select(DuplicateSet).options(selectinload(DuplicateSet.files))
    )
    dup_set = result.scalar_one()
    ranker = AsyncMock(spec=ArrQualityRanker)
    ranks = {web.file_path: 0, bluray.file_path: 2}
    ranker.evaluate.side_effect = lambda media_type, paths: {
        path: arr_quality(ranks.get(path, -1)) for path in paths
    }

    # A file removed outside Deduparr triggers a re-rank of the remaining files
    set_valid, files_removed = await verify_and_update_existing_set(
        test_db,
        dup_set,
        [web, bluray],
        ScoringEngine(),
        [],
        logging.getLogger("test"),
        ranker,
    )
    await test_db.commit()

    assert set_valid and files_removed == 1
    assert ranker.evaluate.await_args.args[0] == MediaType.MOVIE
    files = {f.file_path: f for f in dup_set.files}
    assert files[bluray.file_path].keep is True
    assert files[web.file_path].keep is False
