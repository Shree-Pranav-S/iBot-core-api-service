"""API schemas for deterministic holistic interview evaluations."""

import uuid
from datetime import datetime

from pydantic import Field

from src.schemas.base import AppBaseModel


class EvaluationSkillBreakdown(AppBaseModel):
    score: float
    priority_score: float
    questions_evaluated: int
    confidence: float


class SectionCommunicationBreakdown(AppBaseModel):
    score: float
    summary: str
    evidence: list[str] = Field(default_factory=list)


class SeverityCounts(AppBaseModel):
    low: int
    medium: int
    high: int
    critical: int


class ViolationSummary(AppBaseModel):
    has_violation: bool
    validated_violation_count: int
    severity_counts: SeverityCounts
    summary: str
    penalty_applied: float = 0.0
    hard_gate_reasons: list[str] = Field(default_factory=list)


class InterviewEvaluationResponse(AppBaseModel):
    """Full persisted report for one candidate assessment."""

    id: uuid.UUID
    candidate_assessment_id: uuid.UUID
    session_id: uuid.UUID
    candidate_name: str | None = None
    candidate_email: str | None = None
    assessment_title: str | None = None
    role_name: str | None = None
    recruiter_decision: str | None = None
    recruiter_feedback: str | None = None

    intro_section_score: float
    intro_section_summary: str
    intro_section_evidence: list[str]

    skill_scores: dict[str, EvaluationSkillBreakdown]
    overall_technical_skill_score: float
    skill_summary: dict[str, str]
    skill_evidence: dict[str, list[str]]

    behavioural_cultural_score: float
    behavioural_cultural_summary: str
    behavioural_cultural_evidence: list[str]

    communication_score: float
    communication_summary: str
    communication_evidence: list[str]
    section_communication_scores: dict[
        str,
        SectionCommunicationBreakdown,
    ]

    violation_summary: ViolationSummary | None
    violation_evidence: list[str] | None

    raw_overall_score: float
    violation_penalty: float
    overall_score: float
    hiring_recommendation: str
    model_recommendation: str
    recommendation_override_reason: str | None
    overall_summary: str
    recommendation_reasoning: str
    strengths: list[str]
    concerns: list[str]

    prompt_version: str
    model_name: str
    model_provider: str
    evaluation_schema_version: str
    transcript_hash: str

    rank_in_assessment: int | None
    percentile_in_assessment: int | None
    total_candidates_evaluated: int | None
    generated_at: datetime


class RecruiterEvaluationListItem(AppBaseModel):
    """Compact report for the recruiter evaluations dashboard."""

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
    overall_summary: str
    overall_technical_skill_score: float
    behavioural_cultural_score: float
    communication_score: float
    rank_in_assessment: int | None
    percentile_in_assessment: int | None
    total_candidates_evaluated: int | None
    strengths: list[str]
    concerns: list[str]
    validated_violation_count: int
    skill_scores: dict[str, EvaluationSkillBreakdown]
