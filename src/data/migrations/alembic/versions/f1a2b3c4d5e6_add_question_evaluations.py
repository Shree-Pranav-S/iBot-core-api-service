"""Add structured per-question interview evaluations.

Revision ID: f1a2b3c4d5e6
Revises: e8b7c6d5a4f3
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e8b7c6d5a4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "question_evaluations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("interview_evaluations", "question_evaluations")
