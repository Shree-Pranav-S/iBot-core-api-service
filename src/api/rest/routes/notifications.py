"""Recruiter dashboard notification routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import AuthenticationException, BadRequestException
from src.core.services.notification_service import NotificationService
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.schemas.common import APIResponse
from src.schemas.notification import RecruiterDashboardNotification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=APIResponse[list[RecruiterDashboardNotification]],
    summary="List report-ready notifications for the recruiter",
)
async def list_notifications(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[list[RecruiterDashboardNotification]]:
    """Return report-ready dashboard notifications for the authenticated recruiter."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    service = NotificationService(NotificationLogRepository(db))
    notifications = await service.list_for_recruiter(recruiter_id)
    return APIResponse(
        message="Notifications retrieved successfully.",
        data=notifications,
    )
