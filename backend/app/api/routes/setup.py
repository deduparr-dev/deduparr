"""
Setup wizard API endpoints
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.setup_service import SetupService
from app.services.plex_service import PlexAuthService

# Import token manager at module level so tests can patch it via
# "app.api.routes.setup.get_token_manager". The actual decryption is used
# only inside the endpoint.
from app.services.security import get_token_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class PlexConnectionTest(BaseModel):
    """Request model for testing Plex connection"""

    auth_token: str
    server_name: str


class RadarrConnectionTest(BaseModel):
    """Request model for testing Radarr connection"""

    url: str
    api_key: str


class SonarrConnectionTest(BaseModel):
    """Request model for testing Sonarr connection"""

    url: str
    api_key: str


class QBittorrentConnectionTest(BaseModel):
    """Request model for testing qBittorrent connection"""

    url: str
    username: str
    password: str


class EmailConnectionTest(BaseModel):
    """Request model for testing email/SMTP connection"""

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    notification_email: str


class PlexLibrariesRequest(BaseModel):
    """Request model for getting Plex libraries"""

    auth_token: str
    server_name: str


class SaveConfigurationRequest(BaseModel):
    """Request model for saving configuration"""

    config: Dict[str, str]


class SetupStatusResponse(BaseModel):
    """Response model for setup status"""

    is_complete: bool
    missing_required: List[str]
    configured_services: Dict[str, bool]
    database_type: str


class ConnectionTestResponse(BaseModel):
    """Response model for connection tests"""

    success: bool
    error: Optional[str] = None
    version: Optional[str] = None
    server_name: Optional[str] = None
    platform: Optional[str] = None
    available_servers: Optional[List[str]] = None
    # Optional free-form message returned by some test endpoints
    message: Optional[str] = None


class PlexLibraryResponse(BaseModel):
    """Response model for Plex library"""

    key: str
    title: str
    type: str
    agent: str


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status(db: AsyncSession = Depends(get_db)):
    """
    Get setup wizard status

    Returns detailed information about what configuration is missing
    """
    setup_service = SetupService(db)
    status = await setup_service.get_setup_status()
    return status


@router.get("/plex/auth/initiate")
async def initiate_plex_auth():
    """
    Initiate Plex OAuth authentication

    Returns PIN and OAuth URL for user to authenticate
    """
    try:
        auth_data = await PlexAuthService.initiate_auth()
        return auth_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plex/auth/check/{pin_id}")
async def check_plex_auth(pin_id: str):
    """
    Check if Plex OAuth authentication is complete

    Args:
        pin_id: PIN ID from initiate_plex_auth

    Returns:
        Encrypted auth token if complete, None if still pending
    """
    try:
        encrypted_token = await PlexAuthService.check_auth(pin_id)
        if encrypted_token:
            return {"success": True, "encrypted_token": encrypted_token}
        return {"success": False, "encrypted_token": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PlexServersRequest(BaseModel):
    """Request model for getting Plex servers"""

    auth_token: str


@router.post("/plex/servers")
async def get_plex_servers(request: PlexServersRequest):
    """
    Get available Plex servers for the authenticated user

    Args:
        request: Request containing encrypted auth token

    Returns:
        List of available Plex servers
    """
    try:
        servers = await PlexAuthService.get_servers(request.auth_token)
        return {"servers": servers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/plex", response_model=ConnectionTestResponse)
async def test_plex_connection(
    request: PlexConnectionTest, db: AsyncSession = Depends(get_db)
):
    """
    Test Plex server connection

    Args:
        request: Plex connection details

    Returns:
        Connection test result
    """
    setup_service = SetupService(db)
    result = await setup_service.test_plex_connection(
        request.auth_token, request.server_name
    )
    return result


@router.post("/test/radarr", response_model=ConnectionTestResponse)
async def test_radarr_connection(
    request: RadarrConnectionTest, db: AsyncSession = Depends(get_db)
):
    """
    Test Radarr API connection

    Args:
        request: Radarr connection details

    Returns:
        Connection test result
    """
    setup_service = SetupService(db)
    result = await setup_service.test_radarr_connection(request.url, request.api_key)
    return result


@router.post("/test/sonarr", response_model=ConnectionTestResponse)
async def test_sonarr_connection(
    request: SonarrConnectionTest, db: AsyncSession = Depends(get_db)
):
    """
    Test Sonarr API connection

    Args:
        request: Sonarr connection details

    Returns:
        Connection test result
    """
    setup_service = SetupService(db)
    result = await setup_service.test_sonarr_connection(request.url, request.api_key)
    return result


@router.post("/test/qbittorrent", response_model=ConnectionTestResponse)
async def test_qbittorrent_connection(
    request: QBittorrentConnectionTest, db: AsyncSession = Depends(get_db)
):
    """
    Test qBittorrent connection

    Args:
        request: qBittorrent connection details

    Returns:
        Connection test result
    """
    setup_service = SetupService(db)
    result = await setup_service.test_qbittorrent_connection(
        request.url, request.username, request.password
    )
    return result


@router.post("/test/email", response_model=ConnectionTestResponse)
async def test_email_connection(
    request: EmailConnectionTest, db: AsyncSession = Depends(get_db)
):
    """
    Test email/SMTP connection by sending a test email

    Args:
        request: SMTP connection details

    Returns:
        Connection test result
    """
    from app.services.email_service import EmailService

    try:
        # Decrypt password if it looks encrypted (has the itsdangerous format)
        smtp_password = request.smtp_password
        if "." in smtp_password and len(smtp_password) > 50:
            # Looks like an encrypted token, decrypt it
            try:
                token_manager = get_token_manager()
                smtp_password = token_manager.decrypt(smtp_password)
            except Exception:
                # If decryption fails, use as-is (might be a plain password)
                pass

        email_service = EmailService(
            smtp_host=request.smtp_host,
            smtp_port=request.smtp_port,
            smtp_user=request.smtp_user,
            smtp_password=smtp_password,
        )

        # Send test email
        success, error_msg = email_service.send_test_email(request.notification_email)

        if success:
            return ConnectionTestResponse(
                success=True,
                message=f"Test email sent successfully to {request.notification_email}",
            )
        else:
            return ConnectionTestResponse(
                success=False,
                error=error_msg
                or "Failed to send test email. Check your SMTP configuration.",
            )

    except Exception as e:
        logger.error(f"Email connection test failed: {e}")
        return ConnectionTestResponse(success=False, error=str(e))


@router.get("/plex/libraries", response_model=List[PlexLibraryResponse])
async def get_stored_plex_libraries(db: AsyncSession = Depends(get_db)):
    """
    Get available Plex libraries using stored credentials

    Returns:
        List of available libraries from configured Plex server
    """
    try:
        setup_service = SetupService(db)

        # Get stored Plex credentials from config
        from app.models import Config
        from sqlalchemy import select

        result = await db.execute(select(Config).where(Config.key == "plex_auth_token"))
        token_config = result.scalar_one_or_none()

        result = await db.execute(
            select(Config).where(Config.key == "plex_server_name")
        )
        server_config = result.scalar_one_or_none()

        if not token_config or not server_config:
            raise ValueError("Plex not configured - complete setup first")

        # Convert to plain string to detach from SQLAlchemy session
        encrypted_token = str(token_config.value) if token_config.value else None
        server_name = str(server_config.value) if server_config.value else None

        libraries = await setup_service.get_plex_libraries(encrypted_token, server_name)

        # Filter to only supported library types (movie and show)
        supported_libraries = [
            lib for lib in libraries if lib.get("type") in ["movie", "show"]
        ]

        return supported_libraries
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/plex/libraries", response_model=List[PlexLibraryResponse])
async def get_plex_libraries(
    request: PlexLibrariesRequest, db: AsyncSession = Depends(get_db)
):
    """
    Get available Plex libraries (setup wizard version - requires credentials)

    Args:
        request: Plex connection details

    Returns:
        List of available libraries
    """
    try:
        setup_service = SetupService(db)
        libraries = await setup_service.get_plex_libraries(
            request.auth_token, request.server_name
        )
        return libraries
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
async def save_configuration(
    request: SaveConfigurationRequest, db: AsyncSession = Depends(get_db)
):
    """
    Save configuration settings

    Args:
        request: Configuration data

    Returns:
        Success message
    """
    try:
        setup_service = SetupService(db)
        await setup_service.save_configuration(request.config)
        return {"status": "success", "message": "Configuration saved"}
    except Exception as e:
        logger.error(f"Failed to save configuration: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete")
async def mark_setup_complete(db: AsyncSession = Depends(get_db)):
    """
    Mark setup wizard as complete

    Returns:
        Success message
    """
    try:
        setup_service = SetupService(db)

        if not await setup_service.is_setup_complete():
            status = await setup_service.get_setup_status()
            if status["missing_required"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot complete setup. Missing required configuration: {', '.join(status['missing_required'])}",
                )

        await setup_service.mark_setup_complete()
        return {"status": "success", "message": "Setup completed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_setup(db: AsyncSession = Depends(get_db)):
    """
    Reset setup wizard to allow reconfiguration

    This allows users to re-run the setup wizard from settings
    to update their configuration.

    Returns:
        Success message
    """
    try:
        setup_service = SetupService(db)
        await setup_service.reset_setup()
        return {"status": "success", "message": "Setup reset - wizard can be run again"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
