"""
NotificationLog model.

Audit log of every notification dispatched to candidates and recruiters.
Used to prevent duplicate sends and track delivery failures.
Owned by: core-api
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.candidate_assessment import CandidateAssessment


class NotificationLog(Base):
    """SQLAlchemy model for notification delivery records."""

    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    candidate_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # INVITATION | REMINDER_24H | REMINDER_8H | REMINDER_1H |
    # APPROVAL | REJECTION | REPORT_READY | SESSION_DEACTIVATED
    notification_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # SENT | FAILED
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False, default="SENT")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    candidate_assessment: Mapped["CandidateAssessment"] = relationship(
        back_populates="notification_logs",
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationLog id={self.id} "
            f"type={self.notification_type} status={self.delivery_status}>"
        )
