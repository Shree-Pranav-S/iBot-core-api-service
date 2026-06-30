"""
Candidate schemas.

Covers bulk CSV upload processing, candidate responses, and
candidate-assessment lifecycle representations.
"""

import uuid
from datetime import datetime

from pydantic import Field

from src.schemas.base import AppBaseModel, ORMBaseModel

# CSV upload schemas


class CSVRowResult(AppBaseModel):
    """Per-row outcome within a bulk upload response."""

    row: int
    email: str
    status: str = Field(..., pattern="^(success|failed)$")
    reason: str | None = None


class BulkUploadResponse(AppBaseModel):
    """
    POST /assessments/{id}/candidates/bulk-upload response.
    Returned immediately - Celery processes rows asynchronously.
    """

    upload_id: uuid.UUID
    total_rows: int
    successful_rows: int
    failed_rows: int
    row_results: list[CSVRowResult]
    overall_status: str


class SingleCandidateResponse(AppBaseModel):
    """Response for creating a single candidate manually."""

    candidate_assessment_id: uuid.UUID
    candidate_id: uuid.UUID
    full_name: str
    email: str
    status: str


class ExistingCandidateListItem(AppBaseModel):
    """A unique candidate record (not per-assessment) for use in enrollment dropdowns."""

    id: uuid.UUID
    full_name: str
    email: str


class EnrollCandidateResponse(AppBaseModel):
    """Response for enrolling an existing candidate into a new assessment."""

    candidate_assessment_id: uuid.UUID
    candidate_id: uuid.UUID
    full_name: str
    email: str
    status: str


class TranscriptTurn(AppBaseModel):
    """A single turn in the interview transcript."""

    turn_number: int
    speaker: str
    text: str
    tone: str | None = None


class InterviewTranscriptResponse(AppBaseModel):
    """Full interview transcript for a candidate assessment."""

    candidate_assessment_id: uuid.UUID
    candidate_name: str | None = None
    assessment_title: str | None = None
    total_elapsed_secs: int = 0
    turns: list[TranscriptTurn]


# Candidate response schemas


class CandidateResponse(ORMBaseModel):
    """Candidate record as returned by the API."""

    id: uuid.UUID
    full_name: str
    email: str
    created_by: uuid.UUID
    created_at: datetime


# CandidateAssessment schemas


class CandidateAssessmentListItem(ORMBaseModel):
    """
    Single candidate row in the recruiter dashboard candidate list.
    GET /assessments/{id}/candidates
    """

    id: uuid.UUID
    full_name: str = ""
    email: str = ""
    status: str
    resume_parse_status: str
    interview_started_at: datetime | None
    interview_ended_at: datetime | None
    recruiter_decision: str
    assessment_id: uuid.UUID | None = None
    role_name: str = ""
    resume_parsed: dict | None = None
    resume_file_path: str | None = None
    jd_text: str | None = ""

    @classmethod
    def from_orm_with_candidate(cls, ca: object) -> "CandidateAssessmentListItem":
        """Build from a CandidateAssessment ORM object with an eagerly loaded candidate."""
        return cls(
            id=ca.id,
            full_name=ca.candidate.full_name if ca.candidate else "",
            email=ca.candidate.email if ca.candidate else "",
            status=ca.status,
            resume_parse_status=ca.resume_parse_status,
            interview_started_at=ca.interview_started_at,
            interview_ended_at=ca.interview_ended_at,
            recruiter_decision=ca.recruiter_decision,
            assessment_id=ca.assessment_id,
            role_name=ca.assessment.role_name if ca.assessment else "",
            resume_parsed=ca.resume_parsed,
            resume_file_path=ca.resume_file_path,
            jd_text=ca.assessment.jd_text if ca.assessment else "",
        )


class CandidateAssessmentResponse(ORMBaseModel):
    """Full candidate-assessment record."""

    id: uuid.UUID
    candidate_id: uuid.UUID
    assessment_id: uuid.UUID
    resume_file_path: str
    resume_parse_status: str
    status: str
    interview_started_at: datetime | None
    interview_ended_at: datetime | None
    recruiter_decision: str
    recruiter_feedback: str | None
    reminders_sent: dict
    created_at: datetime
    updated_at: datetime


# Recruiter decision schema


class RecruiterDecisionRequest(AppBaseModel):
    """POST /candidates/{ca_id}/decision request body."""

    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    feedback: str | None = Field(
        None,
        max_length=2000,
        description="Optional manual feedback included in rejection email",
    )


class RecruiterDecisionResponse(ORMBaseModel):
    """POST /candidates/{ca_id}/decision response."""

    candidate_assessment_id: uuid.UUID
    recruiter_decision: str
    updated_at: datetime


# Token validation schema (candidate-facing)


class TokenValidationResponse(AppBaseModel):
    """
    GET /interview/validate-token response.
    Returned to the candidate's browser to populate the waiting room.
    """

    candidate_name: str
    company_name: str
    assessment_title: str
    interview_duration_mins: int
    window_end: datetime
    status: str
    sections_overview: list[str]


class CandidateTokenValidationResponse(AppBaseModel):
    """
    Response returned by internal token validation endpoint.
    Used by gateway to authenticate candidate WebSocket connections.
    """

    candidate_id: uuid.UUID
    assessment_id: uuid.UUID
    candidate_assessment_id: uuid.UUID
