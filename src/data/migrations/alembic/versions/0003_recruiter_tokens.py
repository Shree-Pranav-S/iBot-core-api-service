"""Add recruiter refresh token table.

Revision ID: 0003_recruiter_tokens
Revises: 0002_interview_tables
Create Date: 2026-06-10 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003_recruiter_tokens"
down_revision: str | Sequence[str] | None = "0002_interview_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiter_tokens",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recruiter_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recruiters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "is_revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_recruiter_tokens_token_hash"),
    )
    op.create_index(
        "ix_recruiter_tokens_recruiter_id",
        "recruiter_tokens",
        ["recruiter_id"],
        unique=False,
    )
    op.create_index(
        "ix_recruiter_tokens_recruiter_id_is_revoked",
        "recruiter_tokens",
        ["recruiter_id", "is_revoked"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recruiter_tokens_recruiter_id_is_revoked",
        table_name="recruiter_tokens",
    )
    op.drop_index("ix_recruiter_tokens_recruiter_id", table_name="recruiter_tokens")
    op.drop_table("recruiter_tokens")
