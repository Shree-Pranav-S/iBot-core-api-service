"""Repository for interview evaluation records."""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.candidate import Candidate
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.interview_evaluation import InterviewEvaluation
from src.data.models.postgres.interview_session import InterviewSession
from src.data.models.postgres.notification_log import NotificationLog
from src.data.models.postgres.recruiter import Recruiter
from src.schemas.evaluation_llm import FinalEvaluationRecord

logger = logging.getLogger(__name__)


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class EvaluationRepository:
    """Data access layer for interview_evaluation records."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the active database session."""
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

    async def load_evaluation_source(
        self,
        candidate_assessment_id: str | uuid.UUID,
    ) -> dict[str, Any] | None:
        """Load transcript, violations, JD, plan, and candidate context."""
        statement = (
            select(
                InterviewSession.id.label("session_id"),
                InterviewSession.candidate_assessment_id,
                InterviewSession.status.label("session_status"),
                InterviewSession.transcript,
                InterviewSession.violations,
                InterviewSession.total_elapsed_secs,
                InterviewSession.total_pause_secs,
                CandidateAssessment.assessment_id,
                CandidateAssessment.status.label("candidate_assessment_status"),
                Assessment.recruiter_id,
                Candidate.full_name.label("candidate_name"),
                Candidate.email.label("candidate_email"),
                Assessment.title.label("assessment_title"),
                Assessment.role_name,
                Assessment.jd_analysis,
                Assessment.interview_plan,
                Assessment.interview_duration_mins,
                func.coalesce(Recruiter.company_name, "").label("company_name"),
                func.coalesce(Recruiter.email, "").label("recruiter_email"),
            )
            .join(
                CandidateAssessment,
                CandidateAssessment.id == InterviewSession.candidate_assessment_id,
            )
            .join(
                Candidate,
                Candidate.id == CandidateAssessment.candidate_id,
            )
            .join(
                Assessment,
                Assessment.id == CandidateAssessment.assessment_id,
            )
            .outerjoin(Recruiter, Recruiter.id == Assessment.recruiter_id)
            .where(
                InterviewSession.candidate_assessment_id
                == _uuid(candidate_assessment_id)
            )
        )
        result = await self._session.execute(statement)
        row = result.mappings().first()
        return dict(row) if row else None

    async def evaluation_exists_for_hash(
        self,
        candidate_assessment_id: str | uuid.UUID,
        transcript_hash: str,
    ) -> bool:
        """Return whether this exact immutable context was evaluated."""
        statement = select(
            exists().where(
                InterviewEvaluation.candidate_assessment_id
                == _uuid(candidate_assessment_id),
                InterviewEvaluation.transcript_hash == transcript_hash,
            )
        )
        return bool((await self._session.execute(statement)).scalar_one())

    async def mark_evaluation_failed(
        self,
        candidate_assessment_id: str | uuid.UUID,
    ) -> None:
        """Persist terminal evaluation failure without changing candidate outcome."""
        statement = (
            update(InterviewSession)
            .where(
                InterviewSession.candidate_assessment_id
                == _uuid(candidate_assessment_id)
            )
            .where(InterviewSession.status != "EVALUATED")
            .values(status="EVALUATION_FAILED", last_updated_at=func.now())
        )
        await self._session.execute(statement)

    async def save_final_evaluation(
        self,
        record: FinalEvaluationRecord,
        *,
        recruiter_email: str,
    ) -> dict[str, Any]:
        """Save the report, lifecycle state, ranks, and dashboard notice."""
        values = record.model_dump(mode="python", exclude={"assessment_id"})
        values["candidate_assessment_id"] = _uuid(record.candidate_assessment_id)
        values["session_id"] = _uuid(record.session_id)

        insert_statement = insert(InterviewEvaluation).values(**values)
        update_values = {
            field: getattr(insert_statement.excluded, field)
            for field in values
            if field not in {"candidate_assessment_id"}
        }
        update_values["generated_at"] = func.now()
        await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=[
                    InterviewEvaluation.candidate_assessment_id,
                ],
                set_=update_values,
            )
        )

        await self._session.execute(
            update(InterviewSession)
            .where(InterviewSession.id == _uuid(record.session_id))
            .values(status="EVALUATED", last_updated_at=func.now())
        )
        await self._session.execute(
            update(CandidateAssessment)
            .where(
                CandidateAssessment.id == _uuid(record.candidate_assessment_id),
            )
            .values(
                status="EVALUATED",
                interview_ended_at=func.coalesce(
                    CandidateAssessment.interview_ended_at,
                    func.now(),
                ),
                updated_at=func.now(),
            )
        )

        notification = NotificationLog(
            candidate_assessment_id=_uuid(record.candidate_assessment_id),
            notification_type="REPORT_READY",
            recipient_email=recruiter_email,
            delivery_status="SENT",
        )
        self._session.add(notification)
        await self._session.flush()
        await self._session.refresh(notification)

        await self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(str(record.assessment_id)),
                )
            )
        )
        await self._refresh_assessment_ranking(_uuid(record.assessment_id))
        return {"id": notification.id, "sent_at": notification.sent_at}

    async def _refresh_assessment_ranking(self, assessment_id: uuid.UUID) -> None:
        statement = (
            select(InterviewEvaluation)
            .join(
                CandidateAssessment,
                CandidateAssessment.id == InterviewEvaluation.candidate_assessment_id,
            )
            .where(CandidateAssessment.assessment_id == assessment_id)
            .order_by(
                InterviewEvaluation.overall_score.desc(),
                InterviewEvaluation.generated_at.asc(),
            )
            .with_for_update()
        )
        evaluations = list((await self._session.execute(statement)).scalars().all())
        total = len(evaluations)
        for rank, evaluation in enumerate(evaluations, start=1):
            evaluation.rank_in_assessment = rank
            evaluation.total_candidates_evaluated = total
            evaluation.percentile_in_assessment = (
                100
                if total <= 1
                else math.floor(((total - rank) / (total - 1)) * 100 + 0.5)
            )
        await self._session.flush()
