"""Candidate REST routes - bulk CSV upload and candidate listing."""

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
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.exceptions import (
    AuthenticationException,
    BadRequestException,
)
from src.core.services.candidate_service import CandidateService
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    ExistingCandidateListItem,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    SingleCandidateResponse,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/candidates", tags=["candidates"])


def get_candidate_service(
    db: AsyncSession = Depends(get_db_session),
) -> CandidateService:
    """Build the candidate service from request-scoped dependencies."""
    return CandidateService(
        candidate_repo=CandidateRepository(db),
        ca_repo=CandidateAssessmentRepository(db),
        assessment_repo=AssessmentRepository(db),
        event_logs_repo=EventLogsRepository(db),
    )


@router.post(
    "/bulk-upload",
    response_model=APIResponse[BulkUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk upload candidates from CSV",
    description=(
        "Upload a CSV file containing candidate records. "
        "Each row must have columns: name, email, resume, assessment_id. "
        "Candidates are matched to assessments by assessment_id (UUID) "
        "and receive an invitation email with their unique interview link."
    ),
)
async def bulk_upload_candidates(
    csv_file: UploadFile = File(
        ...,
        description="CSV file with columns: name, email, resume, assessment_id",
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
    description="Upload a candidate with their resume PDF manually, selecting the assessment by ID.",
)
async def create_single_candidate_manual(
    name: str = Form(...),
    email: str = Form(...),
    assessment_id: str = Form(..., description="UUID of the target assessment"),
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

    try:
        assessment_uuid = uuid.UUID(assessment_id)
    except ValueError:
        raise BadRequestException(
            "Invalid assessment_id format — must be a valid UUID."
        )

    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise BadRequestException("Uploaded resume must be a PDF (.pdf extension).")

    file_bytes = await resume.read()
    if not file_bytes:
        raise BadRequestException("Uploaded resume file is empty.")

    ca_record = await service.create_single_candidate(
        recruiter_id=recruiter_id,
        name=name,
        email=email,
        assessment_id=assessment_uuid,
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
    "/all-candidates",
    response_model=APIResponse[list[ExistingCandidateListItem]],
    summary="List unique candidates for recruiter",
    description="Return all unique candidates (not per-assessment) created by the recruiter. Used for enrollment into additional assessments.",
)
async def list_unique_candidates(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[list[ExistingCandidateListItem]]:
    """Return all unique candidate records for the recruiter."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    candidates = await service.get_unique_candidates_for_recruiter(recruiter_id)
    return APIResponse(
        message="Candidates retrieved successfully.",
        data=[
            ExistingCandidateListItem(
                id=c.id,
                full_name=c.full_name,
                email=c.email,
            )
            for c in candidates
        ],
    )


@router.post(
    "/enroll",
    response_model=APIResponse[SingleCandidateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Enroll an existing candidate into a new assessment",
    description=(
        "Enroll an already-known candidate into a new assessment. "
        "Checks that the new assessment's time window does not conflict with "
        "any active (non-completed) enrollment for the candidate. "
        "Optionally accepts a new resume PDF; otherwise the previous resume is reused."
    ),
)
async def enroll_existing_candidate(
    candidate_id: str = Form(..., description="UUID of the existing candidate"),
    assessment_id: str = Form(..., description="UUID of the target assessment"),
    resume: UploadFile | None = File(default=None),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[SingleCandidateResponse]:
    """Enroll an existing candidate into an additional assessment."""
    if not x_user_id:
        raise AuthenticationException("Missing identity header.")
    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    try:
        candidate_uuid = uuid.UUID(candidate_id)
    except ValueError:
        raise BadRequestException("Invalid candidate_id format — must be a valid UUID.")

    try:
        assessment_uuid = uuid.UUID(assessment_id)
    except ValueError:
        raise BadRequestException(
            "Invalid assessment_id format — must be a valid UUID."
        )

    resume_bytes: bytes | None = None
    resume_filename: str | None = None
    if resume is not None and resume.filename:
        if not resume.filename.lower().endswith(".pdf"):
            raise BadRequestException("Uploaded resume must be a PDF (.pdf extension).")
        resume_bytes = await resume.read()
        if resume_bytes:
            resume_filename = resume.filename

    ca_record, candidate = await service.enroll_existing_candidate(
        recruiter_id=recruiter_id,
        candidate_id=candidate_uuid,
        assessment_id=assessment_uuid,
        resume_file_bytes=resume_bytes,
        resume_filename=resume_filename,
    )

    return APIResponse(
        message="Candidate enrolled and invitation queued.",
        data=SingleCandidateResponse(
            candidate_assessment_id=ca_record.id,
            candidate_id=ca_record.candidate_id,
            full_name=candidate.full_name,
            email=candidate.email,
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
