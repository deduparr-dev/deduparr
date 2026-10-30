"""
Application configuration settings
"""

from typing import Annotated, Literal, Optional

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

# Import version from package
from app import DEDUPARR_VERSION

# The values a schedule can hold, from the environment or saved in Settings
ScanScheduleMode = Literal["daily", "interval"]
ScanTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]  # HH:MM
ScanIntervalHours = Annotated[int, Field(ge=1, le=168)]


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # A .env file may still name settings that no longer exist
    model_config = ConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

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

    # Scheduler, until the schedule is saved in Settings (Automation)
    enable_scheduled_scans: bool = False
    scan_schedule_mode: ScanScheduleMode = "daily"
    scheduled_scan_time: ScanTime = "02:00"  # The daily scan, or the interval's start
    scan_interval_hours: ScanIntervalHours = 24  # Interval mode only
    enable_scheduled_deletion: bool = False


settings = Settings()
