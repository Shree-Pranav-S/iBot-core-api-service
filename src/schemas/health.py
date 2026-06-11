"""Health response schema."""

from src.schemas.base import AppBaseModel


class HealthResponse(AppBaseModel):
    """GET /health response."""

    status: str = "ok"
    service: str
    environment: str
    database: str = "ok"
    redis: str = "ok"
