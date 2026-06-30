"""Request and response schemas for internal interview persistence APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from src.schemas.base import AppBaseModel
from src.schemas.evaluation_llm import FinalEvaluationRecord


class CandidateSessionEntryRequest(AppBaseModel):
    invitation_token: uuid.UUID


class CandidateSessionContextRequest(AppBaseModel):
    session_token: str = Field(min_length=32, max_length=255)


class CandidateSessionBootstrapResponse(AppBaseModel):
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
    session_id: uuid.UUID
    connection_id: str
    candidate_assessment_id: uuid.UUID
    candidate_id: uuid.UUID
    assessment_id: uuid.UUID
    candidate_name: str
    session_token_expires_at: datetime
    elapsed_secs: int = 0
    interview_started: bool = False


class RecordDisconnectRequest(AppBaseModel):
    session_id: uuid.UUID
    connection_id: str
    candidate_assessment_id: uuid.UUID
    reason: str
    elapsed_secs: int


class InitializeGraphContextRequest(AppBaseModel):
    candidate_assessment_id: uuid.UUID


class InitializeGraphContextResponse(AppBaseModel):
    context: dict[str, Any]
    session: dict[str, Any]


class PersistTurnRequest(AppBaseModel):
    transcript_items: list[dict[str, Any]] = Field(default_factory=list)
    violations: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_secs: int | None = None


class CompleteSessionRequest(AppBaseModel):
    total_elapsed_secs: int


class SaveFinalEvaluationRequest(AppBaseModel):
    record: FinalEvaluationRecord
    recruiter_email: str


class SaveFinalEvaluationResponse(AppBaseModel):
    id: uuid.UUID
    sent_at: datetime


class MarkTimerStartedResponse(AppBaseModel):
    started_at: datetime
