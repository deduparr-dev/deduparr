# **Deduparr** - Duplicate Management for the *arr Stack
## Implementation Plan

---

## 🎯 **Project Overview**

**Name:** Deduparr (Deduplication + *arr)

**Purpose:** A Docker-based web application that finds and manages duplicate media files across Plex, Radarr, Sonarr, and qBittorrent with a modern GUI.

**Core Philosophy:** Safe, transparent, and integrates seamlessly with the existing *arr ecosystem.

---

## 🏗️ **Architecture**

### **Technology Stack**

**Backend:**
- **Python 3.14** with FastAPI (async/await for performance)
- **SQLite** (default) or **PostgreSQL** (optional) for database
  - SQLite with WAL mode for better concurrency
  - PostgreSQL option for power users (>50k items, multi-user)
  - SQLAlchemy ORM for database abstraction (supports both)
- **APScheduler** for scheduled tasks
- **PlexAPI** for Plex integration
- **qBittorrent-API** for library management
- **httpx** for Radarr/Sonarr API clients (custom async implementation)

**Frontend:**
- **React** with TypeScript
- **TailwindCSS** for styling
- **shadcn/ui** components (modern, accessible)
- **React Query** for data fetching
- **Recharts** for statistics/graphs

**Infrastructure:**
- **Docker** + Docker Compose
- **Nginx** as reverse proxy (included in container)
- **Multi-stage builds** for optimal image size

---

## 📋 **Core Features**

### **Phase 1: MVP (Minimum Viable Product)** ✅ **COMPLETE**

#### **1.1 Duplicate Detection**
- [x] Scan Plex libraries for duplicates
- [x] Support for both Movies and TV Shows
- [x] Configurable scoring system (similar to plex_dupefinder):
  - File size
  - Video resolution (4K > 1080p > 720p > SD)
  - Video codec (HEVC/H.265 > H.264 > others)
  - Audio codec (TrueHD/DTS-MA > AC3 > AAC)
  - Bitrate
  - Source (Remux > BluRay > WEB-DL > HDTV)
- [x] Manual file path pattern scoring (regex-based)
- [x] Quick actions

#### **1.2 Review & Approval System**
- [x] **Dry-run mode by default**
- [x] Web UI showing all detected duplicates
- [x] Side-by-side comparison view:
  - File paths
  - File sizes
  - Quality metrics
  - Scores
  - ~~Preview thumbnails (from Plex)~~ (moved to Phase 2)
- [ ] Bulk actions (approve all, reject all, selective approval)
- [x] Individual delete per duplicate set
- [ ] "Keep both" option with reason logging

#### **1.3 Deletion Pipeline**
- [x] Multi-stage deletion process:
  1. **Stage 1 - Radarr/Sonarr API:** Delete file via *arr API
  2. **Stage 2 - qBittorrent API:** Remove torrent item (with file deletion)
  3. **Stage 3 - *arr Rescan:** Refresh *arr library to update state
  4. **Stage 4 - Fallback Disk Cleanup:** Direct filesystem cleanup for:
     - Manually added media files (not managed by *arr)
     - Associated files (.srt subtitles, .nfo metadata, fanart, etc.)
     - Common subdirectories (Sample, Subs, Proof, Extras)
     - Empty parent directories (recursive cleanup)
  5. **Stage 5 - Plex Refresh:** Update Plex library
- [x] Transaction-like behavior (rollback on failure)
- [x] Detailed logging for each step
- [x] Activity history/audit log
- [x] Configurable media mount permissions (`:ro` for API-only, `:rw` for full cleanup)

#### **1.4 Configuration Management**
- [x] Setup wizard on first run
- [x] Database selection (SQLite default, optional PostgreSQL)
- [x] API connection testing (Plex, Radarr, Sonarr, qBittorrent)
- [x] Library selection (which Plex libraries to scan)
- [x] Scoring rules customization
- [x] Safe mode toggles (dry-run)
- [ ] Export/import configuration

#### **1.5 Dashboard**
- [x] Statistics overview:
  - Total duplicates found
  - Space that can be reclaimed
  - Processing history
