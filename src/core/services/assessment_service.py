"""Business logic for recruiter assessments, JD analysis, and interview planning."""

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
    generate_interview_plan,
    parse_pdf_jd,
    run_jd_analysis,
)

logger = logging.getLogger(__name__)


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
        assessment.status = new_status
        await self._repository._session.flush()
        logger.info(
            "Assessment status updated",
            extra={"assessment_id": str(assessment.id), "status": new_status},
        )
        return assessment

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
        The heavy processing (PDF parsing, LLM analysis, plan generation) is offloaded to a background task.
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

        return await self._repository.create_assessment(db_assessment)


async def process_assessment_in_background(
    assessment_id: uuid.UUID,
    jd_text: str | None = None,
    jd_file_bytes: bytes | None = None,
    jd_filename: str | None = None,
    focus_areas: list[FocusAreaOverride] | None = None,
) -> None:
    """Background task to parse PDF, run LLM analysis, generate plan, and activate assessment."""
    from groq import AsyncGroq

    from src.config.settings import settings
    from src.data.clients.postgres_client import get_session_factory
    from src.data.repositories.assessment_repository import AssessmentRepository

    SessionLocal = await get_session_factory()
    async with SessionLocal() as session:
        try:
            repo = AssessmentRepository(session)
            assessment = await repo.get_by_id(assessment_id)
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

            assessment.jd_text = parsed_jd_text

            # Run LLM analysis
            groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            jd_analysis = await run_jd_analysis(parsed_jd_text, groq_client)
            assessment.jd_analysis = jd_analysis.model_dump()

            # Generate Interview Plan
            interview_plan = generate_interview_plan(
                assessment.interview_duration_mins, jd_analysis.skills, focus_areas
            )
            assessment.interview_plan = interview_plan.model_dump()

            # Set status to ACTIVE
            assessment.status = "ACTIVE"
            await session.commit()
            logger.info(
                "Successfully processed assessment %s asynchronously.", assessment_id
            )
        except Exception:
            logger.exception(
                "Failed to process assessment %s in background.", assessment_id
            )
            try:
                # Set status to CLOSED to signal failure
                repo = AssessmentRepository(session)
                assessment = await repo.get_by_id(assessment_id)
                if assessment:
                    assessment.status = "CLOSED"
                    await session.commit()
            except Exception:
                logger.exception(
                    "Failed to update status to CLOSED after error on assessment %s",
                    assessment_id,
                )
