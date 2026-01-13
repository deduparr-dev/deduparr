# Deduparr AI Coding Agent Instructions

## Coding Standards

### Code Quality Principles

1. **No Duplicate Code**: We're building a deduplication app - our code must exemplify this. Always reuse existing functionality and logic. Extract common patterns into shared utilities. DRY (Don't Repeat Yourself) is mandatory.
2. **Professional Code Only**: No verbose comments, no attributions in code. Keep comments technical and necessary.
3. **Modern Dependencies**: Use cutting-edge, well-maintained packages. Current stack uses Python 3.14, React 19, FastAPI latest.
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

Deduparr is a duplicate media management system for the *arr ecosystem (Radarr/Sonarr/qBittorrent/Plex). It detects duplicate movies/episodes, scores them by quality, and safely removes lower-quality versions across all services.

**Tech Stack:**
- Backend: Python 3.14 + FastAPI + SQLAlchemy (async)
- Frontend: React 19.2 + TypeScript + Vite + TailwindCSS
- Database: SQLite (default) or PostgreSQL
- Deployment: Docker multi-stage builds

**External API Documentation:**
- **Radarr API**: https://radarr.video/docs/api/
- **Sonarr API**: https://sonarr.tv/docs/api/
- **Plex API**: https://python-plexapi.readthedocs.io/ (using plexapi Python library)
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
- Never use direct Plex server URLs
- Never support manual token entry - OAuth only
- Always authenticate via plex.tv token first
- All tokens/API keys encrypted using `services/security.py`
- Use `get_token_manager()` for all encryption/decryption operations (works for any service)
- Encryption key is file-based at `/app/data/.encryption_key` (auto-generated, persists via Docker volume)
- `security.py` is service-agnostic - use it for Plex, Radarr, Sonarr, qBittorrent, etc.

### Database Models Structure

Five core models with specific relationships:

- `DuplicateSet`: Groups duplicate media items (has many `DuplicateFile`)
- `DuplicateFile`: Individual file in duplicate set (has one `DeletionHistory`)
- `DeletionHistory`: Tracks multi-stage deletion (qBittorrent → *arr → disk → Plex refresh)
- `ScoringRule`: User-defined regex patterns for scoring
- `Config`: Key-value settings store

All models use timezone-aware UTC timestamps via `datetime.now(timezone.utc)`. Enums defined as `str, enum.Enum` for JSON serialization.

### Multi-Stage Deletion Pipeline

Deletion is a transaction-like process with four stages tracked in `DeletionHistory`:

1. `deleted_from_qbit`: Remove item from qBittorrent
2. `deleted_from_arr`: Delete from Radarr/Sonarr via API
3. `deleted_from_disk`: Physical file deletion
4. `plex_refreshed`: Trigger Plex library scan

The `is_complete` property verifies all stages succeeded without errors. Implement rollback logic if any stage fails.

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
docker-compose -f docker-compose.dev.yml up

# Production build test
docker build -t deduparr:test .
docker run -dp 8655:8655 deduparr:test
```

Production uses multi-stage build: frontend → backend → nginx+supervisor runtime.

## Code Conventions

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

## Integration Points

### Plex API (`plexapi`)

- OAuth via `MyPlexPinLogin` and `MyPlexAccount`
- Server connection via `account.resource(name).connect()`
- Media objects: `Movie`, `Show`, `Episode` with nested `.media[0].parts[0]`
- Refresh libraries: `library.update()`

### *arr APIs (httpx-based clients)

**Direct httpx implementation** (migrated from PyArr):
- **RadarrClient** (`app.services.arr_client.RadarrClient`): Radarr API v3 client
- **SonarrClient** (`app.services.arr_client.SonarrClient`): Sonarr API v3/v5 client
- Both use `httpx.AsyncClient` for async HTTP requests
- Error handling via `ArrConnectionError` exception
- API keys stored in `Config` model (encrypted)
- Key methods:
  - `get_system_status()`: Get version/status info
  - `get_movie()` / `get_series()`: Retrieve media items
  - `get_root_folder()`: Get configured root folders
  - `del_movie_file()` / `del_episode_file()`: Delete files
  - `post_command()`: Execute commands (RescanMovie, RefreshSeries, etc.)
  - `update_movie()` / `update_series()`: Update media item metadata

**Usage Pattern:**
```python
from app.services.arr_client import RadarrClient, ArrConnectionError

client = RadarrClient(base_url="http://localhost:7878", api_key="xxx")
try:
    movies = await client.get_movie()
    await client.post_command("DownloadedMoviesScan", path="/movies")
except ArrConnectionError as e:
    logger.error(f"Radarr API error: {e}")
```

### qBittorrent (`qbittorrent-api`)

Not yet implemented. Will remove torrents by hash after verifying file path matches.

## Common Gotchas

1. **SQLite WAL Mode**: Applied in `init_db()` for concurrency. Don't remove these PRAGMAs.
2. **Async Session Cleanup**: Always use `async with` or `try/finally` to close sessions.
3. **Plex Media Structure**: Files are at `media.media[0].parts[0].file`, not directly on media object.
4. **Model Imports**: Import from `app.models` package (models/__init__.py), not individual files.
5. **Frontend API URL**: Uses env var `VITE_API_URL`, defaults to `http://localhost:3001` in dev.

## Phase 1 Implementation Status

**Fully Implemented ✅:**
- Database models and migrations (all 5 core models)
- Plex OAuth authentication flow with encrypted token storage
- Complete duplicate detection for movies and episodes
- Plex library scanning and media info extraction
- Scoring engine with configurable regex rules
- Multi-stage deletion pipeline with rollback support
- Complete API endpoints:
  - Setup routes (OAuth, service testing, configuration)
  - Scan routes (duplicate detection, deletion, status)
  - Config routes (library selection, settings)
  - Stats routes (dashboard, activity, deletions)
  - Scoring routes (custom rules management)
- All backend services:
  - PlexService (OAuth, library scanning, media detection)
  - RadarrService (API integration, file deletion)
  - SonarrService (API integration, episode deletion)
  - QBittorrentService (torrent management)
  - DeletionPipeline (multi-stage deletion with error handling)
  - ScoringEngine (quality-based file scoring)
  - StatsService (dashboard metrics)
  - SetupService (wizard, connection testing)
  - Security service (token encryption/decryption)
- Frontend UI components with React Query integration:
  - Dashboard with real-time statistics
  - Scan page with duplicate management and dry-run deletion
  - DefaultPageLayout component system for consistent UI
- Hardlink detection in duplicate files
- Type-safe codebase (no `any` types in TypeScript or Python)
- Comprehensive test suite (pytest with async support)

**Partially Implemented ⏳:**
- Settings page (UI exists, needs backend integration)
- Setup wizard (UI exists, needs OAuth flow refinement)

**Not Yet Implemented ❌:**
- Plex smart collections support
- Kometa integration
- Preview thumbnails from Plex
- Bulk actions (approve all, reject all)
- "Keep both" option with reason logging
- Export/import configuration
- Scheduled scans (automation)
- Auto-approve rules
- Advanced analytics
- Webhook notifications

Refer to `todo/IMPLEMENTATION_PLAN.md` for detailed roadmap and feature specifications.
