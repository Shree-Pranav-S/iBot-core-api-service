"""Repository for full candidate_assessment CRUD operations."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data.models.postgres.candidate_assessment import CandidateAssessment

logger = logging.getLogger(__name__)


class CandidateAssessmentFullRepository:
    """Full CRUD access layer for candidate_assessment records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_invitation_token(
        self, token: uuid.UUID
    ) -> CandidateAssessment | None:
        """Return a CandidateAssessment row matching the invitation token."""
        statement = select(CandidateAssessment).where(
            CandidateAssessment.invitation_token == token
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_candidate_and_assessment(
        self, candidate_id: uuid.UUID, assessment_id: uuid.UUID
    ) -> CandidateAssessment | None:
        """Return an existing link between a candidate and an assessment."""
        statement = select(CandidateAssessment).where(
            CandidateAssessment.candidate_id == candidate_id,
            CandidateAssessment.assessment_id == assessment_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all_by_assessment(
        self, assessment_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessment links for a given assessment, with candidate data loaded."""
        statement = (
            select(CandidateAssessment)
            .options(selectinload(CandidateAssessment.candidate))
            .where(CandidateAssessment.assessment_id == assessment_id)
            .order_by(CandidateAssessment.created_at.desc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        candidate_id: uuid.UUID,
        assessment_id: uuid.UUID,
        resume_file_path: str,
    ) -> CandidateAssessment:
        """Create and flush a new candidate-assessment link."""
        ca = CandidateAssessment(
            candidate_id=candidate_id,
            assessment_id=assessment_id,
            resume_file_path=resume_file_path,
            status="INVITED",
            resume_parse_status="PENDING",
            recruiter_decision="PENDING",
        )
        self._session.add(ca)
        await self._session.flush()
        await self._session.refresh(ca)
        logger.info(
            "CandidateAssessment created",
            extra={
                "candidate_assessment_id": str(ca.id),
                "candidate_id": str(candidate_id),
                "assessment_id": str(assessment_id),
            },
        )
        return ca
