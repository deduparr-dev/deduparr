# Deduparr Production Deployment Guide

Welcome to **Deduparr**! Follow these steps to deploy in production.

---

## 📋 Prerequisites

Before you begin, ensure you have:

- ✅ Docker and Docker Compose installed
- ✅ Plex Media Server or Jellyfin (either, or both) running
- ✅ Radarr and/or Sonarr configured (optional)
- ✅ qBittorrent with Web UI enabled (optional)
- ✅ At least 500MB of disk space for the application

---

## 🚀 Quick Start

### Step 1: Create Docker Compose File

Create a directory for Deduparr:

```bash
mkdir -p ~/deduparr
cd ~/deduparr
```

Create `docker-compose.yml`:

```yaml
services:
  deduparr:
    image: ghcr.io/deduparr-dev/deduparr:latest  # Use 'latest' for stable releases, 'dev' for latest features
    container_name: deduparr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York  # Change to your timezone
      - DATABASE_TYPE=sqlite
      # Optional: Enable scheduled scans
      - ENABLE_SCHEDULED_SCANS=false  # Set to 'true' to enable
      - SCAN_INTERVAL_HOURS=24        # Only with SCAN_SCHEDULE_MODE=interval (default: daily at 02:00)
    volumes:
      - ./config:/config
      - ./data:/app/data
      - /path/to/media:/path/in/media/server:rw  # The paths your media server reports; see table below for :ro vs :rw
    ports:
      - 8655:8655
    restart: unless-stopped
```

### Step 2: Configure Environment

Edit these values in `docker-compose.yml`:
- `PUID` and `PGID` - Run `id` to find your user/group IDs
- `TZ` - Your timezone (e.g., `America/New_York`)
- The media volume - Your media files, mounted at the same paths your media server reports (see the table below)

### Step 3: Start Deduparr

```bash
docker-compose up -d
```

### Step 4: Access the Setup Wizard

Open your browser to: **http://127.0.0.1:8655/setup**

You'll see the Setup Wizard to configure:
1. ✅ Media server: Plex (OAuth sign-in), Jellyfin (URL and API key), or both
2. ✅ Libraries to scan
3. ✅ Radarr, Sonarr and qBittorrent connections (optional)

---

## 🔧 Advanced Configuration

### Docker Image Tags

Deduparr provides multiple Docker image tags for different deployment scenarios:

| Tag | Description | Use Case | Updates |
|-----|-------------|----------|---------|
| `latest` | Latest stable release | **Production** (recommended) | Only on version tag releases (v0.1.2, etc.) |
| `0.1.2`, `0.1` | Specific versions (semver) | Production (pinned) | `0.1.2` never (immutable); `0.1` on each `0.1.x` release |
| `dev` | Development branch | Testing latest features | Every push to `develop`, and nightly (midnight UTC) |
| `sha-<commit>` | Specific commit SHA from `develop` | Testing/debugging dev builds | Never (immutable) |

**Recommendations:**
- **Production:** Use `latest` for automatic updates or pin to specific version like `0.1.2`
- **Testing:** Use `dev` to test upcoming features before release
- **Debugging:** Use `sha-*` tags only when troubleshooting specific develop commits

**Examples:**

```yaml
# Production (stable, recommended)
image: ghcr.io/deduparr-dev/deduparr:latest

# Specific version (pinned)
image: ghcr.io/deduparr-dev/deduparr:0.1.2

# Latest development features
image: ghcr.io/deduparr-dev/deduparr:dev

# Specific commit for testing
image: ghcr.io/deduparr-dev/deduparr:sha-d94e262
```

### Using PostgreSQL Instead of SQLite

For better performance with large libraries, use PostgreSQL:

