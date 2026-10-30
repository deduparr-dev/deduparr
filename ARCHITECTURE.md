# Architecture

A fast map of how Deduparr is built, for finding the right place in the code.
The rules for changing it are in [AGENTS.md](AGENTS.md). Update this file when a
boundary, a stage or a real service's behaviour it describes changes.

Deduparr is a duplicate media management system for the *arr ecosystem (Plex/Jellyfin/Radarr/Sonarr/qBittorrent). It detects duplicate movies/episodes, scores them by quality, and safely removes lower-quality versions across all services.

**Tech Stack:**
- Backend: Python 3.15 + FastAPI + SQLAlchemy (async)
- Frontend: React 19 + TypeScript + Vite + TailwindCSS
- Database: SQLite (default) or PostgreSQL
- Deployment: Docker multi-stage builds


## Backend

### Async first

All database operations use async/await. Database sessions via `AsyncSession`, models inherit from `Base`, and the engine is `create_async_engine`. When writing new endpoints or services:

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# In endpoints
async def endpoint(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model))
```

### Media Servers

Deduparr reads libraries from Plex, Jellyfin, or both at once. Everything above
`app/services/media_server/` works against one contract and never touches a
server SDK, except the setup wizard, which lists Plex libraries through
`PlexService` (`setup_service.get_plex_libraries`):

- `base.py` - the `MediaServer` protocol and `DuplicateGroup`, which carries an
  item id, a title and the `MediaMetadata` of each file
- `plex_adapter.py` / `jellyfin_adapter.py` - one per server
- `file_probe.py` - sample detection and video extensions, which both adapters
  and the disk scanner share, and the stat/inode probe (`probe_file`) the
  adapters use
- `__init__.py` - `get_media_servers(db)`, and `selected_libraries()` for the
  per-server `plex_libraries` / `jellyfin_libraries` selection

**A server counts as configured when its credentials are present**, so there is
no separate "which server" setting to drift out of step. Duplicate sets are
keyed on `(media_server, item_id)`: the same title on both servers stays two
sets, and one server's scan never discards the other's findings.

Authentication is deliberately outside the protocol, because the two differ:

- **Plex** uses the plex.tv OAuth PIN flow described below
- **Jellyfin** uses a server URL and an API key, which **must belong to an
  administrator** - library paths and scan triggers are admin-only endpoints,
  and item queries need a user id only an admin key can look up

The Jellyfin adapter uses the official `jellyfin-apiclient-python` SDK. That
SDK is synchronous, so every call goes through `asyncio.to_thread`. Two of its
quirks are worth knowing: `get_system_info()` reads `System/Configuration` and
carries no version (`get_system_info_new()` reads `System/Info`), and Jellyfin
routes and binds query parameters case-insensitively, which the SDK relies on.
`authenticate()` does not raise on a rejected key: the server entry keeps its
`Id` and has no `AccessToken`, while an unreachable server has no `Id` at all.

A duplicate on Jellyfin is an item with more than one `MediaSource`. Jellyfin
reports no resolution label, so the scoring engine derives it from the height.

`e2e/fake-jellyfin/` is a stand-in server so the suite can drive the adapter
without a Jellyfin install; demo.jellyfin.org is a real one to check against.

### Plex OAuth Authentication Flow

Unlike typical Plex integrations using direct server URLs or manual X-Plex-Token entry, this project uses **plex.tv OAuth with PIN login ONLY**:

1. Frontend calls `PlexAuthService.initiate_auth()` → returns PIN and OAuth URL
2. User visits OAuth URL and authorizes
3. Frontend polls `PlexAuthService.check_auth(pin_id)` → returns the **encrypted** token when complete
4. Encrypted token stored in database (`Config` model with key `plex_auth_token`)
5. `PlexService` reads the token back on demand to connect to Plex servers

**Security Features:**
- **Encrypted secrets**: tokens, API keys and passwords are stored encrypted with Fernet (`cryptography`), under a key derived from the key file; startup converts older signed or plain values. The API returns a set secret only as `SECRET_MASK`, and sending the mask or a blank back keeps the stored one. A connection test sends a stored secret only to the server stored with it
- **File-based key**: stored in `/app/data/.encryption_key` (separate from database). Losing it loses the secrets, which are then entered again
- **No CORS**: the frontend is same-origin, so another site in the browser cannot call the API; there is still no login
- **Secure Logging**: secrets are never logged, not even in part; a logging filter masks known patterns

**Critical:** 
- For **Plex**, never use direct server URLs and never support manual token
  entry - OAuth only. This rule is specific to Plex; Jellyfin is configured
  with a URL and an admin API key, which is the only thing it offers.
- Always authenticate via plex.tv token first
- Tokens/API keys are encrypted using `services/shared/security.py`
- Use `get_token_manager()` for encrypting and reading back secrets (`encrypt()`/`decrypt()`; works for any service)
- The key file is at `/app/data/.encryption_key` (auto-generated, persists via Docker volume)
- `security.py` is service-agnostic - use it for Plex, Radarr, Sonarr, qBittorrent, etc.

### Database Models Structure

The schema is owned by **Alembic** (`backend/alembic/`), applied on startup by
`init_db()`. A model change reaches it as described in
[Database Migrations](AGENTS.md#database-migrations).

Five core models with specific relationships:

- `DuplicateSet`: Groups duplicate media items (has many `DuplicateFile`).
  `media_server` + `item_id` say which server reported it and its id there
  (`item_id` is stored as `plex_item_id`, the column's 0.5.7 name)
- `DuplicateFile`: Individual file in duplicate set (its `deletion_history` is a
  list; the pipeline keeps one row per file)
- `DeletionHistory`: Tracks multi-stage deletion (*arr → qBittorrent → disk → media server refresh)
- `ScoringRule`: User-defined regex patterns for scoring
- `Config`: Key-value settings store

`DeletionHistory.media_server_refreshed` (stored as `plex_refreshed`) records
the final stage for whichever server owns the set.

All models use timezone-aware UTC timestamps via `datetime.now(timezone.utc)`. Enums defined as `str, enum.Enum` for JSON serialization.

### Multi-Stage Deletion Pipeline

`DeletionPipeline` (`services/deletion/pipeline.py`) deletes one file in these
stages, tracked in `DeletionHistory`:

1. `deleted_from_arr`: delete through Radarr/Sonarr, which removes the file
2. `deleted_from_qbit`: remove the torrent holding the file, with its data -
   unless it is the kept file's torrent, or holds other videos (a season pack)
3. `deleted_from_disk`: delete the file if still on disk, then the side files
   named after it (.nfo, subtitles, artwork), and the release's
   Sample/Subs/Proof/Extras folders once no other video shares the directory,
   then the folders left empty - up to the library folder the media server
   reports, never it, and none when the server cannot list its libraries
4. `media_server_refreshed`: refresh the item on the server that reported it

Once every file of the set is done, and if any was deleted, the *arr rescans
once for the set: `RescanMovie`/`RescanSeries` re-reads the item from disk,
importing the kept file - or the whole library when the *arr tracks neither
file, as it may hold one under its own mount. A kept file directly in a root
folder cannot be imported; it is never moved, and the result says so.

Plex and Jellyfin list the same files as two sets, each with its own choice of
what to keep. So a set deletes nothing unless a file it keeps is on disk, a keep
toggle reaches the same file in the other server's pending set, and a file both
list counts once. A file the other set already deleted is not an error, and a
hardlink frees nothing while another link stays, so a set reports what it really
reclaimed.

A file is only ever identified by more than its name, since other titles share
names like `S01E01.mkv`: on disk by the media server's path, or that path's
tail under the media directory at the reported size; in qBittorrent by full
path, or by name and size. A file counts as deleted only once it is gone from
disk; anything less is an error and the set stays pending for a retry. The
dashboard counts deletions the same way (`DeletionHistory.is_complete`).

## Integration Points

### Plex API (`plexapi`)

- OAuth PIN through plex.tv's `/api/v2/pins` (with `requests`), then `MyPlexAccount`
- Server connection via `account.resource(name).connect()`
- Media objects: `Movie`, `Show`, `Episode` with nested `.media[0].parts[0]`
- Refresh libraries: `library.update()`

### *arr APIs (httpx-based clients)

**Direct httpx implementation** (migrated from PyArr):
- **RadarrClient** (`app.services.arr.client.RadarrClient`): Radarr API v3 client
- **SonarrClient** (`app.services.arr.client.SonarrClient`): Sonarr API v3/v5 client
- Both use `httpx.AsyncClient` for async HTTP requests
- With path mappings set (`app.services.arr.path_mapping.PathMapper`), the
  client translates every path it exchanges with the *arr, so the code above it
  works with the paths the media server reports
- Errors raise `ArrClientError` or a subclass: `ArrConnectionError` (unreachable,
  timeout), `ArrAuthError` (401/403), `ArrNotFoundError` (404)
- API keys stored in `Config` model (encrypted)
- Responses are typed with the TypedDicts in `client.py` (`MediaItem`,
  `ArrFile`, `Episode`, `QualityProfile`, ...) for the fields Deduparr reads
- Key methods:
  - `get_system_status()`: Get version/status info
  - `get_movie()` / `get_series()`: One item by ID, or all of them
  - `get_root_folder()`: Get configured root folders
  - `delete_movie_file()` / `delete_episode_file()`: Delete files
  - `post_command()`: Execute commands (RescanMovie, RescanSeries)
  - `update_movie()` / `update_series()`: Send an item back changed, e.g. a new path

Behaviour read from Radarr's and Sonarr's source and their real APIs, which
Deduparr relies on:
- A delete answers 200 with an empty body, not JSON.
- `/manualimport` with the item's id answers "Unknown" for a file not imported
  yet, and Sonarr gives no quality at all without it; `/parse?title=<file name>`
  reads the quality and custom formats on both.
- Sonarr's episode files do not name their episodes.
- `RescanMovie`/`RescanSeries` re-read one item from disk, or every item when
  given no id.
- `DownloadedMoviesScan`/`DownloadedEpisodesScan` refuse a folder that belongs
  to an item, and read any other folder's name as a title ("Unknown Movie").
- `RefreshMovie`/`RefreshSeries` re-read the disk only as the *arr's "Rescan
  after refresh" setting allows; commands sent through the API count as manual.
- Identical queued commands are merged into one.
- Root folders are stored with a trailing `/`, and a root folder can never be
  an item's path.

**Usage Pattern:**
```python
from app.services.arr.client import RadarrClient, ArrClientError

client = RadarrClient(base_url="http://localhost:7878", api_key="xxx")
try:
    movies = await client.get_movie()
    await client.post_command("RescanMovie", movieId=movies[0]["id"])
except ArrClientError as e:
    logger.error(f"Radarr API error: {e}")
```

### qBittorrent (`qbittorrent-api`)

`QBittorrentService` (`services/download/qbittorrent_service.py`) finds the
torrent holding a file and removes it by hash; the deletion pipeline above says
when. `qbittorrent-api` sends `hash` in the POST form, encodes booleans as
`"True"`, and raises `LoginFailed` with no message; the stand-in mirrors this.
