"""
Assessment schemas.

Covers assessment creation, JD analysis structures, and response shapes.
"""

import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import Form
from pydantic import ConfigDict, Field, ValidationError, model_validator

from src.core.exceptions import BadRequestException
from src.schemas.base import AppBaseModel, ORMBaseModel

# ── Shared literals ────────────────────────────────────────────────────────────

InferredDifficulty = Literal["junior level", "mid-level", "senior level"]


# ── Nested data structures ─────────────────────────────────────────────────────


class SkillPriority(AppBaseModel):
    """A single skill extracted from the JD with its inferred priority score."""

    model_config = ConfigDict(extra="ignore")

    skill: str = Field(..., description="Skill name, e.g. 'Python', 'System Design'")
    priority_score: float = Field(
        ..., ge=1.0, le=10.0, description="LLM-inferred priority from 1 to 10"
    )
    reasoning: str = Field(..., description="LLM evidence from JD for this score")


class JDAnalysis(AppBaseModel):
    """
    Structured output of the LLM JD analysis step.
    Stored as JSONB in assessments.jd_analysis.
    """

    model_config = ConfigDict(extra="ignore")

    inferred_difficulty: InferredDifficulty = Field(
        ...,
        description="Inferred interview difficulty: junior level, mid-level, or senior level",
    )
    skills: list[SkillPriority]
    behavioural_signals: list[str] = Field(
        default_factory=list,
        description="Key behavioural traits inferred from JD language",
    )


class SelfIntroSection(AppBaseModel):
    """Intro section in the interview plan."""

    model_config = ConfigDict(extra="ignore")

    section_name: Literal["self_intro"] = "self_intro"
    skill: None = Field(
        default=None,
        description="Always null for self_intro",
    )
    allocated_mins: float = Field(
        default=1.0,
        description="Self intro is capped at min(10% of total duration, 1 minute)",
    )


class TechnicalInterviewSection(AppBaseModel):
    """Technical skill section in the interview plan."""

    model_config = ConfigDict(extra="ignore")

    section_name: str
    skill: str = Field(..., description="Exact skill name from jd_analysis.skills")
    allocated_mins: float = Field(..., gt=0)
    expected_signals: list[str] = Field(
        default_factory=list,
        description="What the bot should listen for while assessing this technical skill",
    )

    @model_validator(mode="after")
    def validate_technical_section(self) -> "TechnicalInterviewSection":
        if self.section_name in {"self_intro", "behavioural_cultural"}:
            raise ValueError(
                "Technical section_name cannot be self_intro or behavioural_cultural."
            )

        if self.section_name != self.skill:
            raise ValueError("For technical sections, section_name must match skill.")

        return self


class BehaviouralCulturalSection(AppBaseModel):
    """Combined behavioural and cultural section in the interview plan."""

    model_config = ConfigDict(extra="ignore")

    section_name: Literal["behavioural_cultural"] = "behavioural_cultural"
    skill: None = Field(
        default=None,
        description="Always null for behavioural_cultural",
    )
    allocated_mins: float = Field(
        ...,
        gt=0,
        description="Deterministically normalized to 10 percent of total interview time",
    )
    expected_signals: list[str] = Field(
        default_factory=list,
        description="Behavioural and cultural/team-fit signals to assess",
    )


InterviewSection = (
    SelfIntroSection | TechnicalInterviewSection | BehaviouralCulturalSection
)


class InterviewPlan(AppBaseModel):
    """
    Base interview plan computed from JD analysis.
    Stored as JSONB in assessments.interview_plan.
    """

    model_config = ConfigDict(extra="ignore")

    total_mins: int
    inferred_difficulty: InferredDifficulty
    sections: list[InterviewSection]


class JDAnalysisAndInterviewPlan(AppBaseModel):
    """
    Combined LLM output for assessment creation.
    The API persists these as separate JSONB fields.
    """

    model_config = ConfigDict(extra="ignore")

    jd_analysis: JDAnalysis
    interview_plan: InterviewPlan

    @model_validator(mode="before")
    @classmethod
    def inherit_interview_plan_difficulty(cls, data: object) -> object:
        """Inject JD difficulty before nested interview-plan validation."""

        if not isinstance(data, dict):
            return data

        jd_analysis = data.get("jd_analysis")
        interview_plan = data.get("interview_plan")
        if not isinstance(jd_analysis, dict) or not isinstance(interview_plan, dict):
            return data

        inferred_difficulty = jd_analysis.get("inferred_difficulty")
        if inferred_difficulty is None:
            return data

        normalized = dict(data)
        normalized["interview_plan"] = {
            **interview_plan,
            "inferred_difficulty": inferred_difficulty,
        }
        return normalized

    @model_validator(mode="after")
    def sync_interview_plan_difficulty(self) -> "JDAnalysisAndInterviewPlan":
        """
        The interview plan must inherit inferred_difficulty from jd_analysis.

        This avoids failing the entire LLM response if the model returns a mismatched
        difficulty in interview_plan. The deterministic normalizer can still rebuild
        the final plan afterwards.
        """

        self.interview_plan.inferred_difficulty = self.jd_analysis.inferred_difficulty
        return self


class FocusAreaOverride(AppBaseModel):
    """Recruiter-specified weight override for a single skill."""

    skill: str
    weight_override: float = Field(..., ge=0.0, le=10.0)


# ── Request schemas ────────────────────────────────────────────────────────────


class AssessmentCreateRequest(AppBaseModel):
    """POST /assessments request body, multipart JD file handled separately."""

    title: str = Field(..., min_length=2, max_length=200)
    role_name: str = Field(..., min_length=2, max_length=120)

    # Either jd_text or jd_file must be provided, validated in the endpoint/service.
    jd_text: str | None = Field(
        None,
        description="Raw JD text; omit if uploading a PDF",
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
        focus_areas_list: list[FocusAreaOverride] = []

        if focus_areas:
            try:
                parsed = json.loads(focus_areas)

                if not isinstance(parsed, list):
                    raise ValueError("focus_areas must be a JSON array.")

                focus_areas_list = [
                    FocusAreaOverride.model_validate(item) for item in parsed
                ]

            except Exception as exc:
                raise BadRequestException(
                    f"Invalid focus_areas override payload: {exc}"
                ) from exc

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
            raise BadRequestException(f"Validation error: {err_msg}") from val_err

        # Store validated attributes on the form instance for direct access.
        self.title = self.model.title
        self.role_name = self.model.role_name
        self.interview_duration_mins = self.model.interview_duration_mins
        self.window_start = self.model.window_start
        self.window_end = self.model.window_end
        self.jd_text = self.model.jd_text
        self.focus_areas = self.model.focus_areas


class AssessmentUpdateStatusRequest(AppBaseModel):
    """PATCH /assessments/{id}/status — move DRAFT to ACTIVE or ACTIVE to CLOSED."""

    status: str = Field(..., pattern="^(ACTIVE|CLOSED)$")


# ── Response schemas ───────────────────────────────────────────────────────────


class AssessmentResponse(ORMBaseModel):
    """Full assessment representation returned by create and get endpoints."""

    id: uuid.UUID
    recruiter_id: uuid.UUID
    title: str
    role_name: str
    jd_text: str
    jd_file_path: str | None
    jd_analysis: JDAnalysis | None
    focus_areas: list[FocusAreaOverride] | None
    interview_plan: InterviewPlan | None
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