1. Add a `postgres` service to `docker-compose.yml` (the repository's [docker-compose.yml](docker-compose.yml) has one, commented out)
2. Set these under `environment:` of the `deduparr` service:
   ```yaml
   - DATABASE_TYPE=postgres
   - DATABASE_URL=postgresql+asyncpg://deduparr:deduparr@postgres:5432/deduparr
   ```
3. Restart: `docker-compose up -d`

### Reverse Proxy Setup (Nginx/Traefik)

**Example Nginx config:**

```nginx
server {
    listen 80;
    server_name deduparr.yourdomain.com;

    location / {
        proxy_pass http://localhost:8655;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Example Traefik labels:**

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.deduparr.rule=Host(`deduparr.example.com`)"
  - "traefik.http.services.deduparr.loadbalancer.server.port=8655"
```

---

## 📊 Volume Mounts Explained

| Path | Purpose | Permission | Required |
|------|---------|------------|----------|
| `./config:/config` | Database & settings | Read/Write | Yes |
| `./data:/app/data` | The key stored secrets are signed with | Read/Write | Yes |
| `/path/to/media:/path/in/media/server` | Media files scan & deletion, at the same paths your media server reports | Read-Only or Read/Write | Yes |

### Media Mount Permissions: `:ro` vs `:rw`

**Choose based on your deletion strategy:**

| Mode | When to Use | What Works |
|------|-------------|------------|
| `:ro` | API-only deletion via Radarr/Sonarr/qBittorrent | Stages 1, 2, 4 and 5 (API deletion only) |
| `:rw` | Complete cleanup including associated files ⭐ | All stages 1-5 (full cleanup) |

#### Deletion Pipeline (5 Stages)

Each file to delete goes through stages 1-4, in this order; stage 5 runs once per set, after all of its files.

1. **Radarr/Sonarr API** - Deletes file via *arr API
2. **qBittorrent API** - Removes torrent
3. **Disk Cleanup** - Deletes the file if it is still on disk; requires `:rw` for:
   - Manually added files (not in *arr)
   - Associated files (`.srt`, `.nfo`, fanart)
   - Subdirectories (`Sample/`, `Subs/`, `Proof/`, `Extras/`) once no other video shares the folder
   - Empty directories, up to (never including) the library folder
4. **Media Server Refresh** - Updates Plex or Jellyfin
5. ***arr Rescan** - Has Radarr/Sonarr import the kept file

**Note:** Stage 3 runs for every file: it deletes the file if an earlier stage left it, then what it leaves behind. Deletions require manual approval (dry-run by default), except scheduled deletion: when enabled in Settings, it deletes the pending sets 30 minutes after each scheduled scan.

### When the Media Server and Radarr/Sonarr See Different Paths

Deduparr matches the files your media server (Plex or Jellyfin) reports with the movies and episodes Radarr and Sonarr track by comparing their paths. If the containers mount the same library under different paths (for example `/movies` in Plex and `/data/movies` in Radarr), nothing matches: Deduparr cannot tell which files Radarr/Sonarr track, so the *arr quality profile ranking falls back to Deduparr's own score, and files are removed as if the *arr did not know them.

Fix it in **Settings → Radarr** (and **Sonarr**) under **Path mappings**. Write one mapping per line, as `path in the *arr=path in the media server`:

```
/data/movies=/movies
/data/cartoons=/cartoons
```

A mapping applies to a whole directory, and the most specific one wins. To drop a common prefix from every path, map it to the root: `/data=/`. Paths exchanged with Radarr/Sonarr are translated in both directions, so nothing changes in Radarr, Sonarr or the media server. Leave the field empty when they all see the same paths. A path no mapping covers is sent unchanged, which suits a folder both see at the same path. When the copy Deduparr keeps is in another folder than the movie or series, Deduparr points the movie or series there only if a mapping covers that folder or one of the *arr's root folders holds it; otherwise it changes nothing in the *arr and says why.

These mappings do not apply to Deduparr's own media mount: mount the media at the same paths the media server reports, as above. The scan looks for each file at exactly the path the media server reports and skips a duplicate whose file it cannot find; deletion also tries the end of that path under `/media`, of the size the server reported (`/movies/Film/Film.mkv` as `/media/movies/Film/Film.mkv` or `/media/Film/Film.mkv`).

To check it, start a scan and run a dry-run deletion: the log must say `Found movie '...' (ID: ...) in Radarr`, not `Movie not tracked in Radarr (orphaned/old file)`.

### Scheduled Automated Scans

Enable automatic duplicate detection:

```yaml
environment:
  - ENABLE_SCHEDULED_SCANS=true
  - SCAN_SCHEDULE_MODE=interval
  - SCAN_INTERVAL_HOURS=24
```

**Options:**
- `ENABLE_SCHEDULED_SCANS`: `true`/`false` (default: `false`)
- `SCAN_SCHEDULE_MODE`: `daily` or `interval` (default: `daily`)
- `SCHEDULED_SCAN_TIME`: `HH:MM` - The daily scan, or the first one in interval mode (default: `02:00`)
- `SCAN_INTERVAL_HOURS`: Hours between scans in interval mode, `1` to `168` (default: `24`)

Scans detect duplicates in background. Deletions still require manual approval via UI, unless scheduled deletion is enabled in Settings: it then deletes the pending sets 30 minutes after each scheduled scan.

---

## 🔐 Security Best Practices

1. **File Permissions:** The API runs as user `deduparr`, with the UID/GID set by `PUID`/`PGID` (default 1000); supervisord and the nginx master process run as root
2. **Secrets:** API tokens/keys are stored signed, not encrypted: anyone who can reach the API or read the database can read them
3. **OAuth:** Plex uses OAuth - never stores your password
4. **Network:** Consider running behind a reverse proxy with HTTPS
5. **Backups:** Regularly backup the `/config` and `/app/data` directories (the database, and the key stored secrets are signed with)

---

## 🐛 Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs -f deduparr

# Check permissions
ls -la config/ data/

# Fix permissions (your PUID:PGID)
sudo chown -R 1000:1000 config/ data/
```

### Can't access Web UI

```bash
# Verify container is running
docker ps | grep deduparr

# Check port isn't in use
netstat -tuln | grep 8655

# Test from inside container
docker exec deduparr curl http://localhost:8655/health
```

### Database errors

```bash
# Reset database (WARNING: Deletes all data!)
rm -f config/deduparr.db
docker-compose restart
```

### Plex connection fails

- Ensure Plex is accessible from the Docker network
- Check firewall rules
- Verify Plex Server is running on the expected address

---

## 📚 Additional Resources

- [API Documentation](./docs/API_USAGE_EXAMPLES.md)
- [Docker Testing Guide](./docs/DOCKER_TESTING.md)
- [Implementation Roadmap](./todo/IMPLEMENTATION_PLAN.md)
- [Contributing Guidelines](./CONTRIBUTING.md)

---

## 🆘 Getting Help

- 📖 [Documentation](./docs/)
- 🐛 [Report Issues or Ask Questions](https://github.com/deduparr-dev/deduparr/issues)

---

## 🔄 Updating

```bash
# Pull latest image
docker-compose pull

# Recreate container
docker-compose up -d

# Release notes: https://github.com/deduparr-dev/deduparr/releases
```

---

**Ready to reclaim your storage space? Start scanning! 🚀**
