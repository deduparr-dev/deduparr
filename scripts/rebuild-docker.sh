#!/bin/bash
set -e

# Parse arguments
MODE="prod"
if [ "$1" == "--dev" ]; then
    MODE="dev"
elif [ "$1" == "--prod" ] || [ -z "$1" ]; then
    MODE="prod"
    COMPOSE_FILE="docker-compose.yml"
    IMAGE_TAG="ghcr.io/deduparr-dev/deduparr:latest"
else
    echo "❌ Invalid argument. Use --dev or --prod (default)"
    exit 1
fi

# Change to project directory
cd /workspaces/deduparr

echo "🔄 Starting rebuild process (${MODE} mode)..."
echo ""

if [ "$MODE" == "dev" ]; then
    # Development runs under Podman quadlets (see quadlet/README.md), so the
    # lifecycle is systemd units rather than compose.

    echo "🛑 Stopping development services..."
    systemctl --user stop deduparr-frontend.service deduparr-backend.service 2>/dev/null || true
    podman pod rm -f deduparr-dev 2>/dev/null || true
    echo "✅ Services stopped"
    echo ""

    echo "🗑️  Removing database and encryption key..."
    rm -f config/deduparr.db config/deduparr.db-shm config/deduparr.db-wal config/.encryption_key
    echo "✅ Database and encryption key removed"
    echo ""

    echo "🧹 Removing development images..."
    podman rmi -f localhost/deduparr-backend-dev:latest \
                  localhost/deduparr-frontend-dev:latest 2>/dev/null || true
    echo "✅ Images removed"
    echo ""

    # Images rebuild automatically on start via the .build units.
    echo "🚀 Starting development pod (rebuilds images)..."
    systemctl --user daemon-reload
    systemctl --user start deduparr-frontend.service
    echo "✅ Pod started"
    echo ""

    echo "✨ Rebuild complete (dev mode)!"
    echo ""
    echo "📊 View logs with: journalctl --user -u deduparr-frontend.service -f"
    echo "🌐 Frontend: http://localhost:3000"
    echo "🔧 Backend:  http://localhost:3001"
    exit 0
fi

# ---------------------------------------------------------------- production

# 1. Stop and remove containers using the relevant ports
echo "🔍 Checking for containers using port 8655..."
CONTAINERS=$(docker ps -a --format "{{.ID}} {{.Ports}}" | grep "8655" | awk '{print $1}' || true)

if [ -n "$CONTAINERS" ]; then
    echo "🛑 Stopping and removing containers..."
    echo "$CONTAINERS" | xargs -r docker rm -f
    echo "✅ Port containers removed"
else
    echo "✅ No containers using the ports"
fi
echo ""

# 2. Docker compose down
echo "📦 Running docker compose down..."
docker compose -f ${COMPOSE_FILE} down
echo "✅ Compose down complete"
echo ""

# 3. Remove database and encryption key
echo "🗑️  Removing database and encryption key..."
rm -f config/deduparr.db config/deduparr.db-shm config/deduparr.db-wal config/.encryption_key
echo "✅ Database and encryption key removed"
echo ""

# 4. System prune
echo "🧹 Cleaning up Docker system..."
docker system prune -af
echo "✅ Docker system cleaned"
echo ""

# 5. Rebuild without cache
echo "🔨 Building Docker image (no cache)..."
docker build --no-cache -t ${IMAGE_TAG} .
echo "✅ Build complete"
echo ""

# 6. Start containers
echo "🚀 Starting containers..."
docker compose -f ${COMPOSE_FILE} up -d
echo "✅ Containers started"
echo ""

echo "✨ Docker rebuild complete (prod mode)!"
echo ""
echo "📊 View logs with: docker compose -f ${COMPOSE_FILE} logs -f"
echo "🌐 Setup at: http://127.0.0.1:8655/setup"