- [x] Recent activity log
- [x] Quick actions

#### **1.6 Automation** ✅ **COMPLETE**
- [x] Scheduled scans (interval-based with APScheduler)
- [x] Environment variable configuration (`ENABLE_SCHEDULED_SCANS`, `SCAN_INTERVAL_HOURS`)
- [x] Background scanning without blocking UI
- [x] Detects duplicates automatically (manual approval still required for deletion)
- [x] Configurable scan intervals (6h, 12h, 24h, 48h, weekly, etc.)
- [x] Quick actions

---

### **Phase 2: Advanced Features** 🚧 **IN PROGRESS**

#### **2.1 Enhanced UI/UX**
- [ ] Preview thumbnails from Plex
- [ ] Bulk actions (approve all, reject all, selective approval)
- [ ] "Keep both" option with reason logging
- [ ] Advanced filtering and search
- [ ] Keyboard shortcuts

#### **2.2 Smart Features**
- [ ] Auto-approve rules:
  - "Always keep highest quality"
  - "Always delete files < X GB"
  - Custom rule engine
- [ ] Plex smart collections support
- [ ] Kometa integration
- [ ] Machine learning scoring (optional)
- [ ] HDR vs SDR detection
- [ ] Audio track language detection
- [ ] Subtitle availability scoring
- [ ] Release group reputation scoring

#### **2.3 Notifications & Integrations**
- [ ] Webhook notifications (Discord, Slack, etc.)
- [ ] Email notifications
- [ ] Notifiarr integration
- [ ] Export/import configuration
- [ ] API for external integrations

#### **2.3 Enhanced Integrations**
- [ ] **Overseerr/Jellyseerr:** Update request status
- [ ] **Tautulli:** Check if file was recently watched
- [ ] **Prowlarr:** Verify if better release exists
- [ ] **Maintainerr:** Bidirectional integration

#### **2.4 Advanced UI**
- [ ] Dark/Light theme toggle
- [x] Mobile-responsive design (implemented with Tailwind)
- [ ] Filtering and sorting duplicates
- [ ] Search functionality
- [ ] Export duplicate reports (CSV, JSON)
- [ ] Preview thumbnails from Plex
- [ ] Bulk actions (approve all, reject all)
- [ ] "Keep both" option with reason logging

---

### **Phase 3: Enterprise Features**

#### **3.1 Multi-User Support**
- [ ] Role-based access control (RBAC)
- [ ] Approval workflows (require X approvals)
- [ ] User activity tracking

#### **3.2 Advanced Analytics**
- [ ] Storage trends over time
- [ ] Quality distribution charts
- [ ] Duplicate patterns analysis
- [ ] Cost savings calculator

#### **3.3 Backup & Safety**
- [ ] "Recycle bin" feature (soft delete before hard delete)
- [ ] Configurable retention period
- [ ] Backup before delete option
- [ ] Disaster recovery options

---

## 🗂️ **Project Structure**

```
deduparr/
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app
│   │   ├── api/
│   │   │   ├── routes/             # API endpoints
│   │   │   │   ├── duplicates.py
│   │   │   │   ├── config.py
│   │   │   │   ├── history.py
│   │   │   │   └── stats.py
│   │   │   └── deps.py             # Dependencies
│   │   ├── core/
│   │   │   ├── config.py           # App configuration
│   │   │   ├── database.py         # SQLite setup
│   │   │   └── scheduler.py        # APScheduler
│   │   ├── services/
│   │   │   ├── plex_service.py
│   │   │   ├── radarr_service.py
│   │   │   ├── sonarr_service.py
│   │   │   ├── qbittorrent_service.py
│   │   │   ├── duplicate_finder.py
│   │   │   ├── scoring_engine.py
│   │   │   └── deletion_pipeline.py
│   │   ├── models/
│   │   │   ├── duplicate.py
│   │   │   ├── config.py
│   │   │   └── history.py
│   │   └── utils/
│   │       ├── logger.py
│   │       └── helpers.py
│   ├── requirements.txt
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── DuplicateList.tsx
│   │   │   ├── DuplicateComparison.tsx
│   │   │   ├── Settings.tsx
│   │   │   └── History.tsx
│   │   ├── hooks/
│   │   ├── services/
│   │   │   └── api.ts
│   │   ├── types/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── config/
│   └── config.example.yml
├── README.md
└── LICENSE
```

