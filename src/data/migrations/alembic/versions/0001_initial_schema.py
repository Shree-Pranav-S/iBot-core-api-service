"""Initial core-api schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiters",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_recruiters_email"),
    )
    op.create_index("ix_recruiters_email", "recruiters", ["email"], unique=False)

    op.create_table(
        "candidates",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recruiters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_candidates_email"),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"], unique=False)
    op.create_index(
        "ix_candidates_created_by", "candidates", ["created_by"], unique=False
    )

    op.create_table(
        "assessments",
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
            sa.ForeignKey("recruiters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("role_name", sa.Text(), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("jd_file_path", sa.Text(), nullable=True),
        sa.Column("jd_analysis", pg.JSONB(), nullable=True),
        sa.Column("focus_areas", pg.JSONB(), nullable=True),
        sa.Column("interview_plan", pg.JSONB(), nullable=True),
        sa.Column("interview_duration_mins", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("window_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'DRAFT'")
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_assessments_recruiter_id", "assessments", ["recruiter_id"], unique=False
    )
    op.create_index(
        "ix_assessments_role_name", "assessments", ["role_name"], unique=False
    )
    op.create_index("ix_assessments_status", "assessments", ["status"], unique=False)

    op.create_table(
        "candidate_assessments",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "candidate_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resume_file_path", sa.Text(), nullable=False),
        sa.Column("resume_parsed", pg.JSONB(), nullable=True),
        sa.Column(
            "resume_parse_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "invitation_token",
            pg.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'INVITED'")
        ),
        sa.Column("interview_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("interview_ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "recruiter_decision",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("recruiter_feedback", sa.Text(), nullable=True),
        sa.Column(
            "reminders_sent",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "candidate_id", "assessment_id", name="uq_candidate_assessment"
        ),
        sa.UniqueConstraint(
            "invitation_token", name="uq_candidate_assessments_invitation_token"
        ),
    )
    op.create_index(
        "ix_candidate_assessments_candidate_id",
        "candidate_assessments",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_assessments_assessment_id",
        "candidate_assessments",
        ["assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_assessments_status",
        "candidate_assessments",
        ["status"],
        unique=False,
    )

    op.create_table(
        "csv_upload_logs",
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
            sa.ForeignKey("recruiters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column(
            "successful_rows", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "failed_rows", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "row_results",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "overall_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PROCESSING'"),
        ),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_csv_upload_logs_recruiter_id",
        "csv_upload_logs",
        ["recruiter_id"],
        unique=False,
    )
    op.create_index(
        "ix_csv_upload_logs_assessment_id",
        "csv_upload_logs",
        ["assessment_id"],
        unique=False,
    )

    op.create_table(
        "notification_logs",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "candidate_assessment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("candidate_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("recipient_email", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "delivery_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'SENT'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_notification_logs_candidate_assessment_id",
        "notification_logs",
        ["candidate_assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_logs_notification_type",
        "notification_logs",
        ["notification_type"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_status", sa.Text(), nullable=False),
        sa.Column(
            "candidate_assessment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("candidate_assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recruiter_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recruiters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metadata", pg.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_logs_service", "audit_logs", ["service"], unique=False)
    op.create_index(
        "ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False
    )
    op.create_index(
        "ix_audit_logs_event_status", "audit_logs", ["event_status"], unique=False
    )
    op.create_index(
        "ix_audit_logs_candidate_assessment_id",
        "audit_logs",
        ["candidate_assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_recruiter_id", "audit_logs", ["recruiter_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_recruiter_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_candidate_assessment_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_status", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_service", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(
        "ix_notification_logs_notification_type", table_name="notification_logs"
    )
    op.drop_index(
        "ix_notification_logs_candidate_assessment_id", table_name="notification_logs"
    )
    op.drop_table("notification_logs")

    op.drop_index("ix_csv_upload_logs_assessment_id", table_name="csv_upload_logs")
    op.drop_index("ix_csv_upload_logs_recruiter_id", table_name="csv_upload_logs")
    op.drop_table("csv_upload_logs")

    op.drop_index("ix_candidate_assessments_status", table_name="candidate_assessments")
    op.drop_index(
        "ix_candidate_assessments_assessment_id", table_name="candidate_assessments"
    )
    op.drop_index(
        "ix_candidate_assessments_candidate_id", table_name="candidate_assessments"
    )
    op.drop_table("candidate_assessments")

    op.drop_index("ix_assessments_status", table_name="assessments")
    op.drop_index("ix_assessments_role_name", table_name="assessments")
    op.drop_index("ix_assessments_recruiter_id", table_name="assessments")
    op.drop_table("assessments")

    op.drop_index("ix_candidates_created_by", table_name="candidates")
    op.drop_index("ix_candidates_email", table_name="candidates")
    op.drop_table("candidates")

    op.drop_index("ix_recruiters_email", table_name="recruiters")
    op.drop_table("recruiters")
