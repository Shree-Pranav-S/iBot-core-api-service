"""
Common schemas.

Generic response envelopes and the health check response used across
the entire core-api.
"""

from typing import Generic, TypeVar

from src.schemas.base import AppBaseModel

T = TypeVar("T")


# ── Generic response envelope ─────────────────────────────────────────────────


class APIResponse(AppBaseModel, Generic[T]):
    """
    Standard JSON envelope wrapping all successful API responses.

    Example:
        {
            "success": true,
            "message": "Assessment created.",
            "data": { ... }
        }
    """

    success: bool = True
    message: str = "OK"
    data: T | None = None


# ── Error response ────────────────────────────────────────────────────────────


class ErrorDetail(AppBaseModel):
    """Single validation or field-level error detail."""

    field: str | None = None
    message: str


class ErrorResponse(AppBaseModel):
    """Standard error envelope returned on 4xx / 5xx responses."""

    success: bool = False
    message: str
    errors: list[ErrorDetail] | None = None


# ── Health check ──────────────────────────────────────────────────────────────


class HealthResponse(AppBaseModel):
    """GET /health response."""

    status: str = "ok"
    service: str
    environment: str
    database: str = "ok"
    redis: str = "ok"
