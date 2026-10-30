# Deduparr Agent Instructions

## How We Work

Be critical. Base everything on facts: code you read, a command you ran, the API documentation. Do not guess.

1. **Check the entire codebase first.** Stay consistent with what is there, and reuse shared components, helpers and services wherever it makes sense. We build a deduplication app: duplicate code is a defect.
2. **Understand before changing.** Read whole files, and check `git blame`, old pull requests and issues for how the code is supposed to work.
3. **Correct, tight and minimal.** Implement it correctly and to best practice, with no more code than it needs.
4. **Review your own change.** Look for bugs, and list what you find and what could improve at the end, for discussion, rather than fixing beyond the task.
5. **Test against the real stack, as a user would.** Run the Podman stack ([quadlet/](quadlet/README.md)) and test every server and service with real calls and real logs, the backend API directly, and every flow through the frontend (port 3000) with Playwright. Conclusions are reproducible defects in the current code, not speculative edge cases.
6. **Only the tests and comments that are needed.** No debug output or clutter in the code.
7. **The full suite is heavy.** Run the tests you touch while working, and `scripts/test.sh` once, before committing a pull request.
8. **No AI attribution** in commits, pull requests or code. `.claude/settings.json` turns it off for Claude Code.
9. **No summary or report documents** in the repository: the reasoning goes in commit messages and pull requests.
10. **Reference project**: [maintainerr](https://github.com/Maintainerr/Maintainerr) solves the same media server and *arr problems. Look at how it does things; do not copy it.
11. **Subagents**, if you use any, run on the most capable model: Opus in Claude Code.

## Coding Standards

### Code Quality Principles

1. **No Duplicate Code**: Always reuse existing functionality and logic. Extract common patterns into shared utilities. DRY (Don't Repeat Yourself) is mandatory.
2. **Professional Code Only**: No verbose comments, no attributions in code. Keep comments technical and necessary.
3. **Modern Dependencies**: Use cutting-edge, well-maintained packages. Current stack uses Python 3.15, React 19, FastAPI latest.
4. **Type Safety - NO `Any` TYPE**: 
   - **NEVER** use `Any` type in TypeScript or Python
   - Always use specific types: `string`, `number`, `boolean`, `object`, etc.
   - For complex objects, define proper interfaces/types: `interface User { id: number; name: string }`
   - For unknown types, use union types: `string | number` or generics: `Array<T>`
   - For truly unknown data, use `unknown` (TypeScript) and validate before use
   - For flexible objects, use specific record types: `Record<string, string>` not `Record<string, any>`
   - Example: ❌ `function process(data: any)` → ✅ `function process(data: { id: number; value: string })`
5. **Code Formatting**: Always format code with `black` and lint with `ruff --fix` before committing. Run tests after formatting to ensure nothing broke.
6. **Test-Driven Development**:
   - Create tests for every feature and change
   - Tests must validate actual production code and real scenarios
   - Never modify tests just to make them pass - fix the production code instead
   - Exception: When production behavior intentionally changes, update test expectations (not logic)
7. **Thorough Analysis**: Read entire files, don't skip sections. Understand full context before making changes.
8. **Debugging Protocol**:
   - Document findings comprehensively
   - Create implementation plans with phased fixes
   - Verify logic matches intended behavior 100%
   - Compare actual implementation against documented requirements
9. **Issue Reporting**: List discovered issues at end of analysis for discussion - don't auto-fix without approval.
10. **Self-Sufficiency**: Use available tools (grep_search, read_file, semantic_search) instead of asking users to run commands.

## Project Overview

Deduparr is a duplicate media management system for the *arr ecosystem (Plex/Jellyfin/Radarr/Sonarr/qBittorrent). It detects duplicate movies/episodes, scores them by quality, and safely removes lower-quality versions across all services.

**Tech Stack:**
- Backend: Python 3.15 + FastAPI + SQLAlchemy (async)
- Frontend: React 19.2 + TypeScript + Vite + TailwindCSS
- Database: SQLite (default) or PostgreSQL
- Deployment: Docker multi-stage builds

**External API Documentation:**
- **Radarr API**: https://radarr.video/docs/api/
- **Sonarr API**: https://sonarr.tv/docs/api/
- **Plex API**: https://python-plexapi.readthedocs.io/ (using plexapi Python library)
- **Jellyfin API**: https://api.jellyfin.org/ (using the jellyfin-apiclient-python library)
- **qBittorrent API**: https://github.com/rmartin16/qbittorrent-api (using qbittorrent-api Python library)

**IMPORTANT**: When changing or adding functionality related to these services, **always consult their API documentation** to ensure correct usage, parameter validation, and error handling.

## React 19.2 Best Practices

### Modern React Patterns

1. **No Unnecessary Directives**: 
   - Don't use `"use client"` or `"use server"` unless building Server Components with a framework like Next.js
   - These directives are framework-specific and not needed for standard Vite+React apps
   - React 19 itself doesn't require these directives for client-only applications

2. **Avoid Premature Optimization**:
   - **Don't use `useCallback` or `useMemo`** unless there's a proven performance issue
   - Keep code simple and readable first
   - Only add memoization when profiling shows it's necessary
   - Modern React is fast enough without manual memoization in most cases

3. **Ref Handling - Modern Pattern**:
   - `ref` is now a regular prop - **no need for `forwardRef`** in new components
   - Define `ref` in props interface: `interface Props { ref?: React.Ref<HTMLElement> }`
   - Access refs directly: `function MyInput({ ref, ...props }: Props) { return <input ref={ref} {...props} /> }`
   - Ref cleanup: Return cleanup function from ref callbacks
   - Example: `ref={(node) => { /* setup */; return () => { /* cleanup */ }; }}`
   - **All UI components updated**: Input, Button, Label, Checkbox, Card, Toast, Tooltip now use this pattern

4. **Loading States with `useTransition`**:
   - **Use `useTransition`** instead of manual loading state management
   - Automatic pending state: `const [isPending, startTransition] = useTransition()`
   - Wrap async operations: `startTransition(async () => { await doSomething(); })`
   - No need for try/finally blocks to manage loading flags
   - Better integration with React's concurrent features
   - **Applied in**: SetupWizard, Settings pages

5. **React Query: Always use `isPending` not `isLoading`**:
   - **Use `isPending`** from `useQuery`/`useMutation` for guaranteed type safety
   - `isPending` is derived from `status` field and guarantees TypeScript type narrowing
   - `isLoading` combines `status` + `fetchStatus` and can be false when data is undefined
   - Edge cases where `isLoading` fails: disabled queries, offline mode, lazy queries
   - **All queries updated**: Dashboard, Settings, System, Scan pages use `isPending`

6. **FORBIDDEN: Do NOT use `useEffect`, `useCallback`, or `useEffectEvent`!**:
   - **NEVER** use `useEffect` - it's forbidden in this project
   - **NEVER** use `useCallback` - it's forbidden in this project
   - **NEVER** use `useEffectEvent` - experimental and potentially buggy
   - Use alternative patterns: React Query, form actions, `useActionState`, `useTransition`, `useOptimistic`
   - For data fetching: Use React Query hooks (`useQuery`, `useMutation`)
   - For side effects: Use form actions or event handlers
   - For memoization: Don't optimize prematurely - React 19 is fast enough

7. **Form Actions**:
   - Use `useActionState` (formerly `useFormState`) for form state management
   - Forms support `action` prop with async functions
   - Use `useFormStatus` in child components to access form pending state
   - Example: `<form action={async (formData) => { await save(formData); }}>`

8. **Context as Provider**:
   - Use `<Context>` directly instead of `<Context.Provider>`
   - Example: `<ThemeContext value="dark">{children}</ThemeContext>`
   - `Context.Provider` will be deprecated in future versions

9. **Transitions and Optimistic Updates**:
   - Use `useTransition` for async operations with pending state
   - Use `useOptimistic` for optimistic UI updates during mutations
   - Actions (async functions in transitions) automatically handle pending/error states

10. **Document Metadata**:
   - Render `<title>`, `<meta>`, `<link>` tags directly in components
   - React automatically hoists them to `<head>`
   - No need for react-helmet in simple cases

11. **Type Safety in React**:
   - **NEVER** use `any` type in TypeScript
   - Define proper prop interfaces: `interface Props { name: string; onClick: () => void }`
   - Use specific event types: `React.MouseEvent<HTMLButtonElement>` not `any`
   - For flexible props, use union types or generics, never `any`
   - Example: ❌ `const handleClick = (e: any)` → ✅ `const handleClick = (e: React.MouseEvent<HTMLButtonElement>)`

10. **New in React 19.2 - `<Activity />`**:
    - Use `<Activity>` for pre-rendering and controlling UI visibility/priority
    - Two modes: `visible` (normal) and `hidden` (pre-render without blocking)
    - Perfect for pre-loading next pages or preserving navigation state
    - Example: `<Activity mode={isVisible ? 'visible' : 'hidden'}><Page /></Activity>`

### Component Simplification Principles

- Extract small, focused components (single responsibility)
- Avoid nested ternaries - use early returns or separate functions
- Keep JSX clean and readable - extract complex logic to helper functions
- Use destructuring to reduce repetition
- Prefer explicit conditionals over inline ternary chains

## Architecture Patterns

### Async-First Backend

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
server SDK:

- `base.py` - the `MediaServer` protocol and `DuplicateGroup`, which carries an
  item id, a title and the `MediaMetadata` of each file
- `plex_adapter.py` / `jellyfin_adapter.py` - one per server
- `file_probe.py` - sample detection and the stat/inode probe both adapters and
  the disk scanner share
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

Unlike typical Plex integrations using direct server URLs or manual X-Plex-Token entry, this project uses **plex.tv OAuth with PIN login ONLY** with enterprise-grade security:

1. Frontend calls `PlexAuthService.initiate_auth()` → returns PIN and OAuth URL
2. User visits OAuth URL and authorizes
3. Frontend polls `PlexAuthService.check_auth(pin_id)` → returns **encrypted** token when complete
4. Encrypted token stored in database (`Config` model with key `plex_auth_token`)
5. `PlexService` decrypts token on demand to connect to Plex servers

**Security Features:**
- **Token Encryption**: All tokens/API keys encrypted with itsdangerous URLSafeSerializer before storage
- **File-based Encryption Key**: Key stored in `/app/data/.encryption_key` (separate from database)
- **CSRF Protection**: State tokens validate OAuth flow authenticity
- **Token Validation**: Periodic validation ensures tokens remain valid
- **Secure Logging**: Sensitive data sanitized in logs (shows only first/last few chars)

**Critical:** 
- For **Plex**, never use direct server URLs and never support manual token
  entry - OAuth only. This rule is specific to Plex; Jellyfin is configured
  with a URL and an admin API key, which is the only thing it offers.
- Always authenticate via plex.tv token first
- All tokens/API keys encrypted using `services/shared/security.py`
- Use `get_token_manager()` for all encryption/decryption operations (works for any service)
- Encryption key is file-based at `/app/data/.encryption_key` (auto-generated, persists via Docker volume)
- `security.py` is service-agnostic - use it for Plex, Radarr, Sonarr, qBittorrent, etc.

### Database Models Structure

The schema is owned by **Alembic** (`backend/alembic/`), applied on startup by
`init_db()`. A model change reaches it as described in
[Database Migrations](#database-migrations).

Five core models with specific relationships:

- `DuplicateSet`: Groups duplicate media items (has many `DuplicateFile`).
  `media_server` + `item_id` say which server reported it and its id there
  (`item_id` is stored as `plex_item_id`, the column's 0.5.7 name)
- `DuplicateFile`: Individual file in duplicate set (has one `DeletionHistory`)
- `DeletionHistory`: Tracks multi-stage deletion (*arr → qBittorrent → disk → media server refresh)
- `ScoringRule`: User-defined regex patterns for scoring
- `Config`: Key-value settings store

`DeletionHistory.media_server_refreshed` (stored as `plex_refreshed`) records
the final stage for whichever server owns the set.

All models use timezone-aware UTC timestamps via `datetime.now(timezone.utc)`. Enums defined as `str, enum.Enum` for JSON serialization.

### Database Migrations

Migrations are generated by Alembic's autogenerate, never written or edited by
hand.

- **A model change ships with its migration in the same commit.** After
  changing a model, run `bash scripts/new-migration.sh "Short description"`. It
  upgrades a throwaway database to the newest migration, compares it with the
  models and writes `backend/alembic/versions/<next number>_<description>.py`,
  formatted by ruff and black. Keep the description under 40 characters, where
  Alembic cuts the file name.
- **If a generated migration is wrong, change the model and generate it
  again.** Autogenerate cannot see:
  - a rename: it drops the column and adds a new one, which loses the data.
    Rename only the attribute and keep the column's name, as in
    `item_id = Column("plex_item_id", ...)`.
  - a change to data, such as moving a config key: make the code read the old
    form, or give a new column a `server_default`.
- **Never change or delete a migration that is in a release**
  (`git tag --contains <commit>`).
- The history starts at the first release. `0001` is the schema of 0.1.1, and
  `0002` and `0003` are the changes 0.2.0 and 0.5.3 made to it, each generated
  from that release's models. No release before migrations altered a table, so
  an install keeps the schema of its first start: `alembic/env.py` marks a
  database that has tables but no Alembic version as being at `0001`, and the
  upgrade replays the rest (`0002` and `0003` only alter columns, so they are
  safe to repeat).
- Migrations connect through the app's async driver (aiosqlite or asyncpg), so
  SQLite and PostgreSQL run the same files.
- `tests/test_migrations.py` checks that `0001` and `0003` are the schemas of
  0.1.1 and 0.5.7, that a new install and upgraded 0.1.1 and 0.5.7 installs all
  match the models (`alembic check`), and that downgrading restores each
  release's schema. A model change without its migration fails there, in CI.
- On SQLite, a release's database stores enums by name (`MOVIE`, `PENDING`)
  and booleans as 0/1: data written for a migration test must look the same.

### Multi-Stage Deletion Pipeline

`DeletionPipeline` (`services/deletion/pipeline.py`) deletes one file in these
stages, tracked in `DeletionHistory`:

1. `deleted_from_arr`: delete through Radarr/Sonarr, which removes the file
2. `deleted_from_qbit`: remove the torrent holding the file, with its data -
   unless the kept file has a torrent, or the torrent holds other videos too
   (a season pack)
3. *arr rescan, once per set: `RescanMovie`/`RescanSeries` re-reads the item
   from disk, importing the kept file - or the whole library when the *arr
   tracks neither file, as it may hold one under its own mount. A kept file
   directly in a root folder cannot be imported; it is never moved, and the
   result says so
4. `deleted_from_disk`: delete the file if still on disk, then the side files
   named after it (.nfo, subtitles, artwork), and the release's
   Sample/Subs/Proof/Extras folders once no other video shares the directory,
   then the folders left empty - up to the library folder the media server
   reports, never it, and none when the server cannot list its libraries
5. `media_server_refreshed`: refresh the item on the server that reported it

A file is only ever identified by more than its name, since other titles share
names like `S01E01.mkv`: on disk by the media server's path, or that path's
tail under the media directory at the reported size; in qBittorrent by full
path, or by name and size. A file counts as deleted only once it is gone from
disk; anything less is an error and the set stays pending for a retry. The
dashboard counts deletions the same way (`DeletionHistory.is_complete`).

## Development Workflows

### Running Tests

```bash
cd backend
pytest                          # Run all tests
pytest --cov=app tests/         # With coverage
pytest tests/test_plex_service.py -v  # Specific test file
```

Tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`) and pytest-asyncio. Mock external services (Plex, *arr APIs) using `unittest.mock`.

### Docker Rebuild

**ALWAYS** use the rebuild script for rebuilding Docker containers (never use manual docker commands):

```bash
# Production rebuild (default)
bash scripts/rebuild-docker.sh --prod

# Development rebuild
bash scripts/rebuild-docker.sh --dev
```

The script handles:
1. Port cleanup (stops containers using relevant ports)
2. Docker compose down
3. Database and encryption key removal
4. Docker system prune
5. Image rebuild (no cache)
6. Container startup

**Never** manually run `docker build`, `docker compose build`, or similar commands. The rebuild script ensures proper cleanup and consistency.

### Local Development

```bash
# Backend (port 3001)
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main

# Frontend (port 3000)
cd frontend
npm install
npm run dev
```

Backend runs via `uvicorn` with hot reload. Frontend proxies API requests to `http://localhost:3001`.

### Docker Development

```bash
# Full stack (separate containers for hot reload)
systemctl --user start deduparr-frontend.service   # Podman quadlets, see quadlet/

# Production build test
docker build -t deduparr:test .
docker run -dp 8655:8655 deduparr:test
```

Production uses multi-stage build: frontend → backend → nginx+supervisor runtime.

### Branches and Pull Requests

- One branch per piece of work, and its pull request targets `develop`. `main`
  only receives `develop`, when a version is cut.
- CI runs on the pull request, not on a pushed branch.
- Pull requests are squash-merged, so the commit subject ends with `(#n)`: the
  release notes find the pull request from it.
- Rulesets: `develop` takes a pull request with an approval and passing CI;
  `main` and the `v*` tags change only when a version is cut.
- Dependabot's pull requests approve and merge themselves once CI passes
  ([docs/DEPENDABOT_AUTO_MERGE.md](docs/DEPENDABOT_AUTO_MERGE.md)).

### Releases

How a version is cut and its notes written: [docs/RELEASING.md](docs/RELEASING.md). Every
release uses the notes format there; v0.6.0 is the model.

## Code Conventions

### Layout and Naming

- Backend services are grouped by domain under `app/services/`: `media_server`,
  `arr`, `scan`, `deletion`, `notifications`, `download`, `shared`. A file is
  named for its role (`pipeline.py`, `runner.py`), and for its thing and role
  where several share one (`plex_adapter.py`, `radarr_service.py`).
- Every frontend API call goes through `src/services/api.ts`, and the stored
  configuration is one React Query key, `["config"]`.
- No dead code paths: reconnect them or remove them.
- Prefer the clean design over compatibility layers: Deduparr has few users,
  and existing data moves with a generated migration.

### Import Organization

Standard library → third-party → local app imports, separated by blank lines:

```python
from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from plexapi.server import PlexServer

from app.core.database import Base
from app.models import DuplicateSet
```

### SQLAlchemy Relationships

Always use `selectinload` when accessing relationships to prevent N+1 queries:

```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(DuplicateSet)
    .options(selectinload(DuplicateSet.files))
    .where(DuplicateSet.id == set_id)
)
```

### Error Handling in Services

Services raise descriptive errors; endpoints catch and return appropriate HTTP responses:

```python
# In service
if not library:
    raise ValueError(f"Library '{name}' not found")

# In endpoint
try:
    result = await service.method()
except ValueError as e:
    raise HTTPException(status_code=404, detail=str(e))
```

### Testing Patterns

Use fixtures for database and mocks. Test async functions with `@pytest.mark.asyncio`:

```python
@pytest.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # ... yield session

@pytest.mark.asyncio
async def test_function(test_db):
    # Test implementation
```

Mocks have hidden real defects here: a patched-out pipeline hid that scheduled
deletion deleted nothing, and an `os.path.exists` that always answered True hid
the disk stage deleting other titles' files. Test file handling on a real
temporary directory, and a flow end to end.

The end-to-end suite (`frontend/e2e/`) runs against stand-ins for Jellyfin,
Radarr, Sonarr and qBittorrent (`fake-jellyfin/`, `fake-services/`), which
behave like the real APIs wherever Deduparr depends on them, quirks included.
Its database is never reset, so each spec works on a title unique to its run
(`uniqueTitle`). Playwright reuses whatever already listens on its ports. Select
by `data-testid` and assert `toHaveCount(1)`; a toast's text appears twice, in
the toast and in its live announcer. The `/api/scan/dev/*` endpoints that seed
duplicate sets exist only with `LOG_LEVEL=DEBUG`, which the suite's backend sets.

## Integration Points

### Plex API (`plexapi`)

- OAuth via `MyPlexPinLogin` and `MyPlexAccount`
- Server connection via `account.resource(name).connect()`
- Media objects: `Movie`, `Show`, `Episode` with nested `.media[0].parts[0]`
- Refresh libraries: `library.update()`

### *arr APIs (httpx-based clients)

**Direct httpx implementation** (migrated from PyArr):
- **RadarrClient** (`app.services.arr.client.RadarrClient`): Radarr API v3 client
- **SonarrClient** (`app.services.arr.client.SonarrClient`): Sonarr API v3/v5 client
- Both use `httpx.AsyncClient` for async HTTP requests
- Error handling via `ArrConnectionError` exception
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

Behaviour read from Radarr's and Sonarr's source, which the rescans rely on:
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
from app.services.arr.client import RadarrClient, ArrConnectionError

client = RadarrClient(base_url="http://localhost:7878", api_key="xxx")
try:
    movies = await client.get_movie()
    await client.post_command("RescanMovie", movieId=movies[0]["id"])
except ArrConnectionError as e:
    logger.error(f"Radarr API error: {e}")
```

### qBittorrent (`qbittorrent-api`)

`QBittorrentService` (`services/download/qbittorrent_service.py`) finds the
torrent holding a file and removes it by hash; the deletion pipeline above says
when. `qbittorrent-api` sends `hash` in the POST form, encodes booleans as
`"True"`, and raises `LoginFailed` with no message; the stand-in mirrors this.

## Common Gotchas

1. **SQLite WAL Mode**: Applied in `init_db()` for concurrency. Don't remove these PRAGMAs.
2. **Async Session Cleanup**: Always use `async with` or `try/finally` to close sessions.
3. **Plex Media Structure**: Files are at `media.media[0].parts[0].file`, not directly on media object.
4. **Model Imports**: Import from `app.models` package (models/__init__.py), not individual files.
5. **Frontend API URL**: Uses env var `VITE_API_URL`, defaults to `http://localhost:3001` in dev.
6. **Processed sets are history**: when an item is duplicated again, the scan opens a new pending set.
7. **Deep scan only logs**: it reports duplicates the media server does not list, and creates no sets from them.

## Status and Roadmap

What each version shipped is in [docs/releases/](docs/releases/); the roadmap is in
`todo/IMPLEMENTATION_PLAN.md`.
