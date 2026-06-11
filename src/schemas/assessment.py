"""
Assessment schemas.

Covers assessment creation, JD analysis structures, and response shapes.
"""

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from src.schemas.base import AppBaseModel, ORMBaseModel

# ── Nested data structures ────────────────────────────────────────────────────


class SkillPriority(AppBaseModel):
    """A single skill extracted from the JD with its inferred priority score."""

    skill: str = Field(..., description="Skill name, e.g. 'Python', 'System Design'")
    priority_score: float = Field(
        ..., ge=1.0, le=10.0, description="LLM-inferred priority 1–10"
    )
    depth_required: str = Field(
        ..., description="e.g. 'Expert', 'Intermediate', 'Awareness'"
    )
    reasoning: str = Field(..., description="LLM evidence from JD for this score")


class JDAnalysis(AppBaseModel):
    """
    Structured output of the LLM JD analysis step.
    Stored as JSONB in assessments.jd_analysis.
    """

    inferred_role_title: str
    seniority_level: str = Field(
        ..., description="e.g. 'Senior', 'Mid-level', 'Junior'"
    )
    difficulty: str = Field(..., description="e.g. 'High', 'Medium', 'Low'")
    skills: list[SkillPriority]
    behavioural_signals: list[str] = Field(
        default_factory=list,
        description="Key behavioural traits inferred from JD language",
    )


class InterviewSection(AppBaseModel):
    """One section in the base interview plan timeline."""

    section_name: str
    skill: str | None = Field(
        None,
        description="Skill assessed in this section; null for intro/behavioural/cultural",
    )
    allocated_mins: float
    priority_score: float | None = None


class InterviewPlan(AppBaseModel):
    """
    Base interview plan computed from JD analysis.
    Stored as JSONB in assessments.interview_plan.
    """

    total_mins: int
    sections: list[InterviewSection]


class FocusAreaOverride(AppBaseModel):
    """Recruiter-specified weight override for a single skill."""

    skill: str
    weight_override: float = Field(..., ge=0.0, le=10.0)


# ── Request schemas ───────────────────────────────────────────────────────────


class AssessmentCreateRequest(AppBaseModel):
    """POST /assessments request body (multipart — jd_file handled separately)."""

    title: str = Field(..., min_length=2, max_length=200)
    role_name: str = Field(..., min_length=2, max_length=120)
    # Either jd_text or jd_file must be provided (validated below)
    jd_text: str | None = Field(
        None, description="Raw JD text; omit if uploading a PDF"
    )
    interview_duration_mins: int = Field(..., ge=10, le=180)
    window_start: datetime
    window_end: datetime
    focus_areas: list[FocusAreaOverride] | None = None

    @model_validator(mode="after")
    def window_order(self) -> "AssessmentCreateRequest":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start.")
        return self


class AssessmentUpdateStatusRequest(AppBaseModel):
    """PATCH /assessments/{id}/status — move DRAFT → ACTIVE or ACTIVE → CLOSED."""

    status: str = Field(..., pattern="^(ACTIVE|CLOSED)$")


# ── Response schemas ──────────────────────────────────────────────────────────


class AssessmentResponse(ORMBaseModel):
    """Full assessment representation returned by create and get endpoints."""

    id: uuid.UUID
    recruiter_id: uuid.UUID
    title: str
    role_name: str
    jd_text: str
    jd_file_path: str | None
    jd_analysis: dict | None
    focus_areas: dict | None
    interview_plan: dict | None
    interview_duration_mins: int
    window_start: datetime
    window_end: datetime
    status: str
    created_at: datetime
    updated_at: datetime


class AssessmentSummaryResponse(ORMBaseModel):
    """Lightweight assessment representation used in list views."""

    id: uuid.UUID
    title: str
    role_name: str
    status: str
    interview_duration_mins: int
    window_start: datetime
    window_end: datetime
    created_at: datetime
