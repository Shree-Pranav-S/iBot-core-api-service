"""Add interview engine tables.

Revision ID: 0002_interview_tables
Revises: 0001_initial_schema
Create Date: 2026-06-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002_interview_tables"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
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
            sa.ForeignKey("candidate_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'INITIALIZING'"),
        ),
        sa.Column(
            "current_section",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'self_intro'"),
        ),
        sa.Column(
            "section_progress",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("timer_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "total_elapsed_secs",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_pause_secs",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("paused_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "grace_period_expires_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "connectivity_events",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "candidate_assessment_id",
            name="uq_interview_sessions_candidate_assessment_id",
        ),
    )
    op.create_index(
        "ix_interview_sessions_candidate_assessment_id",
        "interview_sessions",
        ["candidate_assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_interview_sessions_status", "interview_sessions", ["status"], unique=False
    )

    op.create_table(
        "transcript_turns",
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
            sa.ForeignKey("candidate_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("stt_confidence", sa.Float(), nullable=True),
        sa.Column("turn_type", sa.Text(), nullable=True),
        sa.Column("concept_tags", pg.ARRAY(sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "candidate_assessment_id",
            "turn_number",
            name="uq_transcript_turns_candidate_assessment_turn_number",
        ),
    )
    op.create_index(
        "ix_transcript_turns_candidate_assessment_id",
        "transcript_turns",
        ["candidate_assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_transcript_turns_turn_number",
        "transcript_turns",
        ["turn_number"],
        unique=False,
    )

    op.create_table(
        "answer_evaluations",
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
            sa.ForeignKey("candidate_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("skill", sa.Text(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "signals_present",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "signals_missing",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("tone_scores", pg.JSONB(), nullable=True),
        sa.Column("one_line_feedback", sa.Text(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "candidate_assessment_id",
            "turn_number",
            name="uq_answer_evaluations_candidate_assessment_turn_number",
        ),
    )
    op.create_index(
        "ix_answer_evaluations_candidate_assessment_id",
        "answer_evaluations",
        ["candidate_assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_answer_evaluations_turn_number",
        "answer_evaluations",
        ["turn_number"],
        unique=False,
    )

    op.create_table(
        "interview_evaluations",
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
            sa.ForeignKey("candidate_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("skill_scores", pg.JSONB(), nullable=False),
        sa.Column("technical_dimension_score", sa.Float(), nullable=False),
        sa.Column("problem_solving_score", sa.Float(), nullable=False),
        sa.Column("problem_solving_evidence", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("problem_solving_summary", sa.Text(), nullable=False),
        sa.Column("communication_score", sa.Float(), nullable=False),
        sa.Column("communication_evidence", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("communication_summary", sa.Text(), nullable=False),
        sa.Column("behavioural_score", sa.Float(), nullable=False),
        sa.Column("behavioural_evidence", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("behavioural_summary", sa.Text(), nullable=False),
        sa.Column("cultural_fit_score", sa.Float(), nullable=False),
        sa.Column("cultural_fit_evidence", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("cultural_fit_summary", sa.Text(), nullable=False),
        sa.Column("tone_classification_score", sa.Float(), nullable=True),
        sa.Column("tone_distribution", pg.JSONB(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("hiring_recommendation", sa.Text(), nullable=False),
        sa.Column("recommendation_override_reason", sa.Text(), nullable=True),
        sa.Column("overall_narrative", sa.Text(), nullable=False),
        sa.Column("strengths", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("concerns", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "red_flags",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("best_answer", pg.JSONB(), nullable=True),
        sa.Column("weakest_answer", pg.JSONB(), nullable=True),
        sa.Column("recommendation_reasoning", sa.Text(), nullable=False),
        sa.Column("rank_in_assessment", sa.Integer(), nullable=True),
        sa.Column("percentile_in_assessment", sa.Integer(), nullable=True),
        sa.Column("total_candidates_evaluated", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "candidate_assessment_id",
            name="uq_interview_evaluations_candidate_assessment_id",
        ),
    )
    op.create_index(
        "ix_interview_evaluations_candidate_assessment_id",
        "interview_evaluations",
        ["candidate_assessment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_evaluations_candidate_assessment_id",
        table_name="interview_evaluations",
    )
    op.drop_table("interview_evaluations")

    op.drop_index("ix_answer_evaluations_turn_number", table_name="answer_evaluations")
    op.drop_index(
        "ix_answer_evaluations_candidate_assessment_id", table_name="answer_evaluations"
    )
    op.drop_table("answer_evaluations")

    op.drop_index("ix_transcript_turns_turn_number", table_name="transcript_turns")
    op.drop_index(
        "ix_transcript_turns_candidate_assessment_id", table_name="transcript_turns"
    )
    op.drop_table("transcript_turns")

    op.drop_index("ix_interview_sessions_status", table_name="interview_sessions")
    op.drop_index(
        "ix_interview_sessions_candidate_assessment_id", table_name="interview_sessions"
    )
    op.drop_table("interview_sessions")
