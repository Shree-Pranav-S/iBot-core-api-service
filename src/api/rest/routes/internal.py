"""
Internal endpoints — only reachable from within the Docker network.

These routes are blocked at the gateway for external traffic
(BLOCKED_ROUTES includes "/internal").  They are called service-to-service,
e.g. the gateway WS proxy calling validate-candidate-token before opening
the interview WebSocket.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get(
    "/validate-candidate-token",
    response_model=APIResponse[dict],
    summary="Validate candidate invitation token",
    description=(
        "Internal-only endpoint called by the gateway WS proxy to verify a "
        "candidate's one-time invitation token before establishing the interview "
        "WebSocket. Returns candidate_id and assessment_id on success."
    ),
)
async def validate_candidate_token(
    token: str = Query(..., description="Candidate invitation token (UUID)"),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Resolve an invitation token to candidate_id + assessment_id."""

    cleaned_token = token.strip(" +")
    try:
        token_uuid = uuid.UUID(cleaned_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token format.",
        )

    repo = CandidateAssessmentRepository(session)
    record = await repo.get_by_invitation_token(token_uuid)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or already used.",
        )

    return APIResponse(
        message="Token valid.",
        data={
            "candidate_id": str(record.candidate_id),
            "assessment_id": str(record.assessment_id),
        },
    )
