"""Celery handlers for assessment JD analysis and interview plan generation."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from typing import Any

from groq import AsyncGroq

from src.config.settings import settings
from src.core.exceptions import AssessmentTaskFailedException
from src.core.services.event_log_service import try_record_event_in_background
from src.core.services.realtime_event_service import publish_recruiter_event
from src.data.clients.celery_client import celery_app, run_async
from src.data.clients.postgres_client import async_session_scope
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.handlers.celery_tasks.notification_tasks import enqueue_cancellation_email
from src.schemas.assessment import FocusAreaOverride
from src.schemas.event_log import EventLogCreate, EventName, EventSource
from src.schemas.realtime import RecruiterEventType
from src.utils.assessment_utils import (
    format_jd_to_markdown,
    parse_pdf_jd,
    run_jd_analysis_and_interview_plan,
)

logger = logging.getLogger(__name__)


async def _process_assessment(
    assessment_id: str,
    jd_text: str | None,
    jd_file_base64: str | None,
    jd_filename: str | None,
    focus_areas_payload: list[dict[str, Any]] | None,
) -> None:
    file_bytes = (
        base64.b64decode(jd_file_base64.encode("ascii")) if jd_file_base64 else None
    )
    focus_areas = (
        [
            FocusAreaOverride.model_validate(focus_area)
            for focus_area in focus_areas_payload
        ]
        if focus_areas_payload
        else None
    )

    assessment_uuid = uuid.UUID(assessment_id)
    assessment_info: tuple[uuid.UUID, str, str, int] | None = None
    try:
        async with async_session_scope() as session:
            assessment = await AssessmentRepository(session).get_by_id(assessment_uuid)
            if not assessment:
                logger.error(
                    "Assessment %s not found in background task.", assessment_uuid
                )
                return
            assessment_info = (
                assessment.recruiter_id,
                assessment.title,
                assessment.role_name,
                assessment.interview_duration_mins,
            )

        parsed_jd_text = ""
        if file_bytes and jd_filename:
            parsed_jd_text = await parse_pdf_jd(file_bytes, jd_filename)
        elif jd_text:
            parsed_jd_text = jd_text

        if not parsed_jd_text.strip():
            raise AssessmentTaskFailedException("Job description content is empty.")

        # Run one LLM call that generates both JD analysis and the executable plan.
        assert assessment_info is not None
        recruiter_id, title, role_name, duration_mins = assessment_info
        groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        generated = await run_jd_analysis_and_interview_plan(
            parsed_jd_text,
            duration_mins,
            focus_areas,
            groq_client,
        )
        jd_analysis = generated.jd_analysis
        interview_plan = generated.interview_plan
        # Best-effort: store a neatly formatted Markdown JD for display.
        formatted_jd_text = await format_jd_to_markdown(
            parsed_jd_text,
            groq_client,
        )
        async with async_session_scope() as session:
            await AssessmentRepository(session).activate_assessment(
                assessment_uuid,
                formatted_jd_text,
                jd_analysis.model_dump(),
                interview_plan.model_dump(),
            )
        await publish_recruiter_event(
            recruiter_id=recruiter_id,
            event_type=RecruiterEventType.ASSESSMENT_PROCESSING_COMPLETED,
            payload={
                "assessment_id": str(assessment_uuid),
                "title": title,
                "role_name": role_name,
                "status": "ACTIVE",
            },
        )
        logger.info(
            "Successfully processed assessment %s asynchronously.", assessment_uuid
        )
    except Exception:
        logger.exception(
            "Failed to process assessment %s in background.", assessment_uuid
        )
        try:
            failure_info: tuple[uuid.UUID, str, str] | None = None
            async with async_session_scope() as session:
                repository = AssessmentRepository(session)
                assessment = await repository.get_by_id(assessment_uuid)
                if assessment is not None:
                    failure_info = (
                        assessment.recruiter_id,
                        assessment.title,
                        assessment.role_name,
                    )
                    await repository.close_assessment_on_failure(assessment_uuid)
            if failure_info is not None:
                recruiter_id, title, role_name = failure_info
                await publish_recruiter_event(
                    recruiter_id=recruiter_id,
                    event_type=(RecruiterEventType.ASSESSMENT_PROCESSING_FAILED),
                    payload={
                        "assessment_id": str(assessment_uuid),
                        "title": title,
                        "role_name": role_name,
                        "status": "CLOSED",
                    },
                )
        except Exception:
            logger.exception(
                "Failed to update status to CLOSED after error on assessment %s",
                assessment_uuid,
            )


@celery_app.task(  # type: ignore
    bind=True,
    max_retries=3,
    name="core.process_assessment",
)
def process_assessment_task(
    self: Any,
    assessment_id: str,
    jd_text: str | None,
    jd_file_base64: str | None,
    jd_filename: str | None,
    focus_areas_payload: list[dict[str, Any]] | None,
) -> None:
    """Generate JD analysis and interview plan for an assessment."""

    task_id = str(self.request.id or assessment_id)
    started_at = time.monotonic()
    run_async(
        try_record_event_in_background(
            EventLogCreate(
                event_name=EventName.CELERY_TASK_STARTED,
                source_service=EventSource.CORE_API,
                correlation_id=task_id,
                metadata={
                    "task_name": self.name,
                    "retry_number": self.request.retries,
                    "assessment_id": assessment_id,
                },
            )
        )
    )
    try:
        run_async(
            _process_assessment(
                assessment_id,
                jd_text,
                jd_file_base64,
                jd_filename,
                focus_areas_payload,
            )
        )
        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.CELERY_TASK_COMPLETED,
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    metadata={
                        "task_name": self.name,
                        "retry_number": self.request.retries,
                        "assessment_id": assessment_id,
                    },
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            )
        )
    except Exception as exc:
        countdown = min(60, 2**self.request.retries)
        exhausted = self.request.retries >= int(self.max_retries or 0)
        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=(
                        EventName.CELERY_TASK_FAILED
                        if exhausted
                        else EventName.CELERY_TASK_RETRYING
                    ),
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    metadata={
                        "task_name": self.name,
                        "retry_number": self.request.retries,
                        "assessment_id": assessment_id,
                        "retry_in_seconds": None if exhausted else countdown,
                        "exception_type": type(exc).__name__,
                    },
                    error_message=str(exc),
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            )
        )
        logger.exception(
            "Celery assessment processing failed",
            extra={"assessment_id": assessment_id, "retry_in": countdown},
        )
        if exhausted:
            raise
        raise self.retry(exc=exc, countdown=countdown)


def enqueue_assessment_processing(
    *,
    assessment_id: uuid.UUID,
    jd_text: str | None,
    jd_file_bytes: bytes | None,
    jd_filename: str | None,
    focus_areas: list[FocusAreaOverride] | None,
) -> None:
    """Queue heavy assessment processing on the core assessment worker."""
    jd_file_base64 = (
        base64.b64encode(jd_file_bytes).decode("ascii") if jd_file_bytes else None
    )
    focus_areas_payload = (
        [focus_area.model_dump(mode="json") for focus_area in focus_areas]
        if focus_areas
        else None
    )
    process_assessment_task.delay(
        str(assessment_id),
        jd_text,
        jd_file_base64,
        jd_filename,
        focus_areas_payload,
    )


async def _dispatch_assessment_cancellations(assessment_uuid: uuid.UUID) -> None:
    try:
        async with async_session_scope() as session:
            records = await CandidateAssessmentRepository(
                session
            ).get_all_by_assessment(assessment_uuid)
            candidates_info = [
                {
                    "candidate_assessment_id": record.id,
                    "candidate_name": record.candidate.full_name,
                    "recipient_email": record.candidate.email,
                    "assessment_title": record.assessment.title,
                    "role_name": record.assessment.role_name,
                }
                for record in records
                if record.candidate and record.candidate.email and record.assessment
            ]

        if not candidates_info:
            logger.warning(
                "No candidates found or assessment missing during cancellation dispatch for %s",
                assessment_uuid,
            )
            return

        for info in candidates_info:
            enqueue_cancellation_email(
                ca_record_id=info["candidate_assessment_id"],  # type: ignore[arg-type]
                candidate_name=info["candidate_name"],  # type: ignore[arg-type]
                recipient_email=info["recipient_email"],  # type: ignore[arg-type]
                assessment_title=info["assessment_title"],  # type: ignore[arg-type]
                role_name=info["role_name"],  # type: ignore[arg-type]
            )

        logger.info(
            "Successfully dispatched cancellation emails for assessment %s",
            assessment_uuid,
        )
    except Exception:
        logger.exception(
            "Failed to dispatch cancellation emails for assessment %s",
            assessment_uuid,
        )


@celery_app.task(  # type: ignore
    bind=True,
    max_retries=3,
    name="core.dispatch_assessment_cancellations",
)
def dispatch_assessment_cancellations_task(self: Any, assessment_id: str) -> None:
    """Batch fetch all candidates and dispatch individual cancellation emails."""
    assessment_uuid = uuid.UUID(assessment_id)
    task_id = str(self.request.id or assessment_id)
    started_at = time.monotonic()
    run_async(
        try_record_event_in_background(
            EventLogCreate(
                event_name=EventName.CELERY_TASK_STARTED,
                source_service=EventSource.CORE_API,
                correlation_id=task_id,
                metadata={
                    "task_name": self.name,
                    "assessment_id": assessment_id,
                },
            )
        )
    )
    try:
        run_async(_dispatch_assessment_cancellations(assessment_uuid))
        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.CELERY_TASK_COMPLETED,
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    metadata={
                        "task_name": self.name,
                        "assessment_id": assessment_id,
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
                        metadata={
                            "task_name": self.name,
                            "assessment_id": assessment_id,
                            "retry_number": self.request.retries,
                            "retry_in_seconds": countdown,
                        },
                        error_message=str(exc),
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                    )
                )
            )
            raise self.retry(exc=exc, countdown=countdown)

        run_async(
            try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.CELERY_TASK_FAILED,
                    source_service=EventSource.CORE_API,
                    correlation_id=task_id,
                    metadata={
                        "task_name": self.name,
                        "assessment_id": assessment_id,
                        "retry_number": self.request.retries,
                    },
                    error_message=str(exc),
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            )
        )
        raise


def enqueue_assessment_cancellations(assessment_id: uuid.UUID) -> None:
    """Queue assessment cancellation dispatch."""
    dispatch_assessment_cancellations_task.delay(str(assessment_id))
