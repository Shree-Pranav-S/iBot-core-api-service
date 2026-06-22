"""
Evaluation schemas.

Schemas for returning the fully structured LLM evaluation report to the frontend.
"""

import uuid
from datetime import datetime
from typing import Any

from src.schemas.base import AppBaseModel


class EvaluationSkillBreakdown(AppBaseModel):
    priority_score: float | None = None
    weighted_score: float
    raw_score: float | None = None
    difficulty_reached: float | None = None
    signals_demonstrated: list[str] = []
    signals_missing: list[str] = []
    summary: str


class EvaluationSectionSummary(AppBaseModel):
    summary: str
    avg_score: float
    difficulty_reached: float | None = None
    questions_asked: int | None = None


class HighlightAnswer(AppBaseModel):
    question: str
    turn_number: int
    section: str | None = None
    difficulty_at_time: str | float | None = None
    reason: str


class RedFlag(AppBaseModel):
    description: str
    severity: str  # "critical" | "minor"


class ViolationSummary(AppBaseModel):
    total_irrelevant: int
    total_silences: int
    terminated_early: bool
    entries: list[Any]


class InterviewEvaluationResponse(AppBaseModel):
    """Full candidate evaluation report."""

    id: uuid.UUID
    candidate_assessment_id: uuid.UUID
    session_id: uuid.UUID

    # Skills
    skill_scores: dict[str, Any]

    # Dimensions
    technical_dimension_score: float
    score_evidence: list[str] = []
    score_summary: str = ""
    problem_solving_score: float | None = None
    problem_solving_evidence: list[str] = []
    problem_solving_summary: str | None = None
    communication_score: float | None = None
    communication_evidence: list[str] = []
    communication_summary: str | None = None
    behavioural_score: float
    behavioural_evidence: list[str]
    behavioural_summary: str
    cultural_fit_score: float
    cultural_fit_evidence: list[str]
    cultural_fit_summary: str
    tone_classification_score: float | None
    tone_distribution: list[Any] | None

    # Section summaries
    section_summaries: dict[str, EvaluationSectionSummary]

    # Overall
    overall_score: float
    hiring_recommendation: str
    recommendation_override_reason: str | None = None
    overall_narrative: str
    recommendation_reasoning: str

    # Highlights & Flags
    strengths: list[str]
    concerns: list[str]
    red_flags: list[RedFlag] = []
    violation_summary: ViolationSummary | None
    best_answer: HighlightAnswer | None
    weakest_answer: HighlightAnswer | None

    # Ranking
    rank_in_assessment: int | None
    percentile_in_assessment: int | None
    total_candidates_evaluated: int | None

    generated_at: datetime


class RecruiterEvaluationListItem(AppBaseModel):
    """Flattened evaluation row for the recruiter evaluations dashboard."""

    candidate_assessment_id: uuid.UUID
    candidate_name: str
    candidate_email: str
    assessment_id: uuid.UUID
    assessment_title: str
    role_name: str
    recruiter_decision: str
    interview_started_at: datetime | None
    interview_ended_at: datetime | None
    generated_at: datetime

    overall_score: float
    hiring_recommendation: str
    recommendation_reasoning: str
    overall_narrative: str
    technical_dimension_score: float
    behavioural_score: float
    cultural_fit_score: float
    tone_classification_score: float | None
    rank_in_assessment: int | None
    percentile_in_assessment: int | None
    total_candidates_evaluated: int | None
    strengths: list[str]
    concerns: list[str]
    red_flags_count: int
    skill_scores: dict[str, Any]