---

## 🔄 **Workflow Example**

### **User Flow:**
1. **Setup** → User configures API connections via web UI
2. **Scan** → Clicks "Scan for Duplicates" or runs on schedule
3. **Review** → Views duplicates in comparison view
4. **Approve** → Selects which files to delete (dry-run shows what would happen)
5. **Execute** → Confirms deletion, backend processes deletion pipeline
6. **Verify** → Checks history/logs, reclaims storage

### **Backend Flow:**
```
Scan Request
    ↓
Plex API: Get all items (or from smart collection)
    ↓
Group by duplicate (same movie/episode)
    ↓
Score each version
    ↓
Identify files to keep/delete
    ↓
Present to user
    ↓
[User Approval]
    ↓
For each approved deletion:
    1. Find item in qBittorrent (by file path hash)
    2. Remove torrent
    3. Call Radarr/Sonarr delete file endpoint
    4. Verify file deleted from disk
    5. Trigger Plex library scan
    6. Log result
    ↓
Show completion summary
```

---

## 📊 **Database Schema**

### **Design Philosophy:**
- Use **SQLAlchemy ORM** for database-agnostic models
- **SQLite** as default (zero-config, optimized with WAL mode)
- **PostgreSQL** as optional upgrade path for power users

### **SQLite Optimizations:**
```sql
-- Enable WAL mode for better concurrency
PRAGMA journal_mode = WAL;
-- Faster writes, still crash-safe
PRAGMA synchronous = NORMAL;
-- 64MB cache
PRAGMA cache_size = -64000;
-- Temp tables in RAM
PRAGMA temp_store = MEMORY;
-- 256MB memory-mapped I/O
PRAGMA mmap_size = 268435456;
```

### **Schema (SQLAlchemy models):**

```sql
-- Configuration
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP
);

-- Duplicate sets found
CREATE TABLE duplicate_sets (
    id INTEGER PRIMARY KEY,
    plex_item_id TEXT,
    title TEXT,
    media_type TEXT, -- 'movie' or 'episode'
    found_at TIMESTAMP,
    status TEXT, -- 'pending', 'approved', 'rejected', 'processed'
    space_to_reclaim BIGINT,
    INDEX idx_status (status),
    INDEX idx_found_at (found_at)
);

-- Individual duplicate files
CREATE TABLE duplicate_files (
    id INTEGER PRIMARY KEY,
    set_id INTEGER,
    file_path TEXT,
    file_size BIGINT,
    score INTEGER,
    keep BOOLEAN,
    metadata JSON, -- video/audio codec, resolution, etc. (JSONB in PostgreSQL)
    FOREIGN KEY (set_id) REFERENCES duplicate_sets(id) ON DELETE CASCADE,
    INDEX idx_set_id (set_id),
    INDEX idx_file_path (file_path)
);

-- Deletion history
CREATE TABLE deletion_history (
    id INTEGER PRIMARY KEY,
    duplicate_file_id INTEGER,
    deleted_at TIMESTAMP,
    deleted_from_qbit BOOLEAN,
    deleted_from_arr BOOLEAN,
    deleted_from_disk BOOLEAN,
    error TEXT,
    FOREIGN KEY (duplicate_file_id) REFERENCES duplicate_files(id) ON DELETE CASCADE,
    INDEX idx_deleted_at (deleted_at)
);

-- Scoring rules (user-defined)
CREATE TABLE scoring_rules (
    id INTEGER PRIMARY KEY,
    rule_type TEXT, -- 'filename_pattern', 'codec', 'resolution'
    pattern TEXT,
    score_modifier INTEGER,
    enabled BOOLEAN,
    created_at TIMESTAMP,
    INDEX idx_enabled (enabled)
);
```

