"""Repository for candidate assessment data access."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.candidate_assessment import CandidateAssessment

logger = logging.getLogger(__name__)


class CandidateAssessmentRepository:
    """Read-only access layer for candidate assessment tokens."""

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
