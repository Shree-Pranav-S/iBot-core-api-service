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
