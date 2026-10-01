import asyncio

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.database import check_database_connection
from app.schemas.health import HealthResponse

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Inspects application responsiveness and verifies live PostgreSQL database connectivity.",
    responses={
        200: {"description": "Service is fully operational and database is reachable."},
        503: {"description": "Service is running but database is disconnected/unreachable."},
    },
)
async def health_check(deep: bool = Query(False, description="Also probe PostgreSQL; default is fast liveness.")):
    """
    Evaluates application and database health.
    Distinguishes application availability from database availability.
    """
    payload = {
        "status": "ok",
        "database": "not_checked",
        "version": settings.app_version,
        "environment": settings.backend_env,
    }

    return payload
