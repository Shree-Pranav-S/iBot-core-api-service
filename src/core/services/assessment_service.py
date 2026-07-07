"""Business logic for recruiter assessments, JD analysis, and interview planning."""

import asyncio
import logging
import uuid
from datetime import datetime

from groq import AsyncGroq

from src.config.settings import settings
from src.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from src.data.clients.postgres_client import async_session_scope
from src.data.models.postgres.assessment import Assessment
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.handlers.celery_tasks.assessment_tasks import enqueue_assessment_processing
from src.schemas.assessment import FocusAreaOverride
from src.utils.candidates import send_cancellation_email

logger = logging.getLogger(__name__)


class AssessmentService:
    """Service layer managing the assessment creation lifecycle and JD parsing/analysis."""

    def __init__(self, repository: AssessmentRepository) -> None:
        """Initialize the assessment service with its repository."""
        self._repository = repository
        self._groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def get_assessment_by_id(
        self, assessment_id: uuid.UUID, recruiter_id: uuid.UUID
    ) -> Assessment:
        """Fetch an assessment and ensure the recruiter owns it."""
        assessment = await self._repository.get_by_id(assessment_id)
        if assessment is None:
            raise NotFoundException("Assessment not found.")
        if assessment.recruiter_id != recruiter_id:
            raise ForbiddenException("You do not have access to this assessment.")
        return assessment

    async def get_recruiter_assessments(
        self, recruiter_id: uuid.UUID
    ) -> list[Assessment]:
        """Fetch all assessments for a recruiter."""
        return await self._repository.get_all_by_recruiter(recruiter_id)

    async def update_status(
        self, assessment_id: uuid.UUID, recruiter_id: uuid.UUID, new_status: str
    ) -> Assessment:
        """Update the status of an assessment."""
        assessment = await self.get_assessment_by_id(assessment_id, recruiter_id)

        # If it's being closed from an active state, notify candidates
        if assessment.status != "CLOSED" and new_status == "CLOSED":
            asyncio.create_task(
                self.send_cancellation_emails_in_background(assessment_id)
            )

        updated_assessment = await self._repository.update_status(
            assessment, new_status
        )
        logger.info(
            "Assessment status updated",
            extra={"assessment_id": str(updated_assessment.id), "status": new_status},
        )
        return updated_assessment

    async def create_assessment(
        self,
        recruiter_id: uuid.UUID,
        title: str,
        role_name: str,
        duration_mins: int,
        window_start: datetime,
        window_end: datetime,
        jd_text: str | None = None,
        jd_file_bytes: bytes | None = None,
        jd_filename: str | None = None,
        focus_areas: list[FocusAreaOverride] | None = None,
    ) -> Assessment:
        """
        Create a new assessment in PROCESSING status.
        The heavy processing is queued after the request transaction commits.
        """
        if not jd_file_bytes and not jd_text:
            raise BadRequestException(
                "Either job description text or a PDF file must be provided."
            )

        db_assessment = Assessment(
            recruiter_id=recruiter_id,
            title=title,
            role_name=role_name,
            jd_text=jd_text if jd_text else "",
            jd_file_path=jd_filename,
            jd_analysis=None,
            focus_areas=[fa.model_dump() for fa in focus_areas]
            if focus_areas
            else None,
            interview_plan=None,
            interview_duration_mins=duration_mins,
            window_start=window_start,
            window_end=window_end,
            status="PROCESSING",
        )

        assessment = await self._repository.create_assessment(db_assessment)
        self._repository.register_after_commit_callback(
            lambda: enqueue_assessment_processing(
                assessment_id=assessment.id,
                jd_text=jd_text,
                jd_file_bytes=jd_file_bytes,
                jd_filename=jd_filename,
                focus_areas=focus_areas,
            )
        )
        return assessment

    async def send_cancellation_emails_in_background(
        self, assessment_id: uuid.UUID
    ) -> None:
        """Fetch all candidates for an assessment and dispatch cancellation emails."""
        try:
            async with async_session_scope() as session:
                records = await CandidateAssessmentRepository(
                    session
                ).get_all_by_assessment(assessment_id)
                candidates_info = [
                    {
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
                    assessment_id,
                )
                return

            for info in candidates_info:
                # Fire and forget email dispatch
                asyncio.create_task(
                    send_cancellation_email(
                        candidate_name=info["candidate_name"],
                        recipient_email=info["recipient_email"],
                        assessment_title=info["assessment_title"],
                        role_name=info["role_name"],
                    )
                )

            logger.info(
                "Successfully dispatched cancellation emails for assessment %s",
                assessment_id,
            )
        except Exception:
            logger.exception(
                "Failed to dispatch cancellation emails for assessment %s",
                assessment_id,
            )
