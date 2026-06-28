"""Add deterministic holistic evaluation and audit columns.

Revision ID: 9f7c2a1e4d6b
Revises: 14b3eb7cc7b2
Create Date: 2026-06-27 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9f7c2a1e4d6b"
down_revision: str | Sequence[str] | None = "14b3eb7cc7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "section_communication_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "raw_overall_score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "violation_penalty",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "model_recommendation",
            sa.Text(),
            nullable=False,
            server_default="no hire",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "recommendation_override_reason",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "prompt_version",
            sa.Text(),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "model_name",
            sa.Text(),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "model_provider",
            sa.Text(),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "evaluation_schema_version",
            sa.Text(),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "transcript_hash",
            sa.Text(),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "interview_evaluations",
        sa.Column(
            "raw_model_output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_interview_evaluations_transcript_hash",
        "interview_evaluations",
        ["transcript_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_evaluations_transcript_hash",
        table_name="interview_evaluations",
    )
    op.drop_column("interview_evaluations", "raw_model_output")
    op.drop_column("interview_evaluations", "transcript_hash")
    op.drop_column("interview_evaluations", "evaluation_schema_version")
    op.drop_column("interview_evaluations", "model_provider")
    op.drop_column("interview_evaluations", "model_name")
    op.drop_column("interview_evaluations", "prompt_version")
    op.drop_column(
        "interview_evaluations",
        "recommendation_override_reason",
    )
    op.drop_column("interview_evaluations", "model_recommendation")
    op.drop_column("interview_evaluations", "violation_penalty")
    op.drop_column("interview_evaluations", "raw_overall_score")
    op.drop_column(
        "interview_evaluations",
        "section_communication_scores",
    )
