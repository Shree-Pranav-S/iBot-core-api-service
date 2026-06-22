import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.interview_evaluation import InterviewEvaluation


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # Cross-service reference key
    candidate_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
    )

    # Ordered conversation transcript
    # [
    #   {
    #       "turn_number": 1,
    #       "speaker": "bot",
    #       "tone": "neutral",
    #       "text": "Tell me about yourself"
    #   }
    # ]
    transcript: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Session violations
    violations: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # INITIALIZING | IN_PROGRESS | PAUSED | COMPLETED
    # EVALUATED | DEACTIVATED | TERMINATED
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="INITIALIZING",
        index=True,
    )

    # Total interview duration excluding pauses
    total_elapsed_secs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Total paused duration
    total_pause_secs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Auto-deactivation deadline
    grace_period_expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # One-to-one evaluation
    evaluation: Mapped["InterviewEvaluation | None"] = relationship(
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<InterviewSession id={self.id} status={self.status}>"
