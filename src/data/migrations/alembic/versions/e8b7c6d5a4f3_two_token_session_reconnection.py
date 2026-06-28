"""Add two-token candidate sessions and bounded reconnection state.

Revision ID: e8b7c6d5a4f3
Revises: c4a8e7d91f02
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b7c6d5a4f3"
down_revision: str | Sequence[str] | None = "c4a8e7d91f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_assessments",
        sa.Column(
            "invite_consumed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "candidate_assessments",
        sa.Column(
            "invite_consumed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    op.alter_column(
        "interview_sessions",
        "grace_period_expires_at",
        new_column_name="reconnect_deadline",
        existing_type=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
    )
    op.add_column(
        "interview_sessions",
        sa.Column("session_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_sessions",
        sa.Column(
            "session_token_expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_sessions",
        sa.Column(
            "disconnect_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "interview_sessions",
        sa.Column(
            "timeout_disconnect_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "interview_sessions",
        sa.Column(
            "last_disconnected_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("active_connection_id", sa.Text(), nullable=True),
    )

    op.execute(
        """
        UPDATE interview_sessions
        SET status = 'DISCONNECTED'
        WHERE status = 'PAUSED'
        """
    )
    op.execute(
        """
        UPDATE candidate_assessments
        SET invite_consumed = TRUE,
            invite_consumed_at = COALESCE(
                invite_consumed_at,
                interview_started_at,
                updated_at
            )
        WHERE status IN ('IN_PROGRESS', 'COMPLETED', 'EVALUATED')
        """
    )

    op.create_unique_constraint(
        "uq_interview_sessions_session_token",
        "interview_sessions",
        ["session_token"],
    )
    op.create_check_constraint(
        "ck_interview_sessions_disconnect_counts_nonnegative",
        "interview_sessions",
        "disconnect_count >= 0 AND timeout_disconnect_count >= 0",
    )
    op.create_check_constraint(
        "ck_interview_sessions_reconnect_deadline_state",
        "interview_sessions",
        ("status NOT IN ('IN_PROGRESS', 'TERMINATED') OR reconnect_deadline IS NULL"),
    )
    op.create_check_constraint(
        "ck_interview_sessions_session_token_pair",
        "interview_sessions",
        (
            "(session_token IS NULL AND session_token_expires_at IS NULL) "
            "OR (session_token IS NOT NULL AND session_token_expires_at IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_interview_sessions_session_token_pair",
        "interview_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_interview_sessions_reconnect_deadline_state",
        "interview_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_interview_sessions_disconnect_counts_nonnegative",
        "interview_sessions",
        type_="check",
    )
    op.drop_constraint(
        "uq_interview_sessions_session_token",
        "interview_sessions",
        type_="unique",
    )

    op.execute(
        """
        UPDATE interview_sessions
        SET status = 'PAUSED'
        WHERE status = 'DISCONNECTED'
        """
    )
    op.drop_column("interview_sessions", "active_connection_id")
    op.drop_column("interview_sessions", "last_disconnected_at")
    op.drop_column("interview_sessions", "timeout_disconnect_count")
    op.drop_column("interview_sessions", "disconnect_count")
    op.drop_column("interview_sessions", "session_token_expires_at")
    op.drop_column("interview_sessions", "session_token")
    op.alter_column(
        "interview_sessions",
        "reconnect_deadline",
        new_column_name="grace_period_expires_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
    )
    op.drop_column("candidate_assessments", "invite_consumed_at")
    op.drop_column("candidate_assessments", "invite_consumed")
