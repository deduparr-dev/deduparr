# Deduparr API Usage Examples

This document demonstrates how to use the duplicate detection and deletion features.

## Overview

The duplicate detection and deletion process works in three stages:
1. **Scan** - Detect duplicates and score files based on quality
2. **Preview** - Review which files would be kept vs deleted
3. **Delete** - Execute deletion (with dry-run support for safety)

The examples call `http://localhost:8655`, where the published image serves the UI and the API. A development backend listens on 3001.

## API Endpoints

### 1. Scan for Duplicates

Scan every configured media server for duplicates. The libraries given per
server become its stored selection, which scheduled scans use as well; send
`{}` to scan the stored selection as it is:

```bash
curl -X POST "http://localhost:8655/api/scan/start" \
  -H "Content-Type: application/json" \
  -d '{
    "libraries": {"plex": ["Movies", "TV Shows"], "jellyfin": ["Films"]}
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Scanned 3 libraries: 8 new, 2 updated, 0 removed",
  "duplicates_found": 22,
  "sets_created": 8,
  "sets_updated": 2,
  "sets_removed": 0,
  "total_sets": 10
}
```

### 2. Get Duplicate Sets

Retrieve the duplicate sets, newest first:

```bash
curl "http://localhost:8655/api/scan/duplicates"
```

**Optional filters:**
- `?status=pending` - Filter by status (pending, approved, rejected, processed)
- `?media_type=movie` - Filter by media type (movie, episode)
- `?limit=50` - Limit results (default: 100, max: 1000)
- `?offset=100` - Skip that many results, for the next page

The `X-Total-Count` response header holds how many sets match in all.

**Response:**
```json
[
  {
    "id": 1,
    "media_server": "plex",
    "item_id": "12345",
    "title": "The Matrix",
    "media_type": "movie",
    "found_at": "2025-11-07T10:30:00.123456",
    "status": "pending",
    "space_to_reclaim": 2147483648,
    "files": [
      {
        "id": 1,
        "file_path": "/movies/Matrix.720p.mkv",
        "file_size": 2147483648,
        "score": 11200,
        "keep": false,
        "file_metadata": {
          "resolution": "720p",
          "video_codec": "h264",
          "audio_codec": "aac"
        }
      },
      {
        "id": 2,
        "file_path": "/movies/Matrix.1080p.BluRay.REMUX.mkv",
        "file_size": 26843545600,
        "score": 42000,
        "keep": true,
        "file_metadata": {
          "resolution": "1080p",
          "video_codec": "h264",
          "audio_codec": "truehd"
        }
      }
    ]
  }
]
```

### 3. Preview Deletion

Preview what would be deleted for a specific duplicate set:

```bash
curl "http://localhost:8655/api/scan/duplicates/1/preview"
```

**Response:**
```json
{
  "set_id": 1,
  "title": "The Matrix",
  "media_type": "movie",
  "status": "pending",
  "files_to_keep": [
    {
      "id": 2,
      "file_path": "/movies/Matrix.1080p.BluRay.REMUX.mkv",
      "file_size": 26843545600,
      "score": 42000,
      "metadata": {
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "truehd"
      }
    }
  ],
  "files_to_delete": [
    {
      "id": 1,
      "file_path": "/movies/Matrix.720p.mkv",
      "file_size": 2147483648,
      "score": 11200,
      "metadata": {
        "resolution": "720p",
        "video_codec": "h264",
        "audio_codec": "aac"
      }
    }
  ],
  "total_files": 2,
  "files_to_delete_count": 1,
  "space_to_reclaim": 2147483648,
  "space_to_reclaim_mb": 2048.0,
  "space_to_reclaim_gb": 2.0
}
```

### 4. Delete Duplicates (Dry Run)

**SAFETY FIRST:** Always test with `dry_run: true` (default) before actual deletion:

```bash
curl -X POST "http://localhost:8655/api/scan/duplicates/1/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": true
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "[DRY-RUN] Would delete 1 file(s) from duplicate set 'The Matrix'",
  "dry_run": true,
  "files_deleted": 1,
  "space_reclaimed": 2147483648,
  "errors": []
}
```

### 5. Delete Duplicates (Actual Deletion)

⚠️ **WARNING:** This will permanently delete files!

```bash
curl -X POST "http://localhost:8655/api/scan/duplicates/1/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": false
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted 1 file(s) from duplicate set 'The Matrix'",
  "dry_run": false,
  "files_deleted": 1,
  "space_reclaimed": 2147483648,
  "errors": []
}
```

## How File Selection Works

The scoring engine automatically selects the best quality file to keep based on:

