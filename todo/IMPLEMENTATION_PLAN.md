# **Deduparr** - Duplicate Management for the *arr Stack
## Implementation Plan

---

## 🎯 **Project Overview**

**Name:** Deduparr (Deduplication + *arr)

**Purpose:** A Docker-based web application that finds and manages duplicate media files across Plex or Jellyfin, Radarr, Sonarr, and qBittorrent with a modern GUI.

**Core Philosophy:** Safe, transparent, and integrates seamlessly with the existing *arr ecosystem.

---

## 🏗️ **Architecture**

### **Technology Stack**

**Backend:**
- **Python 3.15** with FastAPI (async/await for performance)
- **SQLite** (default) or **PostgreSQL** (optional) for database
  - SQLite with WAL mode for better concurrency
  - PostgreSQL option for power users (>50k items, multi-user)
  - SQLAlchemy ORM for database abstraction (supports both)
- **APScheduler** for scheduled tasks
- **PlexAPI** for Plex integration
- **jellyfin-apiclient-python** for Jellyfin integration
- **qBittorrent-API** for library management
- **httpx** for Radarr/Sonarr API clients (custom async implementation)

**Frontend:**
- **React** with TypeScript
- **TailwindCSS** for styling
- **shadcn/ui** components (modern, accessible)
- **React Query** for data fetching
- **Recharts** for statistics/graphs (a dependency; no charts yet)

**Infrastructure:**
- **Docker** + Docker Compose
- **Nginx** as reverse proxy (included in container)
- **Multi-stage builds** for optimal image size

---

## 📋 **Core Features**

### **Phase 1: MVP (Minimum Viable Product)** ✅ **MOSTLY COMPLETE**

#### **1.1 Duplicate Detection**
- [x] Scan Plex and Jellyfin libraries for duplicates
- [x] Support for both Movies and TV Shows
- [x] Scoring system (similar to plex_dupefinder), with fixed weights for:
  - File size
  - Video resolution (4K > 1080p > 720p > SD)
  - Video codec (HEVC/H.265 > H.264 > others)
  - Audio codec (TrueHD/DTS-MA > DTS > AC3 = AAC)
  - ~~Bitrate~~ (stored, not scored)
  - Source (Remux > BluRay > WEB-DL > HDTV)
- [x] Manual file path pattern scoring (regex-based)
- [x] Quick actions

#### **1.2 Review & Approval System**
- [x] **Dry-run mode by default**
- [x] Web UI showing detected duplicates (the newest 100 sets; no paging yet)
- [x] Side-by-side comparison view:
  - File paths
  - File sizes
  - Quality metrics
  - Scores
  - ~~Preview thumbnails (from Plex)~~ (moved to Phase 2)
- [x] Bulk deletion ("Delete All" on the Scan page, for every pending set)
- [ ] Bulk actions (approve all, reject all, selective approval)
- [x] Individual delete per duplicate set
- [ ] "Keep both" option with reason logging

#### **1.3 Deletion Pipeline**
- [x] Multi-stage deletion process (stages 1-4 run for each file, in this order; stage 5 runs once per set, after all of its files):
  1. **Stage 1 - Radarr/Sonarr API:** Delete file via *arr API
  2. **Stage 2 - qBittorrent API:** Remove torrent item (with file deletion)
  3. **Stage 3 - Disk Cleanup:** Delete the file if it is still on disk, then clean up:
     - Manually added media files (not managed by *arr)
     - Associated files (.srt subtitles, .nfo metadata, fanart, etc.)
     - Common subdirectories (Sample, Subs, Proof, Extras)
     - Empty parent directories (recursive cleanup)
  4. **Stage 4 - Media Server Refresh:** Refresh the item on Plex or Jellyfin
  5. **Stage 5 - *arr Rescan:** Have Radarr/Sonarr import the kept file
- [ ] Transaction-like behavior (rollback on failure): nothing is rolled back yet; a file that could not be deleted leaves its set pending, so the deletion can be retried
- [x] Detailed logging for each step
- [x] Activity history/audit log
- [x] Configurable media mount permissions (`:ro` for API-only, `:rw` for full cleanup)

#### **1.4 Configuration Management**
- [x] Setup wizard on first run
- [x] Database selection (SQLite default, optional PostgreSQL)
- [x] API connection testing (Plex, Jellyfin, Radarr, Sonarr, qBittorrent)
- [x] Library selection (which Plex and Jellyfin libraries to scan)
- [x] Scoring rules customization
- [x] Safe mode toggles (dry-run)
- [x] Export/import configuration (API only: `GET /api/config/export/all`, `POST /api/config/import/all`)

#### **1.5 Dashboard**
- [x] Statistics overview:
  - Total duplicates found
  - Space that can be reclaimed
  - Processing history
- [x] Recent activity log
- [ ] Quick actions

#### **1.6 Automation** ✅ **COMPLETE**
- [x] Scheduled scans (daily or interval, with APScheduler)
- [x] Schedule stored from Settings, with environment variables until it is saved
- [x] Background scanning without blocking UI
- [x] Detects duplicates automatically
- [x] Optional scheduled deletion: deletes the extra copies in the pending sets 30 minutes after each scheduled scan
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
- [x] Email notifications (after scheduled scans and scheduled deletions)
- [ ] Notifiarr integration
- [x] Export/import configuration (API only)
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

See the [project structure in CONTRIBUTING.md](../CONTRIBUTING.md#project-structure).

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
Plex or Jellyfin: items that have more than one file
    ↓
Group by duplicate (same movie/episode)
    ↓
Score each version
    ↓
Identify files to keep/delete
    ↓
Present to user
    ↓
[User Approval, or scheduled deletion]
    ↓
For each file to delete:
    1. Call Radarr/Sonarr delete file endpoint
    2. Remove its torrent from qBittorrent (found by path, or by name and size)
    3. Delete the file from disk if still there, and what it leaves behind
    4. Refresh the item on the media server
    5. Log result
    ↓
Once per set: Radarr/Sonarr rescan, importing the kept file
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

The tables are defined by the models in [backend/app/models](../backend/app/models/), and created by the Alembic migrations in [backend/alembic/versions](../backend/alembic/versions/).

### **When to Use PostgreSQL:**
- Library size > 50,000 items
- Multiple concurrent scans needed
- Heavy analytics/reporting usage
- Multi-user environment
- Horizontal scaling requirements

---

## 🐳 **Docker Setup**

Deployment, PostgreSQL included, is in [DEPLOYMENT.md](../DEPLOYMENT.md); the development stack runs as Podman quadlets, in [quadlet/README.md](../quadlet/README.md).

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

5. **License:** Decided: MIT (see [LICENSE](../LICENSE)).

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
- No migration path from SQLite yet: the configuration export/import carries settings and scoring rules over, not duplicate sets or deletion history

---

## 💡 **Next Steps**

The original next steps (project structure, Docker environment, backend API, React frontend, core duplicate detection) are done; what is left is unchecked above.

---

## 📝 **Notes**

- This is a living document and will be updated as development progresses
- All checkboxes represent planned features and their implementation status
- Community feedback and contributions are welcome
