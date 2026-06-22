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

    async def list_by_recruiter(
        self, recruiter_id: uuid.UUID
    ) -> list[tuple[InterviewEvaluation, object, object, object]]:
        """Return evaluated interviews for all assessments owned by a recruiter."""
        from src.data.models.postgres.assessment import Assessment
        from src.data.models.postgres.candidate import Candidate
        from src.data.models.postgres.candidate_assessment import CandidateAssessment

        statement = (
            select(InterviewEvaluation, CandidateAssessment, Candidate, Assessment)
            .join(
                CandidateAssessment,
                InterviewEvaluation.candidate_assessment_id == CandidateAssessment.id,
            )
            .join(Candidate, CandidateAssessment.candidate_id == Candidate.id)
            .join(Assessment, CandidateAssessment.assessment_id == Assessment.id)
            .where(Assessment.recruiter_id == recruiter_id)
            .order_by(InterviewEvaluation.generated_at.desc())
        )
        result = await self._session.execute(statement)
        return [row.tuple() for row in result.all()]
