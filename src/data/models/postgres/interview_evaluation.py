"""
InterviewEvaluation model.

Final holistic interview evaluation written after interview completion.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.data.models.postgres.base import Base


class InterviewEvaluation(Base):
    __tablename__ = "interview_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "candidate_assessment_id",
            name="uq_interview_evaluations_candidate_assessment_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    candidate_assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_assessments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    skill_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    technical_dimension_score: Mapped[float] = mapped_column(Float, nullable=False)
    problem_solving_score: Mapped[float] = mapped_column(Float, nullable=False)
    problem_solving_evidence: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False
    )
    problem_solving_summary: Mapped[str] = mapped_column(Text, nullable=False)
    communication_score: Mapped[float] = mapped_column(Float, nullable=False)
    communication_evidence: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False
    )
    communication_summary: Mapped[str] = mapped_column(Text, nullable=False)
    behavioural_score: Mapped[float] = mapped_column(Float, nullable=False)
    behavioural_evidence: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    behavioural_summary: Mapped[str] = mapped_column(Text, nullable=False)
    cultural_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    cultural_fit_evidence: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False
    )
    cultural_fit_summary: Mapped[str] = mapped_column(Text, nullable=False)
    tone_classification_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    tone_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    hiring_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_override_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    overall_narrative: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    concerns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    red_flags: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    best_answer: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    weakest_answer: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recommendation_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    rank_in_assessment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percentile_in_assessment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_candidates_evaluated: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
