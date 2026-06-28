"""
CandidateAssessment model.

Junction table linking one candidate to one assessment.
Represents the full lifecycle of a candidate's participation from
invitation through recruiter decision.

IMPORTANT: The `id` of this table is the PRIMARY cross-service reference key
used by ALL interview-service tables (interview_sessions, transcript_turns,
answer_evaluations, interview_evaluations).
Owned by: core-api
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base
from src.data.models.postgres.mixins import TimestampMixin

if TYPE_CHECKING:
    from src.data.models.postgres.assessment import Assessment
    from src.data.models.postgres.candidate import Candidate
    from src.data.models.postgres.notification_log import NotificationLog


class CandidateAssessment(TimestampMixin, Base):
    __tablename__ = "candidate_assessments"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "assessment_id",
            name="uq_candidate_assessment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # GCP Storage path to candidate resume PDF
    resume_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    # LlamaParse structured resume output
    resume_parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # PENDING | COMPLETED | FAILED
    resume_parse_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="PENDING"
    )

    # Unique token embedded in the candidate's invitation link
    invitation_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    invite_consumed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    invite_consumed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    # INVITED | WAITING_ROOM | IN_PROGRESS | COMPLETED | EVALUATED | TERMINATED
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="INVITED", index=True
    )

    interview_started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    interview_ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # PENDING | APPROVED | REJECTED
    recruiter_decision: Mapped[str] = mapped_column(
        Text, nullable=False, default="PENDING"
    )
    # Optional manual feedback provided by recruiter on rejection
    recruiter_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tracks which reminder emails have fired
    # e.g. {"24h": true, "8h": false, "1h": false}
    reminders_sent: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    candidate: Mapped["Candidate"] = relationship(
        back_populates="candidate_assessments",
    )
    assessment: Mapped["Assessment"] = relationship(
        back_populates="candidate_assessments",
    )
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="candidate_assessment",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateAssessment id={self.id} "
            f"status={self.status} decision={self.recruiter_decision}>"
        )
