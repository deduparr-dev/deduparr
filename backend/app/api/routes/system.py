"""
System routes - Provides system information and logs
"""

from fastapi import APIRouter, Query

from app.services.system_service import SystemService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/version")
async def get_version_info() -> dict[str, str]:
    """Get version information for all components"""
    return await SystemService.get_version_info()


@router.get("/info")
async def get_system_info() -> dict[str, object]:
    """Get general system information (OS, hardware, process details)"""
    return await SystemService.get_system_info()


@router.get("/app")
async def get_app_info() -> dict[str, object]:
    """Get application-specific information (database, config, etc.)"""
    return await SystemService.get_app_info()


@router.get("/logs")
async def get_logs(
    limit: int = Query(
        100, ge=1, le=1000, description="Number of recent log entries to return"
    )
) -> dict[str, object]:
    """
    Get recent application logs from memory buffer.
    Maximum 1000 logs are kept in memory (FIFO).
    """
    logs = SystemService.get_logs(limit=limit)
    return {
        "logs": logs,
        "total": len(logs),
        "limit": limit,
    }
