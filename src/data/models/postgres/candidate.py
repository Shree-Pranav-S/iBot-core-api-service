"""
Candidate model.

Stores candidate records created via bulk CSV upload.
Candidates have no login credentials — they access the system
exclusively via unique invitation tokens.
Owned by: core-api
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base
from src.data.models.postgres.mixins import TimestampMixin

if TYPE_CHECKING:
    from src.data.models.postgres.candidate_assessment import CandidateAssessment
    from src.data.models.postgres.recruiter import Recruiter


class Candidate(Base, TimestampMixin):
    """SQLAlchemy model for candidate profiles."""

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruiters.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Relationships
    created_by_recruiter: Mapped["Recruiter"] = relationship(
        back_populates="candidates",
    )
    candidate_assessments: Mapped[list["CandidateAssessment"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} email={self.email}>"
