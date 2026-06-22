"""Assessment REST routes."""

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
from src.core.exceptions import (
    AuthenticationException,
    BadRequestException,
)
from src.core.services.assessment_service import AssessmentService
from src.data.repositories.assessment_repository import AssessmentRepository
from src.schemas.assessment import (
    AssessmentCreateForm,
    AssessmentResponse,
    AssessmentSummaryResponse,
    AssessmentUpdateStatusRequest,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/assessments", tags=["assessments"])
logger = logging.getLogger(__name__)


def get_assessment_service(
    session: AsyncSession = Depends(get_db_session),
) -> AssessmentService:
    """Build the assessment service from request-scoped dependencies."""
    return AssessmentService(AssessmentRepository(session))


@router.post(
    "",
    response_model=APIResponse[AssessmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create assessment",
    description="Create an assessment by uploading a PDF JD or submitting raw text.",
)
async def create_assessment(
    background_tasks: BackgroundTasks,
    form_data: AssessmentCreateForm = Depends(),
    jd_file: UploadFile | None = File(None),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Create a new assessment configuration with JD analysis."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header — ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

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

    # Queue the heavy parsing & analysis as a background task
    background_tasks.add_task(
        service.process_assessment_in_background,
        assessment.id,
        form_data.jd_text,
        file_bytes,
        filename,
        form_data.focus_areas,
    )

    return APIResponse(
        message="Assessment creation initiated successfully.",
        data=AssessmentResponse.model_validate(assessment),
    )


@router.get(
    "",
    response_model=APIResponse[list[AssessmentSummaryResponse]],
    summary="List assessments",
    description="List all assessments configured by the authenticated recruiter.",
)
async def list_assessments(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[list[AssessmentSummaryResponse]]:
    """Return all assessments owned by the logged-in recruiter."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header — ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

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
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Return the detailed view of an assessment."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header — ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

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
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    service: AssessmentService = Depends(get_assessment_service),
) -> APIResponse[AssessmentResponse]:
    """Transition the assessment status."""
    if not x_user_id:
        raise AuthenticationException(
            "Missing identity header — ensure request passes through the gateway."
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise BadRequestException("Invalid X-User-Id header format.")

    assessment = await service.update_status(
        assessment_id, recruiter_id, payload.status
    )
    return APIResponse(
        message="Assessment status updated successfully.",
        data=AssessmentResponse.model_validate(assessment),
    )
