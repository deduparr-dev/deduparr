# Deduparr Agent Instructions

Deduparr finds duplicate movies and episodes on Plex and Jellyfin, scores them by
quality, and removes the lower-quality copies across Radarr, Sonarr and
qBittorrent. It deletes real files, so everything here serves one question: what
does it really do to a real library?

## Documentation Map

| Read | For |
|---|---|
| This file | How we work, and the rules for every change |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it is built: media servers, Plex sign-in, the data model, the deletion pipeline, what the real services do |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setting up, commit messages, the pull request checklist |
| [quadlet/README.md](quadlet/README.md) | The Podman stack |
| [docs/RELEASING.md](docs/RELEASING.md) | Cutting a version, and its notes |

## How We Work

Be critical. Base everything on facts: code you read, a command you ran, the API documentation. Do not guess.

1. **Check the entire codebase first.** Stay consistent with what is there, and reuse shared components, modals, helpers and services wherever it makes sense. We build a deduplication app: duplicate code is a defect.
2. **Implement it correctly**, following this file and [ARCHITECTURE.md](ARCHITECTURE.md).
3. **Review your own change.** Look for bugs, and list what you find and what could improve at the end, for discussion, rather than fixing beyond the task.
4. **Test against the real stack, as a user would**: see [The Real Stack](#the-real-stack). Every server and service with real calls and real logs, the backend API directly, and every flow through the frontend with Playwright. Conclusions are reproducible defects in the current code, not speculative edge cases.
5. **Tight, trimmed and minimal, but best practice and functional.** No more code than it needs. This one matters most.
6. **Understand before changing.** Read whole files, and check `git blame`, old pull requests and issues for how the code is supposed to work.
7. **Subagents**, if you use any, run on the most capable model: Opus in Claude Code.
8. **The full suite is heavy.** Run the tests you touch while working, and `scripts/test.sh` once, before committing a pull request.
9. **Only the tests and comments that are needed.** No debug output or clutter in the code.
10. **No AI attribution** in commits, pull requests or code. `.claude/settings.json` turns it off for Claude Code.
11. **No summary or report documents** in the repository: the reasoning goes in commit messages and pull requests.
12. **Reference project**: [maintainerr](https://github.com/Maintainerr/Maintainerr) solves the same media server and *arr problems. Look at how it does things; do not copy it.

### Changing Behaviour

1. **Reproduce it first**, on the real stack, and keep what you saw.
2. **Trace the whole flow** the change touches, across the frontend, the API, the services and the external APIs, including their documentation.
3. **Say what must stay as it is**: a deletion guard, a security contract, a neighbouring flow.
4. **Make the smallest complete fix.** Report what you find along the way separately.
5. **Verify what a user would observe.** A 200 and a counter are what Deduparr claims, not what happened: check the files on disk, what each service now holds, the logs and the screen.
6. **Clean up**: restore the fixtures, stop what you started. Evidence stays out of the repository and holds no credentials.
7. **Finish what was asked** without asking again for what is already authorized.

## The Real Stack

Verification runs against real services, not stand-ins. A stand-in answered `{}` where Radarr answers a delete with nothing at all, and so hid that deleting any tracked file failed; another sent episode ids real Sonarr never sends. Those are the defects this rule exists for.

On the maintainers' dev box a lab holds the real stack, reachable by name from that box only. Use the names: the addresses change whenever a service restarts.

| Service | From the box |
|---|---|
| Plex, server `deduparr-plex` | `http://deduparr-plex:32400` |
| Jellyfin | `http://deduparr-jellyfin:8096` |
| Radarr | `http://deduparr-radarr:7878` |
| Sonarr | `http://deduparr-sonarr:8989` |
| qBittorrent | `http://deduparr-qbittorrent:8654` |

- **Credentials** are in `/lab/creds.env` (`set -a; . /lab/creds.env; set +a`). They, and the name and email of the lab's Plex account, never appear in a commit, pull request, issue, comment or screenshot.
- **Run Deduparr from the checkout** ([Local Development](#local-development)) with `MEDIA_DIR=/media`, on ports of its own: a dev stack may already be running. `/media` is the path every service reports, so every deletion stage runs for real. The lab's base fixtures and the way to sign in to Plex without a browser are in the box's private instructions (`~/.claude/CLAUDE.md`).
- **Tests delete for real.** After each one, `python3 /lab/seed.py --restore` (about 30 s) puts back the files, the torrents and the *arr tracking and rescans both servers; `--verify` only checks. Restore removes anything else in `/media`, so keep nothing else there.
- **Leave the services' settings alone**, and never add an indexer or download anything: production defaults plus a user's setup is what makes the results hold in production. A new fixture changes the base, which is the owner's call.
- **Only use the server `deduparr-plex`**: the account sees others that are not part of the lab.
- **Drive the frontend with Playwright**, using the browser already in `/ms-playwright`: it is shared, so never install into or change it.
- **For each deleting test**, compare before and after: the files with their link counts, what Radarr and Sonarr track, the torrents, and the items on both servers.

Without the lab, run your own real servers. If a service cannot be reached, say in the pull request what was not verified, and do not present a stand-in's pass as verification.

## Writing Tests

A test records approved behaviour and guards it. What earns one: a data-safety guard, a security contract, a defect that was fixed. Not worth one: constants, log text, a pass-through.

- **One test for one behaviour**, on the production code path. A guard's test has to fail without the guard. Never change a test just to make it pass: fix the code, unless the behaviour changed on purpose.
- **Backend** tests use in-memory SQLite and pytest-asyncio, mock only what lies outside the process, and open no real network or timers:

  ```python
  @pytest.mark.asyncio
  async def test_function(test_db):
      ...
  ```

  Test file handling on a real temporary directory. Mocks have hidden real defects here: a patched-out pipeline hid that scheduled deletion deleted nothing, and an `os.path.exists` that always answered True hid the disk stage deleting other titles' files.
- **The end-to-end suite** (`frontend/e2e/`) is what lets CI run without servers. It runs against stand-ins for Jellyfin, Radarr, Sonarr and qBittorrent (`fake-jellyfin/`, `fake-services/`), which keep a real service's answers, quirks included: when the real one differs, correct the stand-in. Passing it verifies no integration. Its database is never reset, so each spec works on a title unique to its run (`uniqueTitle`). Outside CI, Playwright reuses whatever already listens on its ports. Select by `data-testid` and assert `toHaveCount(1)`; a toast's text appears twice, in the toast and in its live announcer. The `/api/scan/dev/*` endpoints that seed duplicate sets exist only with `LOG_LEVEL=DEBUG`, which the suite's backend sets.

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
6. **Tests**: every feature and fix comes with what [Writing Tests](#writing-tests) says it needs.
7. **Thorough Analysis**: Read entire files, don't skip sections. Understand full context before making changes.
8. **Debugging Protocol**:
   - Document findings comprehensively
   - Create implementation plans with phased fixes
   - Verify logic matches intended behavior 100%
   - Compare actual implementation against documented requirements
9. **Issue Reporting**: List discovered issues at end of analysis for discussion - don't auto-fix without approval.
10. **Self-Sufficiency**: Use the tools you have to search and read the code instead of asking users to run commands.

**External API Documentation:**
- **Radarr API**: https://radarr.video/docs/api/
- **Sonarr API**: https://sonarr.tv/docs/api/
- **Plex API**: https://python-plexapi.readthedocs.io/ (using plexapi Python library)
- **Jellyfin API**: https://api.jellyfin.org/ (using the jellyfin-apiclient-python library)
- **qBittorrent API**: https://github.com/rmartin16/qbittorrent-api (using qbittorrent-api Python library)

**IMPORTANT**: When changing or adding functionality related to these services, **always consult their API documentation** to ensure correct usage, parameter validation, and error handling.

## React 19 Best Practices

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

## Development Workflows

### Running Tests

```bash
cd backend
pytest                          # Run all tests
pytest --cov=app tests/         # With coverage
pytest tests/test_plex_service.py -v  # Specific test file
```

What to test, and how: [Writing Tests](#writing-tests).

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

### Docker Rebuild

**ALWAYS** use the rebuild script for rebuilding Docker containers (never use manual docker commands):

```bash
# Production rebuild (default)
bash scripts/rebuild-docker.sh --prod

# Development rebuild
bash scripts/rebuild-docker.sh --dev
```

What each mode stops, deletes and rebuilds is in `scripts/rebuild-docker.sh` (`--dev` drives the Podman quadlets).

**Never** manually run `docker build`, `docker compose build`, or similar commands. The rebuild script ensures proper cleanup and consistency.

### Local Development

```bash
# Backend (port 3001)
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///$PWD/deduparr.db"  # the default, /config/deduparr.db, needs root
python -m app.main

# Frontend (port 3000)
cd frontend
npm install
npm run dev
```

Backend runs via `uvicorn` with hot reload. The frontend calls `/api` on its own origin: nginx proxies it in production, and Vite's dev and preview servers proxy it to `VITE_PROXY_TARGET`, by default `http://127.0.0.1:3001`.

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
- A description is for someone who saw none of the work, in the order
  [the template](.github/pull_request_template.md) asks: what changes for the user,
  a table of what they see before and after when they can see it, the cause and the
  design with their trade-offs, and last what was verified, on what, and what was not.
  A small change gets a small description.
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
  `arr`, `scan`, `deletion`, `notifications`, `download`, `shared`, with
  `scheduler.py`, `setup_service.py`, `stats_service.py` and `system_service.py`
  still at its top level. A file is named for its role (`pipeline.py`,
  `runner.py`), and for its thing and role where several share one
  (`plex_adapter.py`, `radarr_service.py`).
- Every frontend API call goes through `src/services/api.ts`, and the stored
  configuration is cached under `["config"]` (`["config", "deep-scan"]` for
  deep scan), except the scheduler settings, under `["schedulerConfig"]`.
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

## Common Gotchas

1. **SQLite WAL Mode**: Applied in `init_db()` for concurrency. Don't remove these PRAGMAs.
2. **Async Session Cleanup**: Always use `async with` or `try/finally` to close sessions.
3. **Plex Media Structure**: Files are at `media.media[0].parts[0].file`, not directly on media object.
4. **Model Imports**: Import from `app.models` package (models/__init__.py), not individual files.
5. **Frontend API URL**: relative `/api` everywhere, proxied by nginx in production and by Vite (`VITE_PROXY_TARGET`) in development.
6. **Processed sets are history**: when an item is duplicated again, the scan opens a new pending set.
7. **Deep scan only logs**: it reports duplicates the media server does not list, and creates no sets from them.
8. **Deduparr sees media at the media server's paths**: the scan probes each file at exactly the path the media server reports (`media_server/file_probe.py`) and skips a group with a file it cannot find; only deletion also looks under `/media`. Check both before judging advice about mounts or paths.

## Status and Roadmap

What each version shipped is in [docs/releases/](docs/releases/); the roadmap is in
`todo/IMPLEMENTATION_PLAN.md`.
