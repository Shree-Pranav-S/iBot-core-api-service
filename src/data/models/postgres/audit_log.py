"""
AuditLog model.

Centralised event log across both services.
Tracks WebSocket lifecycle events, LLM API calls, Celery task outcomes,
inter-service HTTP calls, and STT / TTS operations.

Written by both core-api and interview-service.
Owned by: shared
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    # core-api | interview-service
    service: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # WS_CONNECTED | LLM_ANSWER_EVALUATION | CELERY_EMAIL_DISPATCH |
    # STT_TRANSCRIPTION | TTS_SYNTHESIS | INTERNAL_HTTP_CALL | etc.
    event_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # SUCCESS | FAILURE | TIMEOUT
    event_status: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # Present when event is scoped to a specific candidate session
    candidate_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_assessments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Present when event is scoped to a recruiter action
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruiters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Event-specific context: error messages, durations, retry counts, etc.
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Operation duration in milliseconds
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} service={self.service} "
            f"event={self.event_type} status={self.event_status}>"
        )
