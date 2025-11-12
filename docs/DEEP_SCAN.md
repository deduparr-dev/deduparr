# Deep Scan

## Overview

Deep Scan is an optional filesystem-based duplicate detection that complements Plex API scanning. Enable it in Settings → General.

## When to Use

**Enable Deep Scan if:**
- Plex misses duplicates in different directories
- You have case-sensitivity issues (e.g., `Movie.mkv` vs `movie.mkv`)
- Files should be hardlinked but aren't

**Keep Disabled if:**
- Your libraries are small and Plex detection works fine
- Scan performance is critical

## Performance

Deep Scan analyzes the entire filesystem:
- **Small libraries** (~100 movies): +2-5 seconds
- **Large libraries** (1000+ movies): +30-60 seconds

Plex API scanning always runs first (fast), then deep scan adds filesystem detection.

## Configuration

**Settings Page:**
```
General → Scan Settings → Enable Deep Scan
```

**API:**
```bash
# Get setting
GET /api/config/deep-scan
{"enabled": false}

# Update setting
PUT /api/config/deep-scan
{"enabled": true}
```

**Backend:**
```python
from app.services.disk_scan_service import DiskScanService

service = DiskScanService()
duplicates = service.find_duplicate_movies_on_disk(["/path/to/movies"])
```

## Technical Details

- **Service:** `DiskScanService` (standalone, Plex-independent)
- **Orchestrator:** `ScanOrchestrator` merges Plex + disk results
- **Storage:** Config key `enable_deep_scan` ("true"/"false" string)
- **Algorithm:** MD5 hashing + fuzzy title matching
- **Tests:** 40 unit tests + 4 integration tests

## See Also

- [Implementation Plan](../todo/disk_scan_implementation.md) - Full technical spec
- [API Usage](./API_USAGE_EXAMPLES.md) - API endpoints
