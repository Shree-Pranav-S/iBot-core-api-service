"""Request and response schemas for internal interview persistence APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from src.schemas.base import AppBaseModel
from src.schemas.evaluation_llm import FinalEvaluationRecord


class CandidateSessionEntryRequest(AppBaseModel):
    """Request to enter an interview session with an invitation token."""

    invitation_token: uuid.UUID


class CandidateSessionContextRequest(AppBaseModel):
    """Request carrying a candidate session token."""

    session_token: str = Field(min_length=32, max_length=255)


class CandidateSessionBootstrapResponse(AppBaseModel):
    """Bootstrap context returned after candidate session entry."""

    session_token: str
    session_token_expires_at: datetime
    session_status: str
    invite_reissued: bool
    interview_started: bool
    reconnect_deadline: datetime | None
    disconnect_count: int
    candidate_name: str
    company_name: str
    assessment_title: str
    interview_duration_mins: int
    window_end: datetime
    status: str
    sections_overview: list[str]


class CandidateConnectionContext(AppBaseModel):
    """Authorized connection context for the interview engine."""

    session_id: uuid.UUID
    connection_id: str
    candidate_assessment_id: uuid.UUID
    candidate_id: uuid.UUID
    assessment_id: uuid.UUID
    candidate_name: str
    session_token_expires_at: datetime
    elapsed_secs: int = 0
    interview_started: bool = False
    tab_switch_count: int = Field(default=0, ge=0)


class RecordDisconnectRequest(AppBaseModel):
    """Request to record a candidate disconnect."""

    session_id: uuid.UUID
    connection_id: str
    candidate_assessment_id: uuid.UUID
    reason: str
    elapsed_secs: int


class RecordTabSwitchRequest(AppBaseModel):
    """Trusted interview-engine request for one browser visibility violation."""

    connection_id: str = Field(min_length=1, max_length=255)
    candidate_assessment_id: uuid.UUID
    event_id: uuid.UUID
    occurred_at: datetime


class RecordTabSwitchResponse(AppBaseModel):
    """Atomic tab-switch count and termination outcome."""

    appended: bool
    tab_switch_count: int = Field(ge=0)
    terminated: bool
    status: str


class InitializeGraphContextRequest(AppBaseModel):
    """Request to initialize graph context for a candidate assessment."""

    candidate_assessment_id: uuid.UUID


class InitializeGraphContextResponse(AppBaseModel):
    """Response containing interview context and session state."""

    context: dict[str, Any]
    session: dict[str, Any]


class PersistTurnRequest(AppBaseModel):
    """Request to persist transcript turns and violations for a session."""

    transcript_items: list[dict[str, Any]] = Field(default_factory=list)
    violations: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_secs: int | None = None


class CompleteSessionRequest(AppBaseModel):
    """Request to complete an interview session."""

    total_elapsed_secs: int


class SaveFinalEvaluationRequest(AppBaseModel):
    """Request to persist a final interview evaluation."""

    record: FinalEvaluationRecord
    recruiter_email: str


class SaveFinalEvaluationResponse(AppBaseModel):
    """Response metadata for a persisted final evaluation."""

    id: uuid.UUID
    sent_at: datetime


class MarkTimerStartedResponse(AppBaseModel):
    """Response containing the timestamp when the timer started."""

    started_at: datetime
