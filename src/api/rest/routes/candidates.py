"""Candidate REST routes — bulk CSV upload and candidate listing."""

import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import AuthenticationException, BadRequestException
from src.core.services.candidate_service import CandidateService
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_full_repository import (
    CandidateAssessmentFullRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.csv_upload_log_repository import CSVUploadLogRepository
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    SingleCandidateResponse,
)
from src.schemas.common import APIResponse
from src.schemas.evaluation import InterviewEvaluationResponse

router = APIRouter(prefix="/candidates", tags=["candidates"])
logger = logging.getLogger(__name__)


def get_candidate_service(
    session: AsyncSession = Depends(get_db_session),
) -> CandidateService:
    """Build the candidate service from request-scoped dependencies."""
    return CandidateService(
        candidate_repo=CandidateRepository(session),
        ca_repo=CandidateAssessmentFullRepository(session),
        assessment_repo=AssessmentRepository(session),
        upload_log_repo=CSVUploadLogRepository(session),
        notification_log_repo=NotificationLogRepository(session),
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
    background_tasks: BackgroundTasks,
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
            "Missing identity header — ensure request passes through the gateway."
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
            f"CSV processed: {result.successful_rows} candidate(s) invited, "
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
        message="Candidate created and invitation dispatched.",
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
    description="Return all candidate-assessment records for the given assessment ID.",
)
async def list_candidates(
    assessment_id: uuid.UUID,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[list[CandidateAssessmentListItem]]:
    """Return all candidates registered under a specific assessment."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header — ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    ca_records = await service.get_candidates_for_assessment(
        assessment_id, recruiter_id
    )

    return APIResponse(
        message="Candidates retrieved successfully.",
        data=[
            CandidateAssessmentListItem.from_orm_with_candidate(ca) for ca in ca_records
        ],
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
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[InterviewEvaluationResponse]:
    """Fetch the evaluation report."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")

    # In a real app we'd verify the recruiter owns the assessment for this ca_id.

    eval_repo = EvaluationRepository(session)
    evaluation = await eval_repo.get_by_candidate_assessment_id(ca_id)

    if not evaluation:
        from src.core.exceptions import NotFoundException

        raise NotFoundException("Evaluation not found for this candidate.")

    return APIResponse(
        message="Evaluation retrieved successfully.",
        data=InterviewEvaluationResponse.model_validate(
            evaluation, from_attributes=True
        ),
    )
