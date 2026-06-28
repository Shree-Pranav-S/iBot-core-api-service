"""
Timestamp mixin.

Provides created_at, updated_at, and deleted_at columns for models that need
consistent lifecycle timestamps and soft deletion.
Import and add to the class definition before Base:

    class MyModel(TimestampMixin, Base):
        ...
"""

from datetime import datetime

from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class TimestampMixin:
    """Adds server-side lifecycle timestamps and nullable soft deletion."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
