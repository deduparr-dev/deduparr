# Multi-stage build for optimized image size

# Build arguments for metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

# Stage 1: Build frontend
FROM node:25-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Build backend
FROM python:3.14-slim AS backend-builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Final runtime image
FROM python:3.14-slim

# Create app user
RUN groupadd -g 1000 deduparr && \
    useradd -u 1000 -g deduparr -s /bin/bash -m deduparr

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=backend-builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy backend application
COPY backend/app ./app

# Copy manifest.json (version source of truth)
COPY manifest.json ./manifest.json

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy nginx and supervisor configs
COPY docker/nginx.conf /etc/nginx/sites-available/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create necessary directories and fix permissions
RUN mkdir -p /config /media && \
    chown -R deduparr:deduparr /app /config /media

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_TYPE=sqlite
ENV DATABASE_URL=sqlite:////config/deduparr.db
ENV ENCRYPTION_KEY_FILE=/app/data/.encryption_key
ENV LOG_LEVEL=INFO

# Metadata labels
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.authors="deduparr-dev" \
      org.opencontainers.image.url="https://github.com/deduparr-dev/deduparr" \
      org.opencontainers.image.documentation="https://github.com/deduparr-dev/deduparr/blob/main/README.md" \
      org.opencontainers.image.source="https://github.com/deduparr-dev/deduparr" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.vendor="deduparr-dev" \
      org.opencontainers.image.title="Deduparr" \
      org.opencontainers.image.description="Intelligent duplicate management for the *arr stack" \
      org.opencontainers.image.licenses="MIT"

# Expose port
EXPOSE 8655

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8655/api/health || exit 1

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Run supervisor to manage nginx and uvicorn
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
