"""
Recruiter model.

Stores recruiter accounts created via self-registration.
Owned by: core-api
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base
from src.data.models.postgres.mixins import TimestampMixin

if TYPE_CHECKING:
    from src.data.models.postgres.assessment import Assessment
    from src.data.models.postgres.candidate import Candidate
    from src.data.models.postgres.csv_upload_log import CSVUploadLog


class Recruiter(TimestampMixin, Base):
    __tablename__ = "recruiters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="recruiter",
        cascade="all, delete-orphan",
    )
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="created_by_recruiter",
    )
    csv_upload_logs: Mapped[list["CSVUploadLog"]] = relationship(
        back_populates="recruiter",
    )

    def __repr__(self) -> str:
        return f"<Recruiter id={self.id} email={self.email}>"
