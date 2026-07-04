"""Internal interview persistence APIs for interview-engine-service."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.api.rest.dependencies_internal import require_interview_engine_service
from src.core.exceptions import NotFoundException
from src.core.services.interview_session_service import InterviewSessionService
from src.data.repositories.assessment_context_repository import (
    AssessmentContextRepository,
)
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)
from src.schemas.common import APIResponse
from src.schemas.event_log import EventLogCreate
from src.schemas.internal_interview import (
    CandidateConnectionContext,
    CandidateSessionBootstrapResponse,
    CandidateSessionContextRequest,
    CandidateSessionEntryRequest,
    CompleteSessionRequest,
    InitializeGraphContextRequest,
    InitializeGraphContextResponse,
    MarkTimerStartedResponse,
    PersistTurnRequest,
    RecordDisconnectRequest,
    SaveFinalEvaluationRequest,
    SaveFinalEvaluationResponse,
)

router = APIRouter(
    prefix="/internal/interview",
    tags=["internal-interview"],
    dependencies=[Depends(require_interview_engine_service)],
)
_session_service = InterviewSessionService()


@router.post(
    "/session/enter",
    response_model=APIResponse[CandidateSessionBootstrapResponse],
)
async def enter_with_invitation(
    body: CandidateSessionEntryRequest,
) -> APIResponse[CandidateSessionBootstrapResponse]:
    """Exchange an invitation token for candidate session bootstrap data."""
    data = await _session_service.enter_with_invitation(body.invitation_token)
    return APIResponse(message="Session entered.", data=data)


@router.post(
    "/session/context",
    response_model=APIResponse[CandidateSessionBootstrapResponse],
)
async def get_session_context(
    body: CandidateSessionContextRequest,
) -> APIResponse[CandidateSessionBootstrapResponse]:
    """Load bootstrap context for an existing candidate session token."""
    data = await _session_service.get_session_context(body.session_token)
    return APIResponse(message="Session context loaded.", data=data)


@router.post(
    "/session/authorize-connection",
    response_model=APIResponse[CandidateConnectionContext],
)
async def authorize_interview_connection(
    body: CandidateSessionContextRequest,
) -> APIResponse[CandidateConnectionContext]:
    """Authorize a candidate interview connection from a session token."""
    data = await _session_service.authorize_interview_connection(body.session_token)
    return APIResponse(message="Connection authorized.", data=data)


@router.post(
    "/session/authorize-demo",
    response_model=APIResponse[dict[str, Any]],
)
async def authorize_demo(
    body: CandidateSessionContextRequest,
) -> APIResponse[dict[str, Any]]:
    """Authorize a demo interview connection from a session token."""
    data = await _session_service.authorize_demo(body.session_token)
    return APIResponse(message="Demo authorized.", data=data)


@router.post(
    "/session/disconnect",
    response_model=APIResponse[dict[str, Any]],
)
async def record_disconnect(
    body: RecordDisconnectRequest,
) -> APIResponse[dict[str, Any]]:
    """Record a candidate disconnect and update reconnect state."""
    data = await _session_service.record_disconnect(
        session_id=body.session_id,
        connection_id=body.connection_id,
        candidate_assessment_id=body.candidate_assessment_id,
        reason=body.reason,
        elapsed_secs=body.elapsed_secs,
    )
    return APIResponse(message="Disconnect recorded.", data=data)


@router.post("/events", response_model=APIResponse[dict[str, str]])
async def create_event_log(
    body: EventLogCreate,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Persist an internal interview event log entry."""
    await EventLogsRepository(db).create(body)
    return APIResponse(message="Event logged.", data={"status": "ok"})


@router.post(
    "/context/initialize",
    response_model=APIResponse[InitializeGraphContextResponse],
)
async def initialize_interview_context(
    body: InitializeGraphContextRequest,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[InitializeGraphContextResponse]:
    """Initialize persisted graph context and session state for an interview."""
    ca_id = body.candidate_assessment_id
    assessment_context = AssessmentContextRepository(db)
    interview_sessions = InterviewSessionRepository(db)

    context = await assessment_context.load_interview_context(ca_id)
    if not context:
        raise NotFoundException(f"Candidate assessment context not found: {ca_id}")

    session = await interview_sessions.get_or_create_session(ca_id)
    await interview_sessions.mark_session_in_progress(str(session["id"]))
    await assessment_context.mark_candidate_started(ca_id)

    return APIResponse(
        message="Interview context initialized.",
        data=InitializeGraphContextResponse(context=context, session=session),
    )


@router.get(
    "/context/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, Any]],
)
async def load_interview_context(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, Any]]:
    """Load the persisted interview context for a candidate assessment."""
    context = await AssessmentContextRepository(db).load_interview_context(
        candidate_assessment_id,
    )
    return APIResponse(message="Context loaded.", data=context)


