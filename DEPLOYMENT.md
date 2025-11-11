# Deduparr Production Deployment Guide

Welcome to **Deduparr**! Follow these steps to deploy in production.

---

## 📋 Prerequisites

Before you begin, ensure you have:

- ✅ Docker and Docker Compose installed
- ✅ Plex Media Server running
- ✅ Radarr and/or Sonarr configured
- ✅ qBittorrent with Web UI enabled
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
    image: ghcr.io/deduparr-dev/deduparr:latest
    container_name: deduparr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York  # Change to your timezone
      - DATABASE_TYPE=sqlite
      # Optional: Enable scheduled scans
      - ENABLE_SCHEDULED_SCANS=false  # Set to 'true' to enable
      - SCAN_INTERVAL_HOURS=24        # Scan every 24 hours
    volumes:
      - ./config:/config
      - ./data:/app/data
      - /path/to/media:/media:rw  # See table below for :ro vs :rw
    ports:
      - 8655:8655
    restart: unless-stopped
```

### Step 2: Configure Environment

1. Copy the environment example:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your settings:
   ```bash
   nano .env
   ```

   Update these values:
   - `PUID` and `PGID` - Run `id` to find your user/group IDs
   - `TZ` - Your timezone (e.g., `America/New_York`)
   - `MEDIA_PATH` - Path to your media files

### Step 3: Start Deduparr

```bash
docker-compose up -d
```

### Step 4: Access the Setup Wizard

Open your browser to: **http://127.0.0.1:8655/setup**

You'll see the Setup Wizard to configure:
1. ✅ Plex
2. ✅ Radarr API connection
3. ✅ Sonarr API connection
4. ✅ qBittorrent credentials

---

## 🔧 Advanced Configuration

### Using PostgreSQL Instead of SQLite

For better performance with large libraries, use PostgreSQL:

1. Uncomment the `postgres` service in `docker-compose.yml`
2. Update `.env`:
   ```env
   DATABASE_TYPE=postgres
   DATABASE_URL=postgresql+asyncpg://deduparr:deduparr@postgres:5432/deduparr
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
| `./data:/app/data` | Encryption keys | Read/Write | Yes |
| `/path/to/media:/media` | Media files scan & deletion | Read-Only or Read/Write | Yes |

### Media Mount Permissions: `:ro` vs `:rw`

**Choose based on your deletion strategy:**

| Mode | When to Use | What Works |
|------|-------------|------------|
| `:ro` | API-only deletion via Radarr/Sonarr/qBittorrent | Stages 1-3, 5 (API deletion only) |
| `:rw` | Complete cleanup including associated files ⭐ | All stages 1-5 (full cleanup) |

#### Deletion Pipeline (5 Stages)

1. **Radarr/Sonarr API** - Deletes file via *arr API
2. **qBittorrent API** - Removes torrent
3. ***arr Rescan** - Updates library state
4. **Fallback Disk Cleanup** - Requires `:rw` for:
   - Manually added files (not in *arr)
   - Associated files (`.srt`, `.nfo`, fanart)
   - Subdirectories (`Sample/`, `Subs/`, `Proof/`, `Extras/`)
   - Empty directories
5. **Plex Refresh** - Updates Plex library

**Note:** Stage 4 only runs as fallback for files missed by API deletion. All deletions require manual approval (dry-run by default).

### Scheduled Automated Scans

Enable automatic duplicate detection:

```yaml
environment:
  - ENABLE_SCHEDULED_SCANS=true
  - SCAN_INTERVAL_HOURS=24
```

**Options:**
- `ENABLE_SCHEDULED_SCANS`: `true`/`false` (default: `false`)
- `SCAN_INTERVAL_HOURS`: Scan frequency - `6`, `12`, `24`, `48`, `168` (weekly)

Scans detect duplicates in background. Deletions still require manual approval via UI.

---

## 🔐 Security Best Practices

1. **File Permissions:** Deduparr runs as user `deduparr` (UID 1000)
2. **Encryption:** All API tokens/keys are encrypted at rest
3. **OAuth:** Plex uses OAuth - never stores your password
4. **Network:** Consider running behind a reverse proxy with HTTPS
5. **Backups:** Regularly backup `/config` directory

---

## 🐛 Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs -f deduparr

# Check permissions
ls -la config/ data/

# Fix permissions
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
- 🐛 [Report Issues](https://github.com/deduparr-dev/deduparr/issues)
- 💬 [Discussions](https://github.com/deduparr-dev/deduparr/discussions)

---

## 🔄 Updating

```bash
# Pull latest image
docker-compose pull

# Recreate container
docker-compose up -d

# View changelog
docker exec deduparr cat /app/CHANGELOG.md
```

---

**Ready to reclaim your storage space? Start scanning! 🚀**
