"""
Deduparr - Duplicate Management for the *arr Stack
Main FastAPI application entry point
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import DEDUPARR_VERSION
from app.core.config import settings
from app.core.database import init_db
from app.api.routes import config, setup, scoring, stats, scan, system
from app.services.scheduler import get_scheduler
from app.services.security import SensitiveDataFilter
from app.services.system_service import SystemService

# Configure logging based on environment variable
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Suppress plexapi library noise - only log critical failures
logging.getLogger("plexapi").setLevel(logging.CRITICAL)

# Add sensitive data filter to all handlers for defense-in-depth
# This allows us to keep DEBUG logging for troubleshooting while automatically
# redacting API keys, tokens, passwords, and encrypted values

for handler in logging.root.handlers:
    handler.addFilter(SensitiveDataFilter())

# Setup log capture for system page
SystemService.setup_log_capture()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    await init_db()
    logger.info(
        f"✅ Deduparr v{DEDUPARR_VERSION} started successfully (log_level={settings.log_level})"
    )

    # Start background scheduler if enabled
    scheduler = get_scheduler()
    if settings.enable_scheduled_scans:
        scan_mode = getattr(settings, "scan_schedule_mode", "daily")
        scan_time = getattr(settings, "scheduled_scan_time", "02:00")
        scan_interval_hours = getattr(settings, "scan_interval_hours", 24)

        await scheduler.start(
            scan_mode=scan_mode,
            scan_time=scan_time,
            scan_interval_hours=scan_interval_hours,
        )

        if scan_mode == "daily":
            logger.info(f"Scheduled scans enabled (daily at {scan_time})")
        else:
            logger.info(
                f"Scheduled scans enabled (every {scan_interval_hours}h starting at {scan_time})"
            )

        if settings.enable_scheduled_deletion:
            logger.info(
                "Scheduled deletion enabled (runs 30 minutes after each scan completes)"
            )
    else:
        logger.info("⏸Scheduled scans disabled")

    yield

    # Shutdown
    logger.info("👋 Deduparr shutting down...")
    await scheduler.stop()


app = FastAPI(
    title="Deduparr API",
    description="Duplicate Management for the *arr Stack",
    version=DEDUPARR_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": DEDUPARR_VERSION}


# API routes
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(scoring.router, prefix="/api/scoring", tags=["scoring"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(system.router, prefix="/api", tags=["system"])

# Additional routes will be added as they are implemented
# from app.api.routes import duplicates, history, stats
# app.include_router(duplicates.router, prefix="/api/duplicates", tags=["duplicates"])
# app.include_router(history.router, prefix="/api/history", tags=["history"])
# app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

# Serve frontend static files (in production)
# app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=3001,
        reload=True,
        log_level="info",
    )
