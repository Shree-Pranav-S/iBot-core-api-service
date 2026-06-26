"""Celery handlers for assessment JD analysis and interview plan generation."""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

from src.core.services.assessment_service import AssessmentService
from src.data.clients.celery_client import celery_app, run_async
from src.data.clients.postgres_client import get_session_factory
from src.data.repositories.assessment_repository import AssessmentRepository
from src.schemas.assessment import FocusAreaOverride

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

    SessionLocal = await get_session_factory()
    async with SessionLocal() as session:
        service = AssessmentService(AssessmentRepository(session))
        await service.process_assessment_in_background(
            assessment_id=uuid.UUID(assessment_id),
            jd_text=jd_text,
            jd_file_bytes=file_bytes,
            jd_filename=jd_filename,
            focus_areas=focus_areas,
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
    except Exception as exc:
        countdown = min(60, 2**self.request.retries)
        logger.exception(
            "Celery assessment processing failed",
            extra={"assessment_id": assessment_id, "retry_in": countdown},
        )
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
