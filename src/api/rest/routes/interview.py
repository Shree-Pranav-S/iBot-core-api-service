"""Interview REST routes — candidate token validation and waiting room details."""

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import NotFoundException
from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.schemas.candidate import TokenValidationResponse
from src.schemas.common import APIResponse

router = APIRouter(prefix="/interview", tags=["interview"])
logger = logging.getLogger(__name__)


@router.get(
    "/validate-token",
    response_model=APIResponse[TokenValidationResponse],
    summary="Validate candidate invitation token",
    description="Validates candidate invitation token and returns metadata for waiting room.",
)
async def validate_token(
    token: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[TokenValidationResponse]:
    """Validate candidate's token and return details for the waiting room."""
    # Query candidate assessment, eager loading candidate and assessment
    stmt = (
        select(CandidateAssessment)
        .options(
            selectinload(CandidateAssessment.candidate),
            selectinload(CandidateAssessment.assessment).selectinload(
                Assessment.recruiter
            ),
        )
        .where(CandidateAssessment.invitation_token == token)
    )
    result = await session.execute(stmt)
    ca = result.scalar_one_or_none()

    if ca is None:
        raise NotFoundException("Candidate invitation token not found.")

    candidate = ca.candidate
    assessment = ca.assessment

    if candidate is None or assessment is None:
        raise NotFoundException(
            "Candidate or assessment not found for this invitation."
        )

    # Extract sections_overview from the interview plan
    sections_overview = []
    if assessment.interview_plan and "sections" in assessment.interview_plan:
        sections_overview = [
            s.get("section_name")
            for s in assessment.interview_plan["sections"]
            if s.get("section_name")
        ]

    data = TokenValidationResponse(
        candidate_name=candidate.full_name,
        company_name=(
            assessment.recruiter.company_name
            if assessment.recruiter is not None
            else "the company"
        ),
        assessment_title=assessment.title,
        interview_duration_mins=assessment.interview_duration_mins,
        window_end=assessment.window_end,
        status=ca.status,
        sections_overview=sections_overview,
    )

    return APIResponse(
        message="Token validated successfully.",
        data=data,
    )
