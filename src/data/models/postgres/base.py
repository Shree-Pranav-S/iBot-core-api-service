"""
Shared SQLAlchemy declarative base.

Every model file imports Base from here so that all tables share
the same MetaData object — which Alembic requires to auto-generate
migrations across the full schema.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all IBot Core-API models."""

    pass
