"""Health-check endpoints."""

from fastapi import APIRouter

from src.config.settings import settings
from src.data.clients.postgres_client import ping_db
from src.data.clients.redis_client import ping_redis
from src.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return service liveness and backing-store health."""
    database_ok = await ping_db()
    redis_ok = await ping_redis()
    return HealthResponse(
        status="ok" if database_ok and redis_ok else "degraded",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        database="ok" if database_ok else "down",
        redis="ok" if redis_ok else "down",
    )
