"""Repository for assessment data access."""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres_client import register_after_commit_callback
from src.data.models.postgres.assessment import Assessment

logger = logging.getLogger(__name__)


class AssessmentRepository:
    """Data access layer for creating and retrieving recruiter assessments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, assessment_id: uuid.UUID) -> Assessment | None:
        """Return an Assessment by its UUID."""
        statement = select(Assessment).where(Assessment.id == assessment_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def check_role_name_exists(
        self, recruiter_id: uuid.UUID, role_name: str
    ) -> bool:
        """Check if an assessment with the given role name already exists for this recruiter (case-insensitive)."""
        statement = select(
            select(Assessment)
            .where(
                Assessment.recruiter_id == recruiter_id,
                func.lower(Assessment.role_name) == role_name.strip().lower(),
            )
            .exists()
        )
        result = await self._session.execute(statement)
        return result.scalar() or False

    async def get_all_by_recruiter(self, recruiter_id: uuid.UUID) -> list[Assessment]:
        """Return all assessments owned by the specified recruiter, ordered by creation date descending."""
        statement = (
            select(Assessment)
            .where(Assessment.recruiter_id == recruiter_id)
            .order_by(Assessment.created_at.desc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def create_assessment(self, assessment: Assessment) -> Assessment:
        """Add and flush an Assessment record to the database."""
        self._session.add(assessment)
        await self._session.flush()
        await self._session.refresh(assessment)
        logger.info("Assessment created", extra={"assessment_id": str(assessment.id)})
        return assessment

    def register_after_commit_callback(self, callback: Callable[[], None]) -> None:
        """Register work that must run after the current transaction commits."""
        register_after_commit_callback(self._session, callback)

    async def activate_assessment(
        self,
        assessment_id: uuid.UUID,
        jd_text: str,
        jd_analysis: dict,
        interview_plan: dict,
    ) -> None:
        assessment = await self.get_by_id(assessment_id)
        if assessment:
            assessment.jd_text = jd_text
            assessment.jd_analysis = jd_analysis
            assessment.interview_plan = interview_plan
            assessment.status = "ACTIVE"
            await self._session.flush()
            logger.info("Assessment %s activated with commit.", assessment_id)

    async def close_assessment_on_failure(self, assessment_id: uuid.UUID) -> None:
        assessment = await self.get_by_id(assessment_id)
        if assessment:
            assessment.status = "CLOSED"
            await self._session.flush()
            logger.info("Assessment %s closed on failure with commit.", assessment_id)

    async def update_status(self, assessment: Assessment, status: str) -> Assessment:
        """Update and persist the assessment status."""
        assessment.status = status
        await self._session.flush()
        await self._session.refresh(assessment)
        return assessment
