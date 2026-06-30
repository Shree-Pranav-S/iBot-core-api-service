"""Internal interview persistence APIs for interview-engine-service."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.api.rest.dependencies import UnitOfWork, get_unit_of_work
from src.api.rest.dependencies_internal import require_interview_engine_service
from src.core.exceptions import NotFoundException
from src.core.services.interview_session_service import InterviewSessionService
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
logger = logging.getLogger(__name__)
_session_service = InterviewSessionService()


@router.post(
    "/session/enter",
    response_model=APIResponse[CandidateSessionBootstrapResponse],
)
async def enter_with_invitation(
    body: CandidateSessionEntryRequest,
) -> APIResponse[CandidateSessionBootstrapResponse]:
    data = await _session_service.enter_with_invitation(body.invitation_token)
    return APIResponse(message="Session entered.", data=data)


@router.post(
    "/session/context",
    response_model=APIResponse[CandidateSessionBootstrapResponse],
)
async def get_session_context(
    body: CandidateSessionContextRequest,
) -> APIResponse[CandidateSessionBootstrapResponse]:
    data = await _session_service.get_session_context(body.session_token)
    return APIResponse(message="Session context loaded.", data=data)


@router.post(
    "/session/authorize-connection",
    response_model=APIResponse[CandidateConnectionContext],
)
async def authorize_interview_connection(
    body: CandidateSessionContextRequest,
) -> APIResponse[CandidateConnectionContext]:
    data = await _session_service.authorize_interview_connection(body.session_token)
    return APIResponse(message="Connection authorized.", data=data)


@router.post(
    "/session/authorize-demo",
    response_model=APIResponse[dict[str, Any]],
)
async def authorize_demo(
    body: CandidateSessionContextRequest,
) -> APIResponse[dict[str, Any]]:
    data = await _session_service.authorize_demo(body.session_token)
    return APIResponse(message="Demo authorized.", data=data)


@router.post(
    "/session/disconnect",
    response_model=APIResponse[dict[str, Any]],
)
async def record_disconnect(
    body: RecordDisconnectRequest,
) -> APIResponse[dict[str, Any]]:
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.event_logs.create(body)
    return APIResponse(message="Event logged.", data={"status": "ok"})


@router.post(
    "/context/initialize",
    response_model=APIResponse[InitializeGraphContextResponse],
)
async def initialize_interview_context(
    body: InitializeGraphContextRequest,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[InitializeGraphContextResponse]:
    ca_id = body.candidate_assessment_id
    context = await unit_of_work.assessment_context.load_interview_context(ca_id)
    if not context:
        raise NotFoundException(f"Candidate assessment context not found: {ca_id}")

    session = await unit_of_work.interview_sessions.get_or_create_session(ca_id)
    await unit_of_work.interview_sessions.mark_session_in_progress(str(session["id"]))
    await unit_of_work.assessment_context.mark_candidate_started(ca_id)

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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, Any]]:
    context = await unit_of_work.assessment_context.load_interview_context(
        candidate_assessment_id,
    )
    return APIResponse(message="Context loaded.", data=context)


@router.get(
    "/sessions/by-ca/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, Any]],
)
async def get_session_by_candidate_assessment(
    candidate_assessment_id: uuid.UUID,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, Any]]:
    session = (
        await unit_of_work.interview_sessions.get_session_by_candidate_assessment_id(
            candidate_assessment_id,
        )
    )
    return APIResponse(message="Session loaded.", data=session)


@router.post(
    "/sessions/{session_id}/persist-turn",
    response_model=APIResponse[dict[str, str]],
)
async def persist_turn(
    session_id: uuid.UUID,
    body: PersistTurnRequest,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    sid = str(session_id)
    for item in body.transcript_items:
        await unit_of_work.interview_sessions.append_transcript_turn(sid, item)
    for violation in body.violations:
        await unit_of_work.interview_sessions.append_violation(sid, violation)
    if body.elapsed_secs is not None:
        await unit_of_work.interview_sessions.update_elapsed_time(
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.interview_sessions.mark_session_in_progress(str(session_id))
    return APIResponse(message="Session marked in progress.", data={"status": "ok"})


@router.post(
    "/sessions/{session_id}/complete",
    response_model=APIResponse[dict[str, str]],
)
async def complete_session(
    session_id: uuid.UUID,
    body: CompleteSessionRequest,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.interview_sessions.complete_session(
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[MarkTimerStartedResponse]:
    started_at = await unit_of_work.assessment_context.mark_candidate_timer_started(
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.assessment_context.mark_candidate_started(
        candidate_assessment_id,
    )
    return APIResponse(message="Candidate started.", data={"status": "ok"})


@router.post(
    "/candidates/{candidate_assessment_id}/completed",
    response_model=APIResponse[dict[str, str]],
)
async def mark_candidate_completed(
    candidate_assessment_id: uuid.UUID,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.assessment_context.mark_candidate_completed(
        candidate_assessment_id,
    )
    return APIResponse(message="Candidate completed.", data={"status": "ok"})


@router.get(
    "/evaluation/source/{candidate_assessment_id}",
    response_model=APIResponse[dict[str, Any] | None],
)
async def load_evaluation_source(
    candidate_assessment_id: uuid.UUID,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, Any] | None]:
    source = await unit_of_work.evaluations.load_evaluation_source(
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[bool]:
    exists = await unit_of_work.evaluations.evaluation_exists_for_hash(
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
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[dict[str, str]]:
    await unit_of_work.evaluations.mark_evaluation_failed(candidate_assessment_id)
    return APIResponse(message="Evaluation marked failed.", data={"status": "ok"})


@router.post(
    "/evaluation/final",
    response_model=APIResponse[SaveFinalEvaluationResponse],
)
async def save_final_evaluation(
    body: SaveFinalEvaluationRequest,
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> APIResponse[SaveFinalEvaluationResponse]:
    notification = await unit_of_work.evaluations.save_final_evaluation(
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
