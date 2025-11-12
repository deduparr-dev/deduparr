"""
System Service - Provides system information and logs
"""

import logging
import os
import platform
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sqlalchemy

from app import DEDUPARR_VERSION, DEDUPARR_NAME, DEDUPARR_DESCRIPTION

logger = logging.getLogger(__name__)


class SystemService:
    """Service for retrieving system information and logs"""

    # In-memory log buffer (last 1000 lines)
    _log_buffer: deque[dict[str, str]] = deque(maxlen=1000)
    _log_handler: Optional[logging.Handler] = None

    @classmethod
    def setup_log_capture(cls) -> None:
        """Setup logging handler to capture logs in memory"""
        if cls._log_handler is not None:
            return  # Already setup

        class MemoryHandler(logging.Handler):
            """Custom handler that stores logs in memory"""

            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = self.format(record)
                    SystemService._log_buffer.append(
                        {
                            "timestamp": datetime.fromtimestamp(
                                record.created, tz=timezone.utc
                            ).isoformat(),
                            "level": record.levelname,
                            "logger": record.name,
                            "message": msg,
                        }
                    )
                except Exception:
                    pass  # Don't break if logging fails

        cls._log_handler = MemoryHandler()
        cls._log_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.getLogger().addHandler(cls._log_handler)
        logger.info("📝 System log capture enabled")

    @classmethod
    def get_logs(cls, limit: int = 100) -> list[dict[str, str]]:
        """Get recent logs from memory buffer"""
        logs = list(cls._log_buffer)
        return logs[-limit:] if limit > 0 else logs

    @staticmethod
    async def get_version_info() -> dict[str, str]:
        """Get version information for all components"""
        import fastapi

        return {
            "deduparr": DEDUPARR_VERSION,
            "python": platform.python_version(),
            "fastapi": fastapi.__version__,
            "sqlalchemy": sqlalchemy.__version__,
            "platform": platform.platform(),
            "architecture": platform.machine(),
        }

    @staticmethod
    async def get_system_info() -> dict[str, object]:
        """Get general system information"""
        # Get uptime if possible
        uptime_seconds = None
        try:
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.readline().split()[0])
        except (FileNotFoundError, ValueError, IndexError):
            pass

        # Get process info
        import psutil

        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()

        return {
            "hostname": platform.node(),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "executable": sys.executable,
            },
            "process": {
                "pid": os.getpid(),
                "memory_rss": memory_info.rss,
                "memory_vms": memory_info.vms,
                "cpu_percent": process.cpu_percent(interval=0.1),
                "threads": process.num_threads(),
            },
            "uptime_seconds": uptime_seconds,
            "timezone": str(datetime.now().astimezone().tzinfo),
        }

    @staticmethod
    async def get_app_info() -> dict[str, object]:
        """Get application-specific information"""
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.models import Config
        from sqlalchemy import select

        # Test database connection
        db_status = "unknown"
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(sqlalchemy.text("SELECT 1"))
                db_status = "connected"
        except Exception as e:
            db_status = f"error: {str(e)}"
            logger.error(f"Database connection test failed: {e}")

        # Get database file size if using SQLite
        db_size = None
        if settings.database_url.startswith("sqlite"):
            db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
            if Path(db_path).exists():
                db_size = Path(db_path).stat().st_size

        # Get scheduler configuration from database
        scheduler_enabled = False
        scheduler_description = "Disabled"
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Config).where(
                        Config.key.in_(
                            [
                                "enable_scheduled_scans",
                                "scan_schedule_mode",
                                "scheduled_scan_time",
                                "scan_interval_hours",
                            ]
                        )
                    )
                )
                config_items = {item.key: item.value for item in result.scalars().all()}

                scheduler_enabled = config_items.get("enable_scheduled_scans") == "true"
                if scheduler_enabled:
                    mode = config_items.get("scan_schedule_mode", "daily")
                    if mode == "daily":
                        scan_time = config_items.get("scheduled_scan_time", "02:00")
                        scheduler_description = f"Daily at {scan_time}"
                    else:  # interval mode
                        interval_hours = config_items.get("scan_interval_hours", "24")
                        scheduler_description = f"Every {interval_hours}h"
        except Exception as e:
            logger.error(f"Failed to get scheduler config: {e}")

        return {
            "name": DEDUPARR_NAME,
            "description": DEDUPARR_DESCRIPTION,
            "version": DEDUPARR_VERSION,
            "database": {
                "url": settings.database_url.split("@")[-1],  # Hide credentials
                "status": db_status,
                "size_bytes": db_size,
            },
            "config": {
                "log_level": settings.log_level,
                "enable_scheduled_scans": scheduler_enabled,
                "scheduler_description": scheduler_description,
                "data_dir": str(settings.config_dir),
            },
        }
