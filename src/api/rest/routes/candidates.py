"""Candidate REST routes - bulk CSV upload and candidate listing."""

import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    UploadFile,
    status,
)

from src.api.rest.dependencies import UnitOfWork, get_unit_of_work
from src.core.exceptions import AuthenticationException, BadRequestException
from src.core.services.candidate_service import CandidateService
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    SingleCandidateResponse,
)
from src.schemas.common import APIResponse
from src.schemas.evaluation import (
    InterviewEvaluationResponse,
    RecruiterEvaluationListItem,
)

router = APIRouter(prefix="/candidates", tags=["candidates"])
logger = logging.getLogger(__name__)


def get_candidate_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> CandidateService:
    """Build the candidate service from request-scoped dependencies."""
    return CandidateService(
        candidate_repo=unit_of_work.candidates,
        ca_repo=unit_of_work.candidate_assessments,
        assessment_repo=unit_of_work.assessments,
        event_logs_repo=unit_of_work.event_logs,
    )


@router.post(
    "/bulk-upload",
    response_model=APIResponse[BulkUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk upload candidates from CSV",
    description=(
        "Upload a CSV file containing candidate records. "
        "Each row must have columns: name, email, resume, role. "
        "Candidates are matched to active assessments by role name (case-insensitive) "
        "and receive an invitation email with their unique interview link."
    ),
)
async def bulk_upload_candidates(
    csv_file: UploadFile = File(
        ...,
        description="CSV file with columns: name, email, resume, role",
    ),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[BulkUploadResponse]:
    """Process a CSV bulk upload, create candidates, and dispatch invitation emails."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header - ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    if not csv_file.filename or not csv_file.filename.lower().endswith(".csv"):
        raise BadRequestException("Uploaded file must be a CSV (.csv extension).")

    file_bytes = await csv_file.read()
    if not file_bytes:
        raise BadRequestException("Uploaded CSV file is empty.")

    result = await service.bulk_upload_from_csv(
        recruiter_id=recruiter_id,
        file_bytes=file_bytes,
        filename=csv_file.filename,
    )

    return APIResponse(
        message=(
            f"CSV processed: {result.successful_rows} candidate invitation(s) queued, "
            f"{result.failed_rows} failed."
        ),
        data=result,
    )


@router.post(
    "/manual",
    response_model=APIResponse[SingleCandidateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a single candidate manually",
    description="Upload a candidate with their resume PDF manually.",
)
async def create_single_candidate_manual(
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    resume: UploadFile = File(...),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[SingleCandidateResponse]:
    """Process a manual candidate creation."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise BadRequestException("Uploaded resume must be a PDF (.pdf extension).")

    file_bytes = await resume.read()
    if not file_bytes:
        raise BadRequestException("Uploaded resume file is empty.")

    ca_record = await service.create_single_candidate(
        recruiter_id=recruiter_id,
        name=name,
        email=email,
        role=role,
        resume_file_bytes=file_bytes,
        resume_filename=resume.filename,
    )

    return APIResponse(
        message="Candidate created and invitation queued.",
        data=SingleCandidateResponse(
            candidate_assessment_id=ca_record.id,
            candidate_id=ca_record.candidate_id,
            full_name=name,
            email=email,
            status=ca_record.status,
        ),
    )


@router.get(
    "",
    response_model=APIResponse[list[CandidateAssessmentListItem]],
    summary="List candidates for an assessment",
    description="Return all candidate-assessment records for the given assessment ID. If assessment_id is not specified, return all candidates for the recruiter.",
)
async def list_candidates(
    assessment_id: uuid.UUID | None = None,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[list[CandidateAssessmentListItem]]:
    """Return candidates registered under a specific assessment, or all candidates for the recruiter."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header - ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    if assessment_id:
        ca_records = await service.get_candidates_for_assessment(
            assessment_id, recruiter_id
        )
    else:
        ca_records = await service.get_all_candidates_for_recruiter(recruiter_id)

    return APIResponse(
        message="Candidates retrieved successfully.",
        data=[
            CandidateAssessmentListItem.from_orm_with_candidate(ca) for ca in ca_records
        ],
    )


@router.get(
    "/evaluations",
    response_model=APIResponse[list[RecruiterEvaluationListItem]],
    summary="List evaluated interviews for recruiter",
    description="Return all completed interview evaluations for assessments owned by the recruiter.",
)
async def list_recruiter_evaluations(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[list[RecruiterEvaluationListItem]]:
    """Return recruiter-owned candidate evaluations for the dashboard."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    rows = await unit_of_work.evaluations.list_by_recruiter(recruiter_id)

    data: list[RecruiterEvaluationListItem] = []
    for evaluation, ca, candidate, assessment in rows:
        validated_violation_count = 0
        if isinstance(evaluation.violation_summary, dict):
            validated_violation_count = int(
                evaluation.violation_summary.get(
                    "validated_violation_count",
                    0,
                )
                or 0
            )
        data.append(
            RecruiterEvaluationListItem(
                candidate_assessment_id=ca.id,
                candidate_name=candidate.full_name,
                candidate_email=candidate.email,
                assessment_id=assessment.id,
                assessment_title=assessment.title,
                role_name=assessment.role_name,
                recruiter_decision=ca.recruiter_decision,
                interview_started_at=ca.interview_started_at,
                interview_ended_at=ca.interview_ended_at,
                generated_at=evaluation.generated_at,
                overall_score=evaluation.overall_score,
                hiring_recommendation=evaluation.hiring_recommendation,
                recommendation_reasoning=evaluation.recommendation_reasoning,
                overall_summary=evaluation.overall_summary,
                overall_technical_skill_score=(
                    evaluation.overall_technical_skill_score
                ),
                behavioural_cultural_score=(evaluation.behavioural_cultural_score),
                communication_score=evaluation.communication_score,
                rank_in_assessment=evaluation.rank_in_assessment,
                percentile_in_assessment=evaluation.percentile_in_assessment,
                total_candidates_evaluated=evaluation.total_candidates_evaluated,
                strengths=evaluation.strengths,
                concerns=evaluation.concerns,
                validated_violation_count=validated_violation_count,
                skill_scores=evaluation.skill_scores,
            )
        )

    return APIResponse(
        message="Evaluations retrieved successfully.",
        data=data,
    )


@router.post(
    "/{ca_id}/decision",
    response_model=APIResponse[RecruiterDecisionResponse],
    summary="Update recruiter hiring decision",
    description="Approve or reject a candidate after reviewing their evaluation.",
)
async def update_recruiter_decision(
    ca_id: uuid.UUID,
    payload: RecruiterDecisionRequest,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[RecruiterDecisionResponse]:
    """Persist the recruiter decision for a candidate assessment."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    ca = await service.update_recruiter_decision(
        ca_id=ca_id,
        recruiter_id=recruiter_id,
        decision=payload.decision,
        feedback=payload.feedback,
    )

    return APIResponse(
        message="Recruiter decision updated successfully. Candidate email queued.",
        data=RecruiterDecisionResponse(
            candidate_assessment_id=ca.id,
            recruiter_decision=ca.recruiter_decision,
            updated_at=ca.updated_at,
        ),
    )


@router.get(
    "/{ca_id}/evaluation",
    response_model=APIResponse[InterviewEvaluationResponse],
    summary="Get candidate evaluation report",
    description="Return the full holistic evaluation report for a candidate.",
)
async def get_candidate_evaluation(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[InterviewEvaluationResponse]:
    """Fetch the evaluation report."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    ca = await unit_of_work.candidate_assessments.get_by_id(ca_id)
    if ca is None:
        from src.core.exceptions import NotFoundException

        raise NotFoundException("Candidate registration not found.")
    if ca.assessment.recruiter_id != recruiter_id:
        from src.core.exceptions import ForbiddenException

        raise ForbiddenException("You do not have access to this evaluation.")

    evaluation = await unit_of_work.evaluations.get_by_candidate_assessment_id(ca_id)

    if not evaluation:
        from src.core.exceptions import NotFoundException

        raise NotFoundException("Evaluation not found for this candidate.")

    response = InterviewEvaluationResponse.model_validate(
        evaluation,
        from_attributes=True,
    )
    response.candidate_name = ca.candidate.full_name if ca.candidate else None
    response.candidate_email = ca.candidate.email if ca.candidate else None
    response.assessment_title = ca.assessment.title if ca.assessment else None
    response.role_name = ca.assessment.role_name if ca.assessment else None
    response.recruiter_decision = ca.recruiter_decision
    response.recruiter_feedback = ca.recruiter_feedback

    return APIResponse(
        message="Evaluation retrieved successfully.",
        data=response,
    )


@router.delete(
    "/{ca_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete candidate from assessment",
    description="Remove a candidate registration from an assessment and delete their interview session.",
)
async def delete_candidate(
    ca_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[None]:
    """Delete a candidate registration from an assessment."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    await service.delete_candidate_from_assessment(ca_id, recruiter_id)
    return APIResponse(
        message="Candidate removed from assessment successfully.",
        data=None,
    )
