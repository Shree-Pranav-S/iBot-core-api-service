"""Evaluation REST routes for recruiter-facing reports and transcripts."""

import uuid

from fastapi import APIRouter, Depends

from src.api.rest.dependencies import get_evaluation_service, require_recruiter_id
from src.core.services.evaluation_service import EvaluationService
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


@router.get(
    "",
    response_model=APIResponse[list[RecruiterEvaluationListItem]],
    summary="List recruiter evaluations",
    description="Return all completed interview evaluations for assessments owned by the recruiter.",
)
async def list_recruiter_evaluations(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    """Return recruiter-owned candidate evaluations for the dashboard."""
    evaluations = await service.list_recruiter_evaluations(recruiter_id)
    return APIResponse(
        message="Evaluations retrieved successfully.",
        data=evaluations,
    )


@router.get(
    "/{ca_id}",
    response_model=APIResponse[InterviewEvaluationResponse],
    summary="Get candidate evaluation report",
    description="Return the full holistic evaluation report for a candidate.",
)
async def get_candidate_evaluation(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewEvaluationResponse]:
    """Fetch the evaluation report."""
    evaluation = await service.get_candidate_evaluation(ca_id, recruiter_id)
    return APIResponse(
        message="Evaluation retrieved successfully.",
        data=evaluation,
    )


@router.get(
    "/{ca_id}/transcript",
    response_model=APIResponse[InterviewTranscriptResponse],
    summary="Get interview transcript",
    description="Return the full interview transcript for a candidate assessment, if an interview session exists.",
)
async def get_interview_transcript(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewTranscriptResponse]:
    """Fetch the interview transcript for a candidate."""
    transcript = await service.get_interview_transcript(ca_id, recruiter_id)
    return APIResponse(
        message="Transcript retrieved successfully.",
        data=transcript,
    )


@router.post(
    "/{ca_id}/rejection-feedback",
    response_model=APIResponse[AIRejectionFeedbackResponse],
    summary="Generate rejection feedback",
    description="Draft editable, candidate-facing rejection feedback from evaluation evidence.",
)
async def create_rejection_feedback(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[AIRejectionFeedbackResponse]:
    """Generate a recruiter-editable rejection feedback draft."""
    feedback = await service.create_rejection_feedback(ca_id, recruiter_id)
    return APIResponse(
        message="Rejection feedback draft generated successfully.",
        data=feedback,
    )


@candidate_compat_router.get(
    "/evaluations",
    response_model=APIResponse[list[RecruiterEvaluationListItem]],
)
async def list_recruiter_evaluations_legacy(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    """Legacy alias for GET /evaluations."""
    return await list_recruiter_evaluations(recruiter_id, service)


@candidate_compat_router.get(
    "/{ca_id}/evaluation",
    response_model=APIResponse[InterviewEvaluationResponse],
)
async def get_candidate_evaluation_legacy(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewEvaluationResponse]:
    """Legacy alias for GET /evaluations/{ca_id}."""
    return await get_candidate_evaluation(ca_id, recruiter_id, service)


@candidate_compat_router.get(
    "/{ca_id}/transcript",
    response_model=APIResponse[InterviewTranscriptResponse],
)
async def get_interview_transcript_legacy(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[InterviewTranscriptResponse]:
    """Legacy alias for GET /evaluations/{ca_id}/transcript."""
    return await get_interview_transcript(ca_id, recruiter_id, service)


@candidate_compat_router.post(
    "/{ca_id}/rejection-feedback",
    response_model=APIResponse[AIRejectionFeedbackResponse],
)
async def create_rejection_feedback_legacy(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: EvaluationService = Depends(get_evaluation_service),
) -> APIResponse[AIRejectionFeedbackResponse]:
    """Legacy alias for POST /evaluations/{ca_id}/rejection-feedback."""
    return await create_rejection_feedback(ca_id, recruiter_id, service)
