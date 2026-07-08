"""Candidate REST routes - bulk CSV upload and candidate listing."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    UploadFile,
    status,
)

from src.api.rest.dependencies import get_candidate_service, require_recruiter_id
from src.core.exceptions import (
    EmptyCsvFileException,
    EmptyResumeFileException,
    InvalidAssessmentIdException,
    InvalidCandidateIdException,
    InvalidCsvFileException,
    InvalidResumeFileException,
)
from src.core.services.candidate_service import CandidateService
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    EnrollCandidateResponse,
    ExistingCandidateListItem,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    SingleCandidateResponse,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.post(
    "/bulk-upload",
    response_model=APIResponse[BulkUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk upload candidates from CSV",
    description=(
        "Upload a CSV file containing candidate records for a single assessment. "
        "The CSV must have columns: name, email, resume. "
        "Select the target assessment in the form; candidates receive "
        "an invitation email with their unique interview link."
    ),
)
async def bulk_upload_candidates(
    csv_file: UploadFile = File(
        ...,
        description="CSV file with columns: name, email, resume",
    ),
    assessment_id: str = Form(..., description="UUID of the target assessment"),
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[BulkUploadResponse]:
    """Process a CSV bulk upload, create candidates, and dispatch invitation emails."""
    try:
        parsed_assessment_id = uuid.UUID(assessment_id)
    except ValueError as exc:
        raise InvalidAssessmentIdException() from exc

    if not csv_file.filename or not csv_file.filename.lower().endswith(".csv"):
        raise InvalidCsvFileException()

    file_bytes = await csv_file.read()
    if not file_bytes:
        raise EmptyCsvFileException()

    result = await service.bulk_upload_from_csv(
        recruiter_id=recruiter_id,
        assessment_id=parsed_assessment_id,
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
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[SingleCandidateResponse]:
    """Process a manual candidate creation."""
    try:
        assessment_uuid = uuid.UUID(assessment_id)
    except ValueError as exc:
        raise InvalidAssessmentIdException() from exc

    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise InvalidResumeFileException()

    file_bytes = await resume.read()
    if not file_bytes:
        raise EmptyResumeFileException()

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
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[list[ExistingCandidateListItem]]:
    """Return all unique candidate records for the recruiter."""
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
    response_model=APIResponse[EnrollCandidateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Enroll an existing candidate into an assessment",
)
async def enroll_existing_candidate(
    candidate_id: str = Form(...),
    assessment_id: str = Form(...),
    resume: UploadFile | None = File(default=None),
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[EnrollCandidateResponse]:
    """Enroll a candidate who already exists in the recruiter's pool."""
    try:
        candidate_uuid = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise InvalidCandidateIdException() from exc

    try:
        assessment_uuid = uuid.UUID(assessment_id)
    except ValueError as exc:
        raise InvalidAssessmentIdException() from exc

    resume_bytes: bytes | None = None
    resume_filename: str | None = None
    if resume is not None and resume.filename:
        if not resume.filename.lower().endswith(".pdf"):
            raise InvalidResumeFileException()
        resume_bytes = await resume.read()
        if not resume_bytes:
            raise EmptyResumeFileException()
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
        data=EnrollCandidateResponse(
            candidate_assessment_id=ca_record.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status=ca_record.status,
        ),
    )


@router.get(
    "",
    response_model=APIResponse[list[CandidateAssessmentListItem]],
    summary="List candidate assessments",
)
async def list_candidates(
    assessment_id: str | None = None,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[list[CandidateAssessmentListItem]]:
    """Return candidate-assessment records, optionally filtered by assessment."""
    if assessment_id is not None:
        try:
            assessment_uuid = uuid.UUID(assessment_id)
        except ValueError as exc:
            raise InvalidAssessmentIdException() from exc
        records = await service.get_candidates_for_assessment(
            assessment_uuid,
            recruiter_id,
        )
    else:
        records = await service.get_all_candidates_for_recruiter(recruiter_id)

    return APIResponse(
        message="Candidates retrieved successfully.",
        data=[
            CandidateAssessmentListItem.from_orm_with_candidate(record)
            for record in records
        ],
    )


@router.post(
    "/{ca_id}/decision",
    response_model=APIResponse[RecruiterDecisionResponse],
    summary="Update recruiter hiring decision",
)
async def update_candidate_decision(
    ca_id: uuid.UUID,
    payload: RecruiterDecisionRequest,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[RecruiterDecisionResponse]:
    """Persist recruiter hiring decision for a candidate assessment."""
    updated = await service.update_recruiter_decision(
        ca_id=ca_id,
        recruiter_id=recruiter_id,
        decision=payload.decision,
        feedback=payload.feedback,
    )
    return APIResponse(
        message="Decision saved successfully.",
        data=RecruiterDecisionResponse(
            candidate_assessment_id=updated.id,
            recruiter_decision=updated.recruiter_decision,
            updated_at=updated.updated_at,
        ),
    )


@router.delete(
    "/{ca_id}",
    response_model=APIResponse[None],
    summary="Delete candidate from assessment",
)
async def delete_candidate(
    ca_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: CandidateService = Depends(get_candidate_service),
) -> APIResponse[None]:
    """Remove a candidate registration from an assessment."""
    await service.delete_candidate_from_assessment(ca_id, recruiter_id)
    return APIResponse(message="Candidate deleted successfully.", data=None)
