"""Internal API endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends

from src.api.rest.dependencies import UnitOfWork, get_unit_of_work
from src.core.exceptions import NotFoundException
from src.schemas.candidate import CandidateTokenValidationResponse
from src.schemas.common import APIResponse

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger(__name__)


@router.get(
    "/validate-candidate-token",
    response_model=APIResponse[CandidateTokenValidationResponse],
    summary="Validate candidate invitation token",
    description="Allows internal microservices (like the Gateway) to resolve a candidate's token.",
)
async def validate_candidate_token(
    token: uuid.UUID,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[CandidateTokenValidationResponse]:
    """Validate token and return candidate and assessment identifiers."""
    candidate_assessment = (
        await unit_of_work.candidate_assessments.get_by_invitation_token(token)
    )
    if candidate_assessment is None:
        raise NotFoundException("Candidate invitation token not found.")

    data = CandidateTokenValidationResponse(
        candidate_id=candidate_assessment.candidate_id,
        assessment_id=candidate_assessment.assessment_id,
        candidate_assessment_id=candidate_assessment.id,
    )
    return APIResponse(
        message="Token validation successful.",
        data=data,
    )
