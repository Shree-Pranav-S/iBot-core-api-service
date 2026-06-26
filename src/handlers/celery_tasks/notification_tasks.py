"""Celery handlers for notification dispatch."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.data.clients.celery_client import celery_app, run_async
from src.data.repositories.notification_log_repository import (
    NotificationLogRepository,
)
from src.utils.candidates import send_invitation_email

logger = logging.getLogger(__name__)


async def _send_invitation(payload: dict[str, Any]) -> None:
    ca_record_id = uuid.UUID(str(payload["candidate_assessment_id"]))
    recipient_email = str(payload["recipient_email"])

    await send_invitation_email(
        candidate_name=str(payload["candidate_name"]),
        recipient_email=recipient_email,
        assessment_title=str(payload["assessment_title"]),
        role_name=str(payload["role_name"]),
        invitation_link=str(payload["invitation_link"]),
        interview_duration_mins=int(payload["interview_duration_mins"]),
    )
    await NotificationLogRepository.log_invitation_sent_in_background(
        ca_record_id,
        recipient_email,
    )


async def _log_invitation_failure(
    payload: dict[str, Any],
    error_message: str,
) -> None:
    await NotificationLogRepository.log_invitation_failed_in_background(
        uuid.UUID(str(payload["candidate_assessment_id"])),
        str(payload["recipient_email"]),
        error_message,
    )


@celery_app.task(  # type: ignore
    bind=True,
    max_retries=3,
    name="core.send_invitation_email",
)
def send_invitation_email_task(self: Any, payload: dict[str, Any]) -> None:
    """Send and log one candidate invitation email."""
    try:
        run_async(_send_invitation(payload))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            countdown = min(60, 2**self.request.retries)
            logger.exception(
                "Invitation email task failed; retrying",
                extra={
                    "candidate_assessment_id": payload.get("candidate_assessment_id"),
                    "retry_in": countdown,
                },
            )
            raise self.retry(exc=exc, countdown=countdown)

        error_message = f"{type(exc).__name__}: {exc}"
        logger.exception(
            "Invitation email task failed permanently",
            extra={"candidate_assessment_id": payload.get("candidate_assessment_id")},
        )
        try:
            run_async(_log_invitation_failure(payload, error_message))
        except Exception:
            logger.exception(
                "Failed to write invitation failure log",
                extra={
                    "candidate_assessment_id": payload.get("candidate_assessment_id")
                },
            )
        raise


def enqueue_invitation_email(
    *,
    ca_record_id: uuid.UUID,
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
    invitation_link: str,
    interview_duration_mins: int,
) -> None:
    """Queue a candidate invitation email for asynchronous delivery."""
    send_invitation_email_task.delay(
        {
            "candidate_assessment_id": str(ca_record_id),
            "candidate_name": candidate_name,
            "recipient_email": recipient_email,
            "assessment_title": assessment_title,
            "role_name": role_name,
            "invitation_link": invitation_link,
            "interview_duration_mins": interview_duration_mins,
        }
    )
