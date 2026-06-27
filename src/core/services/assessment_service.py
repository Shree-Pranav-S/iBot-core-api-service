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
from src.data.models.postgres.assessment import Assessment
from src.data.repositories.assessment_repository import AssessmentRepository
from src.schemas.assessment import FocusAreaOverride
from src.utils.assessment_utils import (
    parse_pdf_jd,
    run_jd_analysis_and_interview_plan,
)
from src.utils.candidates import send_cancellation_email

logger = logging.getLogger(__name__)


def _enqueue_assessment_processing_after_commit(
    *,
    assessment_id: uuid.UUID,
    jd_text: str | None,
    jd_file_bytes: bytes | None,
    jd_filename: str | None,
    focus_areas: list[FocusAreaOverride] | None,
) -> None:
    from src.handlers.celery_tasks.assessment_tasks import (
        enqueue_assessment_processing,
    )

    enqueue_assessment_processing(
        assessment_id=assessment_id,
        jd_text=jd_text,
        jd_file_bytes=jd_file_bytes,
        jd_filename=jd_filename,
        focus_areas=focus_areas,
    )


class AssessmentService:
    """Service layer managing the assessment creation lifecycle and JD parsing/analysis."""

    def __init__(self, repository: AssessmentRepository) -> None:
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

        # Save to Database with status="PROCESSING"
        db_assessment = Assessment(
            recruiter_id=recruiter_id,
            title=title,
            role_name=role_name,
            jd_text=jd_text if jd_text else "",  # initial empty or text
            jd_file_path=jd_filename,  # store file name/metadata
            jd_analysis=None,
            focus_areas=[fa.model_dump() for fa in focus_areas]
            if focus_areas
            else None,
            interview_plan=None,
            interview_duration_mins=duration_mins,
            window_start=window_start,
            window_end=window_end,
            status="PROCESSING",  # Default to PROCESSING for async flow
        )

        assessment = await self._repository.create_assessment(db_assessment)
        self._repository.register_after_commit_callback(
            lambda: _enqueue_assessment_processing_after_commit(
                assessment_id=assessment.id,
                jd_text=jd_text,
                jd_file_bytes=jd_file_bytes,
                jd_filename=jd_filename,
                focus_areas=focus_areas,
            )
        )
        return assessment

    async def process_assessment_in_background(
        self,
        assessment_id: uuid.UUID,
        jd_text: str | None = None,
        jd_file_bytes: bytes | None = None,
        jd_filename: str | None = None,
        focus_areas: list[FocusAreaOverride] | None = None,
    ) -> None:
        """Background task to parse PDF, run LLM analysis, generate plan, and activate assessment."""
        try:
            assessment = await self._repository.get_by_id(assessment_id)
            if not assessment:
                logger.error(
                    "Assessment %s not found in background task.", assessment_id
                )
                return

            parsed_jd_text = ""
            if jd_file_bytes and jd_filename:
                parsed_jd_text = await parse_pdf_jd(jd_file_bytes, jd_filename)
            elif jd_text:
                parsed_jd_text = jd_text

            if not parsed_jd_text.strip():
                raise ValueError("Job description content is empty.")

            # Run one LLM call that generates both JD analysis and the executable plan.
            generated = await run_jd_analysis_and_interview_plan(
                parsed_jd_text,
                assessment.interview_duration_mins,
                focus_areas,
                self._groq_client,
            )
            jd_analysis = generated.jd_analysis
            interview_plan = generated.interview_plan
            # Delegate DB flush and commit to the repository classmethod
            from src.data.repositories.assessment_repository import AssessmentRepository

            await AssessmentRepository.activate_assessment_in_background(
                assessment_id=assessment_id,
                jd_text=parsed_jd_text,
                jd_analysis=jd_analysis.model_dump(),
                interview_plan=interview_plan.model_dump(),
            )
            logger.info(
                "Successfully processed assessment %s asynchronously.", assessment_id
            )
        except Exception:
            logger.exception(
                "Failed to process assessment %s in background.", assessment_id
            )
            try:
                # Set status to CLOSED to signal failure using the repository classmethod
                from src.data.repositories.assessment_repository import (
                    AssessmentRepository,
                )

                await AssessmentRepository.close_assessment_on_failure_in_background(
                    assessment_id
                )
            except Exception:
                logger.exception(
                    "Failed to update status to CLOSED after error on assessment %s",
                    assessment_id,
                )

    async def send_cancellation_emails_in_background(
        self, assessment_id: uuid.UUID
    ) -> None:
        """Fetch all candidates for an assessment and dispatch cancellation emails."""
        try:
            from src.data.repositories.candidate_assessment_repository import (
                CandidateAssessmentRepository,
            )

            candidates_info = await CandidateAssessmentRepository.get_candidate_emails_for_assessment_in_background(
                assessment_id
            )

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
