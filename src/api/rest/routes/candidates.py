"""Candidate REST routes — bulk CSV upload and candidate listing."""

import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
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
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
)
from src.schemas.common import APIResponse

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
