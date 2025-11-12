"""
Application configuration settings
"""

from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

# Import version from package
from app import DEDUPARR_VERSION


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = ConfigDict(env_file=".env", case_sensitive=False)

    # Application
    app_name: str = "Deduparr"
    app_version: str = DEDUPARR_VERSION
    debug: bool = False
    log_level: str = "DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Database
    database_type: str = "sqlite"  # sqlite or postgres
    database_url: str = "sqlite:////config/deduparr.db"  # 4 slashes for absolute path

    # Plex Configuration (OAuth-based)
    plex_auth_token: Optional[str] = None  # OAuth token from plex.tv
    plex_server_name: Optional[str] = None  # Name of Plex server to use

    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None

    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None

    qbittorrent_url: Optional[str] = None
    qbittorrent_username: Optional[str] = None
    qbittorrent_password: Optional[str] = None

    # Paths
    config_dir: str = "/config"
    media_dir: str = "/media"

    # Scheduler
    enable_scheduled_scans: bool = False
    scan_schedule_mode: str = "daily"  # "daily" or "interval"
    scheduled_scan_time: str = (
        "02:00"  # Starting time for scans (HH:MM, 24-hour format)
    )
    scan_interval_hours: int = 24  # Interval in hours (1-168) when mode is "interval"

    enable_scheduled_deletion: bool = False
    deletion_schedule_mode: str = "daily"  # "daily" or "interval"
    scheduled_deletion_time: str = (
        "02:30"  # Starting time for deletions (HH:MM, 24-hour format)
    )
    deletion_interval_hours: int = (
        24  # Interval in hours (1-168) when mode is "interval"
    )


settings = Settings()
