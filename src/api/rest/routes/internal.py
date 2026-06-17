"""Internal API endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import NotFoundException
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
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
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[CandidateTokenValidationResponse]:
    """Validate token and return candidate_id and assessment_id."""
    repo = CandidateAssessmentRepository(session)
    candidate_assessment = await repo.get_by_invitation_token(token)
    if candidate_assessment is None:
        raise NotFoundException("Candidate invitation token not found.")

    data = CandidateTokenValidationResponse(
        candidate_id=candidate_assessment.candidate_id,
        assessment_id=candidate_assessment.id,
    )
    return APIResponse(
        message="Token validation successful.",
        data=data,
    )
