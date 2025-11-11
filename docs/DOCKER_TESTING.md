# Deduparr - Docker Development & Testing Guide

## Quick Start - Test the Docker Setup

### 1. Build the Docker Image

```bash
# Navigate to the project directory
cd deduparr

# Build the image
docker build -t deduparr:test .
```

### 2. Run the Container

```bash
# Run in detached mode with port mapping
docker run -dp 8655:8655 --name deduparr-test deduparr:test
```

### 3. Access the Setup Wizard

Open your browser to: **http://127.0.0.1:8655/setup**

You should see the Deduparr setup wizard!

---

## Development Docker Setup (Simplified)

For development and testing, we'll use a simpler Docker setup that doesn't require building the full multi-stage image.

### Option 1: Backend Only (API Testing)

```bash
cd backend

# Build backend image
docker build -t deduparr-backend:dev -f Dockerfile.dev .

# Run backend
docker run -dp 3001:3001 --name deduparr-backend deduparr-backend:dev
```

Access API docs at: http://localhost:3001/docs

### Option 2: Frontend Only (UI Testing)

```bash
cd frontend

# Build frontend image
docker build -t deduparr-frontend:dev -f Dockerfile.dev .

# Run frontend
docker run -dp 3000:3000 --name deduparr-frontend deduparr-frontend:dev
```

Access UI at: http://localhost:3000

### Option 3: Full Stack with Docker Compose (Recommended)

```bash
# Start development environment (both frontend and backend with hot reload)
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f

# Stop everything
docker-compose -f docker-compose.dev.yml down

# Rebuild after changes
docker-compose -f docker-compose.dev.yml up -d --build
```

**Access Points:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001
- API Docs: http://localhost:3001/docs

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

# Build without cache (fresh build)
docker build --no-cache -t deduparr:test .
```

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

## Testing Checklist


## Production Testing Checklist

- [ ] Image builds without errors
- [ ] Container starts successfully
- [ ] Can access http://127.0.0.1:8655/setup
- [ ] Setup wizard loads

---

## Troubleshooting

**"Cannot connect to Docker daemon"**
- Ensure Docker Desktop is running
- Check: `docker --version`

**"Port already in use"**
- Stop conflicting container: `docker stop <container>`
- 
### Port Conflicts

If port 8655 is already in use:
- Or use different port: `docker run -dp 8656:8655 ...`


**"Build fails"**
- Check Dockerfile syntax
- Build without cache: `docker build --no-cache`
- Check logs for specific error

**"Container exits immediately"**
- Check logs: `docker logs deduparr-test`
- Likely an application error

---

## Next Steps

1. Test the basic Docker setup
2. Verify backend API works
3. Test frontend UI
4. Integrate with actual Plex/Radarr/Sonarr instances
5. Test duplicate detection workflow
