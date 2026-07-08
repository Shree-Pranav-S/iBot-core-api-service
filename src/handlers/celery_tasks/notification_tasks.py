"""Celery handlers for notification dispatch."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from src.config.settings import settings
from src.core.exceptions import ReportContextNotFoundException
from src.core.services.event_log_service import try_record_event_in_background
from src.data.clients.celery_client import celery_app, run_async
from src.data.clients.postgres_client import async_session_scope
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.schemas.event_log import EventLogCreate, EventName, EventSource
from src.utils.candidates import (
    send_cancellation_email,
    send_invitation_email,
    send_report_ready_email,
)

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
    async with async_session_scope() as session:
        await NotificationLogRepository(session).log_invitation_sent(
            ca_record_id,
            recipient_email,
        )


async def _log_invitation_failure(
    payload: dict[str, Any],
    error_message: str,
) -> None:
    async with async_session_scope() as session:
        await NotificationLogRepository(session).log_invitation_failed(
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


async def _send_cancellation(payload: dict[str, Any]) -> None:
    ca_record_id = uuid.UUID(str(payload["candidate_assessment_id"]))
    recipient_email = str(payload["recipient_email"])

    await send_cancellation_email(
        candidate_name=str(payload["candidate_name"]),
        recipient_email=recipient_email,
        assessment_title=str(payload["assessment_title"]),
        role_name=str(payload["role_name"]),
    )
    async with async_session_scope() as session:
        await NotificationLogRepository(session).create(
            candidate_assessment_id=ca_record_id,
            notification_type="ASSESSMENT_CANCELLATION",
            recipient_email=recipient_email,
            delivery_status="SENT",
        )


async def _log_cancellation_failure(
    payload: dict[str, Any],
    error_message: str,
) -> None:
    async with async_session_scope() as session:
        await NotificationLogRepository(session).create(
            candidate_assessment_id=uuid.UUID(str(payload["candidate_assessment_id"])),
            notification_type="ASSESSMENT_CANCELLATION",
            recipient_email=str(payload["recipient_email"]),
            delivery_status="FAILED",
            error_message=error_message,
        )


@celery_app.task(  # type: ignore
    bind=True,
    max_retries=3,
    name="core.send_cancellation_email",
)
def send_cancellation_email_task(self: Any, payload: dict[str, Any]) -> None:
    """Send and log one candidate assessment-cancellation email."""

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
        run_async(_send_cancellation(payload))
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
                "Cancellation email task failed; retrying",
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
            "Cancellation email task failed permanently",
            extra={"candidate_assessment_id": payload.get("candidate_assessment_id")},
        )
        try:
            run_async(_log_cancellation_failure(payload, error_message))
        except Exception:
            logger.exception(
                "Failed to write cancellation failure log",
                extra={
                    "candidate_assessment_id": payload.get("candidate_assessment_id")
                },
            )
        raise


def enqueue_cancellation_email(
    *,
    ca_record_id: uuid.UUID,
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
) -> None:
    """Queue a candidate assessment-cancellation email for asynchronous delivery."""
    send_cancellation_email_task.delay(
        {
            "candidate_assessment_id": str(ca_record_id),
            "candidate_name": candidate_name,
            "recipient_email": recipient_email,
            "assessment_title": assessment_title,
            "role_name": role_name,
        }
    )


async def _send_report_ready(payload: dict[str, Any]) -> None:
    ca_record_id = uuid.UUID(str(payload["candidate_assessment_id"]))
    recipient_email = str(payload["recipient_email"]).strip()

    async with async_session_scope() as session:
        context = await EvaluationRepository(session).load_report_email_context(
            ca_record_id
        )

    if context is None:
        raise ReportContextNotFoundException(
            f"No report-ready email context found for {ca_record_id}",
        )

    report_link = settings.evaluations_url()

    await send_report_ready_email(
        recruiter_email=recipient_email,
        recruiter_name=str(context.get("recruiter_name") or ""),
        candidate_name=str(context.get("candidate_name") or "The candidate"),
        assessment_title=str(context.get("assessment_title") or "Assessment"),
        role_name=str(context.get("role_name") or ""),
        overall_score=context.get("overall_score"),
        hiring_recommendation=context.get("hiring_recommendation"),
        report_link=report_link,
    )
    async with async_session_scope() as session:
        await NotificationLogRepository(session).create(
            candidate_assessment_id=ca_record_id,
            notification_type="REPORT_READY_EMAIL",
            recipient_email=recipient_email,
            delivery_status="SENT",
        )


async def _log_report_ready_failure(
    payload: dict[str, Any],
    error_message: str,
) -> None:
    async with async_session_scope() as session:
        await NotificationLogRepository(session).create(
            candidate_assessment_id=uuid.UUID(str(payload["candidate_assessment_id"])),
            notification_type="REPORT_READY_EMAIL",
            recipient_email=str(payload["recipient_email"]),
            delivery_status="FAILED",
            error_message=error_message,
        )


@celery_app.task(  # type: ignore
    bind=True,
    max_retries=3,
    name="core.send_report_ready_email",
)
def send_report_ready_email_task(self: Any, payload: dict[str, Any]) -> None:
    """Send and log one recruiter report-ready email."""

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
        run_async(_send_report_ready(payload))
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
                "Report-ready email task failed; retrying",
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
            "Report-ready email task failed permanently",
            extra={"candidate_assessment_id": payload.get("candidate_assessment_id")},
        )
        try:
            run_async(_log_report_ready_failure(payload, error_message))
        except Exception:
            logger.exception(
                "Failed to write report-ready failure log",
                extra={
                    "candidate_assessment_id": payload.get("candidate_assessment_id")
                },
            )
        raise


def enqueue_report_ready_email(
    *,
    ca_record_id: uuid.UUID,
    recruiter_email: str,
) -> None:
    """Queue a recruiter report-ready email for asynchronous delivery."""
    send_report_ready_email_task.apply_async(
        args=[
            {
                "candidate_assessment_id": str(ca_record_id),
                "recipient_email": recruiter_email,
            }
        ],
        countdown=5,
    )
