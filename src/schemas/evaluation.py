"""
Evaluation schemas.

Schemas for returning the fully structured LLM evaluation report to the frontend.
"""

import uuid
from datetime import datetime
from typing import Any

from src.schemas.base import AppBaseModel


class TranscriptEvidence(AppBaseModel):
    turn_number: int | None = None
    section: str | None = None
    skill: str | None = None
    question: str | None = None
    quote: str
    interpretation: str


class EvaluationSkillBreakdown(AppBaseModel):
    priority_score: float | None = None
    depth_required: str | None = None
    weighted_score: float
    raw_score: float | None = None
    weight_share: float | None = None
    weighted_contribution: float | None = None
    difficulty_reached: str | float | None = None
    questions_asked: int | None = None
    assessed: bool | None = None
    similar_skill_credit: bool = False
    similar_skills_considered: list[str] = []
    transcript_evidence: list[TranscriptEvidence] = []
    signals_demonstrated: list[str] = []
    signals_missing: list[str] = []
    summary: str


class EvaluationSectionSummary(AppBaseModel):
    summary: str
    avg_score: float | None = None
    difficulty_reached: str | float | None = None
    questions_asked: int | None = None
    evidence: list[TranscriptEvidence] = []
    signals_demonstrated: list[str] = []
    signals_missing: list[str] = []
    score_basis: str | None = None


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
    candidate_name: str | None = None
    candidate_email: str | None = None
    assessment_title: str | None = None
    role_name: str | None = None
    recruiter_decision: str | None = None
    recruiter_feedback: str | None = None

    # Skills
    skill_scores: dict[str, EvaluationSkillBreakdown]

    # Dimensions
    technical_dimension_score: float
    score_evidence: list[str] = []
    score_summary: str = ""
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
    overall_narrative: str
    recommendation_reasoning: str

    # Highlights & Flags
    strengths: list[str]
    concerns: list[str]
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
    skill_scores: dict[str, EvaluationSkillBreakdown]
