"""Consolidate audit and CSV upload logs into event logs.

Revision ID: c4a8e7d91f02
Revises: 9f7c2a1e4d6b
Create Date: 2026-06-28 07:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4a8e7d91f02"
down_revision: str | Sequence[str] | None = "9f7c2a1e4d6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIXIN_TABLES = (
    "assessments",
    "candidate_assessments",
    "candidates",
    "recruiters",
)


def upgrade() -> None:
    for table_name in MIXIN_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "deleted_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
        )

    op.create_table(
        "event_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("source_service", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "candidate_assessment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "recruiter_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "deleted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_event_logs_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_event_logs_metadata_object",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_event_logs_created_at",
        "event_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_logs_event_created_at",
        "event_logs",
        ["event_name", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_logs_correlation_created_at",
        "event_logs",
        ["correlation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_logs_candidate_created_at",
        "event_logs",
        ["candidate_assessment_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("candidate_assessment_id IS NOT NULL"),
    )
    op.create_index(
        "ix_event_logs_recruiter_created_at",
        "event_logs",
        ["recruiter_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("recruiter_id IS NOT NULL"),
    )

    op.drop_table("csv_upload_logs")
    op.drop_table("audit_logs")


def downgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_status", sa.Text(), nullable=False),
        sa.Column(
            "candidate_assessment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "recruiter_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["candidate_assessments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recruiter_id"],
            ["recruiters.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "service",
        "event_type",
        "event_status",
        "candidate_assessment_id",
        "recruiter_id",
        "created_at",
    ):
        op.create_index(
            f"ix_audit_logs_{column_name}",
            "audit_logs",
            [column_name],
            unique=False,
        )

    op.create_table(
        "csv_upload_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "recruiter_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("successful_rows", sa.Integer(), nullable=False),
        sa.Column("failed_rows", sa.Integer(), nullable=False),
        sa.Column(
            "row_results",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("overall_status", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recruiter_id"],
            ["recruiters.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_csv_upload_logs_assessment_id",
        "csv_upload_logs",
        ["assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_csv_upload_logs_recruiter_id",
        "csv_upload_logs",
        ["recruiter_id"],
        unique=False,
    )

    op.drop_table("event_logs")

    for table_name in reversed(MIXIN_TABLES):
        op.drop_column(table_name, "deleted_at")
