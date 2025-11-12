"""
Configuration model for storing application settings in database

Available configuration keys:
- plex_auth_token: Encrypted Plex authentication token (OAuth)
- radarr_url: Radarr server URL
- radarr_api_key: Encrypted Radarr API key
- sonarr_url: Sonarr server URL
- sonarr_api_key: Encrypted Sonarr API key
- qbittorrent_url: qBittorrent server URL
- qbittorrent_username: qBittorrent username
- qbittorrent_password: Encrypted qBittorrent password
- selected_movie_library: Name of selected Plex movie library
- selected_tv_library: Name of selected Plex TV show library
- enable_deep_scan: Enable filesystem-based duplicate detection (default: False)
"""

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base, utc_now


class Config(Base):
    """Configuration key-value store"""

    __tablename__ = "config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return (
            f"<Config(key={self.key}, value={self.value[:50] if self.value else None})>"
        )
