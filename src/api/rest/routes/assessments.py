"""Assessment REST routes."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    UploadFile,
    status,
)

from src.api.rest.dependencies import get_assessment_service, require_recruiter_id
from src.core.services.assessment_service import AssessmentService
from src.schemas.assessment import (
    AssessmentCreateForm,
    AssessmentResponse,
    AssessmentSummaryResponse,
    AssessmentUpdateStatusRequest,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.post(
    "",
    response_model=APIResponse[AssessmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create assessment",
    description="Create an assessment by uploading a PDF JD or submitting raw text.",
)
async def create_assessment(
    form_data: AssessmentCreateForm = Depends(),
    jd_file: UploadFile | None = File(None),
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Create a new assessment configuration with JD analysis."""
    file_bytes = None
    filename = None
    if jd_file:
        file_bytes = await jd_file.read()
        filename = jd_file.filename

    assessment = await service.create_assessment(
        recruiter_id=recruiter_id,
        title=form_data.title,
        role_name=form_data.role_name,
        duration_mins=form_data.interview_duration_mins,
        window_start=form_data.window_start,
        window_end=form_data.window_end,
        jd_text=form_data.jd_text,
        jd_file_bytes=file_bytes,
        jd_filename=filename,
        focus_areas=form_data.focus_areas,
    )

    return APIResponse(
        message="Assessment creation queued successfully.",
        data=AssessmentResponse.model_validate(assessment),
    )


@router.get(
    "",
    response_model=APIResponse[list[AssessmentSummaryResponse]],
    summary="List assessments",
    description="List all assessments configured by the authenticated recruiter.",
)
async def list_assessments(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[list[AssessmentSummaryResponse]]:
    """Return all assessments owned by the logged-in recruiter."""
    assessments = await service.get_recruiter_assessments(recruiter_id)
    return APIResponse(
        message="Assessments retrieved successfully.",
        data=[AssessmentSummaryResponse.model_validate(a) for a in assessments],
    )


@router.get(
    "/{assessment_id}",
    response_model=APIResponse[AssessmentResponse],
    summary="Get assessment details",
    description="Retrieve full details for a specific assessment, including JD analysis and plan.",
)
async def get_assessment(
    assessment_id: uuid.UUID,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Return the detailed view of an assessment."""
    assessment = await service.get_assessment_by_id(assessment_id, recruiter_id)
    return APIResponse(
        message="Assessment details retrieved successfully.",
        data=AssessmentResponse.model_validate(assessment),
    )


@router.patch(
    "/{assessment_id}/status",
    response_model=APIResponse[AssessmentResponse],
    summary="Update assessment status",
    description="Transition assessment status, e.g. ACTIVE -> CLOSED.",
)
async def update_assessment_status(
    assessment_id: uuid.UUID,
    payload: AssessmentUpdateStatusRequest,
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Transition the assessment status."""
    assessment = await service.update_status(
        assessment_id, recruiter_id, payload.status
    )
    return APIResponse(
        message="Assessment status updated successfully.",
        data=AssessmentResponse.model_validate(assessment),
    )
