"""Repository for candidate assessment data access."""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data.models.postgres.candidate_assessment import CandidateAssessment

logger = logging.getLogger(__name__)


class CandidateAssessmentRepository:
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
        """Return all candidate-assessment links for a given assessment, with candidate and assessment data loaded."""
        statement = (
            select(CandidateAssessment)
            .options(
                selectinload(CandidateAssessment.candidate),
                selectinload(CandidateAssessment.assessment),
            )
            .where(CandidateAssessment.assessment_id == assessment_id)
            .order_by(CandidateAssessment.created_at.desc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_all_by_recruiter(
        self, recruiter_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessment links for all assessments of a given recruiter, with candidate and assessment loaded."""
        from src.data.models.postgres.assessment import Assessment

        statement = (
            select(CandidateAssessment)
            .join(Assessment, CandidateAssessment.assessment_id == Assessment.id)
            .options(
                selectinload(CandidateAssessment.candidate),
                selectinload(CandidateAssessment.assessment),
            )
            .where(Assessment.recruiter_id == recruiter_id)
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

    async def update_resume_parsing_result(
        self, ca_id: uuid.UUID, status: str, parsed_data: dict
    ) -> None:
        """Update the resume parsing status and results, with retry logic for async availability."""
        ca_record = None
        for _attempt in range(5):
            statement = select(CandidateAssessment).where(
                CandidateAssessment.id == ca_id
            )
            result = await self._session.execute(statement)
            ca_record = result.scalar_one_or_none()
            if ca_record:
                break
            await asyncio.sleep(0.5)

        if ca_record:
            ca_record.resume_parse_status = status
            ca_record.resume_parsed = parsed_data
            logger.info(
                "Updated resume parse result in DB for ca_record=%s",
                ca_id,
            )
        else:
            logger.error(
                "CandidateAssessment %s not found in database to update parsing results",
                ca_id,
            )

    async def save_parsed_resume_success(self, ca_record_id, parsed_data):
        await self.update_resume_parsing_result(
            ca_record_id, status="COMPLETED", parsed_data=parsed_data
        )
        await self._session.flush()

    async def save_parsed_resume_failed(self, ca_record_id, error_msg):
        await self.update_resume_parsing_result(
            ca_record_id,
            status="FAILED",
            parsed_data={
                "error": error_msg,
                "summary": "Failed to parse resume.",
                "skills": [],
                "experience_years": 0,
            },
        )
        await self._session.flush()

    async def get_by_id(self, ca_id: uuid.UUID) -> CandidateAssessment | None:
        """Return a CandidateAssessment by UUID with candidate and assessment loaded."""
        statement = (
            select(CandidateAssessment)
            .options(
                selectinload(CandidateAssessment.candidate),
                selectinload(CandidateAssessment.assessment),
            )
            .where(CandidateAssessment.id == ca_id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def update_recruiter_decision(
        self,
        ca: CandidateAssessment,
        *,
        decision: str,
        feedback: str | None = None,
    ) -> CandidateAssessment:
        """Persist the recruiter hiring decision for a candidate assessment."""
        ca.recruiter_decision = decision
        ca.recruiter_feedback = feedback
        await self._session.flush()
        await self._session.refresh(ca)
        return ca

    async def delete(self, ca: CandidateAssessment) -> None:
        """Delete a candidate assessment and its associated interview session."""
        from src.data.models.postgres.interview_session import InterviewSession

        statement = select(InterviewSession).where(
            InterviewSession.candidate_assessment_id == ca.id
        )
        result = await self._session.execute(statement)
        session_record = result.scalar_one_or_none()
        if session_record:
            await self._session.delete(session_record)

        await self._session.delete(ca)
        await self._session.flush()

    @classmethod
    async def save_parsed_resume_success_in_background(
        cls, ca_record_id: uuid.UUID, parsed_data: dict
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.save_parsed_resume_success(ca_record_id, parsed_data)
            await session.commit()

    @classmethod
    async def save_parsed_resume_failed_in_background(
        cls, ca_record_id: uuid.UUID, error_msg: str
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.save_parsed_resume_failed(ca_record_id, error_msg)
            await session.commit()

    @classmethod
    async def get_candidate_emails_for_assessment_in_background(
        cls, assessment_id: uuid.UUID
    ) -> list[dict]:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            ca_records = await repo.get_all_by_assessment(assessment_id)
            results = []
            for ca in ca_records:
                if ca.candidate and ca.candidate.email:
                    results.append(
                        {
                            "candidate_name": ca.candidate.full_name,
                            "recipient_email": ca.candidate.email,
                            "assessment_title": ca.assessment.title
                            if ca.assessment
                            else "",
                            "role_name": ca.assessment.role_name
                            if ca.assessment
                            else "",
                        }
                    )
            return results
