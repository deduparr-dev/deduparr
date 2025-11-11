# Deduparr - Docker Development & Testing Guide

## Quick Start - Production Build

**ALWAYS** use the rebuild script for building Docker containers:

```bash
# Production rebuild (default)
bash scripts/rebuild-docker.sh --prod
```

This script handles:
1. Port cleanup (stops containers using port 8655)
2. Docker compose down
3. Database and encryption key removal
4. Docker system prune
5. Image rebuild (no cache)
6. Container startup

**Access the Setup Wizard:** http://127.0.0.1:8655/setup

---

## Development Docker Setup

For development with hot reload, use the development rebuild script:

```bash
# Development rebuild
bash scripts/rebuild-docker.sh --dev
```

This script handles:
1. Port cleanup (stops containers using ports 3000 and 3001)
2. Docker compose down
3. Database and encryption key removal
4. Docker system prune
5. Image rebuild (no cache) for both frontend and backend
6. Container startup with hot reload

**Access Points:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001
- API Docs: http://localhost:3001/docs

### Development Without Rebuild

If you only need to start/stop without rebuilding:

```bash
# Start development environment
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f

# Stop everything
docker-compose -f docker-compose.dev.yml down
```

### Production Without Rebuild

If you only need to start/stop without rebuilding:

```bash
# Start production environment
docker-compose up -d

# View logs
docker-compose logs -f

# Stop everything
docker-compose down
```

---

## Useful Docker Commands

### Container Management

```bash
# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# Stop a container
docker stop deduparr-test

# Start a stopped container
docker start deduparr-test

# Remove a container
docker rm deduparr-test

# View container logs
docker logs deduparr-test

# Follow logs in real-time
docker logs -f deduparr-test

# Execute command in running container
docker exec -it deduparr-test /bin/bash
```

### Image Management

```bash
# List images
docker images

# Remove an image
docker rmi deduparr:test

# Remove unused images
docker image prune
```

**Note:** For rebuilding images, always use the rebuild script instead of manual `docker build` commands:
- Production: `bash scripts/rebuild-docker.sh --prod`
- Development: `bash scripts/rebuild-docker.sh --dev`

### Cleanup

```bash
# Stop and remove all Deduparr containers
docker stop deduparr-test && docker rm deduparr-test

# Remove all stopped containers
docker container prune

# Remove all unused images
docker image prune -a

# Remove everything (containers, images, volumes, networks)
docker system prune -a --volumes
```

---

## VS Code Docker Extension

The tutorial recommends using the **Docker extension for VS Code**:

1. Install: Search "Docker" in VS Code extensions
2. View containers: Click Docker icon in sidebar
3. Right-click containers to:
   - Start/Stop
   - View logs
   - Open in browser
   - Remove
   - Attach shell

---

## Production Testing Checklist

- [ ] Run `bash scripts/rebuild-docker.sh --prod`
- [ ] Image builds without errors
- [ ] Container starts successfully
- [ ] Can access http://127.0.0.1:8655/setup
- [ ] Setup wizard loads

## Development Testing Checklist

- [ ] Run `bash scripts/rebuild-docker.sh --dev`
- [ ] Both frontend and backend containers start
- [ ] Frontend accessible at http://localhost:3000
- [ ] Backend API accessible at http://localhost:3001
- [ ] API docs load at http://localhost:3001/docs
- [ ] Hot reload works when making code changes

---

## Troubleshooting

**"Cannot connect to Docker daemon"**
- Ensure Docker Desktop is running
- Check: `docker --version`

**"Port already in use"**
- The rebuild script automatically stops containers using the relevant ports
- For manual cleanup: `docker stop <container>`
- Or use different port in docker-compose.yml

**"Build fails"**
- Check Docker logs for specific errors
- The rebuild script uses `--no-cache` to ensure fresh builds
- Verify all dependencies are available

**"Container exits immediately"**
- Check logs: `docker compose logs` (prod) or `docker compose -f docker-compose.dev.yml logs` (dev)
- Likely an application error in the logs

---

## Next Steps

1. Test the basic Docker setup
2. Verify backend API works
3. Test frontend UI
4. Integrate with actual Plex/Radarr/Sonarr instances
5. Test duplicate detection workflow