@router.get(
    "/sessions/by-ca/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, Any]],
)
async def get_session_by_candidate_assessment(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, Any]]:
    """Load the interview session linked to a candidate assessment."""
    session = await InterviewSessionRepository(
        db
    ).get_session_by_candidate_assessment_id(
        candidate_assessment_id,
    )
    return APIResponse(message="Session loaded.", data=session)


@router.post(
    "/sessions/{session_id}/persist-turn",
    response_model=APIResponse[dict[str, str]],
)
async def persist_turn(
    session_id: uuid.UUID,
    body: PersistTurnRequest,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Persist transcript turns, violations, and elapsed time for a session."""
    sid = str(session_id)
    repository = InterviewSessionRepository(db)
    for item in body.transcript_items:
        await repository.append_transcript_turn(sid, item)
    for violation in body.violations:
        await repository.append_violation(sid, violation)
    if body.elapsed_secs is not None:
        await repository.update_elapsed_time(
            sid,
            elapsed_secs=body.elapsed_secs,
            total_pause_secs=0,
        )
    return APIResponse(message="Turn persisted.", data={"status": "ok"})


@router.post(
    "/sessions/{session_id}/in-progress",
    response_model=APIResponse[dict[str, str]],
)
async def mark_session_in_progress(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Mark an interview session as in progress."""
    await InterviewSessionRepository(db).mark_session_in_progress(str(session_id))
    return APIResponse(message="Session marked in progress.", data={"status": "ok"})


@router.post(
    "/sessions/{session_id}/complete",
    response_model=APIResponse[dict[str, str]],
)
async def complete_session(
    session_id: uuid.UUID,
    body: CompleteSessionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Mark an interview session complete with final elapsed time."""
    await InterviewSessionRepository(db).complete_session(
        str(session_id),
        total_elapsed_secs=body.total_elapsed_secs,
    )
    return APIResponse(message="Session completed.", data={"status": "ok"})


@router.post(
    "/candidates/{candidate_assessment_id}/timer-started",
    response_model=APIResponse[MarkTimerStartedResponse],
)
async def mark_candidate_timer_started(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[MarkTimerStartedResponse]:
    """Mark that the candidate-facing timer has started."""
    started_at = await AssessmentContextRepository(db).mark_candidate_timer_started(
        candidate_assessment_id,
    )
    return APIResponse(
        message="Timer started.",
        data=MarkTimerStartedResponse(started_at=started_at),
    )


@router.post(
    "/candidates/{candidate_assessment_id}/started",
    response_model=APIResponse[dict[str, str]],
)
async def mark_candidate_started(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Mark that the candidate has started the interview flow."""
    await AssessmentContextRepository(db).mark_candidate_started(
        candidate_assessment_id,
    )
    return APIResponse(message="Candidate started.", data={"status": "ok"})


@router.post(
    "/candidates/{candidate_assessment_id}/completed",
    response_model=APIResponse[dict[str, str]],
)
async def mark_candidate_completed(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Mark that the candidate has completed the interview flow."""
    await AssessmentContextRepository(db).mark_candidate_completed(
        candidate_assessment_id,
    )
    return APIResponse(message="Candidate completed.", data={"status": "ok"})


@router.get(
    "/evaluation/source/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, Any] | None],
)
async def load_evaluation_source(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, Any] | None]:
    """Load source data required for final interview evaluation."""
    source = await EvaluationRepository(db).load_evaluation_source(
        candidate_assessment_id,
    )
    return APIResponse(message="Evaluation source loaded.", data=source)


@router.get(
    "/evaluation/exists",
    response_model=APIResponse[bool],
)
async def evaluation_exists_for_hash(
    candidate_assessment_id: uuid.UUID = Query(...),
    transcript_hash: str = Query(..., min_length=64, max_length=64),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[bool]:
    """Return whether an evaluation already exists for a transcript hash."""
    exists = await EvaluationRepository(db).evaluation_exists_for_hash(
        candidate_assessment_id,
        transcript_hash,
    )
    return APIResponse(message="Hash check complete.", data=exists)


@router.post(
    "/evaluation/failed/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, str]],
)
async def mark_evaluation_failed(
    candidate_assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict[str, str]]:
    """Mark evaluation generation as failed for a candidate assessment."""
    await EvaluationRepository(db).mark_evaluation_failed(candidate_assessment_id)
    return APIResponse(message="Evaluation marked failed.", data={"status": "ok"})


@router.post(
    "/evaluation/final",
    response_model=APIResponse[SaveFinalEvaluationResponse],
)
async def save_final_evaluation(
    body: SaveFinalEvaluationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SaveFinalEvaluationResponse]:
    """Persist a final evaluation and return its notification metadata."""
    notification = await EvaluationRepository(db).save_final_evaluation(
        body.record,
        recruiter_email=body.recruiter_email,
    )
    return APIResponse(
        message="Evaluation saved.",
        data=SaveFinalEvaluationResponse(
            id=notification["id"],
            sent_at=notification["sent_at"],
        ),
    )
