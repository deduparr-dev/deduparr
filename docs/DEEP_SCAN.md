# Deep Scan

Deep scan is an optional pass over the library folders on disk, after the media
server's own duplicate detection. Enable it in **Settings → General → Scan
Settings → Enable Deep Scan**, or through the API:

```bash
GET /api/config/deep-scan    # {"enabled": false}
PUT /api/config/deep-scan    # {"enabled": true}
```

## What It Does

For each scanned library it walks the folders the media server (Plex or
Jellyfin) reports for it, and groups video files by name and similar size,
leaving out samples and hardlinks. The duplicates the media server did not list
are **logged**: "Deep scan found N duplicate file(s) the media server does not
list". Deep scan creates no duplicate sets: the media server has never
catalogued those files, so Deduparr cannot verify what it would delete.

The Deduparr container must see the library folders at the paths the media
server reports; a library without paths is skipped with a warning.

## Technical Details

- `app/services/scan/disk_scan.py`: `DiskScanService`, the filesystem walk and
  its matching strategies
- `app/services/scan/orchestrator.py`: runs the media server scan, then the
  disk pass, and logs what only the disk pass found
- Stored as the config key `enable_deep_scan` (`"true"` or `"false"`)