### **When to Use PostgreSQL:**
- Library size > 50,000 items
- Multiple concurrent scans needed
- Heavy analytics/reporting usage
- Multi-user environment
- Horizontal scaling requirements

---

## 🐳 **Docker Setup**

### **docker-compose.yml (SQLite - Default)**
```yaml
**docker-compose.dev.yml**:
```yaml
services:
  backend:
```

### **docker-compose.yml (PostgreSQL - Optional)**
```yaml
services:
  deduparr:
    image: deduparr/deduparr:latest
    container_name: deduparr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - DATABASE_TYPE=postgres
      - DATABASE_URL=postgresql://deduparr:deduparr@postgres:5432/deduparr
    volumes:
      - ./config:/config
      - /path/to/media:/media:ro
    ports:
      - 8655:8655
    depends_on:
      - postgres
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: deduparr-postgres
    environment:
      - POSTGRES_USER=deduparr
      - POSTGRES_PASSWORD=deduparr
      - POSTGRES_DB=deduparr
    volumes:
      - ./postgres-data:/var/lib/postgresql/data
    restart: unless-stopped
```

---

## 🎨 **UI Mockup Concepts**

### **Dashboard:**
- Card: "X duplicates found, Y GB can be reclaimed"
- Card: "Last scan: timestamp"
- Card: "Recent deletions: count"
- Quick action buttons
- Activity timeline

### **Duplicates View:**
- Table/Grid view toggle
- Filters: Media type, library, status
- Each row expandable to show comparison
- Bulk action bar at top

### **Comparison View:**
- Split screen showing File A vs File B
- Color-coded scores (green = keep, red = delete)
- Thumbnail previews
- Technical specs table
- Decision buttons: "Keep Left", "Keep Right", "Keep Both"

---

## 🚀 **Development Phases**

### **Phase 1 (MVP) - 4-6 weeks**
- Core duplicate detection
- Basic web UI
- Manual approval workflow
- Deletion pipeline
- Docker packaging

### **Phase 2 (Enhancement) - 3-4 weeks**
- Automation features
- Advanced scoring
- Better integrations
- Polish UI

### **Phase 3 (Optional) - Ongoing**
- Community features
- ML enhancements
- Plugin system

---

## 🤔 **Open Questions for Discussion**

1. **Kometa Integration:** Should Deduparr have a Kometa plugin/module, or just support importing Kometa collections via Plex?

2. **Scoring System:** Should we use plex_dupefinder's scoring as default, or create our own?

3. **Safety First:** Should there be a mandatory "recycle bin" period (e.g., 7 days) before permanent deletion?

4. **API-First:** Should we prioritize API endpoints for headless operation (like other *arr apps)?

5. **License:** Open source (GPL/MIT/Apache) or proprietary?

---

## 🗄️ **Database Strategy**

### **Default: SQLite (Recommended for most users)**
**Pros:**
- ✅ Zero configuration
- ✅ No extra containers
- ✅ No version upgrades needed
- ✅ Perfect for libraries up to 50,000 items
- ✅ Faster for single-user scenarios

**Optimizations:**
- WAL mode for better read concurrency
- Proper indexing on all foreign keys and search fields
- Connection pooling via SQLAlchemy
- In-memory caching for hot data

### **Optional: PostgreSQL (For power users)**
**When to use:**
- Library > 50,000 items
- Multiple concurrent scans
- Multi-user environment
- Heavy analytics workload
- Need horizontal scaling

**Implementation:**
- Configurable via `DATABASE_TYPE` environment variable
- Same SQLAlchemy models work for both
- Migration path provided for users who outgrow SQLite

---

## 💡 **Next Steps**

If you approve this plan, we can:
1. Create the initial project structure
2. Set up Docker environment
3. Build the backend API framework
4. Create a basic React frontend
5. Implement core duplicate detection logic

---

## 📝 **Notes**

- This is a living document and will be updated as development progresses
- All checkboxes represent planned features and their implementation status
- Community feedback and contributions are welcome
