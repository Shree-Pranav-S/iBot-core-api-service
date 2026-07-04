"""
Assessment model.

Assessment configurations created by recruiters.
Contains the JD analysis with inferred skill priorities and the base
interview plan shared across all candidates under this assessment.
Owned by: core-api
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base
from src.data.models.postgres.mixins import TimestampMixin

if TYPE_CHECKING:
    from src.data.models.postgres.candidate_assessment import CandidateAssessment
    from src.data.models.postgres.recruiter import Recruiter


class Assessment(TimestampMixin, Base):
    """SQLAlchemy model for recruiter assessments."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruiters.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Used to match candidates from CSV upload by role name
    role_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # Full JD text after LlamaParse extraction
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    # GCP Storage path to uploaded JD file (nullable — text-only JDs have no file)
    jd_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM-extracted structured JD analysis including skill priority scores
    jd_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Recruiter-specified skill weight overrides
    focus_areas: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Base section timeline computed from JD analysis at assessment creation
    interview_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    interview_duration_mins: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    # DRAFT | ACTIVE | CLOSED
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="DRAFT", index=True
    )

    # Relationships
    recruiter: Mapped["Recruiter"] = relationship(back_populates="assessments")
    candidate_assessments: Mapped[list["CandidateAssessment"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Assessment id={self.id} role={self.role_name} status={self.status}>"
