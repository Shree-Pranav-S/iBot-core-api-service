"""Repository for assessment data access."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    @classmethod
    async def activate_assessment_in_background(
        cls,
        assessment_id: uuid.UUID,
        jd_text: str,
        jd_analysis: dict,
        interview_plan: dict,
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.activate_assessment(
                assessment_id, jd_text, jd_analysis, interview_plan
            )
            await session.commit()

    @classmethod
    async def close_assessment_on_failure_in_background(
        cls, assessment_id: uuid.UUID
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.close_assessment_on_failure(assessment_id)
            await session.commit()
