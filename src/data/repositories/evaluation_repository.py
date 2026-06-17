"""Repository for interview evaluation records."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.interview_evaluation import InterviewEvaluation

logger = logging.getLogger(__name__)


class EvaluationRepository:
    """Read access layer for interview_evaluation records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_candidate_assessment_id(
        self, candidate_assessment_id: uuid.UUID
    ) -> InterviewEvaluation | None:
        """Return the holistic evaluation report for a given candidate assessment."""
        statement = select(InterviewEvaluation).where(
            InterviewEvaluation.candidate_assessment_id == candidate_assessment_id
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
