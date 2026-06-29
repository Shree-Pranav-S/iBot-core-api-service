"""Interview REST routes — candidate token validation and waiting room details."""

import logging
import uuid

from fastapi import APIRouter, Depends

from src.api.rest.dependencies import UnitOfWork, get_unit_of_work
from src.core.exceptions import NotFoundException
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[TokenValidationResponse]:
    """Validate candidate's token and return details for the waiting room."""
    ca = await unit_of_work.candidate_assessments.get_invitation_context(token)

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
