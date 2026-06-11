"""
Schemas package.

Single import surface for all Pydantic schemas used in core-api.
"""

from src.schemas.assessment import (
    AssessmentCreateRequest,
    AssessmentResponse,
    AssessmentSummaryResponse,
    AssessmentUpdateStatusRequest,
    FocusAreaOverride,
    InterviewPlan,
    InterviewSection,
    JDAnalysis,
    SkillPriority,
)
from src.schemas.audit import AuditEventPayload, AuditLogResponse
from src.schemas.auth import (
    LoginRequest,
    RecruiterRegisterRequest,
    RecruiterResponse,
    TokenPayload,
    TokenResponse,
)
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    CandidateAssessmentResponse,
    CandidateResponse,
    CSVRowResult,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    TokenValidationResponse,
)
from src.schemas.common import (
    APIResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
)
from src.schemas.notification import (
    NotificationLogResponse,
    SendInvitationPayload,
    SendOutcomePayload,
    SendReminderPayload,
)

__all__ = [
    # auth
    "RecruiterRegisterRequest",
    "LoginRequest",
    "RecruiterResponse",
    "TokenResponse",
    "TokenPayload",
    # assessment
    "AssessmentCreateRequest",
    "AssessmentUpdateStatusRequest",
    "AssessmentResponse",
    "AssessmentSummaryResponse",
    "SkillPriority",
    "JDAnalysis",
    "InterviewSection",
    "InterviewPlan",
    "FocusAreaOverride",
    # candidate
    "CandidateResponse",
    "BulkUploadResponse",
    "CSVRowResult",
    "CandidateAssessmentListItem",
    "CandidateAssessmentResponse",
    "RecruiterDecisionRequest",
    "RecruiterDecisionResponse",
    "TokenValidationResponse",
    # notification
    "NotificationLogResponse",
    "SendInvitationPayload",
    "SendReminderPayload",
    "SendOutcomePayload",
    # audit
    "AuditEventPayload",
    "AuditLogResponse",
    # common
    "APIResponse",
    "PaginatedResponse",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
]
