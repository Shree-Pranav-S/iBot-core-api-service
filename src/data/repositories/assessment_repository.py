"""Repository for assessment data access."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres_client import register_after_commit_callback
from src.data.models.postgres.assessment import Assessment

logger = logging.getLogger(__name__)


class AssessmentRepository:
    """Data access layer for creating and retrieving recruiter assessments."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the active database session."""
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

    def register_after_commit_callback(self, callback: Callable[[], None]) -> None:
        """Register work that must run after the current transaction commits."""
        register_after_commit_callback(self._session, callback)

    async def activate_assessment(
        self,
        assessment_id: uuid.UUID,
        jd_text: str,
        jd_analysis: dict,
        interview_plan: dict,
    ) -> str:
        """Persist generated analysis without reopening closed or expired work."""

        final_status = case(
            (Assessment.status == "CLOSED", "CLOSED"),
            (Assessment.window_end <= func.now(), "CLOSED"),
            else_="ACTIVE",
        )
        result = await self._session.execute(
            update(Assessment)
            .where(Assessment.id == assessment_id)
            .values(
                jd_text=jd_text,
                jd_analysis=jd_analysis,
                interview_plan=interview_plan,
                status=final_status,
                updated_at=func.now(),
            )
            .returning(Assessment.status)
        )
        status = result.scalar_one_or_none()
        if status is None:
            logger.warning(
                "Assessment %s disappeared during activation.", assessment_id
            )
            return "CLOSED"
        await self._session.flush()
        logger.info(
            "Assessment %s processing completed with status %s.",
            assessment_id,
            status,
        )
        return str(status)

    async def close_expired_assessments(self) -> list[dict[str, Any]]:
        """Atomically close every assessment whose interview window has ended."""

        result = await self._session.execute(
            update(Assessment)
            .where(Assessment.status != "CLOSED")
            .where(Assessment.window_end <= func.now())
            .values(status="CLOSED", updated_at=func.now())
            .returning(
                Assessment.id,
                Assessment.recruiter_id,
                Assessment.title,
                Assessment.role_name,
            )
        )
        expired = [dict(row) for row in result.mappings().all()]
        if expired:
            await self._session.flush()
            logger.info("Closed %s expired assessments.", len(expired))
        return expired

    async def close_assessment_on_failure(self, assessment_id: uuid.UUID) -> None:
        """Close an assessment whose background processing failed."""
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
