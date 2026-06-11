"""
Audit log schemas.

Used when writing audit events programmatically and when returning
log entries via API.
"""

import uuid
from datetime import datetime

from pydantic import Field

from src.schemas.base import AppBaseModel, ORMBaseModel

# ── Internal write payload ────────────────────────────────────────────────────


class AuditEventPayload(AppBaseModel):
    """
    Typed payload passed to the audit logger utility.
    Not exposed over HTTP — used internally by middleware and services.
    """

    service: str  # core-api | interview-service
    event_type: str  # WS_CONNECTED | LLM_CALL | etc.
    event_status: str  # SUCCESS | FAILURE | TIMEOUT
    candidate_assessment_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID | None = None
    metadata: dict | None = None
    error_message: str | None = None
    duration_ms: int | None = None


# ── Response schema ───────────────────────────────────────────────────────────


class AuditLogResponse(ORMBaseModel):
    """Audit log entry as returned by the API."""

    id: uuid.UUID
    service: str
    event_type: str
    event_status: str
    candidate_assessment_id: uuid.UUID | None
    recruiter_id: uuid.UUID | None
    metadata: dict | None = Field(alias="metadata_json")
    error_message: str | None
    duration_ms: int | None
    created_at: datetime
