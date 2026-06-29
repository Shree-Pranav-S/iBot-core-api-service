"""Celery handlers for notification dispatch."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from src.core.services.event_log_service import try_record_event_in_background
from src.data.clients.celery_client import celery_app, run_async
from src.data.repositories.unit_of_work import UnitOfWork
from src.schemas.event_log import EventLogCreate, EventName, EventSource
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
    async with UnitOfWork() as unit_of_work:
        await unit_of_work.notifications.log_invitation_sent(
            ca_record_id, recipient_email
        )


async def _log_invitation_failure(
    payload: dict[str, Any],
    error_message: str,
) -> None:
    async with UnitOfWork() as unit_of_work:
        await unit_of_work.notifications.log_invitation_failed(
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

    candidate_assessment_id = str(payload["candidate_assessment_id"])
    task_id = str(self.request.id or candidate_assessment_id)
    started_at = time.monotonic()
    run_async(
        try_record_event_in_background(
            EventLogCreate(
                event_name=EventName.CELERY_TASK_STARTED,
                source_service=EventSource.CORE_API,
                correlation_id=task_id,
                candidate_assessment_id=uuid.UUID(candidate_assessment_id),
                metadata={
                    "task_name": self.name,
                    "retry_number": self.request.retries,
                },
            )
        )
    )
    try:
        run_async(_send_invitation(payload))
        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.CELERY_TASK_COMPLETED,
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    candidate_assessment_id=uuid.UUID(candidate_assessment_id),
                    metadata={
                        "task_name": self.name,
                        "retry_number": self.request.retries,
                    },
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            )
        )
    except Exception as exc:
        if self.request.retries < self.max_retries:
            countdown = min(60, 2**self.request.retries)
            run_async(
                try_record_event_in_background(
                    EventLogCreate(
                        event_name=EventName.CELERY_TASK_RETRYING,
                        source_service=EventSource.CORE_API,
                        correlation_id=task_id,
                        candidate_assessment_id=uuid.UUID(candidate_assessment_id),
                        metadata={
                            "task_name": self.name,
                            "retry_number": self.request.retries,
                            "retry_in_seconds": countdown,
                            "exception_type": type(exc).__name__,
                        },
                        error_message=str(exc),
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                    )
                )
            )
            logger.exception(
                "Invitation email task failed; retrying",
                extra={
                    "candidate_assessment_id": payload.get("candidate_assessment_id"),
                    "retry_in": countdown,
                },
            )
            raise self.retry(exc=exc, countdown=countdown)

        error_message = f"{type(exc).__name__}: {exc}"
        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.CELERY_TASK_FAILED,
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    candidate_assessment_id=uuid.UUID(candidate_assessment_id),
                    metadata={
                        "task_name": self.name,
                        "retry_number": self.request.retries,
                        "exception_type": type(exc).__name__,
                    },
                    error_message=str(exc),
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            )
        )
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