1. **Resolution** - Higher is better (4K > 1080p > 720p > 480p)
2. **Video Codec** - Better codecs score higher (HEVC > H.264 > VC-1 > VP9 > MPEG-4/XviD)
3. **Audio Codec** - Better codecs score higher (TrueHD/Atmos > DTS-HD > FLAC/PCM > DTS > E-AC-3 > AC3 = AAC)
4. **File Size** - 100 points per GiB, at most 5000
5. **Release** - Patterns in the file path, e.g. REMUX +20000, WEB-DL +5000, HDTV -1000
6. **Custom Rules** - Your own regex patterns, matched against the file path

Bitrate is stored but not scored.

### Testing File Selection

`test_scoring_picks_the_best_of_several_versions` (`backend/tests/test_scan_routes.py`) checks that only the highest-scoring file is marked `keep: true`, and that `space_to_reclaim` is the size of the others. `backend/tests/test_scoring_engine.py` covers the score order, the keep flags and custom rules.

### Prefer *arr Quality Profile (optional)

If you manage quality profiles and custom formats in Radarr/Sonarr (for example with Recyclarr and the TRaSH guides), Deduparr can keep the file your *arr would keep instead of relying on its own score. Enable **Settings → General → Scan Settings → Prefer *arr Quality Profile**, or use the API:

```bash
curl -X PUT http://localhost:8655/api/config/arr-quality-profile \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

Files are then ranked the way Radarr/Sonarr rank upgrades:

1. **Quality** - Position in the movie's/series' quality profile (a quality group counts as one rank)
2. **Revision** - Propers and repacks beat the original release
3. **Custom format score** - As calculated by the quality profile
4. **Deduparr score** - Only breaks ties

Radarr is used for movies and Sonarr for episodes; Radarr is called on `/api/v3`, Sonarr on `/api/v5` with a fallback to `/api/v3`. Tracked files are read from `moviefile` or `episodefile`. Files the *arr does not track yet are evaluated with `manualimport` against the item's own quality profile. When the kept file is untracked, the deletion pipeline's existing rescan makes the *arr import it.

If any file in a duplicate set cannot be evaluated (no matching movie/series, *arr not configured or unreachable, or a quality the *arr cannot parse), the **whole set** uses Deduparr's score and the reason is logged. The two scales are never mixed within one set. Files ranked by the *arr show their quality and custom format score in the duplicate set (`file_metadata.arr_quality` and `file_metadata.arr_custom_format_score`).

The setting applies when a duplicate set is created, or re-ranked because its files changed. Existing pending sets and keep choices made by hand are left as they are.

> **Paths:** Deduparr matches files by the path the media server reports, so Radarr/Sonarr have to see your media under the same paths, or have [path mappings](../DEPLOYMENT.md#when-the-media-server-and-radarrsonarr-see-different-paths), as for deletion.

## Deletion Pipeline Stages

When deletion is executed (non-dry-run), each file to delete goes through these stages:

1. **\*arr Removal** - Delete through Radarr/Sonarr
   - Skipped if Radarr/Sonarr is not configured, or does not track the file
2. **qBittorrent Removal** - Remove the torrent holding the file
   - Skipped if qBittorrent is not configured. The torrent stays when the kept file has a torrent too, so it keeps seeding, or when the torrent holds other videos, as a season pack does
3. **Disk Deletion** - Delete the file if still there, and what it leaves behind
4. **Media Server Refresh** - Refresh the item on Plex or Jellyfin

Once every file is done:

5. **\*arr Rescan** - Have Radarr/Sonarr import the kept file

Each file's *arr, qBittorrent, disk and refresh stages are recorded in the deletion history. Nothing is rolled back: a file that could not be deleted is reported in `errors`, and the set stays pending, so the deletion can be retried.

## Error Handling

The deletion endpoint returns errors in the response:

```json
{
  "success": false,
  "message": "Deleted 1 file(s) from duplicate set 'The Matrix'. Note: qBittorrent not configured",
  "dry_run": false,
  "files_deleted": 1,
  "space_reclaimed": 2147483648,
  "errors": [
    "Failed to delete /movies/SomeFile.mkv: qBittorrent not configured; File not found for deletion (checked its path and /media): /movies/SomeFile.mkv"
  ]
}
```

## Common Status Codes

- `200` - Success
- `400` - Bad request (unknown status or media type, set already processed, no file marked for deletion, no media server configured)
- `404` - Duplicate set not found
- `422` - Validation error (a parameter or body field of the wrong type, or out of range)
- `500` - Server error

## Best Practices

1. **Always preview first** - Use the `/preview` endpoint to see what would be deleted
2. **Test with dry-run** - Use `dry_run: true` before actual deletion
3. **Review scores** - Check that the scoring logic selected the right files to keep
4. **Configure custom rules** - Add scoring rules (`/api/scoring`) for patterns you prefer beyond the built-in ones
5. **Monitor space reclaimed** - Check `space_to_reclaim` values match expectations
6. **Check status after deletion** - Verify duplicate set status changes to "processed"
