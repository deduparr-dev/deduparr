"""
Base service class for external service integrations (*arr, qBittorrent)
Provides common functionality for encrypted config retrieval and connection testing
"""

import logging
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import Config
from app.services.security import get_token_manager, InvalidTokenError

logger = logging.getLogger(__name__)


class BaseExternalService:
    """Base class for external service integrations with encrypted config support"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_encrypted_config(
        self, service_name: str, config_keys: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Get and decrypt configuration for an external service

        Args:
            service_name: Name of service (for error messages)
            config_keys: Dict mapping internal keys to database config keys
                        e.g., {"url": "radarr_url", "api_key": "radarr_api_key"}

        Returns:
            Dict with decrypted configuration values

        Raises:
            ValueError: If required config is missing or invalid
        """
        config_values = {}

        for internal_key, db_key in config_keys.items():
            result = await self.db.execute(select(Config).where(Config.key == db_key))
            config = result.scalar_one_or_none()

            if not config:
                raise ValueError(
                    f"{service_name} configuration not found in database (missing: {db_key})"
                )

            # Convert to plain string to detach from SQLAlchemy session
            config_values[internal_key] = str(config.value) if config.value else None

        encrypted_keys = ["api_key", "password"]
        for key in encrypted_keys:
            if key in config_values:
                if not config_values[key]:
                    raise ValueError(
                        f"{service_name} {key.replace('_', ' ')} is not configured"
                    )

                try:
                    token_manager = get_token_manager()
                    decrypted = token_manager.decrypt(config_values[key])
                    if decrypted:
                        config_values[key] = decrypted
                    else:
                        logger.error(
                            f"{service_name} decryption returned None - using stored value as plain text"
                        )
                except (InvalidTokenError, Exception) as e:
                    logger.warning(
                        f"{service_name} {key} decryption failed ({e}), treating as plain text. "
                        f"Re-save configuration to encrypt it."
                    )

        return config_values
