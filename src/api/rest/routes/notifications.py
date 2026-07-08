"""Recruiter dashboard notification routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from src.api.rest.dependencies import get_notification_service, require_recruiter_id
from src.core.services.notification_service import NotificationService
from src.schemas.common import APIResponse
from src.schemas.notification import RecruiterDashboardNotification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=APIResponse[list[RecruiterDashboardNotification]],
    summary="List report-ready notifications for the recruiter",
)
async def list_notifications(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: NotificationService = Depends(get_notification_service),
) -> APIResponse[list[RecruiterDashboardNotification]]:
    """Return report-ready dashboard notifications for the authenticated recruiter."""
    notifications = await service.list_for_recruiter(recruiter_id)
    return APIResponse(
        message="Notifications retrieved successfully.",
        data=notifications,
    )
