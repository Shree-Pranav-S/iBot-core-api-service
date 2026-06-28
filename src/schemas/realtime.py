"""Typed recruiter dashboard events delivered through Server-Sent Events."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from src.schemas.base import AppBaseModel


class RecruiterEventType(StrEnum):
    """Completion states that the recruiter dashboard can consume live."""

    ASSESSMENT_PROCESSING_COMPLETED = "ASSESSMENT_PROCESSING_COMPLETED"
    ASSESSMENT_PROCESSING_FAILED = "ASSESSMENT_PROCESSING_FAILED"
    RESUME_PARSING_COMPLETED = "RESUME_PARSING_COMPLETED"
    RESUME_PARSING_FAILED = "RESUME_PARSING_FAILED"
    INTERVIEW_EVALUATED = "INTERVIEW_EVALUATED"


class RecruiterRealtimeEvent(AppBaseModel):
    """Envelope published to one recruiter-specific Redis channel."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: RecruiterEventType
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
