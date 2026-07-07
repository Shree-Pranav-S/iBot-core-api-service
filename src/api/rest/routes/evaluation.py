"""Evaluation REST routes for recruiter-facing reports and transcripts."""

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import AuthenticationException, BadRequestException
from src.core.services.evaluation_service import EvaluationService
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)
from src.schemas.candidate import (
    AIRejectionFeedbackResponse,
    InterviewTranscriptResponse,
)
from src.schemas.common import APIResponse
from src.schemas.evaluation import (
    InterviewEvaluationResponse,
    RecruiterEvaluationListItem,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
candidate_compat_router = APIRouter(
    prefix="/candidates",
    tags=["evaluations"],
    include_in_schema=False,
)


def get_evaluation_service(
    db: AsyncSession = Depends(get_db_session),
) -> EvaluationService:
    """Build the evaluation service from request-scoped dependencies."""
    return EvaluationService(
        candidate_assessment_repo=CandidateAssessmentRepository(db),
        evaluation_repo=EvaluationRepository(db),
        session_repo=InterviewSessionRepository(db),
    )


def _recruiter_id_from_header(x_user_id: str | None) -> uuid.UUID:
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        return uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")


async def _list_recruiter_evaluations_response(
    x_user_id: str | None,
    service: EvaluationService,
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    recruiter_id = _recruiter_id_from_header(x_user_id)
    evaluations = await service.list_recruiter_evaluations(recruiter_id)
    return APIResponse(
        message="Evaluations retrieved successfully.",
        data=evaluations,
    )


async def _candidate_evaluation_response(
    ca_id: uuid.UUID,
    x_user_id: str | None,
    service: EvaluationService,
) -> APIResponse[InterviewEvaluationResponse]:
    recruiter_id = _recruiter_id_from_header(x_user_id)
    evaluation = await service.get_candidate_evaluation(ca_id, recruiter_id)
    return APIResponse(
        message="Evaluation retrieved successfully.",
        data=evaluation,
    )


async def _interview_transcript_response(
    ca_id: uuid.UUID,
    x_user_id: str | None,
    service: EvaluationService,
) -> APIResponse[InterviewTranscriptResponse]:
    recruiter_id = _recruiter_id_from_header(x_user_id)
    transcript = await service.get_interview_transcript(ca_id, recruiter_id)
    return APIResponse(
        message="Transcript retrieved successfully.",
        data=transcript,
    )


async def _rejection_feedback_response(
    ca_id: uuid.UUID,
    x_user_id: str | None,
    service: EvaluationService,
) -> APIResponse[AIRejectionFeedbackResponse]:
    recruiter_id = _recruiter_id_from_header(x_user_id)
    feedback = await service.create_rejection_feedback(ca_id, recruiter_id)
    return APIResponse(
        message="Rejection feedback draft generated successfully.",
        data=feedback,
    )


@router.get(
    "",
    response_model=APIResponse[list[RecruiterEvaluationListItem]],
    summary="List recruiter evaluations",
    description="Return all completed interview evaluations for assessments owned by the recruiter.",
)
async def list_recruiter_evaluations(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    """Return recruiter-owned candidate evaluations for the dashboard."""
    return await _list_recruiter_evaluations_response(x_user_id, service)


@router.get(
    "/{ca_id}",
    response_model=APIResponse[InterviewEvaluationResponse],
    summary="Get candidate evaluation report",
    description="Return the full holistic evaluation report for a candidate.",
)
async def get_candidate_evaluation(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewEvaluationResponse]:
    """Fetch the evaluation report."""
    return await _candidate_evaluation_response(ca_id, x_user_id, service)


@router.get(
    "/{ca_id}/transcript",
    response_model=APIResponse[InterviewTranscriptResponse],
    summary="Get interview transcript",
    description="Return the full interview transcript for a candidate assessment, if an interview session exists.",
)
async def get_interview_transcript(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewTranscriptResponse]:
    """Fetch the interview transcript for a candidate."""
    return await _interview_transcript_response(ca_id, x_user_id, service)


@router.post(
    "/{ca_id}/rejection-feedback",
    response_model=APIResponse[AIRejectionFeedbackResponse],
    summary="Generate rejection feedback",
    description="Draft editable, candidate-facing rejection feedback from evaluation evidence.",
)
async def create_rejection_feedback(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[AIRejectionFeedbackResponse]:
    """Generate a recruiter-editable rejection feedback draft."""
    return await _rejection_feedback_response(ca_id, x_user_id, service)


@candidate_compat_router.get(
    "/evaluations",
    response_model=APIResponse[list[RecruiterEvaluationListItem]],
)
async def list_recruiter_evaluations_legacy(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    """Legacy alias for GET /evaluations."""
    return await _list_recruiter_evaluations_response(x_user_id, service)


@candidate_compat_router.get(
    "/{ca_id}/evaluation",
    response_model=APIResponse[InterviewEvaluationResponse],
)
async def get_candidate_evaluation_legacy(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewEvaluationResponse]:
    """Legacy alias for GET /evaluations/{ca_id}."""
    return await _candidate_evaluation_response(ca_id, x_user_id, service)


@candidate_compat_router.get(
    "/{ca_id}/transcript",
    response_model=APIResponse[InterviewTranscriptResponse],
)
async def get_interview_transcript_legacy(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewTranscriptResponse]:
    """Legacy alias for GET /evaluations/{ca_id}/transcript."""
    return await _interview_transcript_response(ca_id, x_user_id, service)


@candidate_compat_router.post(
    "/{ca_id}/rejection-feedback",
    response_model=APIResponse[AIRejectionFeedbackResponse],
)
async def create_rejection_feedback_legacy(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[AIRejectionFeedbackResponse]:
    """Legacy alias for POST /evaluations/{ca_id}/rejection-feedback."""
    return await _rejection_feedback_response(ca_id, x_user_id, service)
