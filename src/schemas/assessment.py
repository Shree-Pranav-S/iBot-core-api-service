"""
Assessment schemas.

Covers assessment creation, JD analysis structures, and response shapes.
"""

import json
import uuid
from datetime import datetime

from fastapi import Form
from pydantic import Field, ValidationError, model_validator

from src.core.exceptions import BadRequestException
from src.schemas.base import AppBaseModel, ORMBaseModel

# â”€â”€ Nested data structures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class SkillPriority(AppBaseModel):
    """A single skill extracted from the JD with its inferred priority score."""

    skill: str = Field(..., description="Skill name, e.g. 'Python', 'System Design'")
    priority_score: float = Field(
        ..., ge=1.0, le=10.0, description="LLM-inferred priority 1â€“10"
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
    expected_signals: list[str] = Field(
        default_factory=list,
        description="What the bot should listen for while assessing this section",
    )


class InterviewPlan(AppBaseModel):
    """
    Base interview plan computed from JD analysis.
    Stored as JSONB in assessments.interview_plan.
    """

    total_mins: int
    sections: list[InterviewSection]


class JDAnalysisAndInterviewPlan(AppBaseModel):
    """
    Combined LLM output for assessment creation.
    The API persists these as separate JSONB fields.
    """

    jd_analysis: JDAnalysis
    interview_plan: InterviewPlan


class FocusAreaOverride(AppBaseModel):
    """Recruiter-specified weight override for a single skill."""

    skill: str
    weight_override: float = Field(..., ge=0.0, le=10.0)


# â”€â”€ Request schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class AssessmentCreateRequest(AppBaseModel):
    """POST /assessments request body (multipart â€” jd_file handled separately)."""

    title: str = Field(..., min_length=2, max_length=200)
    role_name: str = Field(..., min_length=2, max_length=120)
    # Either jd_text or jd_file must be provided (validated below)
    jd_text: str | None = Field(
        None, description="Raw JD text; omit if uploading a PDF"
    )
    interview_duration_mins: int = Field(..., ge=2, le=180)
    window_start: datetime
    window_end: datetime
    focus_areas: list[FocusAreaOverride] | None = None

    @model_validator(mode="after")
    def window_order(self) -> "AssessmentCreateRequest":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start.")
        return self


class AssessmentCreateForm:
    """Dependency form wrapper for parsing multipart/form-data for assessment creation."""

    def __init__(
        self,
        title: str = Form(...),
        role_name: str = Form(...),
        interview_duration_mins: int = Form(...),
        window_start: datetime = Form(...),
        window_end: datetime = Form(...),
        jd_text: str | None = Form(None),
        focus_areas: str | None = Form(
            None,
            description='Expecting JSON string: \'[{"skill": "Python", "weight_override": 8.0}]\'',
        ),
    ):
        focus_areas_list = []
        if focus_areas:
            try:
                parsed = json.loads(focus_areas)
                if isinstance(parsed, list):
                    focus_areas_list = [
                        FocusAreaOverride.model_validate(item) for item in parsed
                    ]
            except Exception as exc:
                raise BadRequestException(
                    f"Invalid focus_areas override payload: {exc}"
                )

        try:
            self.model = AssessmentCreateRequest(
                title=title,
                role_name=role_name,
                interview_duration_mins=interview_duration_mins,
                window_start=window_start,
                window_end=window_end,
                jd_text=jd_text,
                focus_areas=focus_areas_list,
            )
        except ValidationError as val_err:
            errors = val_err.errors()
            err_msg = "; ".join(
                [
                    f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                    for err in errors
                ]
            )
            raise BadRequestException(f"Validation error: {err_msg}")

        # Store validated attributes on the form instance for direct access
        self.title = self.model.title
        self.role_name = self.model.role_name
        self.interview_duration_mins = self.model.interview_duration_mins
        self.window_start = self.model.window_start
        self.window_end = self.model.window_end
        self.jd_text = self.model.jd_text
        self.focus_areas = self.model.focus_areas


class AssessmentUpdateStatusRequest(AppBaseModel):
    """PATCH /assessments/{id}/status â€” move DRAFT â†’ ACTIVE or ACTIVE â†’ CLOSED."""

    status: str = Field(..., pattern="^(ACTIVE|CLOSED)$")


# â”€â”€ Response schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
