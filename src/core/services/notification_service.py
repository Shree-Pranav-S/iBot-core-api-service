"""Recruiter dashboard notification business logic."""

from __future__ import annotations

import uuid

from src.data.repositories.notification_log_repository import (
    NotificationLogRepository,
)
from src.schemas.notification import RecruiterDashboardNotification


class NotificationService:
    """Build recruiter-facing notifications from persisted delivery records."""

    def __init__(self, repository: NotificationLogRepository) -> None:
        self._repository = repository

    async def list_for_recruiter(
        self,
        recruiter_id: uuid.UUID,
    ) -> list[RecruiterDashboardNotification]:
        rows = await self._repository.list_report_ready_for_recruiter(recruiter_id)
        return [
            RecruiterDashboardNotification(
                id=log.id,
                candidate_assessment_id=log.candidate_assessment_id,
                notification_type=log.notification_type,
                title="Interview evaluation ready",
                message=(
                    f"{candidate_name}'s evaluation for {assessment_title} "
                    "is ready to review."
                ),
                candidate_name=candidate_name,
                assessment_title=assessment_title,
                role_name=role_name,
                sent_at=log.sent_at,
            )
            for log, candidate_name, assessment_title, role_name in rows
        ]
