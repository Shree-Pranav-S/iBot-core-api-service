"""
CSVUploadLog model.

Tracks the outcome of each bulk CSV upload batch.
Provides the recruiter with a per-row processing summary
showing successes and failures with specific reasons.
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

if TYPE_CHECKING:
    from src.data.models.postgres.assessment import Assessment
    from src.data.models.postgres.recruiter import Recruiter


class CSVUploadLog(Base):
    __tablename__ = "csv_upload_logs"

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
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    row_results: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # PROCESSING | COMPLETED | COMPLETED_WITH_ERRORS
    overall_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="PROCESSING"
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    recruiter: Mapped["Recruiter"] = relationship(back_populates="csv_upload_logs")
    assessment: Mapped["Assessment"] = relationship(back_populates="csv_upload_logs")

    def __repr__(self) -> str:
        return f"<CSVUploadLog id={self.id} status={self.overall_status}>"
